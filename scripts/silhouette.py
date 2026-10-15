#!/usr/bin/env python3
"""Advisory silhouette comparison between a reference image and CAD view masks.

This is a coarse, scale- and position-normalized overlap score, not a visual
acceptance gate. The reference foreground is estimated by growing the
background inward from the image border, so it works for illustrations and
product shots on plain or smoothly varying backgrounds and fails on busy
photographs or objects coloured like their background. ``reliable`` is false
when the estimated foreground does not look like one object (several blobs,
speckle, touching the border); pass a hand-made mask for such photos.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


WORK_SIZE = 256
NORMALIZED_SIZE = 160
NEIGHBOR_TOLERANCE = 14
MIN_LARGEST_COMPONENT_SHARE = 0.85
MAX_BORDER_FOREGROUND = 0.10
# Boundary pixels / sqrt(area). Clean outlines of the example illustrations
# (including a legged horse) score 4.6-8.8; speckled photo segmentations and
# line drawings score 11.6 and up.
MAX_BOUNDARY_ROUGHNESS = 10.0


def reference_foreground(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    # Nearest-neighbour keeps edges hard: averaged edge pixels would form a
    # colour ramp that lets the background grow into a low-contrast object.
    image.thumbnail((WORK_SIZE, WORK_SIZE), Image.Resampling.NEAREST)
    pixels = np.asarray(image, dtype=np.int16)
    height, width = pixels.shape[:2]
    background = np.zeros((height, width), dtype=bool)
    background[0, :] = background[-1, :] = background[:, 0] = background[:, -1] = True
    # Each pixel joins the background when it is close in colour to a neighbour
    # that is already background, so soft gradients and ground planes are
    # absorbed while a contrasting object boundary stops the growth.
    similar = {}
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        shifted = np.roll(pixels, (dy, dx), axis=(0, 1))
        similar[(dy, dx)] = np.abs(pixels - shifted).max(axis=2) <= NEIGHBOR_TOLERANCE
    for _ in range(height * width):
        grown = background.copy()
        for (dy, dx), close in similar.items():
            neighbour = np.roll(background, (dy, dx), axis=(0, 1))
            if dy == 1:
                neighbour[0, :] = False
            elif dy == -1:
                neighbour[-1, :] = False
            elif dx == 1:
                neighbour[:, 0] = False
            else:
                neighbour[:, -1] = False
            grown |= neighbour & close
        if np.array_equal(grown, background):
            break
        background = grown
    return ~(background | enclosed_background(pixels, background))


def enclosed_background(pixels: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Pixels cut off from the border (e.g. sky between legs) that match a common background colour."""
    if not background.any():
        return np.zeros(background.shape, dtype=bool)
    bins = pixels[background] // 8
    keys, counts = np.unique(bins[:, 0] * 1024 + bins[:, 1] * 32 + bins[:, 2], return_counts=True)
    frequent = keys[counts >= 0.01 * counts.sum()]
    centres = np.stack([frequent // 1024, (frequent // 32) % 32, frequent % 32], axis=1) * 8 + 4
    candidates = ~background
    distance = np.full(background.shape, np.inf)
    for centre in centres:
        distance = np.minimum(distance, np.abs(pixels - centre).max(axis=2))
    return candidates & (distance <= NEIGHBOR_TOLERANCE)


def provided_mask(path: Path, reference: Path) -> np.ndarray:
    mask_image = Image.open(path).convert("L")
    reference_size = Image.open(reference).size
    if mask_image.size != reference_size:
        raise ValueError(f"reference mask is {mask_image.size[0]}x{mask_image.size[1]}, reference image is {reference_size[0]}x{reference_size[1]}")
    mask_image.thumbnail((WORK_SIZE, WORK_SIZE), Image.Resampling.NEAREST)
    return np.asarray(mask_image) > 127


def component_sizes(mask: np.ndarray) -> list[int]:
    """Sizes of 4-connected foreground components, largest first."""
    seen = np.zeros(mask.shape, dtype=bool)
    height, width = mask.shape
    sizes = []
    for start_y, start_x in zip(*np.nonzero(mask)):
        if seen[start_y, start_x]:
            continue
        seen[start_y, start_x] = True
        queue = deque([(start_y, start_x)])
        size = 0
        while queue:
            y, x = queue.popleft()
            size += 1
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((ny, nx))
        sizes.append(size)
    return sorted(sizes, reverse=True)


def segmentation_quality(foreground: np.ndarray) -> dict[str, Any]:
    fraction = float(foreground.mean())
    sizes = component_sizes(foreground)
    largest_share = sizes[0] / sum(sizes) if sizes else 0.0
    # The outermost pixels seed the background, so look at a thin band just inside them.
    band = 3
    border = np.concatenate([foreground[1:band + 1, :].ravel(), foreground[-band - 1:-1, :].ravel(),
                             foreground[:, 1:band + 1].ravel(), foreground[:, -band - 1:-1].ravel()])
    border_fraction = float(border.mean())
    padded = np.pad(foreground, 1)
    interior = padded[1:-1, 1:-1] & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    area = int(foreground.sum())
    roughness = float((foreground & ~interior).sum() / np.sqrt(area)) if area else 0.0
    reasons = []
    if not 0.02 <= fraction <= 0.85:
        reasons.append(f"foreground covers {fraction:.1%} of the image (expected 2-85%)")
    if largest_share < MIN_LARGEST_COMPONENT_SHARE:
        reasons.append(f"foreground is fragmented: largest blob is {largest_share:.0%} of it across {len(sizes)} blobs")
    if roughness > MAX_BOUNDARY_ROUGHNESS:
        reasons.append(f"outline is speckled or full of holes (boundary roughness {roughness:.1f}, expected <= {MAX_BOUNDARY_ROUGHNESS:g})")
    if border_fraction > MAX_BORDER_FOREGROUND:
        reasons.append(f"foreground touches {border_fraction:.0%} of the image border (background not separated)")
    return {
        "reference_foreground_fraction": round(fraction, 4),
        "largest_component_share": round(largest_share, 4),
        "component_count": len(sizes),
        "border_foreground_fraction": round(border_fraction, 4),
        "boundary_roughness": round(roughness, 2),
        "reliable": not reasons,
        "unreliable_reasons": reasons,
    }


def normalize(mask: np.ndarray) -> np.ndarray | None:
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if not len(rows) or not len(cols):
        return None
    cropped = mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    side = max(cropped.shape)
    square = np.zeros((side, side), dtype=bool)
    top = (side - cropped.shape[0]) // 2
    left = (side - cropped.shape[1]) // 2
    square[top:top + cropped.shape[0], left:left + cropped.shape[1]] = cropped
    resized = Image.fromarray(square.astype(np.uint8) * 255).resize((NORMALIZED_SIZE, NORMALIZED_SIZE), Image.Resampling.BILINEAR)
    return np.asarray(resized) >= 128


def iou(first: np.ndarray, second: np.ndarray) -> float:
    union = np.logical_or(first, second).sum()
    return float(np.logical_and(first, second).sum() / union) if union else 0.0


def compare(reference: Path, view_masks: dict[str, np.ndarray], overlay_path: Path, mask_path: Path | None = None) -> dict[str, Any]:
    if mask_path is not None:
        foreground = provided_mask(mask_path, reference)
        method = "provided reference mask"
    else:
        foreground = reference_foreground(reference)
        method = "border-grown background segmentation"
    quality = segmentation_quality(foreground)
    if mask_path is not None:
        # A hand-made mask is trusted as the outline; only an empty or full mask is rejected.
        quality["unreliable_reasons"] = [reason for reason in quality["unreliable_reasons"] if reason.startswith("foreground covers")]
        quality["reliable"] = not quality["unreliable_reasons"]
    reference_mask = normalize(foreground)
    result: dict[str, Any] = {
        "advisory": True,
        "method": f"{method}; bounding-box normalized IoU; best of direct and mirrored",
        **quality,
        "views": {},
    }
    if reference_mask is None:
        result["reliable"] = False
        return result
    best: tuple[float, str, np.ndarray] | None = None
    for title, mask in view_masks.items():
        cad_mask = normalize(mask)
        if cad_mask is None:
            continue
        direct = iou(reference_mask, cad_mask)
        mirrored_mask = cad_mask[:, ::-1]
        mirrored = iou(reference_mask, mirrored_mask)
        score, chosen, is_mirrored = (mirrored, mirrored_mask, True) if mirrored > direct else (direct, cad_mask, False)
        result["views"][title] = {"iou": round(score, 4), "mirrored": is_mirrored}
        if best is None or score > best[0]:
            best = (score, title, chosen)
    if best is None:
        return result
    result["best_view"] = best[1]
    result["best_iou"] = round(best[0], 4)
    overlay = np.full((NORMALIZED_SIZE, NORMALIZED_SIZE, 3), 255, dtype=np.uint8)
    overlay[reference_mask & best[2]] = (120, 120, 120)
    overlay[reference_mask & ~best[2]] = (214, 69, 65)
    overlay[~reference_mask & best[2]] = (52, 120, 200)
    Image.fromarray(overlay).resize((NORMALIZED_SIZE * 3, NORMALIZED_SIZE * 3), Image.Resampling.NEAREST).save(overlay_path, format="PNG", optimize=True)
    result["overlay_legend"] = "gray: both; red: reference only (CAD missing); blue: CAD only (extra)"
    return result

#!/usr/bin/env python3
"""Advisory silhouette comparison between a reference image and CAD view masks.

This is a coarse, scale- and position-normalized overlap score, not a visual
acceptance gate. The reference foreground is estimated by growing the
background inward from the image border, so it works for illustrations and
product shots on plain or smoothly varying backgrounds and degrades on busy
photographs; the result reports when the estimate looks unreliable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


WORK_SIZE = 256
NORMALIZED_SIZE = 160
NEIGHBOR_TOLERANCE = 14


def reference_foreground(path: Path) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    image.thumbnail((WORK_SIZE, WORK_SIZE), Image.Resampling.BILINEAR)
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
    return ~background


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


def compare(reference: Path, view_masks: dict[str, np.ndarray], overlay_path: Path) -> dict[str, Any]:
    foreground = reference_foreground(reference)
    fraction = float(foreground.mean())
    reference_mask = normalize(foreground)
    result: dict[str, Any] = {
        "advisory": True,
        "method": "border-grown background segmentation; bounding-box normalized IoU; best of direct and mirrored",
        "reference_foreground_fraction": round(fraction, 4),
        "reliable": 0.02 <= fraction <= 0.85,
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

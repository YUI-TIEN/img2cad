#!/usr/bin/env python3
"""Trace colour regions of a reference image into pixel outlines.

Each pixel inside the subject (the --mask, or the whole image) is assigned to
the nearest palette colour given with --color. Connected regions of the
requested colours are traced into simplified outline polygons in image pixel
coordinates, with interior holes listed separately (for example the white
highlight inside a black eye). Feed the outlines to
`img2cad_lib.projected_decal` to build exact painted details.

Run with the CAD interpreter (it has numpy, scipy and Pillow):

    .venv-cad/bin/python scripts/trace_regions.py reference.png --mask mask.png \\
        --color white=245,245,242 --color black=25,25,25 --color pink=240,170,165 \\
        --trace black --trace pink --out regions.json --overlay regions.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

# Moore neighbourhood, clockwise starting west (row, col offsets).
NEIGHBOURS = [(0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1)]


def parse_color(raw: str) -> tuple[str, tuple[int, int, int]]:
    name, _, rgb = raw.partition("=")
    values = tuple(int(value) for value in rgb.split(","))
    if not name or len(values) != 3 or not all(0 <= value <= 255 for value in values):
        raise argparse.ArgumentTypeError("expected name=r,g,b, e.g. black=25,25,25")
    return name, values  # type: ignore[return-value]


def trace_boundary(component: np.ndarray) -> list[tuple[int, int]]:
    """Outer boundary of one 8-connected component as (x, y) pixel centres, in order."""
    padded = np.pad(component, 1)
    rows, cols = np.nonzero(padded)
    start = (int(rows[0]), int(cols[0]))  # top-most, then left-most pixel
    boundary = [start]
    current, backtrack = start, 0  # came from the west
    for _ in range(4 * padded.size):
        for step in range(8):
            direction = (backtrack + step) % 8
            candidate = (current[0] + NEIGHBOURS[direction][0], current[1] + NEIGHBOURS[direction][1])
            if padded[candidate]:
                # Next search starts just after the neighbour we came from.
                backtrack = (direction + 5) % 8
                current = candidate
                break
        else:
            break  # isolated pixel
        if current == start:
            break
        boundary.append(current)
    return [(col - 1, row - 1) for row, col in boundary]


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker simplification of a closed outline."""
    if len(points) < 4:
        return points

    def reduce(segment: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(segment) < 3:
            return segment
        (x0, y0), (x1, y1) = segment[0], segment[-1]
        length = max(np.hypot(x1 - x0, y1 - y0), 1e-9)
        distances = [abs((x1 - x0) * (y0 - y) - (x0 - x) * (y1 - y0)) / length for x, y in segment[1:-1]]
        index = int(np.argmax(distances)) + 1
        if distances[index - 1] <= tolerance:
            return [segment[0], segment[-1]]
        return reduce(segment[:index + 1])[:-1] + reduce(segment[index:])

    # Split the closed loop at its farthest point from the start.
    far = int(np.argmax([np.hypot(x - points[0][0], y - points[0][1]) for x, y in points]))
    first = reduce(points[:far + 1])
    second = reduce(points[far:] + [points[0]])
    return first[:-1] + second[:-1]


def classify(pixels: np.ndarray, palette: dict[str, tuple[int, int, int]]) -> tuple[np.ndarray, list[str]]:
    names = list(palette)
    centres = np.array([palette[name] for name in names], dtype=np.float64)
    distances = np.linalg.norm(pixels[:, :, None, :].astype(np.float64) - centres[None, None, :, :], axis=3)
    return np.argmin(distances, axis=2), names


def trace(reference: Path, palette: dict[str, tuple[int, int, int]], targets: list[str], mask_path: Path | None,
          min_area: int, tolerance: float, edge_band: int = 0) -> dict[str, Any]:
    image = Image.open(reference).convert("RGB")
    pixels = np.asarray(image)
    inside = np.ones(pixels.shape[:2], dtype=bool)
    if mask_path is not None:
        mask = Image.open(mask_path).convert("L")
        if mask.size != image.size:
            raise ValueError(f"mask is {mask.size}, reference is {image.size}")
        inside = np.asarray(mask) > 127
    labels, names = classify(pixels, palette)
    # Pixels near the subject's outline mix with the background; regions that
    # touch this band are usually background bleeding in, not paint.
    edge = inside & ~ndimage.binary_erosion(inside, iterations=edge_band) if edge_band > 0 else np.zeros_like(inside)
    result: dict[str, Any] = {"reference": str(reference), "size": list(image.size), "palette": {name: list(rgb) for name, rgb in palette.items()},
                              "coordinates": "image pixels, x right, y down", "regions": {}}
    for target in targets:
        region_mask = inside & (labels == names.index(target))
        # Drop speckle before labelling so specks do not become regions.
        region_mask = ndimage.binary_opening(region_mask, iterations=1)
        components, count = ndimage.label(region_mask, structure=np.ones((3, 3)))
        regions = []
        for index in range(1, count + 1):
            component = components == index
            area = int(component.sum())
            if area < min_area or (component & edge).any():
                continue
            filled = ndimage.binary_fill_holes(component)
            outline = simplify([(float(x), float(y)) for x, y in trace_boundary(filled)], tolerance)
            holes = []
            hole_labels, hole_count = ndimage.label(filled & ~component, structure=np.ones((3, 3)))
            for hole_index in range(1, hole_count + 1):
                hole = hole_labels == hole_index
                if hole.sum() >= min_area:
                    holes.append(simplify([(float(x), float(y)) for x, y in trace_boundary(hole)], tolerance))
            rows, cols = np.nonzero(component)
            regions.append({
                "area_px": area,
                "centroid_px": [round(float(cols.mean()), 1), round(float(rows.mean()), 1)],
                "bbox_px": [int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())],
                "outline": [[round(x, 1), round(y, 1)] for x, y in outline],
                "holes": [[[round(x, 1), round(y, 1)] for x, y in hole] for hole in holes],
            })
        regions.sort(key=lambda region: (region["centroid_px"][1], region["centroid_px"][0]))
        result["regions"][target] = regions
    return result


def draw_overlay(reference: Path, traced: dict[str, Any], output: Path) -> None:
    image = Image.open(reference).convert("RGB")
    image = Image.blend(image, Image.new("RGB", image.size, (255, 255, 255)), 0.45)
    draw = ImageDraw.Draw(image)
    outline_colors = [(220, 30, 30), (20, 110, 230), (20, 160, 60), (200, 120, 0)]
    for color_index, (name, regions) in enumerate(traced["regions"].items()):
        color = outline_colors[color_index % len(outline_colors)]
        for index, region in enumerate(regions):
            draw.line([tuple(point) for point in region["outline"]] + [tuple(region["outline"][0])], fill=color, width=2)
            for hole in region["holes"]:
                draw.line([tuple(point) for point in hole] + [tuple(hole[0])], fill=color, width=1)
            draw.text(tuple(region["centroid_px"]), f"{name}[{index}]", fill=color)
    image.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--color", type=parse_color, action="append", required=True, help="palette entry name=r,g,b; include every colour present on the subject")
    parser.add_argument("--trace", action="append", required=True, help="palette name whose regions to trace (repeatable)")
    parser.add_argument("--mask", type=Path, help="white = subject; pixels outside are ignored")
    parser.add_argument("--min-area", type=int, default=30, help="ignore regions smaller than this many pixels")
    parser.add_argument("--simplify", type=float, default=1.0, help="outline simplification tolerance in pixels")
    parser.add_argument("--edge-band", type=int, default=4, help="drop regions within this many pixels of the mask outline (0 keeps them)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, help="write the traced outlines over the reference for checking")
    args = parser.parse_args()
    palette = dict(args.color)
    unknown = [name for name in args.trace if name not in palette]
    if unknown:
        parser.error(f"--trace names not in the palette: {unknown}")
    traced = trace(args.reference, palette, args.trace, args.mask, args.min_area, args.simplify, args.edge_band if args.mask else 0)
    args.out.write_text(json.dumps(traced, indent=1) + "\n", encoding="utf-8")
    if args.overlay:
        draw_overlay(args.reference, traced, args.overlay)
    print(json.dumps({name: [{"centroid_px": region["centroid_px"], "area_px": region["area_px"], "points": len(region["outline"]), "holes": len(region["holes"])}
                             for region in regions] for name, regions in traced["regions"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

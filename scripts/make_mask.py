#!/usr/bin/env python3
"""Make a subject mask (white = subject) for --reference-mask and trace_regions.

    img2cad mask photo.png mask.png --polygon "120,40 300,38 310,260 115,262"
    img2cad mask photo.png mask.png --ellipse 290,112,122,97 --polygon "..."    # union of shapes
    img2cad mask photo.png mask.png --seed 300,200 --tolerance 18              # grow a colour region
    img2cad mask photo.png mask.png --background-seed 5,5 --tolerance 12      # everything except the grown background

Shapes are unioned; `--subtract-polygon` removes areas (a gap between legs).
Seeds grow over neighbouring pixels within `--tolerance` of the seed colour
(shading-tolerant distance), so a plain background or a flat-coloured part is
one click. Always look at the written `*_check.png`: the photo darkened
outside the mask.

There is no learned segmentation here (no SAM): it would need large model
downloads. Draw polygons on the gridded zooms the agent already uses, or seed
a clean background.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def parse_points(text: str) -> list[tuple[float, float]]:
    points = [tuple(float(v) for v in pair.split(",")) for pair in text.split()]
    if len(points) < 3 or any(len(p) != 2 for p in points):
        raise argparse.ArgumentTypeError("polygon needs at least three 'x,y' points separated by spaces")
    return points  # type: ignore[return-value]


def parse_numbers(count: int):
    def parse(text: str) -> tuple[float, ...]:
        values = tuple(float(v) for v in text.split(","))
        if len(values) != count:
            raise argparse.ArgumentTypeError(f"expected {count} comma-separated numbers")
        return values
    return parse


def features(rgb: np.ndarray) -> np.ndarray:
    """Shading-tolerant colour features (same idea as the registered overlay)."""
    rgb = rgb.astype(np.float64)
    return np.stack([0.5 * rgb.mean(axis=-1), rgb[..., 0] - rgb[..., 1], rgb[..., 1] - rgb[..., 2]], axis=-1)


def grow(rgb: np.ndarray, seed: tuple[float, float], tolerance: float) -> np.ndarray:
    from scipy import ndimage

    x, y = int(round(seed[0])), int(round(seed[1]))
    feats = features(rgb)
    close = np.linalg.norm(feats - feats[y, x], axis=-1) <= tolerance
    labels, _ = ndimage.label(close)
    return labels == labels[y, x]


def make_mask(image_path: Path, polygons=(), ellipses=(), seeds=(), background_seeds=(), subtract=(), tolerance: float = 15.0) -> np.ndarray:
    photo = Image.open(image_path).convert("RGB")
    rgb = np.asarray(photo)
    shapes = Image.new("L", photo.size, 0)
    draw = ImageDraw.Draw(shapes)
    for polygon in polygons:
        draw.polygon(polygon, fill=255)
    for cx, cy, rx, ry in ellipses:
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    mask = np.asarray(shapes) > 127
    for seed in seeds:
        mask |= grow(rgb, seed, tolerance)
    if background_seeds:
        background = np.zeros(mask.shape, dtype=bool)
        for seed in background_seeds:
            background |= grow(rgb, seed, tolerance)
        mask |= ~background
    if subtract:
        cut = Image.new("L", photo.size, 0)
        cut_draw = ImageDraw.Draw(cut)
        for polygon in subtract:
            cut_draw.polygon(polygon, fill=255)
        mask &= ~(np.asarray(cut) > 127)
    if not mask.any():
        raise ValueError("the mask is empty")
    return mask


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--polygon", type=parse_points, action="append", default=[], help="'x,y x,y x,y ...' in image pixels (repeatable)")
    parser.add_argument("--ellipse", type=parse_numbers(4), action="append", default=[], help="cx,cy,rx,ry (repeatable)")
    parser.add_argument("--seed", type=parse_numbers(2), action="append", default=[], help="x,y inside a subject region to grow (repeatable)")
    parser.add_argument("--background-seed", type=parse_numbers(2), action="append", default=[], help="x,y on a plain background; everything else is subject")
    parser.add_argument("--subtract-polygon", type=parse_points, action="append", default=[], help="area to remove (repeatable)")
    parser.add_argument("--tolerance", type=float, default=15.0, help="colour tolerance for seeds")
    args = parser.parse_args()
    if not (args.polygon or args.ellipse or args.seed or args.background_seed):
        parser.error("give at least one --polygon, --ellipse, --seed or --background-seed")
    mask = make_mask(args.image, args.polygon, args.ellipse, args.seed, args.background_seed, args.subtract_polygon, args.tolerance)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((mask * 255).astype(np.uint8)).save(args.out)
    check = np.asarray(Image.open(args.image).convert("RGB")).astype(np.float64)
    check[~mask] *= 0.25
    check_path = args.out.with_name(args.out.stem + "_check.png")
    Image.fromarray(check.astype(np.uint8)).save(check_path)
    print(f"mask: {args.out} ({mask.mean():.1%} of the image); check: {check_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

Learned segmentation (optional): `--sam` uses Meta's SAM 2 when it is
installed (`pip install "img2cad[sam]"`). Give it what to cut with clicks
and/or a box; the mask is unioned with any shapes above:

    img2cad mask photo.png mask.png --sam --point 300,200 --point 340,260 --negative 40,40
    img2cad mask photo.png mask.png --sam --box 120,40,480,390
    img2cad mask photo.png mask.png --sam --sam-model facebook/sam2.1-hiera-large

The model is fetched from Hugging Face on first use (or pass a local
`--sam-checkpoint` and `--sam-config`). Without SAM 2 installed, `--sam`
fails with an install hint; the other modes need nothing extra.

Busy backgrounds without SAM: `--auto` separates the object from the
background by colour statistics, GrabCut-style. Everything outside `--box`
(default: a 4 % border) is background; colour models of object and
background are refined over several rounds, smoothed, and the largest
connected region is kept. It needs the object's colours to differ from the
background's somewhere; check the `*_check.png`.

    img2cad mask photo.png mask.png --auto --box 120,40,480,390
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


def sam_mask(rgb: np.ndarray, points=(), negatives=(), box=None, model: str = "facebook/sam2.1-hiera-small",
             checkpoint: str | None = None, config: str | None = None) -> np.ndarray:
    """Best-scoring SAM 2 mask for the given clicks / box."""
    try:
        from sam2.sam2_image_predictor import SAM2ImagePredictor
    except ImportError as error:
        raise RuntimeError('SAM 2 is not installed: pip install "img2cad[sam]" (or pip install sam2 torch)') from error
    if not points and box is None:
        raise ValueError("--sam needs at least one --point or a --box")
    if checkpoint:
        from sam2.build_sam import build_sam2

        predictor = SAM2ImagePredictor(build_sam2(config, checkpoint))
    else:
        predictor = SAM2ImagePredictor.from_pretrained(model)
    predictor.set_image(rgb)
    coords = [list(p) for p in points] + [list(p) for p in negatives]
    labels = [1] * len(points) + [0] * len(negatives)
    masks, scores, _ = predictor.predict(
        point_coords=np.array(coords, dtype=np.float32) if coords else None,
        point_labels=np.array(labels, dtype=np.int32) if coords else None,
        box=np.array(box, dtype=np.float32) if box is not None else None,
        multimask_output=box is None and len(points) == 1)
    masks = np.asarray(masks)
    if masks.ndim == 2:
        masks = masks[None]
    return masks[int(np.argmax(np.asarray(scores).reshape(-1)))] > 0.5


def _kmeans(samples: np.ndarray, k: int, rng: np.random.Generator, rounds: int = 12) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centres, per-cluster diagonal variances and weights of a small Gaussian mixture (k-means fit)."""
    k = max(1, min(k, len(samples)))
    centres = samples[rng.choice(len(samples), size=k, replace=False)]
    for _ in range(rounds):
        labels = np.argmin(((samples[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            members = samples[labels == j]
            if len(members):
                centres[j] = members.mean(axis=0)
    labels = np.argmin(((samples[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
    variances = np.stack([samples[labels == j].var(axis=0) + 25.0 if np.any(labels == j) else np.full(samples.shape[1], 400.0)
                          for j in range(k)])
    weights = np.bincount(labels, minlength=k) / len(labels) + 1e-6
    return centres, variances, weights


def _log_likelihood(pixels: np.ndarray, model: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    centres, variances, weights = model
    terms = []
    for centre, variance, weight in zip(centres, variances, weights):
        terms.append(np.log(weight) - 0.5 * (((pixels - centre) ** 2) / variance + np.log(variance)).sum(-1))
    stacked = np.stack(terms)
    top = stacked.max(axis=0)
    return top + np.log(np.exp(stacked - top).sum(axis=0))


def auto_mask(rgb: np.ndarray, box: tuple[float, float, float, float] | None = None, rounds: int = 6, clusters: int = 5,
              seed: int = 0) -> np.ndarray:
    """Object vs background by iterated colour mixtures (no learned model); outside `box` is background."""
    from scipy import ndimage

    height, width = rgb.shape[:2]
    if box is None:
        mx, my = max(2, int(width * 0.04)), max(2, int(height * 0.04))
        box = (mx, my, width - mx, height - my)
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    inside = np.zeros((height, width), dtype=bool)
    inside[max(0, y0):min(height, y1), max(0, x0):min(width, x1)] = True
    pixels = rgb.astype(np.float64)
    rng = np.random.default_rng(seed)
    foreground = inside.copy()
    for _ in range(rounds):
        models = []
        for region in (foreground, ~foreground):
            samples = pixels[region]
            if len(samples) > 6000:
                samples = samples[rng.choice(len(samples), size=6000, replace=False)]
            models.append(_kmeans(samples.copy(), clusters, rng))
        ratio = _log_likelihood(pixels, models[0]) - _log_likelihood(pixels, models[1])
        ratio = ndimage.gaussian_filter(ratio, sigma=max(1.0, min(height, width) / 200))
        candidate = (ratio > 0) & inside
        candidate = ndimage.binary_opening(candidate, iterations=2)
        labels, count = ndimage.label(candidate)
        if count == 0:
            break
        sizes = ndimage.sum(candidate, labels, range(1, count + 1))
        candidate = ndimage.binary_fill_holes(labels == int(np.argmax(sizes)) + 1)
        if np.array_equal(candidate, foreground):
            break
        foreground = candidate
    return foreground


def make_mask(image_path: Path, polygons=(), ellipses=(), seeds=(), background_seeds=(), subtract=(), tolerance: float = 15.0,
              sam: dict | None = None, auto: dict | None = None) -> np.ndarray:
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
    if sam is not None:
        mask |= sam_mask(rgb, **sam)
    if auto is not None:
        mask |= auto_mask(rgb, **auto)
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
    parser.add_argument("--auto", action="store_true", help="separate the object from a busy background by colour (no extra install); with --box")
    sam = parser.add_argument_group("SAM 2 (optional, pip install \"img2cad[sam]\")")
    sam.add_argument("--sam", action="store_true", help="add a SAM 2 mask from --point/--negative/--box")
    sam.add_argument("--point", type=parse_numbers(2), action="append", default=[], help="x,y on the object (repeatable)")
    sam.add_argument("--negative", type=parse_numbers(2), action="append", default=[], help="x,y NOT on the object (repeatable)")
    sam.add_argument("--box", type=parse_numbers(4), help="x0,y0,x1,y1 around the object (for --sam and --auto)")
    sam.add_argument("--sam-model", default="facebook/sam2.1-hiera-small", help="Hugging Face model id")
    sam.add_argument("--sam-checkpoint", help="local checkpoint instead of downloading (with --sam-config)")
    sam.add_argument("--sam-config", help="model config name for --sam-checkpoint, e.g. configs/sam2.1/sam2.1_hiera_s.yaml")
    args = parser.parse_args()
    if not (args.polygon or args.ellipse or args.seed or args.background_seed or args.sam or args.auto):
        parser.error("give at least one --polygon, --ellipse, --seed, --background-seed, --auto or --sam")
    sam_options = None
    if args.sam:
        sam_options = {"points": args.point, "negatives": args.negative, "box": args.box, "model": args.sam_model,
                       "checkpoint": args.sam_checkpoint, "config": args.sam_config}
    try:
        mask = make_mask(args.image, args.polygon, args.ellipse, args.seed, args.background_seed, args.subtract_polygon, args.tolerance,
                         sam_options, {"box": args.box} if args.auto else None)
    except RuntimeError as error:
        parser.exit(2, f"FAIL: {error}\n")
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

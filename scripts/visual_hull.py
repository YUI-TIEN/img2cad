#!/usr/bin/env python3
"""Starting body from two or three silhouettes (visual hull).

    img2cad hull views.json --out hull/          # hull.step, outlines.json, model_hull.py

views.json lists orthographic views of the same object, each with a subject
mask (white = object, see `img2cad mask`) and its registration:

    {"views": [
      {"view": "front", "mask": "front_mask.png", "mm_per_px": 0.5, "origin_px": [320, 400]},
      {"view": "right", "mask": "side_mask.png",  "mm_per_px": 0.5, "origin_px": [300, 400]},
      {"view": "top",   "mask": "top_mask.png",   "mm_per_px": 0.5, "origin_px": [320, 240]}
    ]}

Conventions match the comparison panels (Z up): `front` is seen from -Y
(image right = +X, up = +Z), `right` from +X (right = +Y, up = +Z), `top`
from +Z (right = +X, up = +Y). `origin_px` is where model (0, 0, 0) appears.

Photos from any angle work too: instead of "view", give each one the camera
fitted by `img2cad camera` (its fit.json, or the frame inline). All photos
must share one model frame, so fit them against the same known features:

    {"views": [
      {"frame": "fit-a/fit.json", "mask": "a_mask.png"},
      {"frame": {"mm_per_px": 0.3, "origin_px": [270, 240], "view": [0.5, -0.7, 0.5], "roll": 0, "distance": 600},
       "mask": "b_mask.png"}
    ]}

Each silhouette is extruded straight through the model and the extrusions are
intersected. The result contains the object but is larger wherever no view
sees a concavity (a cup's hollow, the space between legs): it is a blockout,
not the answer.

A hollow that opens toward a camera can be cut in: give the opening's mask
in that view (the rim's inside, white) and how deep it goes, from the
object's face nearest that camera. Depth is not in any silhouette: take it
from a known dimension, a side photo or the plan, and say it is estimated:

    {"views": [...],
     "cavities": [{"view": "top", "mask": "opening_mask.png", "mm_per_px": 0.5, "origin_px": [320, 240], "depth": 72}]}

A cavity may use a fitted "frame" instead of "view", like the views. `model_hull.py` rebuilds it from the traced outlines with
`img2cad_lib.visual_hull`, so the agent can start from it and carve.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

VIEWS = ("front", "right", "top")


def outline_from_mask(mask_path: Path, simplify_px: float = 1.0) -> list[tuple[float, float]]:
    """Outer boundary of the largest white region, in image pixels."""
    from scipy import ndimage

    from trace_regions import simplify, trace_boundary

    mask = np.asarray(Image.open(mask_path).convert("L")) > 127
    labels, count = ndimage.label(mask)
    if count == 0:
        raise ValueError(f"{mask_path}: mask is empty")
    sizes = ndimage.sum(mask, labels, range(1, count + 1))
    component = ndimage.binary_fill_holes(labels == (int(np.argmax(sizes)) + 1))
    return simplify([(float(x), float(y)) for x, y in trace_boundary(component)], simplify_px)


def to_mm(outline_px: list[tuple[float, float]], mm_per_px: float, origin_px: tuple[float, float]) -> list[tuple[float, float]]:
    """Image pixels -> (screen right, screen up) in mm."""
    return [((x - origin_px[0]) * mm_per_px, (origin_px[1] - y) * mm_per_px) for x, y in outline_px]


def run(spec_path: Path, out_dir: Path, simplify_px: float = 1.0) -> dict[str, Any]:
    from build123d import export_step

    from img2cad_lib import visual_hull

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    views = spec.get("views") or []
    if len(views) < 2:
        raise ValueError("a visual hull needs at least two views")
    seen = set()
    outlines = []
    for index, view in enumerate(views):
        outline = outline_from_mask((spec_path.parent / view["mask"]).resolve(), simplify_px)
        if "frame" in view:
            frame = view["frame"]
            if isinstance(frame, str):
                frame = json.loads((spec_path.parent / frame).read_text(encoding="utf-8"))
                frame = frame.get("frame", frame)  # accept img2cad camera's fit.json
            mm = to_mm(outline, float(frame["mm_per_px"]), tuple(frame["origin_px"]))
            outlines.append({"frame": {key: frame.get(key) for key in ("view", "roll", "distance")},
                             "outline_mm": [[round(a, 3), round(b, 3)] for a, b in mm]})
            seen.add(f"camera {index + 1}")
            continue
        name = view.get("view")
        if name not in VIEWS or name in seen:
            raise ValueError(f"each view must be one of {', '.join(VIEWS)} (at most once) or carry a fitted frame")
        seen.add(name)
        outlines.append({"view": name, "outline_mm": [[round(a, 3), round(b, 3)] for a, b in
                                                       to_mm(outline, float(view["mm_per_px"]), tuple(view["origin_px"]))]})
    cavities = []
    for cavity in spec.get("cavities") or []:
        outline = outline_from_mask((spec_path.parent / cavity["mask"]).resolve(), simplify_px)
        if "depth" not in cavity:
            raise ValueError("each cavity needs a depth in mm (it is not visible in any silhouette)")
        if "frame" in cavity:
            frame = cavity["frame"]
            if isinstance(frame, str):
                frame = json.loads((spec_path.parent / frame).read_text(encoding="utf-8"))
                frame = frame.get("frame", frame)
            mm = to_mm(outline, float(frame["mm_per_px"]), tuple(frame["origin_px"]))
            entry = {"frame": {key: frame.get(key) for key in ("view", "roll", "distance")}}
        else:
            if cavity.get("view") not in VIEWS:
                raise ValueError(f"each cavity's view must be one of {', '.join(VIEWS)} or a fitted frame")
            mm = to_mm(outline, float(cavity["mm_per_px"]), tuple(cavity["origin_px"]))
            entry = {"view": cavity["view"]}
        cavities.append({**entry, "depth": float(cavity["depth"]), "outline_mm": [[round(a, 3), round(b, 3)] for a, b in mm]})
    hull = visual_hull(outlines, cavities)
    out_dir.mkdir(parents=True, exist_ok=True)
    export_step(hull, str(out_dir / "hull.step"))
    (out_dir / "outlines.json").write_text(json.dumps({"views": outlines, "cavities": cavities}) + "\n", encoding="utf-8")
    (out_dir / "model_hull.py").write_text(
        '"""Visual-hull blockout: the intersection of the traced silhouettes. Carve concavities from here."""\n\n'
        "import json\nfrom pathlib import Path\n\nfrom build123d import *\nfrom img2cad_lib import visual_hull\n\n"
        "OUTLINES = json.loads((Path(__file__).parent / \"outlines.json\").read_text())\n\n\n"
        "def build_model():\n    return visual_hull(OUTLINES)\n", encoding="utf-8")
    box = hull.bounding_box()
    report = {"views": sorted(seen), "cavities": len(cavities), "volume_mm3": round(float(hull.volume), 2),
              "size_mm": [round(float(v), 3) for v in (box.size.X, box.size.Y, box.size.Z)],
              "files": {name: str(out_dir / name) for name in ("hull.step", "outlines.json", "model_hull.py")},
              "note": "contains the object; concavities no view sees are filled unless declared as cavities (a blockout, not the final shape)"}
    (out_dir / "hull.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--simplify", type=float, default=1.0, help="outline simplification tolerance in pixels")
    args = parser.parse_args()
    print(json.dumps(run(args.spec, args.out, args.simplify), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

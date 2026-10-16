"""img2cad hull: silhouettes intersect into the expected blockout."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@unittest.skipUnless(os.environ.get("IMG2CAD_CAD_PYTHON"), "set IMG2CAD_CAD_PYTHON to build the hull")
class VisualHullTests(unittest.TestCase):
    def test_cylinder_from_front_and_right_silhouettes(self) -> None:
        import visual_hull

        # A cylinder along X: radius 20 mm, length 80 mm, centred on the origin; 1 px = 0.5 mm.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            front = Image.new("L", (300, 200), 0)
            ImageDraw.Draw(front).rectangle((150 - 80, 100 - 40, 150 + 80, 100 + 40), fill=255)   # 80 x 40 mm rectangle
            front.save(root / "front.png")
            right = Image.new("L", (200, 200), 0)
            ImageDraw.Draw(right).ellipse((100 - 40, 100 - 40, 100 + 40, 100 + 40), fill=255)      # 40 mm circle
            right.save(root / "right.png")
            (root / "views.json").write_text(json.dumps({"views": [
                {"view": "front", "mask": "front.png", "mm_per_px": 0.5, "origin_px": [150, 100]},
                {"view": "right", "mask": "right.png", "mm_per_px": 0.5, "origin_px": [100, 100]},
            ]}), encoding="utf-8")
            report = visual_hull.run(root / "views.json", root / "out")
            x, y, z = report["size_mm"]
            self.assertAlmostEqual(x, 80, delta=1.5)
            self.assertAlmostEqual(y, 40, delta=1.5)
            self.assertAlmostEqual(z, 40, delta=1.5)
            self.assertAlmostEqual(report["volume_mm3"], math.pi * 20 ** 2 * 80, delta=0.04 * math.pi * 20 ** 2 * 80)
            for name in ("hull.step", "outlines.json", "model_hull.py"):
                self.assertTrue((root / "out" / name).is_file(), name)

    def test_declared_cavity_hollows_a_cup(self) -> None:
        import visual_hull

        # A cup: outer radius 20, 40 tall; the opening seen from the top has radius 16 and goes 36 deep. 1 px = 0.5 mm.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def mask(name, draw):
                image = Image.new("L", (200, 200), 0)
                draw(ImageDraw.Draw(image))
                image.save(root / name)

            mask("front.png", lambda d: d.rectangle((60, 20, 140, 100), fill=255))
            mask("right.png", lambda d: d.rectangle((60, 20, 140, 100), fill=255))
            mask("top.png", lambda d: d.ellipse((60, 60, 140, 140), fill=255))
            mask("opening.png", lambda d: d.ellipse((68, 68, 132, 132), fill=255))
            frame = {"mm_per_px": 0.5, "origin_px": [100, 100]}
            spec = {"views": [{"view": v, "mask": f"{v}.png", **frame} for v in ("front", "right", "top")],
                    "cavities": [{"view": "top", "mask": "opening.png", "depth": 36, **frame}]}
            (root / "views.json").write_text(json.dumps(spec))
            report = visual_hull.run(root / "views.json", root / "out")
            cup = math.pi * 20 ** 2 * 40 - math.pi * 16 ** 2 * 36
            self.assertAlmostEqual(report["volume_mm3"] / cup, 1.0, delta=0.04)
            self.assertEqual(report["cavities"], 1)
            del spec["cavities"][0]["depth"]
            (root / "views.json").write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError, "depth"):
                visual_hull.run(root / "views.json", root / "out2")

    def test_sphere_from_three_fitted_cameras_at_odd_angles(self) -> None:
        import numpy as np
        from scipy.spatial import ConvexHull

        import visual_hull
        from img2cad_lib import ImageFrame

        # Truth: a sphere of radius 20 at the origin, seen by three cameras (one with perspective).
        cameras = [
            {"mm_per_px": 0.25, "origin_px": [200, 200], "view": [0.6, -0.7, 0.4], "roll": 0.0, "distance": None},
            {"mm_per_px": 0.25, "origin_px": [200, 200], "view": [-0.8, -0.3, 0.5], "roll": 5.0, "distance": 400.0},
            {"mm_per_px": 0.25, "origin_px": [200, 200], "view": [0.1, 0.4, 0.9], "roll": 0.0, "distance": None},
        ]
        u, v = np.meshgrid(np.linspace(0, 2 * np.pi, 60), np.linspace(0, np.pi, 30))
        surface = np.stack([20 * np.cos(u) * np.sin(v), 20 * np.sin(u) * np.sin(v), 20 * np.cos(v)], -1).reshape(-1, 3)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            views = []
            for index, cam in enumerate(cameras):
                frame = ImageFrame(mm_per_px=cam["mm_per_px"], origin_px=tuple(cam["origin_px"]), view=tuple(cam["view"]), roll=cam["roll"], distance=cam["distance"])
                pixels = np.array([frame.project(*p) for p in surface])
                outline = pixels[ConvexHull(pixels).vertices]
                mask = Image.new("L", (400, 400), 0)
                ImageDraw.Draw(mask).polygon([tuple(p) for p in outline], fill=255)
                mask.save(root / f"m{index}.png")
                (root / f"fit{index}.json").write_text(json.dumps({"frame": cam}), encoding="utf-8")
                views.append({"frame": f"fit{index}.json", "mask": f"m{index}.png"})
            (root / "views.json").write_text(json.dumps({"views": views}), encoding="utf-8")
            report = visual_hull.run(root / "views.json", root / "out")
            sphere = 4 / 3 * math.pi * 20 ** 3
            self.assertGreater(report["volume_mm3"], 0.98 * sphere)   # contains the sphere
            self.assertLess(report["volume_mm3"], 1.6 * sphere)       # three views already carve most of the box away
            for size in report["size_mm"]:
                self.assertTrue(40 * 0.98 < size < 40 * 1.3, report["size_mm"])  # corners no camera trims stay


if __name__ == "__main__":
    unittest.main()

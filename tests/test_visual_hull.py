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


if __name__ == "__main__":
    unittest.main()

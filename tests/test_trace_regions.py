from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import trace_regions  # needs scipy, which is in the CAD environment
except ImportError:  # pragma: no cover - depends on the interpreter
    trace_regions = None


@unittest.skipIf(trace_regions is None, "trace_regions needs scipy (run with .venv-cad/bin/python)")
class TraceRegionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="img2cad-trace-test-")
        self.root = Path(self.temp.name)
        # White face on grey: a black ring "eye" with a white hole, a pink
        # blush with a black stripe, and a black speck on the outline.
        image = Image.new("RGB", (300, 200), (120, 120, 120))
        draw = ImageDraw.Draw(image)
        draw.ellipse((20, 20, 280, 180), fill=(245, 245, 242))
        draw.ellipse((70, 60, 130, 120), fill=(20, 20, 20))
        draw.ellipse((90, 80, 110, 100), fill=(245, 245, 242))
        draw.ellipse((170, 80, 250, 130), fill=(240, 170, 165))
        draw.rectangle((205, 90, 213, 120), fill=(20, 20, 20))
        draw.rectangle((22, 95, 32, 105), fill=(20, 20, 20))
        self.reference = self.root / "reference.png"
        image.save(self.reference)
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).ellipse((20, 20, 280, 180), fill=255)
        self.mask = self.root / "mask.png"
        mask.save(self.mask)
        self.palette = {"white": (245, 245, 242), "black": (20, 20, 20), "pink": (240, 170, 165)}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_traces_regions_with_holes_and_drops_edge_specks(self) -> None:
        traced = trace_regions.trace(self.reference, self.palette, ["black", "pink"], self.mask, min_area=20, tolerance=1.0, edge_band=4)
        black = traced["regions"]["black"]
        self.assertEqual(len(black), 2, "eye ring and blush stripe; the speck on the mask edge is dropped")
        eye = min(black, key=lambda region: region["centroid_px"][0])
        self.assertEqual(len(eye["holes"]), 1)
        x0, y0, x1, y1 = eye["bbox_px"]
        self.assertTrue(68 <= x0 <= 72 and 128 <= x1 <= 132 and 58 <= y0 <= 62 and 118 <= y1 <= 122, eye["bbox_px"])
        pink = traced["regions"]["pink"]
        self.assertEqual(len(pink), 1)
        self.assertEqual(len(pink[0]["holes"]), 1, "the black stripe is a hole in the blush")

    def test_outline_follows_the_region_boundary(self) -> None:
        traced = trace_regions.trace(self.reference, self.palette, ["pink"], self.mask, min_area=20, tolerance=0.5, edge_band=4)
        outline = traced["regions"]["pink"][0]["outline"]
        # Every outline point lies on the drawn ellipse boundary (within 2 px).
        for x, y in outline:
            radius = ((x - 210) / 40) ** 2 + ((y - 105) / 25) ** 2
            self.assertAlmostEqual(radius, 1.0, delta=0.15)


if __name__ == "__main__":
    unittest.main()

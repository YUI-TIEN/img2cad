from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import silhouette  # noqa: E402


def disc_mask(size: tuple[int, int], box: tuple[int, int, int, int]) -> np.ndarray:
    image = Image.new("L", size, 0)
    ImageDraw.Draw(image).ellipse(box, fill=255)
    return np.asarray(image) > 0


class SilhouetteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="img2cad-silhouette-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def reference(self) -> Path:
        # A sky/ground background split with a contrasting ellipse straddling it.
        image = Image.new("RGB", (400, 300), (236, 242, 242))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 200, 400, 300), fill=(220, 229, 221))
        draw.ellipse((100, 120, 300, 240), fill=(190, 128, 80))
        path = self.root / "reference.png"
        image.save(path)
        return path

    def test_background_growth_ignores_ground_plane(self) -> None:
        foreground = silhouette.reference_foreground(self.reference())
        self.assertAlmostEqual(float(foreground.mean()), np.pi * 100 * 60 / (400 * 300), delta=0.03)

    def test_matching_shape_scores_higher_than_wrong_shape(self) -> None:
        overlay = self.root / "overlay.png"
        result = silhouette.compare(self.reference(), {
            "Side": disc_mask((610, 380), (55, 90, 555, 390)),
            "Top": disc_mask((610, 380), (205, 40, 405, 340)),
        }, overlay)
        self.assertTrue(result["advisory"])
        self.assertTrue(result["reliable"])
        self.assertEqual(result["best_view"], "Side")
        self.assertGreater(result["views"]["Side"]["iou"], 0.9)
        self.assertLess(result["views"]["Top"]["iou"], 0.6)
        self.assertTrue(overlay.is_file())

    def test_empty_masks_do_not_produce_a_score(self) -> None:
        result = silhouette.compare(self.reference(), {"Side": np.zeros((10, 10), dtype=bool)}, self.root / "overlay.png")
        self.assertNotIn("best_iou", result)


if __name__ == "__main__":
    unittest.main()

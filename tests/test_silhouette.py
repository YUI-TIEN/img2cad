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

    def test_fragmented_foreground_is_reported_unreliable(self) -> None:
        # An object coloured like its background leaves only scattered specks.
        image = Image.new("RGB", (300, 200), (200, 170, 130))
        draw = ImageDraw.Draw(image)
        for index in range(12):
            x = 20 + index * 22
            draw.rectangle((x, 90 + (index % 3) * 20, x + 6, 96 + (index % 3) * 20), fill=(250, 250, 250))
        path = self.root / "speckled.png"
        image.save(path)
        result = silhouette.compare(path, {"Side": disc_mask((100, 100), (10, 10, 90, 90))}, self.root / "overlay.png")
        self.assertFalse(result["reliable"])
        self.assertTrue(any("fragmented" in reason for reason in result["unreliable_reasons"]))

    def test_speckled_outline_is_reported_unreliable(self) -> None:
        # A textured object on a similar background segments into a connected
        # but speckled blob; roughness, not fragmentation, catches it.
        rng = np.random.default_rng(0)
        pixels = np.full((200, 300, 3), (200, 170, 130), dtype=np.uint8)
        inside = disc_mask((300, 200), (40, 40, 260, 160))
        noise = rng.random((200, 300)) < 0.5
        pixels[inside & noise] = (240, 240, 240)
        pixels[inside & ~noise] = (205, 175, 135)
        path = self.root / "textured.png"
        Image.fromarray(pixels).save(path)
        quality = silhouette.segmentation_quality(silhouette.reference_foreground(path))
        self.assertFalse(quality["reliable"])
        self.assertTrue(any("speckled" in reason for reason in quality["unreliable_reasons"]))

    def test_provided_mask_replaces_segmentation(self) -> None:
        reference = self.root / "speckled.png"
        Image.new("RGB", (300, 200), (200, 170, 130)).save(reference)
        mask = Image.new("L", (300, 200), 0)
        ImageDraw.Draw(mask).ellipse((50, 50, 250, 150), fill=255)
        mask_path = self.root / "mask.png"
        mask.save(mask_path)
        result = silhouette.compare(reference, {"Side": disc_mask((610, 380), (55, 90, 555, 340))}, self.root / "overlay.png", mask_path)
        self.assertTrue(result["reliable"])
        self.assertIn("provided reference mask", result["method"])
        self.assertGreater(result["best_iou"], 0.9)
        Image.new("L", (10, 10), 255).save(mask_path)
        with self.assertRaisesRegex(ValueError, "reference mask is 10x10"):
            silhouette.compare(reference, {"Side": disc_mask((10, 10), (1, 1, 9, 9))}, self.root / "overlay.png", mask_path)

    def test_empty_masks_do_not_produce_a_score(self) -> None:
        result = silhouette.compare(self.reference(), {"Side": np.zeros((10, 10), dtype=bool)}, self.root / "overlay.png")
        self.assertNotIn("best_iou", result)


if __name__ == "__main__":
    unittest.main()

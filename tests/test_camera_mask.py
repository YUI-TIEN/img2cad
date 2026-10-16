"""img2cad camera recovers a known camera and refuses an under-constrained fit; img2cad mask."""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import scipy  # noqa: F401
    import camera_fit
    import make_mask
except ImportError:  # pragma: no cover - CAD environment only
    camera_fit = None


@unittest.skipIf(camera_fit is None, "needs scipy (run with .venv-cad/bin/python)")
class CameraFitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        Image.new("RGB", (640, 480), (30, 30, 30)).save(self.root / "photo.png")
        # Truth: orthographic camera 40 degrees up, 0.5 mm/px.
        self.truth = camera_fit.Camera(40.0, 0.0, 0.0, 0.5, (320.0, 300.0), None)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def circle_pixels(self, cx, cy, z, r, angles):
        pts = np.array([[cx + r * math.cos(a), cy + r * math.sin(a), z] for a in angles])
        return self.truth.project(pts).round(2).tolist()

    def write(self, features, **extra) -> Path:
        path = self.root / "camera.json"
        path.write_text(json.dumps({"image": "photo.png", "projection": "orthographic", "features": features, **extra}), encoding="utf-8")
        return path

    def test_recovers_a_known_camera_and_profile(self) -> None:
        angles = [2 * math.pi * k / 10 for k in range(10)]
        spec = self.write([
            {"name": "base", "type": "circle", "center": [0, 0], "z": 0, "radius": 60, "points": self.circle_pixels(0, 0, 0, 60, angles)},
            {"name": "top", "type": "circle", "center": [0, 0], "z": "fit", "radius": "fit", "points": self.circle_pixels(0, 0, 50, 30, angles)},
            {"name": "side", "type": "revolve_edge", "axis": "top", "side": "right", "points": [self.truth.project(np.array([[40.0, 0, 20]]))[0].tolist()]},
        ])
        report = camera_fit.run(spec, self.root / "fit")
        self.assertEqual(report["status"], "ok", report["problems"])
        self.assertAlmostEqual(report["values"]["elevation"]["value"], 40.0, delta=0.2)
        self.assertAlmostEqual(report["values"]["top.z"]["value"], 50.0, delta=0.5)
        self.assertAlmostEqual(report["values"]["top.radius"]["value"], 30.0, delta=0.3)
        edge = report["revolve_edges"]["side"][0]
        self.assertAlmostEqual(edge["radius"], 40.0, delta=0.5)
        self.assertAlmostEqual(edge["z"], 20.0, delta=0.8)
        self.assertTrue((self.root / "fit/overlay.png").is_file())
        self.assertIn("IMAGE_FRAME = ImageFrame(", (self.root / "fit/frame.py").read_text())

    def test_refuses_when_depth_and_height_trade_off(self) -> None:
        # The upper circle's centre is free, and only its front arc is seen:
        # moving it back and down along the pixel rays fits as well, so its height is not pinned.
        front = [math.pi * (1.2 + 0.15 * k) for k in range(5)]
        spec = self.write([
            {"name": "base", "type": "circle", "center": [0, 0], "z": 0, "radius": 60,
             "points": self.circle_pixels(0, 0, 0, 60, [2 * math.pi * k / 8 for k in range(8)])},
            {"name": "top", "type": "circle", "center": "fit", "z": "fit", "radius": 30, "arc": "front",
             "points": self.circle_pixels(0, 0, 50, 30, front)},
        ])
        report = camera_fit.run(spec, self.root / "fit")
        self.assertEqual(report["status"], "refused")
        self.assertTrue(any("not pinned down" in problem for problem in report["problems"]), report["problems"])
        self.assertFalse((self.root / "fit/frame.py").exists())

    def test_priors_are_reported_as_assumptions(self) -> None:
        angles = [2 * math.pi * k / 10 for k in range(10)]
        spec = self.write([
            {"name": "base", "type": "circle", "center": [0, 0], "z": 0, "radius": 60, "points": self.circle_pixels(0, 0, 0, 60, angles)},
            {"name": "top", "type": "circle", "center": "fit", "z": 50, "radius": 30, "points": self.circle_pixels(0, 0, 50, 30, angles)},
        ], priors={"top.center_y": [0, 3]})
        report = camera_fit.run(spec, self.root / "fit")
        self.assertIn("prior top.center_y", report["assumptions"])

    def test_mask_unions_shapes_and_grows_seeds(self) -> None:
        photo = np.zeros((100, 100, 3), dtype=np.uint8)
        photo[:, :] = (200, 200, 200)
        photo[20:60, 20:60] = (200, 40, 30)
        Image.fromarray(photo).save(self.root / "m.png")
        mask = make_mask.make_mask(self.root / "m.png", seeds=[(30, 30)])
        self.assertEqual(int(mask.sum()), 40 * 40)
        mask = make_mask.make_mask(self.root / "m.png", background_seeds=[(2, 2)], subtract=[[(20, 20), (30, 20), (30, 30), (20, 30)]])
        self.assertLess(int(mask.sum()), 40 * 40)
        self.assertTrue(mask[50, 50] and not mask[2, 2])

    def test_auto_mask_separates_an_object_from_a_busy_background(self) -> None:
        import numpy as np

        import make_mask

        rng = np.random.default_rng(3)
        rows, cols = np.mgrid[0:240, 0:320]
        stripes = np.stack([128 + 100 * np.sin(cols / 9 + rows / 13), 128 + 100 * np.sin(cols / 17 - rows / 7 + 1),
                            128 + 90 * np.cos(cols / 11)], -1) + rng.normal(0, 12, (240, 320, 3))
        target = ((cols - 170) / 80) ** 2 + ((rows - 120) / 60) ** 2 < 1
        shade = 0.6 + 0.4 * (1 - (cols - 170) / 160)
        body = np.stack([200 * shade, 40 * shade + 20, 60 * shade + 10], -1) + rng.normal(0, 8, (240, 320, 3))
        image = np.where(target[..., None], body, stripes).clip(0, 255).astype(np.uint8)
        found = make_mask.auto_mask(image, box=(70, 40, 270, 200))
        self.assertGreater((found & target).sum() / (found | target).sum(), 0.9)

    def test_sam_mask_uses_the_predictor_and_reports_a_missing_install(self) -> None:
        import types

        photo = np.zeros((60, 80, 3), dtype=np.uint8)
        Image.fromarray(photo).save(self.root / "s.png")
        calls = {}

        class FakePredictor:
            @classmethod
            def from_pretrained(cls, model):
                calls["model"] = model
                return cls()

            def set_image(self, rgb):
                calls["shape"] = rgb.shape

            def predict(self, point_coords, point_labels, box, multimask_output):
                calls["labels"] = point_labels.tolist()
                low, high = np.zeros((60, 80)), np.zeros((60, 80))
                high[10:30, 20:50] = 1
                return np.stack([low, high]), np.array([0.2, 0.9]), None

        module = types.ModuleType("sam2.sam2_image_predictor")
        module.SAM2ImagePredictor = FakePredictor
        saved = {name: sys.modules.get(name) for name in ("sam2", "sam2.sam2_image_predictor")}
        sys.modules["sam2"] = types.ModuleType("sam2")
        sys.modules["sam2.sam2_image_predictor"] = module
        try:
            mask = make_mask.make_mask(self.root / "s.png", sam={"points": [(30, 20)], "negatives": [(2, 2)], "box": None, "model": "m"})
        finally:
            for name, value in saved.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value
        self.assertEqual(int(mask.sum()), 20 * 30)          # the higher-scoring mask
        self.assertEqual(calls["labels"], [1, 0])
        self.assertEqual(calls["shape"], (60, 80, 3))
        if "sam2" not in sys.modules:
            with self.assertRaisesRegex(RuntimeError, "img2cad\\[sam\\]"):
                make_mask.sam_mask(photo, points=[(1, 1)])


if __name__ == "__main__":
    unittest.main()

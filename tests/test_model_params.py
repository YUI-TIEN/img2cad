"""model.py parameters: found, edited in place, and served by the viewer for live rebuilds."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_params import apply_params, find_params  # noqa: E402

SOURCE = '''"""doc"""
from build123d import *

HEIGHT = 20.0  # [10, 40] overall height, mm
SPOKES = 6  # [3, 12]
OFFSET = -2.5
NAME_LENGTH: float = 7.25  # annotated
SIZES = (1, 2)  # tuple: one parameter per element
lower = 3  # lowercase: not a parameter
FLAG = True  # bool: a switch
DERIVED = HEIGHT * 2  # computed: not a parameter


def build_model():
    wall = 1.5  # [1, 3] wall inside the function
    count = 4  # @param hole count
    unmarked = 9
    return Box(HEIGHT, HEIGHT, HEIGHT)
'''


class ModelParamsTests(unittest.TestCase):
    def test_finds_numeric_uppercase_constants_with_ranges_and_labels(self) -> None:
        params = {p["name"]: p for p in find_params(SOURCE)}
        self.assertEqual(sorted(params), ["FLAG", "HEIGHT", "NAME_LENGTH", "OFFSET", "SIZES[0]", "SIZES[1]", "SPOKES",
                                          "build_model.count", "build_model.wall"])
        self.assertEqual(params["build_model.wall"]["min"], 1.0)
        self.assertEqual(params["build_model.count"]["label"], "hole count")
        edited = apply_params(SOURCE, {"FLAG": 0, "SIZES[1]": 5, "build_model.wall": 2.0})
        self.assertIn("FLAG = False", edited)
        self.assertIn("SIZES = (1, 5)", edited)
        self.assertIn("wall = 2.0  # [1, 3]", edited)
        self.assertEqual((params["FLAG"]["kind"], params["FLAG"]["min"], params["FLAG"]["max"]), ("bool", 0, 1))
        self.assertEqual((params["HEIGHT"]["min"], params["HEIGHT"]["max"], params["HEIGHT"]["label"]), (10.0, 40.0, "overall height, mm"))
        self.assertTrue(params["SPOKES"]["integer"])
        self.assertEqual(params["SPOKES"]["step"], 1)
        self.assertLess(params["OFFSET"]["min"], -2.5)

    def test_apply_changes_only_the_numbers(self) -> None:
        edited = apply_params(SOURCE, {"HEIGHT": 32.5, "SPOKES": 8.4, "OFFSET": -1})
        self.assertIn("HEIGHT = 32.5  # [10, 40] overall height, mm", edited)
        self.assertIn("SPOKES = 8  # [3, 12]", edited)
        self.assertIn("OFFSET = -1.0", edited)
        self.assertEqual(edited.replace("32.5", "20.0").replace("SPOKES = 8", "SPOKES = 6").replace("OFFSET = -1.0", "OFFSET = -2.5"), SOURCE)
        with self.assertRaisesRegex(ValueError, "not parameters"):
            apply_params(SOURCE, {"DERIVED": 1})
        with self.assertRaisesRegex(ValueError, "finite"):
            apply_params(SOURCE, {"HEIGHT": float("nan")})


@unittest.skipUnless(os.environ.get("IMG2CAD_CAD_PYTHON"), "set IMG2CAD_CAD_PYTHON to build models in the viewer")
class ViewerParamsTests(unittest.TestCase):
    def post(self, base: str, path: str, body: dict) -> dict:
        request = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read())

    def test_rebuild_and_save_through_the_viewer(self) -> None:
        import viewer

        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.py"
            model.write_text(SOURCE, encoding="utf-8")
            registry = viewer.Registry()
            file_id = registry.add(model)
            server, base = viewer.start_server(registry)
            try:
                with urllib.request.urlopen(f"{base}api/params?id={file_id}") as response:
                    data = json.loads(response.read())
                self.assertEqual([p["name"] for p in data["params"]][:2], ["HEIGHT", "SPOKES"])
                first = self.post(base, "api/rebuild", {"id": file_id, "values": {"HEIGHT": 30}})
                self.assertTrue(first["ok"], first)
                with urllib.request.urlopen(f"{base}api/file?id={file_id}") as response:
                    self.assertEqual(response.headers["Content-Type"], "model/gltf-binary")
                bad = self.post(base, "api/rebuild", {"id": file_id, "values": {"NOPE": 1}})
                self.assertFalse(bad["ok"])
                saved = self.post(base, "api/save", {"id": file_id, "values": {"HEIGHT": 30}})
                self.assertTrue(saved["ok"], saved)
                self.assertIn("HEIGHT = 30.0  # [10, 40]", model.read_text(encoding="utf-8"))
                self.assertEqual((Path(temp) / "model.py.bak").read_text(encoding="utf-8"), SOURCE)
                self.assertEqual([p.name for p in Path(temp).iterdir() if p.name.startswith(".img2cad-view")], [])
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()

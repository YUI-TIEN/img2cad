from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_cad import source_for  # noqa: E402
from spec_contract import SpecError, validate_spec  # noqa: E402


CASE = ROOT / "benchmark/cases/repro-block"
REFERENCE_SPEC = CASE / "spec.json"


class Object2CADSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = json.loads(REFERENCE_SPEC.read_text(encoding="utf-8"))
        self.temp = tempfile.TemporaryDirectory(prefix="img2cad-spec-test-")
        self.spec_path = Path(self.temp.name) / "spec.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_spec(self) -> None:
        self.spec_path.write_text(json.dumps(self.spec), encoding="utf-8")

    def test_dimensioned_reference_is_ready(self) -> None:
        self.write_spec()
        self.assertTrue(validate_spec(CASE, self.spec_path, require_ready=True)["_model_ready"])

    def test_image_inference_requires_confirmation(self) -> None:
        self.spec["parts"][0]["dimensions"]["height"]["status"] = "inferred"
        self.write_spec()
        self.assertFalse(validate_spec(CASE, self.spec_path)["_model_ready"])
        with self.assertRaisesRegex(SpecError, "not model-ready"):
            validate_spec(CASE, self.spec_path, require_ready=True)

    def test_image_hash_is_pinned(self) -> None:
        self.spec["input_images"][0]["sha256"] = "0" * 64
        self.write_spec()
        with self.assertRaisesRegex(SpecError, "hash mismatch"):
            validate_spec(CASE, self.spec_path)

    def test_hole_cannot_escape_part(self) -> None:
        self.spec["parts"][0]["holes"][0]["x"]["value"] = 15
        self.write_spec()
        with self.assertRaisesRegex(SpecError, "outside the part length"):
            validate_spec(CASE, self.spec_path)

    def test_generator_is_deterministic_and_editable(self) -> None:
        self.write_spec()
        spec = validate_spec(CASE, self.spec_path, require_ready=True)
        first = source_for(spec)
        self.assertEqual(first, source_for(spec))
        self.assertIn("BuildPart()", first)
        self.assertIn("Box(LENGTH, WIDTH, HEIGHT", first)
        self.assertIn("Cylinder(1.0", first)
        self.assertNotIn("exec(", first)


if __name__ == "__main__":
    unittest.main()

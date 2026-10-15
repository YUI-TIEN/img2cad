from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_workflow  # noqa: E402
from agent_cad_worker import parse_model_source  # noqa: E402

EXAMPLES = sorted(path for path in (ROOT / "examples").iterdir() if path.is_dir())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExampleLibraryTests(unittest.TestCase):
    def test_library_has_examples_and_an_index_entry_for_each(self) -> None:
        self.assertGreaterEqual(len(EXAMPLES), 4)
        index = (ROOT / "examples/README.md").read_text(encoding="utf-8")
        for example in EXAMPLES:
            self.assertIn(f"`{example.name}`", index)

    def test_examples_are_complete_and_untampered(self) -> None:
        for example in EXAMPLES:
            with self.subTest(example=example.name):
                summary = json.loads((example / "example.json").read_text(encoding="utf-8"))
                self.assertEqual(summary["name"], example.name)
                self.assertEqual(summary["visual_review"]["verdict"], "acceptable")
                self.assertTrue(summary["techniques"])
                self.assertTrue((example / "README.md").is_file())
                for name, digest in summary["file_sha256"].items():
                    self.assertEqual(sha256(example / name), digest, name)
                parse_model_source((example / "model.py").read_text(encoding="utf-8"), str(example / "model.py"))
                plan = json.loads((example / "plan.json").read_text(encoding="utf-8"))
                self.assertEqual(plan["target_type"], summary["target_type"])
                for constraint in plan["constraints"]:
                    agent_workflow.validate_constraint(constraint)
                if summary["target_type"] == "dimension_constrained":
                    self.assertTrue(summary["dimension_checks"])
                    self.assertTrue(all(check["passed"] for check in summary["dimension_checks"]))

    @unittest.skipUnless(os.environ.get("IMG2CAD_CAD_PYTHON"), "set IMG2CAD_CAD_PYTHON to rebuild examples with the CAD environment")
    def test_examples_rebuild_to_recorded_geometry(self) -> None:
        for example in EXAMPLES:
            with self.subTest(example=example.name), tempfile.TemporaryDirectory() as temp:
                summary = json.loads((example / "example.json").read_text(encoding="utf-8"))
                run_dir = Path(temp) / "run"
                result = subprocess.run([os.environ["IMG2CAD_CAD_PYTHON"], "-B", str(ROOT / "scripts/run_agent_cad.py"), str(example / "model.py"), str(run_dir),
                                         "--cad-python", os.environ["IMG2CAD_CAD_PYTHON"]], capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                inspection = json.loads((run_dir / "run_report.json").read_text(encoding="utf-8"))["inspection"]
                self.assertAlmostEqual(inspection["volume"], summary["geometry"]["volume"], delta=1e-6 * summary["geometry"]["volume"])


if __name__ == "__main__":
    unittest.main()

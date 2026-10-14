from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_cad_worker import parse_model_source  # noqa: E402
from validate_benchmark import ValidationError, validate_case, validate_run  # noqa: E402


DIMENSIONED_CASE = ROOT / "benchmark/cases/repro-block"
VISUAL_CASE = ROOT / "benchmark/cases/visual-pose-dog"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AcceptanceProfileTests(unittest.TestCase):
    def test_dimensioned_case_requires_explicit_dimension_gate(self) -> None:
        case = validate_case(DIMENSIONED_CASE)
        self.assertEqual(len(case["requirements"]["dimensions"]), 3)
        self.assertIn("explicit_dimensions", case["required_gates"])

    def test_visual_case_uses_visual_criteria_without_invented_dimensions(self) -> None:
        case = validate_case(VISUAL_CASE)
        self.assertEqual(case["task_kind"], "visual_reference_to_part")
        self.assertEqual(case["requirements"]["dimensions"], [])
        self.assertNotIn("explicit_dimensions", case["required_gates"])
        self.assertEqual(len(case["requirements"]["visual_criteria"]), 3)
        source = (VISUAL_CASE / "model.py").read_text(encoding="utf-8")
        parse_model_source(source, str(VISUAL_CASE / "model.py"))

    def run_manifest(self, case_dir: Path, run_root: Path, *, visual_findings: bool = True) -> None:
        case = validate_case(case_dir)
        run_root.mkdir()
        artifacts = []
        for role, filename, content in (
            ("spec", "plan.json", "{}"),
            ("model_source", "model.py", "build_model"),
            ("step", "model.step", "fixture bytes; not a CAD validation claim"),
            ("preview", "preview.png", "fixture bytes"),
            ("validation_report", "validation.json", "{}"),
        ):
            path = run_root / filename
            path.write_text(content, encoding="utf-8")
            artifacts.append({"role": role, "path": filename, "sha256": digest(path)})
        dimensions = {item["name"]: item["value"] for item in case["requirements"]["dimensions"]}
        run = {
            "schema_version": 1,
            "run_id": "acceptance-fixture-001",
            "case_id": case["case_id"],
            "created_at": "2026-10-14T00:00:00Z",
            "source_hashes": {item["path"]: item["sha256"] for item in case["source_files"]},
            "pipeline": {
                "git_commit": "a" * 40,
                "prompt_sha256": "b" * 64,
                "provider": "fixture",
                "model": "fixture",
                "model_version": "1",
                "temperature": None,
                "seed": None,
            },
            "artifacts": artifacts,
            "measurements": {"dimensions": dimensions, "solid_count": case["requirements"].get("expected_solid_count") or 1},
            "gates": {gate: "passed" for gate in case["required_gates"]},
            "review": {
                "reviewer": "acceptance-test-fixture",
                "outcome": "pass",
                "findings": "Synthetic validator fixture; not a human visual acceptance claim.",
                "criteria": [
                    {"id": criterion["id"], "outcome": "pass", "findings": "fixture"}
                    for criterion in case["requirements"].get("visual_criteria", [])
                ] if visual_findings else [],
            },
        }
        (run_root / "run.json").write_text(json.dumps(run), encoding="utf-8")

    def test_visual_run_requires_evaluation_for_every_criterion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="img2cad-acceptance-") as temp:
            run_dir = Path(temp) / "visual"
            self.run_manifest(VISUAL_CASE, run_dir)
            case, run = validate_run(run_dir, VISUAL_CASE)
            self.assertEqual(case["case_id"], "visual-pose-dog")
            self.assertEqual(len(run["review"]["criteria"]), 3)

            missing = Path(temp) / "missing-review"
            self.run_manifest(VISUAL_CASE, missing, visual_findings=False)
            with self.assertRaisesRegex(ValidationError, "exactly match"):
                validate_run(missing, VISUAL_CASE)

    def test_dimensioned_run_records_required_dimensions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="img2cad-acceptance-") as temp:
            run_dir = Path(temp) / "dimensioned"
            self.run_manifest(DIMENSIONED_CASE, run_dir)
            case, run = validate_run(run_dir, DIMENSIONED_CASE)
            self.assertEqual(case["case_id"], "repro-block")
            self.assertEqual(len(run["measurements"]["dimensions"]), 3)
            run["measurements"]["dimensions"]["length"] = 25
            (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "outside tolerance"):
                validate_run(run_dir, DIMENSIONED_CASE)


if __name__ == "__main__":
    unittest.main()

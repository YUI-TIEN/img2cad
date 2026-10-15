from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_workflow  # noqa: E402


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="img2cad-workflow-test-")
        self.root = Path(self.temp.name)
        self.reference = self.root / "reference.png"
        self.reference.write_bytes(b"reference-image")
        self.workflow = self.root / "workflow"
        agent_workflow.create(argparse.Namespace(workflow=self.workflow, reference=self.reference, target_type="visual_approximation"))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def json_file(self, name: str, data: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def record_inputs(self) -> None:
        observations = self.json_file("observations.json", {
            "observed": ["elongated body"], "inferred": ["hidden depth"], "unknowns": ["physical scale"],
            "evidence": [{"claim": "elongated body", "source": "reference.png side silhouette"}],
        })
        agent_workflow.record_observations(argparse.Namespace(workflow=self.workflow, file=observations))
        plan = self.json_file("plan.json", {
            "target_type": "visual_approximation", "goal": "recognizable editable approximation",
            "geometry_plan": ["loft oval torso", "join four legs"], "constraints": [], "unknowns": ["scale"],
        })
        agent_workflow.record_plan(argparse.Namespace(workflow=self.workflow, file=plan))

    def add_geometry_gate(self) -> Path:
        self.record_inputs()
        model = self.root / "model.py"
        model.write_text("from build123d import Sphere\ndef build_model():\n    return Sphere(10)\n", encoding="utf-8")
        agent_workflow.source_review(argparse.Namespace(workflow=self.workflow, model=model, inspection_note="checked source against plan"))
        root = self.workflow
        state = agent_workflow.load_state(root)
        revision = agent_workflow.active(state)
        cad = root / revision["directory"] / "cad"
        cad.mkdir()
        reviewed_model = root / revision["directory"] / "model.py"
        artifacts = {}
        for key, filename, content in (
            ("model_source", "model.py", None), ("step", "model.step", "step"),
            ("preview", "preview.png", "preview"), ("reference", "reference.png", "reference"),
            ("comparison", "comparison.png", "comparison"),
        ):
            path = cad / filename
            if key == "model_source":
                path.write_bytes(reviewed_model.read_bytes())
            else:
                path.write_text(content, encoding="utf-8")
            artifacts[key] = {"path": filename, "sha256": agent_workflow.sha256(path)}
        report = {"status": "passed", "status_scope": "geometry_and_step_only", "inspection": {"status": "passed"}, **artifacts}
        report_path = cad / "run_report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        state = agent_workflow.load_state(root)
        revision = agent_workflow.active(state)
        outputs = {key: value["sha256"] for key, value in artifacts.items()}
        outputs["run_report"] = agent_workflow.sha256(report_path)
        revision["stages"]["geometry"] = agent_workflow.stage_record("passed", {"model_source": outputs["model_source"], "reference": artifacts["reference"]["sha256"], "observations": revision["stages"]["observations"]["outputs"]["observations"], "plan": revision["stages"]["plan"]["outputs"]["plan"]}, outputs, run_directory=f"{revision['directory']}/cad")
        revision["stages"]["dimensions"] = agent_workflow.stage_record("not_applicable", {"model_source": outputs["model_source"], "plan": revision["stages"]["plan"]["outputs"]["plan"]}, {"run_report": outputs["run_report"]}, status_scope="not_applicable")
        agent_workflow.save_state(root, state)
        return cad

    def test_state_resume_reports_required_order(self) -> None:
        state = agent_workflow.load_state(self.workflow)
        revision = agent_workflow.active(state)
        self.assertIn("record image observations", agent_workflow.next_action(revision))
        self.assertEqual(revision["stages"]["observations"]["next_step"], "record image evidence: observed / inferred / unknown")
        with self.assertRaisesRegex(ValueError, "observations and image evidence"):
            agent_workflow.record_plan(argparse.Namespace(workflow=self.workflow, file=self.json_file("plan.json", {})))

    def test_observations_require_source_linked_evidence_and_are_immutable(self) -> None:
        bad = self.json_file("bad.json", {"observed": ["body"], "inferred": [], "unknowns": [], "evidence": []})
        with self.assertRaisesRegex(ValueError, "source-linked evidence"):
            agent_workflow.record_observations(argparse.Namespace(workflow=self.workflow, file=bad))
        self.record_inputs()
        with self.assertRaisesRegex(ValueError, "immutable within a revision"):
            agent_workflow.record_observations(argparse.Namespace(workflow=self.workflow, file=bad))

    def test_review_is_blocked_when_geometry_gate_has_not_passed(self) -> None:
        notes = self.json_file("review.json", {"verdict": "acceptable"})
        with self.assertRaisesRegex(ValueError, "blocked until geometry and STEP pass"):
            agent_workflow.review(argparse.Namespace(workflow=self.workflow, notes=notes))

    def test_stale_preview_hash_cannot_pass_visual_review(self) -> None:
        cad = self.add_geometry_gate()
        (cad / "preview.png").write_text("tampered", encoding="utf-8")
        notes = self.json_file("review.json", {"verdict": "acceptable"})
        with self.assertRaisesRegex(ValueError, "stale geometry artifact hash: preview"):
            agent_workflow.review(argparse.Namespace(workflow=self.workflow, notes=notes))

    def test_stale_plan_hash_cannot_pass_visual_review(self) -> None:
        self.add_geometry_gate()
        plan = self.workflow / "revisions/r001/plan.json"
        plan.write_text("{}", encoding="utf-8")
        notes = self.json_file("review.json", {"verdict": "acceptable"})
        with self.assertRaisesRegex(ValueError, "stale or missing plan stage artifact"):
            agent_workflow.review(argparse.Namespace(workflow=self.workflow, notes=notes))

    def test_blocked_review_must_identify_missing_evidence(self) -> None:
        self.add_geometry_gate()
        notes = self.json_file("review.json", {"verdict": "blocked", "next_changes": []})
        with self.assertRaisesRegex(ValueError, "blocked review must identify missing evidence"):
            agent_workflow.review(argparse.Namespace(workflow=self.workflow, notes=notes))

    def test_source_must_follow_observations_and_plan_and_pass_parser(self) -> None:
        model = self.root / "model.py"
        model.write_text("from build123d import Sphere\ndef build_model():\n    return Sphere(10)\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "observations and geometry plan"):
            agent_workflow.source_review(argparse.Namespace(workflow=self.workflow, model=model, inspection_note="checked source"))
        self.record_inputs()
        agent_workflow.source_review(argparse.Namespace(workflow=self.workflow, model=model, inspection_note="checked source against plan"))
        state = agent_workflow.load_state(self.workflow)
        self.assertEqual(agent_workflow.active(state)["stages"]["source_review"]["status"], "passed")

    def test_revision_preserves_prior_and_invalidates_downstream(self) -> None:
        self.record_inputs()
        state = agent_workflow.load_state(self.workflow)
        prior = agent_workflow.active(state)
        prior["stages"]["visual_review"]["status"] = "blocked"
        agent_workflow.save_state(self.workflow, state)
        agent_workflow.new_revision(argparse.Namespace(workflow=self.workflow, reason="need another view"))
        state = agent_workflow.load_state(self.workflow)
        first, second = state["revisions"]
        self.assertEqual(first["id"], "r001")
        self.assertEqual(second["parent"], "r001")
        self.assertEqual(second["stages"]["observations"]["inherited_from"], "r001")
        self.assertEqual(second["stages"]["source_review"]["status"], "pending")
        self.assertEqual(second["stages"]["geometry"]["status"], "pending")
        self.assertEqual(second["stages"]["visual_review"]["status"], "pending")

    def test_inherited_stages_resolve_across_multiple_revisions(self) -> None:
        self.record_inputs()
        for reason in ("first correction", "second correction"):
            state = agent_workflow.load_state(self.workflow)
            agent_workflow.active(state)["stages"]["geometry"]["status"] = "failed"
            agent_workflow.save_state(self.workflow, state)
            agent_workflow.new_revision(argparse.Namespace(workflow=self.workflow, reason=reason))
        state = agent_workflow.load_state(self.workflow)
        third = agent_workflow.active(state)
        self.assertEqual(third["id"], "r003")
        for stage, key in (("observations", "observations"), ("plan", "plan")):
            self.assertEqual(third["stages"][stage]["inherited_from"], "r001")
            path, _ = agent_workflow.recorded_stage_file(self.workflow, state, third, stage, key)
            self.assertEqual(path, self.workflow / "revisions/r001" / f"{key}.json")

    def test_geometry_gate_cannot_rerun_within_revision(self) -> None:
        self.add_geometry_gate()
        with self.assertRaisesRegex(ValueError, "already ran for this revision"):
            agent_workflow.run_geometry(argparse.Namespace(workflow=self.workflow, cad_python="python", reference_view=None))

    def test_plan_rejects_boolean_bounds(self) -> None:
        observations = self.json_file("observations.json", {"observed": [], "inferred": [], "unknowns": []})
        agent_workflow.record_observations(argparse.Namespace(workflow=self.workflow, file=observations))
        plan = self.json_file("plan.json", {
            "target_type": "visual_approximation", "goal": "g", "geometry_plan": ["box"],
            "constraints": [{"name": "length", "value": 10, "tolerance": True}], "unknowns": [],
        })
        with self.assertRaisesRegex(ValueError, "numeric value and nonnegative tolerance"):
            agent_workflow.record_plan(argparse.Namespace(workflow=self.workflow, file=plan))

    def test_revision_can_replace_inherited_evidence_and_plan(self) -> None:
        self.record_inputs()
        state = agent_workflow.load_state(self.workflow)
        agent_workflow.active(state)["stages"]["visual_review"]["status"] = "blocked"
        agent_workflow.save_state(self.workflow, state)
        agent_workflow.new_revision(argparse.Namespace(workflow=self.workflow, reason="new view supplied"))
        observations = self.json_file("new-observations.json", {
            "observed": ["body and rear view"], "inferred": [], "unknowns": [],
            "evidence": [{"claim": "rear profile visible", "source": "additional rear view"}],
        })
        agent_workflow.record_observations(argparse.Namespace(workflow=self.workflow, file=observations))
        plan = self.json_file("new-plan.json", {
            "target_type": "visual_approximation", "goal": "revise with rear view",
            "geometry_plan": ["add rear profile detail"], "constraints": [], "unknowns": [],
        })
        agent_workflow.record_plan(argparse.Namespace(workflow=self.workflow, file=plan))
        state = agent_workflow.load_state(self.workflow)
        first, second = state["revisions"]
        self.assertEqual(first["stages"]["plan"]["outputs"]["plan"], agent_workflow.sha256(self.workflow / "revisions/r001/plan.json"))
        self.assertIsNone(second["stages"]["observations"].get("inherited_from"))
        self.assertIsNone(second["stages"]["plan"].get("inherited_from"))
        self.assertEqual(second["stages"]["source_review"]["status"], "pending")
        self.assertEqual(second["stages"]["geometry"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()

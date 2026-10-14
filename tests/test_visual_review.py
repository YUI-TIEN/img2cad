from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from record_visual_review import record, sha256  # noqa: E402


class VisualReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="img2cad-review-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_fixture(self, name: str, source: str) -> Path:
        run_dir = self.root / name
        run_dir.mkdir()
        artifacts = {}
        for key, filename, content in (
            ("model_source", "model.py", source),
            ("step", "model.step", "step-data"),
            ("preview", "preview.png", "preview-data"),
            ("reference", "reference.png", "same-reference"),
            ("comparison", "comparison.png", "comparison-data"),
        ):
            path = run_dir / filename
            path.write_text(content, encoding="utf-8")
            artifacts[key] = {"path": filename, "sha256": sha256(path)}
        report = {"status": "passed", "inspection": {"status": "passed"}, **artifacts}
        (run_dir / "run_report.json").write_text(json.dumps(report), encoding="utf-8")
        return run_dir

    def notes(self, name: str, verdict: str) -> Path:
        path = self.root / name
        path.write_text(json.dumps({
            "reviewer": "agent",
            "verdict": verdict,
            "source_view": "reference front compared with CAD front; perspective uncertain",
            "matches": ["main outline"],
            "mismatches": ["opening too small"] if verdict == "revise" else [],
            "next_changes": ["increase opening width"] if verdict == "revise" else [],
            "assumptions": ["back surface unseen"],
        }), encoding="utf-8")
        return path

    def test_revision_is_bound_to_reference_source_and_review(self) -> None:
        first = self.run_fixture("r1", "source-v1")
        second = self.run_fixture("r2", "source-v2")
        record(first, self.notes("r1-notes.json", "revise"))
        result = json.loads(record(second, self.notes("r2-notes.json", "acceptable"), first).read_text())
        self.assertEqual(result["geometry_status"], "passed")
        self.assertEqual(result["visual_status"], "recorded_not_independently_verified")
        self.assertEqual(result["human_acceptance"], "not_verified_by_runner")
        self.assertEqual(result["previous"]["visual_review_sha256"], sha256(first / "visual_review.json"))
        with self.assertRaisesRegex(ValueError, "review already exists"):
            record(second, self.notes("again.json", "acceptable"), first)

    def test_tampered_artifact_or_unchanged_model_cannot_be_a_revision(self) -> None:
        first = self.run_fixture("r1", "same-source")
        second = self.run_fixture("r2", "same-source")
        record(first, self.notes("r1-notes.json", "revise"))
        with self.assertRaisesRegex(ValueError, "source did not change"):
            record(second, self.notes("r2-notes.json", "acceptable"), first)
        (second / "reference.png").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch for reference"):
            record(second, self.notes("r2-notes.json", "acceptable"), first)

    def test_symlinked_artifact_is_not_read(self) -> None:
        run_dir = self.run_fixture("r1", "source-v1")
        reference = run_dir / "reference.png"
        reference.unlink()
        outside = self.root / "outside.png"
        outside.write_text("same-reference", encoding="utf-8")
        reference.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "not a regular file for reference"):
            record(run_dir, self.notes("r1-notes.json", "blocked"))


if __name__ == "__main__":
    unittest.main()

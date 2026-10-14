#!/usr/bin/env python3
"""Bind an agent's visual comparison notes to one immutable CAD run and revision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_run(run_dir: Path) -> tuple[dict[str, Any], str]:
    report_path = run_dir / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("inspection", {}).get("status") != "passed":
        raise ValueError(f"geometry/STEP gate did not pass: {run_dir}")
    for key in ("model_source", "step", "preview", "reference", "comparison"):
        artifact = report.get(key)
        if not isinstance(artifact, dict):
            raise ValueError(f"run is missing {key}: {run_dir}")
        name = artifact.get("path")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f"unsafe artifact path for {key}: {name}")
        artifact_path = run_dir / name
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError(f"artifact is not a regular file for {key}: {run_dir}")
        if sha256(artifact_path) != artifact.get("sha256"):
            raise ValueError(f"artifact hash mismatch for {key}: {run_dir}")
    return report, sha256(report_path)


def nonempty_strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of nonempty strings")
    return value


def record(run_dir: Path, notes_path: Path, previous_dir: Path | None = None) -> Path:
    run_dir = run_dir.resolve()
    output = run_dir / "visual_review.json"
    if output.exists():
        raise ValueError(f"review already exists; preserve this run and use a new revision: {output}")
    report, report_hash = load_run(run_dir)
    notes = json.loads(notes_path.read_text(encoding="utf-8"))
    if not isinstance(notes, dict):
        raise ValueError("review notes must be a JSON object")
    verdict = notes.get("verdict")
    if verdict not in {"revise", "acceptable", "blocked"}:
        raise ValueError("verdict must be revise, acceptable, or blocked")
    reviewer = notes.get("reviewer")
    if reviewer not in {"agent", "human"}:
        raise ValueError("reviewer must be agent or human")
    source_view = notes.get("source_view")
    if not isinstance(source_view, str) or not source_view.strip():
        raise ValueError("source_view must explain which image/view was compared with which CAD view")
    matches = nonempty_strings(notes.get("matches"), "matches")
    mismatches = nonempty_strings(notes.get("mismatches"), "mismatches")
    changes = nonempty_strings(notes.get("next_changes"), "next_changes")
    assumptions = nonempty_strings(notes.get("assumptions"), "assumptions")
    if verdict == "revise" and (not mismatches or not changes):
        raise ValueError("a revise verdict requires mismatches and next_changes")
    if verdict == "acceptable" and mismatches:
        raise ValueError("an acceptable verdict cannot leave recorded mismatches unresolved")

    previous: dict[str, str] | None = None
    if previous_dir is not None:
        previous_dir = previous_dir.resolve()
        if previous_dir == run_dir:
            raise ValueError("previous run must differ from current run")
        old_report, old_hash = load_run(previous_dir)
        old_review_path = previous_dir / "visual_review.json"
        old_review = json.loads(old_review_path.read_text(encoding="utf-8"))
        if not isinstance(old_review, dict) or old_review.get("run_report_sha256") != old_hash or old_review.get("verdict") != "revise":
            raise ValueError("previous revision needs a valid revise review")
        if old_report["reference"]["sha256"] != report["reference"]["sha256"]:
            raise ValueError("revision reference image changed")
        if old_report["model_source"]["sha256"] == report["model_source"]["sha256"]:
            raise ValueError("revision model source did not change")
        previous = {"run_report_sha256": old_hash, "visual_review_sha256": sha256(old_review_path)}

    review = {
        "schema_version": 1,
        "run_report_sha256": report_hash,
        "reference_sha256": report["reference"]["sha256"],
        "geometry_status": "passed",
        "visual_status": "recorded_not_independently_verified",
        "human_acceptance": "not_verified_by_runner",
        "verdict": verdict,
        "reviewer": reviewer,
        "source_view": source_view,
        "matches": matches,
        "mismatches": mismatches,
        "next_changes": changes,
        "assumptions": assumptions,
        "previous": previous,
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(review, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="completed run containing reference and comparison")
    parser.add_argument("notes", type=Path, help="JSON visual assessment written after inspecting the images")
    parser.add_argument("--previous", type=Path, help="previous reviewed run for a revision")
    args = parser.parse_args()
    try:
        print(record(args.run_dir, args.notes, args.previous))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

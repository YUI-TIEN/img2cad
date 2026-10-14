#!/usr/bin/env python3
"""Drive a frozen case through spec, editable CAD, STEP gates and human review."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pipeline_state import case_directory, run_directory
from spec_contract import SpecError
from validate_benchmark import ValidationError, read_json, sha256, validate_case, validate_run


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "scripts/pipeline_state.py"
PREPARE = ROOT / "scripts/prepare_spec.py"
CAD_WORKER = ROOT / "scripts/cad_worker.py"


class PipelineBlocked(RuntimeError):
    pass


def call(*args: str) -> str:
    result = subprocess.run([sys.executable, "-B", str(STATE), *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])
    return result.stdout.strip()


def command(args: argparse.Namespace) -> int:
    case_dir = case_directory(args.case_dir)
    run_dir = run_directory(args.run_dir)
    if not run_dir.exists():
        run_dir.mkdir(parents=True)
        prompt_hash = args.prompt_sha256
        if not prompt_hash:
            draft = read_json(args.spec_draft)
            prompt_hash = draft.get("adapter", {}).get("prompt_sha256") or hashlib.sha256(b"no-image-model-used:operator-provided-spec:v1").hexdigest()
        init = ["init", "--case-dir", str(case_dir), "--run-dir", str(run_dir), "--provider", args.provider, "--model", args.model, "--model-version", args.model_version, "--prompt-sha256", prompt_hash]
        if args.temperature is not None:
            init += ["--temperature", str(args.temperature)]
        if args.seed is not None:
            init += ["--seed", str(args.seed)]
        # init expects a not-yet-existing run dir; remove only this newly created empty directory.
        run_dir.rmdir()
        print(call(*init))
    state_path = run_dir / "workflow.json"
    if not state_path.is_file():
        raise RuntimeError("run directory exists without workflow.json; use a new run id")
    case = validate_case(case_dir)

    def current_step(step: str) -> dict[str, Any]:
        state = read_json(state_path)
        found = next(item for item in state["steps"] if item["id"] == step)
        return found

    def start(step: str) -> bool:
        item = current_step(step)
        if item["status"] == "passed":
            return False
        extra = ["--resume"] if item["status"] in {"blocked", "running"} else []
        print(call("start", step, "--run-dir", str(run_dir), *extra))
        return True

    def complete(step: str, *evidence: Path) -> None:
        command_args = ["complete", step, "--run-dir", str(run_dir)]
        for path in evidence:
            command_args += ["--evidence", str(path)]
        print(call(*command_args))

    def block(step: str, reason: str) -> int:
        print(call("block", step, "--run-dir", str(run_dir), "--reason", reason))
        print(f"Run is paused at {step}; resolve the issue, then resume this command.")
        return 2

    if start("input_assessment"):
        assessment = run_dir / "input_assessment.json"
        assessment.write_text(json.dumps({"case_id": case["case_id"], "revision": case["revision"], "source_hashes": {item["path"]: item["sha256"] for item in case["source_files"]}, "supported": case.get("supported", True)}, indent=2) + "\n")
        complete("input_assessment", assessment)

    if start("spec_authoring"):
        draft = args.spec_draft if args.spec_draft.is_absolute() else ROOT / args.spec_draft
        result = subprocess.run([sys.executable, "-B", str(PREPARE), str(case_dir), str(draft), str(run_dir / "spec.json")], cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            return block("spec_authoring", result.stderr.strip()[-1000:] or "spec draft failed validation")
        print(result.stdout.strip())
        complete("spec_authoring", run_dir / "spec.json")

    spec = read_json(run_dir / "spec.json")
    ready = True
    try:
        from spec_contract import validate_spec
        validate_spec(case_dir, run_dir / "spec.json", require_ready=True)
    except SpecError:
        ready = False

    if start("assumption_confirmation"):
        if not ready:
            reason = "critical dimensions/feature assumptions are unresolved; revise spec and cite drawing or user confirmation"
            (run_dir / "assumptions_pending.json").write_text(json.dumps({"unknowns": spec.get("unknowns", []), "required_action": reason}, indent=2) + "\n")
            return block("assumption_confirmation", reason)
        part_dims = spec["parts"][0]["dimensions"]
        mismatches = []
        if case["requirements"].get("expected_solid_count") not in {None, 1}:
            mismatches.append("expected_solid_count (v1 supports one solid)")
        for requirement in case["requirements"]["dimensions"]:
            measurement = part_dims.get(requirement["name"])
            if measurement is None or abs(float(measurement["value"]) - requirement["value"]) > requirement["tolerance"]:
                mismatches.append(requirement["name"])
        if mismatches:
            reason = "spec dimensions disagree with frozen case tolerances: " + ", ".join(mismatches)
            (run_dir / "assumptions_pending.json").write_text(json.dumps({"mismatches": mismatches, "required_action": reason}, indent=2) + "\n")
            return block("assumption_confirmation", reason)
        confirmation = run_dir / "assumption_confirmation.json"
        confirmation.write_text(json.dumps({"model_ready": True, "dimensions_status": sorted({m["status"] for p in spec["parts"] for m in p["dimensions"].values()}), "unknowns": []}, indent=2) + "\n")
        complete("assumption_confirmation", confirmation)

    if start("model_generation"):
        leftovers = [run_dir / name for name in ("model.py", "model.step", "geometry.json", "preview.svg", "validation_report.json") if (run_dir / name).exists()]
        if leftovers:
            history = run_dir / "history" / "failed-model-attempts"
            history.mkdir(parents=True, exist_ok=True)
            for leftover in leftovers:
                target = history / f"{leftover.name}.attempt-{len(list(history.glob(leftover.name + '.attempt-*'))) + 1}"
                leftover.replace(target)
        result = subprocess.run([sys.executable, "-B", str(CAD_WORKER), str(case_dir), str(run_dir / "spec.json"), str(run_dir), "--python", args.cad_python, "--timeout", str(args.timeout)], cwd=ROOT, capture_output=True, text=True, timeout=args.timeout + 20)
        if result.returncode:
            return block("model_generation", (result.stderr or result.stdout).strip()[-1500:] or "CAD worker failed")
        print("CAD worker: STEP and preview generated; see validation_report.json")
        complete("model_generation", run_dir / "model.py")

    report_path = run_dir / "validation_report.json"
    report = read_json(report_path)
    if start("geometry_validation"):
        evidence = run_dir / "geometry_validation.json"
        evidence.write_text(json.dumps({"native_brep_valid": report["checks"]["native_brep_valid"], "step_brep_valid": report["checks"]["step_brep_valid"], "native_single_solid": report["checks"]["native_single_solid"], "step_single_solid": report["checks"]["step_single_solid"], "dimension_checks": {key: val for key, val in report["checks"].items() if key.startswith("step_dimension_")}, "volume_check": report["checks"]["step_volume"]}, indent=2) + "\n")
        complete("geometry_validation", evidence)
    if start("step_roundtrip"):
        complete("step_roundtrip", run_dir / "model.step", report_path)

    if start("visual_review"):
        if not args.review_json:
            return block("visual_review", "human review required: compare case drawing with preview.svg and supply a review JSON")
        review_source = args.review_json if args.review_json.is_absolute() else ROOT / args.review_json
        review = read_json(review_source)
        expected_hashes = {item["path"]: item["sha256"] for item in case["source_files"]}
        supplied_hashes = review.get("input_image_hashes")
        valid_review = (isinstance(review.get("reviewer"), str) and review["reviewer"].strip() and
                        review.get("outcome") in {"pass", "fail"} and isinstance(review.get("findings"), str) and
                        review.get("preview_sha256") == sha256(run_dir / "preview.svg") and supplied_hashes == expected_hashes)
        if not valid_review:
            return block("visual_review", "review JSON must name a reviewer, record pass/fail and findings, and match preview/input hashes")
        shutil.copyfile(review_source, run_dir / "review.json")
        if review["outcome"] != "pass":
            return block("visual_review", "review failed: " + review["findings"][:500])
        complete("visual_review", run_dir / "review.json")

    review = read_json(run_dir / "review.json")

    if start("run_manifest_validation"):
        final_report = read_json(report_path)
        pipeline = read_json(state_path)["pipeline"]
        artifact_paths = [("spec", run_dir / "spec.json"), ("model_source", run_dir / "model.py"), ("step", run_dir / "model.step"), ("preview", run_dir / "preview.svg"), ("validation_report", report_path), ("visual_review", run_dir / "review.json")]
        manifest = {
            "schema_version": 1,
            "run_id": run_dir.name,
            "case_id": case["case_id"],
            "created_at": read_json(state_path)["created_at"],
            "source_hashes": {item["path"]: item["sha256"] for item in case["source_files"]},
            "pipeline": pipeline,
            "artifacts": [{"role": role, "path": path.name, "sha256": sha256(path)} for role, path in artifact_paths],
            "measurements": {"dimensions": final_report["measured_after_step_roundtrip"]["dimensions"], "solid_count": final_report["measured_after_step_roundtrip"]["solid_count"], "volume": final_report["measured_after_step_roundtrip"]["volume"]},
            "gates": {"spec_valid": "passed", "model_build": "passed", "step_roundtrip": "passed", "explicit_dimensions": "passed", "visual_review": "passed"},
            "review": {"reviewer": review["reviewer"], "outcome": review["outcome"], "findings": review["findings"]}
        }
        (run_dir / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
        try:
            complete("run_manifest_validation")
        except RuntimeError as exc:
            return block("run_manifest_validation", str(exc)[-1000:])
    validate_run(run_dir, case_dir)
    print(f"COMPLETE: run {run_dir.name} passed manifest, geometry and recorded review gates")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("spec_draft", type=Path)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--cad-python", default="python3", help="Python interpreter with build123d installed")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--review-json", type=Path, help="human review record tied to exact preview/input hashes")
    parser.add_argument("--provider", default="operator-spec")
    parser.add_argument("--model", default="operator-authored")
    parser.add_argument("--model-version", default="1")
    parser.add_argument("--prompt-sha256")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        return command(args)
    except (OSError, RuntimeError, ValueError, KeyError, ValidationError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

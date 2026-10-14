#!/usr/bin/env python3
"""Track an ordered img2cad run and require evidence at every stage.

This command manages workflow state only. It never executes generated CAD code
or invokes a model/kernel; adapters can be added without changing the state
contract.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_benchmark import ValidationError, read_json, safe_file, sha256, validate_case, validate_run


ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = ROOT / "benchmark" / "runs"
CASES_ROOT = ROOT / "benchmark" / "cases"
STATE_NAME = "workflow.json"
WORKFLOW_ID = "img2cad-v1"
MAX_ATTEMPTS = 3
STEP_IDS = (
    "input_assessment",
    "spec_authoring",
    "assumption_confirmation",
    "model_generation",
    "geometry_validation",
    "step_roundtrip",
    "visual_review",
    "run_manifest_validation",
)
ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def project_child(path: Path, parent: Path, label: str) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    resolved = candidate.resolve()
    base = parent.resolve()
    if resolved == base or base not in resolved.parents:
        raise ValidationError(f"{label} must be inside {base}")
    return resolved


def run_directory(path: Path) -> Path:
    return project_child(path, RUNS_ROOT, "run directory")


def case_directory(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    resolved = project_child(candidate, CASES_ROOT, "case directory")
    if not resolved.is_dir():
        raise ValidationError(f"case directory does not exist: {resolved}")
    return resolved


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def make_state(case_dir: Path, run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    case_manifest = safe_file(case_dir, "case.json")
    case = validate_case(case_dir)
    run_id = run_dir.name
    if not ID_PATTERN.fullmatch(run_id):
        raise ValidationError("run directory name must use letters, digits, dot, underscore, or hyphen")
    prompt_hash = args.prompt_sha256
    if not SHA256_PATTERN.fullmatch(prompt_hash):
        raise ValidationError("--prompt-sha256 must be a lowercase SHA-256")
    for label, value in (("provider", args.provider), ("model", args.model), ("model-version", args.model_version)):
        if not value.strip():
            raise ValidationError(f"--{label} cannot be empty")
    if args.temperature is not None and not math.isfinite(args.temperature):
        raise ValidationError("--temperature must be finite")

    # Run artifacts are untracked by design; they are data, not a change to the
    # pipeline commit. Keep source/config dirtiness from invalidating provenance.
    dirty = git_value(
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude)benchmark/runs/**",
        ":(exclude)benchmark/cases/**",
    )
    if dirty:
        raise ValidationError("initialize benchmark runs from a clean checkout so git_commit identifies the exact pipeline")

    try:
        case_path = case_dir.relative_to(ROOT).as_posix()
    except ValueError:
        case_path = str(case_dir)
    return {
        "schema_version": 1,
        "workflow": WORKFLOW_ID,
        "run_id": run_id,
        "status": "in_progress",
        "case": {
            "id": case["case_id"],
            "revision": case["revision"],
            "path": case_path,
            "manifest_sha256": sha256(case_manifest),
            "source_hashes": {item["path"]: item["sha256"] for item in case["source_files"]},
        },
        "pipeline": {
            "git_commit": git_value("rev-parse", "HEAD"),
            "prompt_sha256": prompt_hash,
            "provider": args.provider,
            "model": args.model,
            "model_version": args.model_version,
            "temperature": args.temperature,
            "seed": args.seed,
        },
        "created_at": now(),
        "updated_at": now(),
        "max_attempts_per_step": MAX_ATTEMPTS,
        "steps": [
            {"id": step_id, "status": "pending", "attempts": 0, "evidence": []}
            for step_id in STEP_IDS
        ],
        "events": [{"event": "initialized", "at": now()}],
    }


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now()
    fd, temp_name = tempfile.mkstemp(prefix=".workflow-", suffix=".tmp", dir=run_dir)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, run_dir / STATE_NAME)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def load_state(run_dir: Path) -> dict[str, Any]:
    state_path = safe_file(run_dir, STATE_NAME)
    state = read_json(state_path)
    if state.get("schema_version") != 1 or state.get("workflow") != WORKFLOW_ID:
        raise ValidationError("unsupported workflow state version")
    if state.get("run_id") != run_dir.name:
        raise ValidationError("workflow run_id does not match its directory")
    steps = state.get("steps")
    if not isinstance(steps, list) or any(not isinstance(item, dict) for item in steps) or [item.get("id") for item in steps] != list(STEP_IDS):
        raise ValidationError("workflow step sequence is missing or out of order")
    if state.get("status") not in {"in_progress", "blocked", "complete"}:
        raise ValidationError("invalid workflow status")
    for step in steps:
        if step.get("status") not in {"pending", "running", "passed", "blocked"}:
            raise ValidationError(f"invalid status for step {step.get('id')}")
        if not isinstance(step.get("attempts"), int) or not 0 <= step["attempts"] <= MAX_ATTEMPTS:
            raise ValidationError(f"invalid attempt count for step {step.get('id')}")
        if step["status"] == "passed":
            evidence = step.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValidationError(f"passed step {step['id']} has no evidence")
            for record in evidence:
                if not isinstance(record, dict):
                    raise ValidationError(f"invalid evidence record for step {step['id']}")
                relative = record.get("path")
                expected = record.get("sha256")
                if not isinstance(relative, str) or not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
                    raise ValidationError(f"invalid evidence record for step {step['id']}")
                actual = sha256(safe_file(run_dir, relative))
                if actual != expected:
                    raise ValidationError(f"evidence changed after step {step['id']} passed: {relative}")
    saw_incomplete = False
    for step in steps:
        if step["status"] == "passed" and saw_incomplete:
            raise ValidationError("a later step passed before an earlier step")
        if step["status"] != "passed":
            saw_incomplete = True
    current = next_step(state)
    all_passed = current is None
    if (state["status"] == "complete") != all_passed:
        raise ValidationError("workflow status does not match its step states")
    if state["status"] == "blocked" and (current is None or current["status"] != "blocked"):
        raise ValidationError("workflow is blocked without a blocked current step")
    if state["status"] == "in_progress" and current is not None and current["status"] == "blocked":
        raise ValidationError("workflow has a blocked step but is marked in progress")
    return state


def next_step(state: dict[str, Any]) -> dict[str, Any] | None:
    return next((step for step in state["steps"] if step["status"] != "passed"), None)


def append_event(state: dict[str, Any], event: str, step_id: str, **details: Any) -> None:
    state["events"].append({"event": event, "step": step_id, "at": now(), **details})


def command_init(args: argparse.Namespace) -> None:
    case_dir = case_directory(args.case_dir)
    run_dir = run_directory(args.run_dir)
    if run_dir.exists():
        raise ValidationError(f"run directory already exists; use a new run id: {run_dir}")
    state = make_state(case_dir, run_dir, args)
    run_dir.mkdir(parents=True, exist_ok=False)
    save_state(run_dir, state)
    print(f"PASS: initialized {state['run_id']} for case {state['case']['id']} r{state['case']['revision']}")
    print(f"Next: {STEP_IDS[0]}")


def command_status(args: argparse.Namespace) -> None:
    run_dir = run_directory(args.run_dir)
    state = load_state(run_dir)
    current = next_step(state)
    if args.json:
        print(json.dumps({"run_id": state["run_id"], "status": state["status"], "next_step": current, "steps": state["steps"]}, indent=2))
        return
    print(f"Run: {state['run_id']} ({state['status']})")
    print(f"Case: {state['case']['id']} r{state['case']['revision']}")
    print(f"Next: {current['id']} [{current['status']}]" if current else "Next: none (all stages passed)")
    for step in state["steps"]:
        print(f"- {step['id']}: {step['status']} (attempts={step['attempts']}, evidence={len(step['evidence'])})")
        if step.get("reason"):
            print(f"  blocked: {step['reason']}")


def command_start(args: argparse.Namespace) -> None:
    run_dir = run_directory(args.run_dir)
    state = load_state(run_dir)
    if state["status"] == "complete":
        raise ValidationError("workflow is already complete")
    current = next_step(state)
    if current is None or current["id"] != args.step:
        expected = current["id"] if current else "none"
        raise ValidationError(f"cannot start {args.step}; next ordered step is {expected}")
    if current["status"] == "blocked":
        if not args.resume:
            raise ValidationError("step is blocked; use --resume after resolving the blocker")
        if current["attempts"] >= MAX_ATTEMPTS:
            raise ValidationError(f"step exhausted its {MAX_ATTEMPTS} attempts")
    elif current["status"] == "running":
        if not args.resume:
            raise ValidationError("step is already running; use --resume to recover an interrupted stage")
        append_event(state, "resumed", args.step, attempt=current["attempts"])
        current["started_at"] = now()
        save_state(run_dir, state)
        print(f"PASS: resumed {args.step} (attempt {current['attempts']}/{MAX_ATTEMPTS})")
        return
    elif current["status"] != "pending":
        raise ValidationError(f"step cannot start from status {current['status']}")
    elif current["attempts"] >= MAX_ATTEMPTS:
        raise ValidationError(f"step exhausted its {MAX_ATTEMPTS} attempts")
    current["status"] = "running"
    current["attempts"] += 1
    current["started_at"] = now()
    current.pop("reason", None)
    state["status"] = "in_progress"
    append_event(state, "started", args.step, attempt=current["attempts"])
    save_state(run_dir, state)
    print(f"PASS: started {args.step} (attempt {current['attempts']}/{MAX_ATTEMPTS})")


def evidence_records(run_dir: Path, paths: list[Path]) -> list[dict[str, str]]:
    if not paths:
        raise ValidationError("completion requires at least one --evidence file")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        candidate = path if path.is_absolute() else run_dir / path
        resolved = safe_file(run_dir, candidate.relative_to(run_dir) if candidate.is_relative_to(run_dir) else str(candidate))
        relative = resolved.relative_to(run_dir).as_posix()
        if relative == STATE_NAME or relative.startswith(".workflow-"):
            raise ValidationError("workflow state files cannot be used as stage evidence")
        if relative in seen:
            raise ValidationError(f"duplicate evidence path: {relative}")
        seen.add(relative)
        records.append({"path": relative, "sha256": sha256(resolved)})
    return records


def command_complete(args: argparse.Namespace) -> None:
    run_dir = run_directory(args.run_dir)
    state = load_state(run_dir)
    current = next_step(state)
    if current is None or current["id"] != args.step or current["status"] != "running":
        raise ValidationError(f"{args.step} must be the currently running ordered step")

    if args.step == "run_manifest_validation":
        if args.evidence:
            raise ValidationError("run_manifest_validation checks run.json itself; do not pass --evidence")
        case_dir = case_directory(Path(state["case"]["path"]))
        case_manifest = safe_file(case_dir, "case.json")
        run_manifest = safe_file(run_dir, "run.json")
        case = validate_case(case_dir)
        if sha256(case_manifest) != state["case"]["manifest_sha256"]:
            raise ValidationError("case manifest changed after workflow initialization")
        if {item["path"]: item["sha256"] for item in case["source_files"]} != state["case"]["source_hashes"]:
            raise ValidationError("case source hashes changed after workflow initialization")
        validate_run(run_dir, case_dir)
        records = [{"path": "run.json", "sha256": sha256(run_manifest)}]
    else:
        records = evidence_records(run_dir, args.evidence)

    current["status"] = "passed"
    current["completed_at"] = now()
    current["evidence"] = records
    append_event(state, "completed", args.step, evidence_count=len(records))
    if all(step["status"] == "passed" for step in state["steps"]):
        state["status"] = "complete"
    save_state(run_dir, state)
    print(f"PASS: completed {args.step}; evidence recorded={len(records)}")
    print(f"Next: {next_step(state)['id']}" if next_step(state) else "Workflow complete: run.json passed benchmark validation")


def command_block(args: argparse.Namespace) -> None:
    run_dir = run_directory(args.run_dir)
    state = load_state(run_dir)
    current = next_step(state)
    if current is None or current["id"] != args.step or current["status"] != "running":
        raise ValidationError(f"{args.step} must be the currently running ordered step")
    reason = args.reason.strip()
    if not reason:
        raise ValidationError("--reason cannot be empty")
    current["status"] = "blocked"
    current["reason"] = reason
    current["blocked_at"] = now()
    state["status"] = "blocked"
    append_event(state, "blocked", args.step, reason=reason)
    save_state(run_dir, state)
    print(f"BLOCKED: {args.step}: {reason}")


def command_revise(args: argparse.Namespace) -> None:
    """Invalidate a step and its downstream outputs while preserving old artifacts."""
    run_dir = run_directory(args.run_dir)
    state = load_state(run_dir)
    index = STEP_IDS.index(args.step)
    if args.step in {"geometry_validation", "step_roundtrip"}:
        index = STEP_IDS.index("model_generation")
    effective_step = STEP_IDS[index]
    selected = state["steps"][index]
    if selected["status"] not in {"passed", "blocked", "running"}:
        raise ValidationError("revise requires a previously started stage")
    reason = args.reason.strip()
    if not reason:
        raise ValidationError("--reason cannot be empty")
    history = run_dir / "history"
    revision = 1 + len(list(history.glob("revision-*"))) if history.exists() else 1
    archive_dir = history / f"revision-{revision}"
    candidates = {"run.json"}
    if index == 0:
        candidates |= {"input_assessment.json", "spec.json", "assumption_confirmation.json", "model.py", "model.step", "geometry.json", "preview.svg", "validation_report.json", "geometry_validation.json", "review.json"}
    elif effective_step == "spec_authoring":
        candidates |= {"spec.json", "assumption_confirmation.json", "model.py", "model.step", "geometry.json", "preview.svg", "validation_report.json", "geometry_validation.json", "review.json"}
    elif effective_step == "model_generation":
        candidates |= {"model.py", "model.step", "geometry.json", "preview.svg", "validation_report.json", "geometry_validation.json", "review.json"}
    elif effective_step == "visual_review":
        candidates |= {"review.json"}
    moved: list[str] = []
    for name in sorted(candidates):
        artifact = run_dir / name
        if artifact.is_file():
            archive_dir.mkdir(parents=True, exist_ok=True)
            archived = archive_dir / name
            artifact.replace(archived)
            moved.append(archived.relative_to(run_dir).as_posix())
    if moved:
        append_event(state, "artifacts_archived", effective_step, paths=moved)
    for step in state["steps"][index:]:
        step.update({"status": "pending", "evidence": []})
        for key in ("started_at", "completed_at", "blocked_at", "reason"):
            step.pop(key, None)
        if step["id"] != args.step:
            step["attempts"] = 0
    selected["reason_last_revised"] = reason
    state["status"] = "in_progress"
    append_event(state, "revision_invalidated", effective_step, requested_step=args.step, reason=reason, downstream_steps=list(STEP_IDS[index:]))
    save_state(run_dir, state)
    print(f"PASS: invalidated {', '.join(STEP_IDS[index:])}; previous artifacts retained under {archive_dir.relative_to(run_dir) if moved else 'no archive needed'}")
    print(f"Next: {effective_step}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize a new immutable benchmark workflow run")
    init.add_argument("--case-dir", type=Path, required=True)
    init.add_argument("--run-dir", type=Path, required=True)
    init.add_argument("--provider", required=True)
    init.add_argument("--model", required=True)
    init.add_argument("--model-version", required=True)
    init.add_argument("--prompt-sha256", required=True)
    init.add_argument("--temperature", type=float)
    init.add_argument("--seed", type=int)
    init.set_defaults(func=command_init)

    status = sub.add_parser("status", help="show ordered workflow state and next step")
    status.add_argument("--run-dir", type=Path, required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    start = sub.add_parser("start", help="start only the next ordered step")
    start.add_argument("step", choices=STEP_IDS)
    start.add_argument("--run-dir", type=Path, required=True)
    start.add_argument("--resume", action="store_true", help="resume a blocked step after resolving its blocker")
    start.set_defaults(func=command_start)

    complete = sub.add_parser("complete", help="complete the running step and record evidence hashes")
    complete.add_argument("step", choices=STEP_IDS)
    complete.add_argument("--run-dir", type=Path, required=True)
    complete.add_argument("--evidence", type=Path, action="append", default=[])
    complete.set_defaults(func=command_complete)

    block = sub.add_parser("block", help="stop at the running step with a recorded reason")
    block.add_argument("step", choices=STEP_IDS)
    block.add_argument("--run-dir", type=Path, required=True)
    block.add_argument("--reason", required=True)
    block.set_defaults(func=command_block)

    revise = sub.add_parser("revise", help="revise an upstream decision and invalidate downstream stage results")
    revise.add_argument("step", choices=STEP_IDS)
    revise.add_argument("--run-dir", type=Path, required=True)
    revise.add_argument("--reason", required=True)
    revise.set_defaults(func=command_revise)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.func(args)
    except (ValidationError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

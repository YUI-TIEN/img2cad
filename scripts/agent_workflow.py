#!/usr/bin/env python3
"""Stateful, resumable workflow for agent-led image-to-editable-CAD runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
from typing import Any

from agent_cad_worker import parse_model_source
from record_visual_review import record as record_visual_review


ROOT = Path(__file__).resolve().parent.parent
STATE_NAME = "workflow.json"
RUN_ARTIFACTS = ("model_source", "step", "preview", "reference", "comparison", "silhouette_overlay")
STAGES = ("observations", "plan", "source_review", "geometry", "dimensions", "visual_review")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_state(root: Path, state: dict[str, Any]) -> None:
    for revision in state["revisions"]:
        for name, stage in revision["stages"].items():
            stage["next_step"] = stage_next_step(revision, name)
    path = root / STATE_NAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_state(root: Path) -> dict[str, Any]:
    path = root.expanduser().resolve() / STATE_NAME
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != 1 or not isinstance(state.get("revisions"), list):
        raise ValueError(f"unsupported or invalid workflow state: {path}")
    return state


def active(state: dict[str, Any]) -> dict[str, Any]:
    return state["revisions"][-1]


def stage_next_step(revision: dict[str, Any], name: str) -> str:
    stages = revision["stages"]
    status = stages[name]["status"]
    target_type = revision.get("target_type", "visual_approximation")
    if name == "observations":
        return "record image evidence: observed / inferred / unknown" if status != "recorded" else "record the geometry plan"
    if name == "plan":
        return "record the geometry plan" if status != "recorded" else "author and inspect model.py"
    if name == "source_review":
        return "author, inspect, and source-review model.py" if status != "passed" else "run CAD/STEP gate"
    if name == "geometry":
        if status == "failed":
            return "start a new revision and correct the CAD failure"
        if status == "passed":
            return "complete the explicit-dimension gate" if target_type == "dimension_constrained" else "inspect comparison and record visual review"
        return "run CAD/STEP gate after source review"
    if name == "dimensions":
        if status == "not_applicable":
            return "inspect comparison and record visual review"
        if status == "failed":
            return "start a new revision and correct declared bounds"
        if status == "passed":
            return "inspect comparison and record visual review"
        return "check declared STEP bounds before visual review"
    if status == "revise":
        return "start a new model revision; prior run remains preserved"
    if status == "blocked":
        return "supply missing view/dimensions, then start a new revision"
    if status == "acceptable":
        return "agent review complete; human acceptance remains separate"
    return "inspect comparison and record acceptable / revise / blocked"


def revision_by_id(state: dict[str, Any], revision_id: str) -> dict[str, Any]:
    for item in state["revisions"]:
        if item["id"] == revision_id:
            return item
    raise ValueError(f"unknown revision: {revision_id}")


def recorded_stage_file(root: Path, state: dict[str, Any], revision: dict[str, Any], stage_name: str, output_key: str) -> tuple[Path, str]:
    stage = revision["stages"][stage_name]
    origin = revision_by_id(state, stage["inherited_from"]) if stage.get("inherited_from") else revision
    filename = stage.get("path") or stage.get("model_path")
    if not isinstance(filename, str):
        raise ValueError(f"{stage_name} stage has no recorded artifact path")
    expected = stage["outputs"].get(output_key)
    if not isinstance(expected, str):
        raise ValueError(f"{stage_name} stage has no recorded {output_key} hash")
    path = root / origin["directory"] / filename
    if not path.is_file() or path.is_symlink() or sha256(path) != expected:
        raise ValueError(f"stale or missing {stage_name} stage artifact: {filename}")
    return path, expected


def stage_record(status: str, inputs: dict[str, str], outputs: dict[str, str], **extra: Any) -> dict[str, Any]:
    return {"status": status, "inputs": inputs, "outputs": outputs, **extra}


def invalidate_downstream(stages: dict[str, Any]) -> None:
    for name in ("source_review", "geometry", "dimensions", "visual_review"):
        stages[name] = {"status": "pending", "inputs": {}, "outputs": {}}


def next_action(revision: dict[str, Any]) -> str:
    stages = revision["stages"]
    if stages["observations"]["status"] != "recorded":
        return "record image observations (separate observed, inferred, and unknown evidence)"
    if stages["plan"]["status"] != "recorded":
        return "record geometry plan and fidelity target"
    if stages["source_review"]["status"] != "passed":
        return "author model.py, inspect it, then run source-review"
    if stages["geometry"]["status"] == "failed":
        return "start a new revision; preserve the failed run and correct the CAD execution issue"
    if stages["dimensions"]["status"] == "failed":
        return "start a new revision; preserve this run and correct the dimension-constrained model"
    if stages["geometry"]["status"] != "passed":
        return "run the CAD geometry/STEP gate"
    if revision.get("target_type", "visual_approximation") == "dimension_constrained" and stages["dimensions"]["status"] != "passed":
        return "complete the explicit-dimension gate before visual review"
    if stages["visual_review"]["status"] == "revise":
        return "start a new revision; preserve this run and change the model"
    if stages["visual_review"]["status"] == "blocked":
        return "supply the missing view/dimension evidence, then start a new revision"
    if stages["visual_review"]["status"] != "acceptable":
        return "inspect comparison.png and record acceptable, revise, or blocked review notes"
    return "agent visual review is acceptable; human acceptance remains separate"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def create(args: argparse.Namespace) -> None:
    root = args.workflow.expanduser().resolve()
    reference = args.reference.expanduser().resolve()
    if not reference.is_file() or reference.is_symlink():
        raise ValueError("reference must be an existing regular, non-symlink image")
    if reference.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("reference must be PNG, JPEG, or WebP")
    if root.exists():
        raise ValueError(f"workflow path already exists; refusing to overwrite: {root}")
    root.mkdir(parents=True)
    inputs_dir = root / "inputs"
    inputs_dir.mkdir()
    local_reference = inputs_dir / f"reference{reference.suffix.lower()}"
    shutil.copyfile(reference, local_reference)
    revision_dir = root / "revisions" / "r001"
    revision_dir.mkdir(parents=True)
    state = {
        "schema_version": 1,
        "workflow_id": root.name,
        "target_type": args.target_type,
        "reference": {"path": "inputs/" + local_reference.name, "sha256": sha256(local_reference)},
        "created_from": str(reference),
        "revisions": [{"id": "r001", "directory": "revisions/r001", "parent": None, "target_type": args.target_type,
                       "stages": {name: {"status": "pending", "inputs": {}, "outputs": {}} for name in STAGES}}],
        "human_acceptance": "not_verified",
    }
    save_state(root, state)
    print(json.dumps({"workflow": str(root), "revision": "r001", "next": next_action(active(state))}, indent=2))


def record_observations(args: argparse.Namespace) -> None:
    root = args.workflow.expanduser().resolve()
    state = load_state(root)
    revision = active(state)
    observation_stage = revision["stages"]["observations"]
    if observation_stage["status"] != "pending" and not observation_stage.get("inherited_from"):
        raise ValueError("observations are immutable within a revision; preserve history and create a new revision")
    source = args.file.expanduser().resolve()
    data = read_json(source)
    for key in ("observed", "inferred", "unknowns"):
        value = data.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError(f"{key} must be an array of nonempty strings (use [] when none)")
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or any(not isinstance(item, dict) or not item.get("claim") or not item.get("source") for item in evidence):
        raise ValueError("evidence must contain objects with claim and source")
    if data["observed"] and not evidence:
        raise ValueError("observations need source-linked evidence")
    output = root / revision["directory"] / "observations.json"
    shutil.copyfile(source, output)
    revision["stages"]["observations"] = stage_record("recorded", {"reference": state["reference"]["sha256"], "input": sha256(source)}, {"observations": sha256(output)}, path=output.name)
    revision["stages"]["plan"] = {"status": "pending", "inputs": {}, "outputs": {}}
    invalidate_downstream(revision["stages"])
    save_state(root, state)
    print(f"recorded observations: {output}")


AXIS_FOR = {"length": "x", "width": "y", "height": "z", "x": "x", "y": "y", "z": "z"}
FEATURE_CONSTRAINTS = {"hole", "boss"}
DEFAULT_TOLERANCE = 0.02


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_constraint(constraint: Any) -> None:
    if not isinstance(constraint, dict) or constraint.get("name") not in {*AXIS_FOR, "volume", *FEATURE_CONSTRAINTS}:
        raise ValueError("measurable constraints must be named length/width/height, x/y/z, volume, hole, or boss")
    tolerance = constraint.get("tolerance", DEFAULT_TOLERANCE)
    if not finite_number(tolerance) or tolerance < 0:
        raise ValueError("each bound constraint needs numeric value and nonnegative tolerance")
    name = constraint["name"]
    if name in FEATURE_CONSTRAINTS:
        count = constraint.get("count")
        if not finite_number(constraint.get("diameter")) or constraint["diameter"] <= 0 or not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError(f"{name} constraints need positive diameter and integer count >= 1")
        return
    if not finite_number(constraint.get("value")):
        raise ValueError("each bound constraint needs numeric value and nonnegative tolerance")
    if name == "volume" and "tolerance" not in constraint:
        raise ValueError("volume constraints need an explicit absolute tolerance in cubic model units")


def check_constraint(constraint: dict[str, Any], inspection: dict[str, Any]) -> dict[str, Any]:
    name = constraint["name"]
    tolerance = float(constraint.get("tolerance", DEFAULT_TOLERANCE))
    if name in FEATURE_CONSTRAINTS:
        diameter = float(constraint["diameter"])
        matches = [item for item in inspection.get("cylindrical_features", []) if item["kind"] == name and item.get("full") and abs(item["diameter"] - diameter) <= tolerance]
        return {"name": name, "diameter": diameter, "tolerance": tolerance, "expected": constraint["count"], "measured": len(matches), "passed": len(matches) == constraint["count"],
                "scope": "full cylindrical features grouped by axis; position is not checked"}
    expected = float(constraint["value"])
    if name == "volume":
        measured = float(inspection["volume"])
        return {"name": name, "expected": expected, "measured": measured, "tolerance": tolerance, "passed": abs(measured - expected) <= tolerance}
    axis = AXIS_FOR[name]
    measured = float(inspection["dimensions"][axis])
    return {"name": name, "axis": axis, "expected": expected, "measured": measured, "tolerance": tolerance, "passed": abs(measured - expected) <= tolerance}


def record_plan(args: argparse.Namespace) -> None:
    root = args.workflow.expanduser().resolve()
    state = load_state(root)
    revision = active(state)
    plan_stage = revision["stages"]["plan"]
    if plan_stage["status"] != "pending" and not plan_stage.get("inherited_from"):
        raise ValueError("plans are immutable within a revision; preserve history and create a new revision")
    if revision["stages"]["observations"]["status"] != "recorded":
        raise ValueError("observations and image evidence are required before planning")
    source = args.file.expanduser().resolve()
    data = read_json(source)
    if data.get("target_type") != state["target_type"]:
        raise ValueError(f"plan target_type must match workflow target_type ({state['target_type']})")
    for key in ("goal", "geometry_plan", "constraints", "unknowns"):
        if key not in data:
            raise ValueError(f"plan is missing {key}")
    if not isinstance(data["geometry_plan"], list) or not data["geometry_plan"]:
        raise ValueError("geometry_plan must be a nonempty list")
    if not isinstance(data["constraints"], list):
        raise ValueError("constraints must be an array")
    if state["target_type"] == "dimension_constrained" and not data["constraints"]:
        raise ValueError("dimension_constrained plans need explicit numeric bounds in constraints")
    for constraint in data["constraints"]:
        validate_constraint(constraint)
    output = root / revision["directory"] / "plan.json"
    shutil.copyfile(source, output)
    revision["stages"]["plan"] = stage_record("recorded", {"observations": revision["stages"]["observations"]["outputs"]["observations"], "input": sha256(source)}, {"plan": sha256(output)}, path=output.name)
    invalidate_downstream(revision["stages"])
    save_state(root, state)
    print(f"recorded plan: {output}")


def source_review(args: argparse.Namespace) -> None:
    root = args.workflow.expanduser().resolve()
    state = load_state(root)
    revision = active(state)
    stages = revision["stages"]
    if stages["source_review"]["status"] != "pending":
        raise ValueError("source review is immutable within a revision; use a new revision to change the model")
    if not args.inspection_note.strip():
        raise ValueError("--inspection-note must summarize the agent's source inspection")
    if stages["observations"]["status"] != "recorded" or stages["plan"]["status"] != "recorded":
        raise ValueError("image observations and geometry plan are required before source review")
    source = args.model.expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise ValueError("model source must be an existing regular, non-symlink file")
    text = source.read_text(encoding="utf-8")
    parse_model_source(text, str(source))
    revision_dir = root / revision["directory"]
    local = revision_dir / "model.py"
    shutil.copyfile(source, local)
    stages["source_review"] = stage_record("passed", {"observations": stages["observations"]["outputs"]["observations"], "plan": stages["plan"]["outputs"]["plan"], "reference": state["reference"]["sha256"]}, {"model_source": sha256(local)}, model_path=local.name, inspection_note=args.inspection_note.strip(), policy="restricted AST/build123d API review passed; recorded inspection note is agent-authored, not independent review evidence")
    stages["geometry"] = {"status": "pending", "inputs": {}, "outputs": {}}
    stages["dimensions"] = {"status": "pending", "inputs": {}, "outputs": {}}
    stages["visual_review"] = {"status": "pending", "inputs": {}, "outputs": {}}
    save_state(root, state)
    print(json.dumps({"source_review": "passed", "model_sha256": sha256(local), "next": next_action(revision)}, indent=2))


def run_geometry(args: argparse.Namespace) -> None:
    root = args.workflow.expanduser().resolve()
    state = load_state(root)
    revision = active(state)
    stages = revision["stages"]
    if stages["source_review"]["status"] != "passed":
        raise ValueError("review model source before executing CAD")
    if stages["geometry"]["status"] != "pending":
        raise ValueError("geometry gate already ran for this revision; start a new revision to rerun")
    _, observations_hash = recorded_stage_file(root, state, revision, "observations", "observations")
    plan_path, plan_hash = recorded_stage_file(root, state, revision, "plan", "plan")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    revision_dir = root / revision["directory"]
    model = revision_dir / stages["source_review"]["model_path"]
    if sha256(model) != stages["source_review"]["outputs"]["model_source"]:
        raise ValueError("model source changed after review; rerun source-review")
    if sha256(root / state["reference"]["path"]) != state["reference"]["sha256"]:
        raise ValueError("reference image changed after workflow initialization")
    cad_dir = revision_dir / "cad"
    command = [args.cad_python, "-B", str(ROOT / "scripts/run_agent_cad.py"), str(model), str(cad_dir), "--reference", str(root / state["reference"]["path"]), "--cad-python", args.cad_python]
    if args.reference_view:
        command.extend(["--reference-view", args.reference_view])
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    (revision_dir / "geometry.stdout.log").write_text(result.stdout, encoding="utf-8")
    (revision_dir / "geometry.stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        stages["geometry"] = stage_record("failed", {"model_source": sha256(model), "reference": state["reference"]["sha256"]}, {}, command=command, exit_code=result.returncode)
        stages["dimensions"] = {"status": "pending", "inputs": {}, "outputs": {}}
        save_state(root, state)
        raise RuntimeError(result.stderr[-2000:] or result.stdout[-2000:] or "CAD runner failed")
    report_path = cad_dir / "run_report.json"
    report = read_json(report_path)
    if report.get("status") != "passed" or report.get("status_scope") != "geometry_and_step_only" or report.get("inspection", {}).get("status") != "passed":
        stages["geometry"] = stage_record("failed", {"model_source": sha256(model), "reference": state["reference"]["sha256"]}, {}, command=command, exit_code=0)
        save_state(root, state)
        raise ValueError("runner did not produce a passing geometry/STEP-only gate")
    artifacts = {name: sha256(cad_dir / report[name]["path"]) for name in RUN_ARTIFACTS if name in report}
    if artifacts["model_source"] != stages["source_review"]["outputs"]["model_source"]:
        raise ValueError("CAD runner source differs from reviewed source")
    checks = [check_constraint(constraint, report["inspection"]) for constraint in plan["constraints"]]
    dimension_applicable = state["target_type"] == "dimension_constrained"
    dimensions_passed = all(item["passed"] for item in checks) if dimension_applicable else True
    stages["geometry"] = stage_record("passed", {"model_source": artifacts["model_source"], "reference": artifacts["reference"], "observations": observations_hash, "plan": plan_hash}, {**artifacts, "run_report": sha256(report_path)}, run_directory=str(cad_dir.relative_to(root)), status_scope="geometry_and_step_only", command=command, exit_code=0)
    stages["dimensions"] = stage_record("passed" if dimension_applicable and dimensions_passed else "not_applicable" if not dimension_applicable else "failed", {"model_source": artifacts["model_source"], "plan": plan_hash}, {"run_report": sha256(report_path)}, checks=checks, status_scope="declared_bounds_volume_and_cylindrical_features" if dimension_applicable else "not_applicable")
    stages["visual_review"] = {"status": "pending", "inputs": {}, "outputs": {}}
    save_state(root, state)
    silhouette = report.get("silhouette") or {}
    summary = {"best_view": silhouette.get("best_view"), "best_iou": silhouette.get("best_iou"), "reliable": silhouette.get("reliable"), "advisory": True} if silhouette else None
    print(json.dumps({"geometry": "passed", "status_scope": "geometry_and_step_only", "artifacts": artifacts, "dimension_checks": checks if dimension_applicable else "not_applicable",
                      "silhouette": summary, "next": next_action(revision)}, indent=2))


def review(args: argparse.Namespace) -> None:
    root = args.workflow.expanduser().resolve()
    state = load_state(root)
    revision = active(state)
    stages = revision["stages"]
    if stages["geometry"]["status"] != "passed":
        raise ValueError("visual review is blocked until geometry and STEP pass")
    if state["target_type"] == "dimension_constrained" and stages["dimensions"]["status"] != "passed":
        raise ValueError("visual review is blocked until the explicit-dimension gate passes")
    if state["target_type"] == "visual_approximation" and stages["dimensions"]["status"] != "not_applicable":
        raise ValueError("visual-approximation workflow has an unexpected dimension-gate state")
    _, observations_hash = recorded_stage_file(root, state, revision, "observations", "observations")
    _, plan_hash = recorded_stage_file(root, state, revision, "plan", "plan")
    _, source_hash = recorded_stage_file(root, state, revision, "source_review", "model_source")
    if source_hash != stages["geometry"]["outputs"].get("model_source"):
        raise ValueError("geometry run does not match the reviewed model source")
    if sha256(root / state["reference"]["path"]) != state["reference"]["sha256"]:
        raise ValueError("pinned reference image changed")
    geometry_inputs = stages["geometry"]["inputs"]
    if geometry_inputs.get("observations") != observations_hash or geometry_inputs.get("plan") != plan_hash:
        raise ValueError("geometry run does not match the active observations/plan hashes")
    if stages["dimensions"]["inputs"].get("plan") != plan_hash or stages["dimensions"]["outputs"].get("run_report") != stages["geometry"]["outputs"].get("run_report"):
        raise ValueError("dimension gate is stale for the active plan or geometry report")
    cad_dir = root / stages["geometry"]["run_directory"]
    for artifact, expected in stages["geometry"]["outputs"].items():
        if artifact == "run_report":
            actual = sha256(cad_dir / "run_report.json")
        elif artifact in RUN_ARTIFACTS:
            actual = sha256(cad_dir / json.loads((cad_dir / "run_report.json").read_text())[artifact]["path"])
        else:
            continue
        if actual != expected:
            raise ValueError(f"stale geometry artifact hash: {artifact}")
    notes_path = args.notes.expanduser().resolve()
    notes = read_json(notes_path)
    if notes.get("verdict") == "blocked" and not notes.get("next_changes"):
        raise ValueError("blocked review must identify missing evidence/view/dimensions in next_changes")
    review_path = record_visual_review(cad_dir, notes_path)
    verdict = notes["verdict"]
    stages["visual_review"] = stage_record(verdict, {"run_report": sha256(cad_dir / "run_report.json"), "model_source": stages["geometry"]["outputs"]["model_source"], "preview": stages["geometry"]["outputs"]["preview"], "reference": state["reference"]["sha256"], "notes": sha256(notes_path)}, {"review": sha256(review_path)}, review_path=str(review_path.relative_to(root)), reviewer=notes["reviewer"], human_acceptance="not_verified_by_runner")
    save_state(root, state)
    print(json.dumps({"visual_review": verdict, "reviewer": notes["reviewer"], "human_acceptance": "not_verified_by_runner", "next": next_action(revision)}, indent=2))


def new_revision(args: argparse.Namespace) -> None:
    root = args.workflow.expanduser().resolve()
    state = load_state(root)
    previous = active(state)
    verdict = previous["stages"]["visual_review"]["status"]
    geometry_status = previous["stages"]["geometry"]["status"]
    dimension_status = previous["stages"]["dimensions"]["status"]
    if verdict not in {"revise", "blocked"} and geometry_status != "failed" and dimension_status != "failed":
        raise ValueError("a revision requires a previous revise/blocked visual review")
    if verdict == "revise" and not previous["stages"]["visual_review"].get("next_changes"):
        review_data = json.loads((root / previous["stages"]["visual_review"]["review_path"]).read_text())
        if not review_data.get("next_changes"):
            raise ValueError("revise review must identify geometry/parameter changes")
    number = len(state["revisions"]) + 1
    revision_id = f"r{number:03d}"
    directory = f"revisions/{revision_id}"
    (root / directory).mkdir(parents=True, exist_ok=False)
    inherited = {}
    for name in ("observations", "plan"):
        prior = previous["stages"][name]
        inherited[name] = {**prior, "inherited_from": prior.get("inherited_from") or previous["id"]}
    stages = {name: inherited.get(name, {"status": "pending", "inputs": {}, "outputs": {}}) for name in STAGES}
    stages["source_review"] = {"status": "pending", "inputs": {}, "outputs": {}}
    stages["geometry"] = {"status": "pending", "inputs": {}, "outputs": {}}
    stages["dimensions"] = {"status": "pending", "inputs": {}, "outputs": {}}
    stages["visual_review"] = {"status": "pending", "inputs": {}, "outputs": {}}
    state["revisions"].append({"id": revision_id, "directory": directory, "parent": previous["id"], "reason": args.reason, "target_type": state["target_type"], "stages": stages})
    save_state(root, state)
    print(json.dumps({"revision": revision_id, "previous_preserved": previous["id"], "downstream_invalidated": ["source_review", "geometry", "dimensions", "visual_review"], "next": next_action(active(state))}, indent=2))


def verified_run_artifact(root: Path, stage: dict[str, Any], key: str) -> Path:
    cad_dir = root / stage["run_directory"]
    report = read_json(cad_dir / "run_report.json")
    if sha256(cad_dir / "run_report.json") != stage["outputs"].get("run_report"):
        raise ValueError(f"stale run report in {stage['run_directory']}")
    path = cad_dir / report[key]["path"]
    if path.is_symlink() or not path.is_file() or sha256(path) != stage["outputs"].get(key):
        raise ValueError(f"stale geometry artifact hash: {key}")
    return path


def promote(args: argparse.Namespace) -> None:
    """Copy an accepted workflow into the example library so later agents can learn from it."""
    root = args.workflow.expanduser().resolve()
    state = load_state(root)
    revision = active(state)
    stages = revision["stages"]
    if stages["visual_review"]["status"] != "acceptable":
        raise ValueError("only a workflow whose active revision has an acceptable visual review can be promoted")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.name):
        raise ValueError("--name must be a lowercase slug such as mounting-plate")
    if not args.technique or any(not item.strip() for item in args.technique):
        raise ValueError("record at least one --technique the example demonstrates")
    destination = args.dest.expanduser().resolve() / args.name
    if destination.exists():
        raise ValueError(f"example already exists; refusing to overwrite: {destination}")
    observations, _ = recorded_stage_file(root, state, revision, "observations", "observations")
    plan, _ = recorded_stage_file(root, state, revision, "plan", "plan")
    reference = root / state["reference"]["path"]
    if sha256(reference) != state["reference"]["sha256"]:
        raise ValueError("pinned reference image changed")
    review_path = root / stages["visual_review"]["review_path"]
    if sha256(review_path) != stages["visual_review"]["outputs"]["review"]:
        raise ValueError("visual review changed after it was recorded")
    files = {
        f"reference{reference.suffix}": reference,
        "observations.json": observations,
        "plan.json": plan,
        "model.py": verified_run_artifact(root, stages["geometry"], "model_source"),
        "comparison.png": verified_run_artifact(root, stages["geometry"], "comparison"),
        "visual_review.json": review_path,
    }
    if "silhouette_overlay" in stages["geometry"]["outputs"]:
        files["silhouette.png"] = verified_run_artifact(root, stages["geometry"], "silhouette_overlay")
    history = []
    for item in state["revisions"]:
        item_stages = item["stages"]
        entry = {"id": item["id"], "reason": item.get("reason"), "geometry": item_stages["geometry"]["status"], "dimensions": item_stages["dimensions"]["status"],
                 "visual_review": item_stages["visual_review"]["status"]}
        if item is not revision and item_stages["geometry"]["status"] == "passed" and item_stages["visual_review"].get("review_path"):
            prefix = f"history/{item['id']}"
            files[f"{prefix}/model.py"] = verified_run_artifact(root, item_stages["geometry"], "model_source")
            files[f"{prefix}/comparison.png"] = verified_run_artifact(root, item_stages["geometry"], "comparison")
            files[f"{prefix}/visual_review.json"] = root / item_stages["visual_review"]["review_path"]
            entry["files"] = prefix
        history.append(entry)
    report = read_json(root / stages["geometry"]["run_directory"] / "run_report.json")
    inspection = report["inspection"]
    summary = {
        "schema_version": 1,
        "name": args.name,
        "target_type": state["target_type"],
        "techniques": [item.strip() for item in args.technique],
        "reference_sha256": state["reference"]["sha256"],
        "final_revision": revision["id"],
        "revisions": history,
        "geometry": {key: inspection[key] for key in ("brep_valid", "solid_count", "dimensions", "volume", "cylindrical_features", "units") if key in inspection},
        "dimension_checks": stages["dimensions"].get("checks", []) if stages["dimensions"]["status"] == "passed" else stages["dimensions"]["status"],
        "silhouette": report.get("silhouette"),
        "visual_review": {"verdict": "acceptable", "reviewer": stages["visual_review"]["reviewer"]},
        "human_acceptance": state["human_acceptance"],
        "file_sha256": {name: sha256(path) for name, path in files.items()},
    }
    destination.mkdir(parents=True)
    for name, path in files.items():
        (destination / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination / name)
    (destination / "example.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"promoted": str(destination), "files": sorted(files), "next": "write a short README.md in the example explaining the technique and any pitfalls, and add it to examples/README.md"}, indent=2))


def show(args: argparse.Namespace) -> None:
    state = load_state(args.workflow.expanduser().resolve())
    revision = active(state)
    print(json.dumps({"workflow_id": state["workflow_id"], "target_type": state["target_type"], "active_revision": revision["id"], "stages": {key: value["status"] for key, value in revision["stages"].items()}, "human_acceptance": state["human_acceptance"], "resume_next": next_action(revision)}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="pin a local image and start a workflow")
    init.add_argument("workflow", type=Path)
    init.add_argument("--reference", type=Path, required=True)
    init.add_argument("--target-type", choices=("visual_approximation", "dimension_constrained"), required=True)
    init.set_defaults(func=create)
    for name, func, help_text in (("observations", record_observations, "record observed/inferred/unknown image evidence"), ("plan", record_plan, "record geometry plan and fidelity target")):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("workflow", type=Path)
        cmd.add_argument("--file", type=Path, required=True)
        cmd.set_defaults(func=func)
    source = commands.add_parser("source-review", help="validate and pin inspected build123d source")
    source.add_argument("workflow", type=Path)
    source.add_argument("--model", type=Path, required=True)
    source.add_argument("--inspection-note", required=True, help="briefly state what was checked in the source and against the plan")
    source.set_defaults(func=source_review)
    run = commands.add_parser("run", help="execute geometry/STEP gate and generate comparison")
    run.add_argument("workflow", type=Path)
    run.add_argument("--cad-python", default=".venv-cad/bin/python")
    run.add_argument("--reference-view")
    run.set_defaults(func=run_geometry)
    visual = commands.add_parser("review", help="record hash-bound acceptable/revise/blocked visual review")
    visual.add_argument("workflow", type=Path)
    visual.add_argument("--notes", type=Path, required=True)
    visual.set_defaults(func=review)
    revise = commands.add_parser("new-revision", help="preserve current run and invalidate downstream stages")
    revise.add_argument("workflow", type=Path)
    revise.add_argument("--reason", required=True)
    revise.set_defaults(func=new_revision)
    library = commands.add_parser("promote", help="copy an accepted workflow into the example library")
    library.add_argument("workflow", type=Path)
    library.add_argument("--name", required=True, help="lowercase slug for the example directory")
    library.add_argument("--technique", action="append", help="modeling technique the example demonstrates (repeatable)")
    library.add_argument("--dest", type=Path, default=ROOT / "examples")
    library.set_defaults(func=promote)
    status = commands.add_parser("status", help="show workflow status and resume action")
    status.add_argument("workflow", type=Path)
    status.set_defaults(func=show)
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

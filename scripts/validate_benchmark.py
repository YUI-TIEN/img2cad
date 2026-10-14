#!/usr/bin/env python3
"""Validate img2cad benchmark manifests and compare repeat runs (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


HEX_256 = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_GATES = {"spec_valid", "model_build", "step_roundtrip", "explicit_dimensions", "visual_review"}


class ValidationError(Exception):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read valid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    base = root.resolve()
    if candidate == base or base not in candidate.parents:
        raise ValidationError(f"artifact path escapes its directory: {relative}")
    if not candidate.is_file():
        raise ValidationError(f"file does not exist: {relative}")
    return candidate


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def validate_case(case_dir: Path) -> dict[str, Any]:
    case = read_json(case_dir / "case.json")
    require(case.get("schema_version") == 1, "case schema_version must be 1")
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(case.get("case_id", "")))), "case_id must be lowercase kebab/snake-safe text")
    require(isinstance(case.get("revision"), int) and case["revision"] >= 1, "revision must be an integer >= 1")
    require(case.get("task_kind") in {"photo_to_part", "visual_reference_to_part", "drawing_to_part", "sketch_to_part"}, "unsupported task_kind")
    files = case.get("source_files")
    require(isinstance(files, list) and bool(files), "source_files must be a non-empty array")
    source_hashes: dict[str, str] = {}
    for item in files:
        require(isinstance(item, dict), "each source_files entry must be an object")
        role, rel, expected = item.get("role"), item.get("path"), item.get("sha256")
        require(role in {"input_image", "reference_cad", "drawing", "other"}, f"invalid source role: {role}")
        require(isinstance(rel, str) and rel, "source file path is required")
        require(rel not in source_hashes, f"duplicate source file path: {rel}")
        require(isinstance(expected, str) and HEX_256.fullmatch(expected), f"invalid SHA-256 for {rel}")
        actual = sha256(safe_file(case_dir, rel))
        require(actual == expected, f"source hash mismatch for {rel}: expected {expected}, got {actual}")
        source_hashes[rel] = actual
    require(any(entry.get("role") in {"input_image", "drawing"} for entry in files), "case must include an input_image or drawing source")
    require(case.get("supported", True) is True, "unsupported cases are tracked separately and cannot count as successful benchmark runs")
    req = case.get("requirements")
    require(isinstance(req, dict) and isinstance(req.get("units"), str) and req["units"], "requirements.units is required")
    dimensions = req.get("dimensions")
    require(isinstance(dimensions, list), "requirements.dimensions must be an array")
    names: set[str] = set()
    for dim in dimensions:
        require(isinstance(dim, dict), "each requirement dimension must be an object")
        name, value, tolerance = dim.get("name"), dim.get("value"), dim.get("tolerance")
        require(isinstance(name, str) and name and name not in names, f"dimension name missing or duplicated: {name}")
        require(isinstance(value, (int, float)) and math.isfinite(value), f"dimension {name} value must be finite")
        require(isinstance(tolerance, (int, float)) and math.isfinite(tolerance) and tolerance >= 0, f"dimension {name} tolerance must be finite and >= 0")
        require(dim.get("status") in {"user_confirmed", "drawing_dimension", "reference_measurement"}, f"dimension {name} needs a grounded status")
        names.add(name)
    visual_criteria = req.get("visual_criteria", [])
    require(isinstance(visual_criteria, list), "requirements.visual_criteria must be an array")
    criterion_ids: set[str] = set()
    for criterion in visual_criteria:
        require(isinstance(criterion, dict), "each visual criterion must be an object")
        criterion_id, description = criterion.get("id"), criterion.get("description")
        require(isinstance(criterion_id, str) and criterion_id and criterion_id not in criterion_ids, f"visual criterion id missing or duplicated: {criterion_id}")
        require(isinstance(description, str) and description.strip(), f"visual criterion {criterion_id} needs a description")
        criterion_ids.add(criterion_id)
    require(bool(dimensions or visual_criteria), "case needs at least one explicit dimension or visual criterion")
    gates = case.get("required_gates")
    require(isinstance(gates, list) and bool(gates), "required_gates must be a non-empty array")
    require(set(gates) <= ALLOWED_GATES and len(set(gates)) == len(gates), "required_gates contains an unknown or duplicate gate")
    require({"model_build", "step_roundtrip", "visual_review"} <= set(gates), "all cases require model_build, step_roundtrip, and visual_review gates")
    if dimensions:
        require("explicit_dimensions" in gates, "dimensioned cases require the explicit_dimensions gate")
    else:
        require("explicit_dimensions" not in gates, "visual-only cases must not claim an explicit_dimensions gate")
    if visual_criteria:
        require("visual_review" in gates, "visual criteria require the visual_review gate")
    return case


def validate_run(run_dir: Path, case_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    case = validate_case(case_dir)
    run = read_json(run_dir / "run.json")
    require(run.get("schema_version") == 1, "run schema_version must be 1")
    require(bool(run.get("run_id")), "run_id is required")
    require(run.get("case_id") == case.get("case_id"), "run case_id does not match case manifest")
    try:
        timestamp = datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
        require(timestamp.tzinfo is not None, "created_at must include a UTC offset")
    except ValueError as exc:
        raise ValidationError("created_at must be an ISO-8601 timestamp") from exc
    pipeline = run.get("pipeline")
    require(isinstance(pipeline, dict), "pipeline metadata is required")
    for field in ("git_commit", "prompt_sha256", "provider", "model", "model_version", "temperature", "seed"):
        require(field in pipeline, f"pipeline.{field} must be recorded (use null when unknown)")
    require(isinstance(pipeline["git_commit"], str) and re.fullmatch(r"[a-f0-9]{40}", pipeline["git_commit"]), "pipeline.git_commit must be a full 40-character commit SHA")
    require(isinstance(pipeline["prompt_sha256"], str) and HEX_256.fullmatch(pipeline["prompt_sha256"]), "pipeline.prompt_sha256 must be a SHA-256")
    for field in ("provider", "model", "model_version"):
        require(isinstance(pipeline[field], str) and bool(pipeline[field]), f"pipeline.{field} must be non-empty")

    declared = {entry["path"]: entry["sha256"] for entry in case["source_files"]}
    require(run.get("source_hashes") == declared, "run source_hashes must exactly match the frozen case files")
    artifacts = run.get("artifacts")
    require(isinstance(artifacts, list), "artifacts must be an array")
    roles: set[str] = set()
    for artifact in artifacts:
        require(isinstance(artifact, dict), "each artifact must be an object")
        role, rel, expected = artifact.get("role"), artifact.get("path"), artifact.get("sha256")
        require(role in {"spec", "model_source", "step", "preview", "validation_report"}, f"invalid artifact role: {role}")
        require(role not in roles or role == "preview", f"duplicate artifact role: {role}")
        require(isinstance(rel, str) and rel, f"artifact path required for {role}")
        require(isinstance(expected, str) and HEX_256.fullmatch(expected), f"invalid artifact SHA-256 for {rel}")
        require(sha256(safe_file(run_dir, rel)) == expected, f"artifact hash mismatch: {rel}")
        roles.add(role)
    require("spec" in roles and "model_source" in roles and "step" in roles, "run must retain spec, model_source, and STEP artifacts")

    measurements = run.get("measurements")
    require(isinstance(measurements, dict), "measurements are required")
    observed_dims = measurements.get("dimensions")
    require(isinstance(observed_dims, dict), "measurements.dimensions must be an object")
    for dim in case["requirements"]["dimensions"]:
        name = dim["name"]
        require(name in observed_dims and isinstance(observed_dims[name], (int, float)) and math.isfinite(observed_dims[name]), f"missing finite measurement for required dimension {name}")
        error = abs(observed_dims[name] - dim["value"])
        require(error <= dim["tolerance"], f"dimension {name} outside tolerance: expected {dim['value']} ± {dim['tolerance']}, got {observed_dims[name]}")
    expected_solids = case["requirements"].get("expected_solid_count")
    solid_count = measurements.get("solid_count")
    if expected_solids is not None:
        require(solid_count == expected_solids, f"solid_count mismatch: expected {expected_solids}, got {solid_count}")
    else:
        require(isinstance(solid_count, int) and solid_count > 0, "measurements.solid_count must be a positive integer")

    gates = run.get("gates")
    require(isinstance(gates, dict), "gates must be an object")
    for gate in case["required_gates"]:
        require(gates.get(gate) == "passed", f"required gate {gate} is {gates.get(gate, 'missing')}, expected passed")
    if "visual_review" in case["required_gates"]:
        review = run.get("review")
        require(isinstance(review, dict) and isinstance(review.get("reviewer"), str) and bool(review["reviewer"]), "visual review requires a named reviewer")
        require(review.get("outcome") == "pass" and isinstance(review.get("findings"), str), "visual review record must include outcome=pass and findings")
        expected_criteria = {item["id"] for item in case["requirements"].get("visual_criteria", [])}
        if expected_criteria:
            evaluations = review.get("criteria")
            require(isinstance(evaluations, list), "visual review must evaluate each case visual criterion")
            observed: dict[str, dict[str, Any]] = {}
            for evaluation in evaluations:
                require(isinstance(evaluation, dict), "each visual criterion evaluation must be an object")
                criterion_id = evaluation.get("id")
                require(isinstance(criterion_id, str) and criterion_id not in observed, f"visual review criterion missing or duplicated: {criterion_id}")
                observed[criterion_id] = evaluation
            require(observed.keys() == expected_criteria, "visual review criteria must exactly match the case criteria")
            for criterion_id, evaluation in observed.items():
                require(evaluation.get("outcome") == "pass", f"visual criterion {criterion_id} is not accepted")
                require(isinstance(evaluation.get("findings"), str) and evaluation["findings"].strip(), f"visual criterion {criterion_id} needs reviewer findings")
    return case, run


def pipeline_fingerprint(pipeline: dict[str, Any]) -> str:
    canonical = json.dumps(pipeline, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(canonical).hexdigest()


def compare_runs(run_a_dir: Path, run_b_dir: Path, case_dir: Path) -> list[str]:
    case, a = validate_run(run_a_dir, case_dir)
    _, b = validate_run(run_b_dir, case_dir)
    require(pipeline_fingerprint(a["pipeline"]) == pipeline_fingerprint(b["pipeline"]), "pipeline configurations differ; pin the same commit, prompt, model/version, temperature, and seed before comparing")
    findings = [f"PASS: same frozen case {case['case_id']} and identical pipeline configuration"]
    a_dims = a["measurements"]["dimensions"]
    b_dims = b["measurements"]["dimensions"]
    for dim in case["requirements"]["dimensions"]:
        name, tolerance = dim["name"], dim["tolerance"]
        delta = abs(a_dims[name] - b_dims[name])
        require(delta <= tolerance, f"repeat-run drift for {name} exceeds case tolerance {tolerance}: delta={delta}")
        findings.append(f"PASS: {name} rerun drift {delta:g} {case['requirements']['units']} (tolerance {tolerance:g})")
    hashes_a = {item["role"]: item["sha256"] for item in a["artifacts"]}
    hashes_b = {item["role"]: item["sha256"] for item in b["artifacts"]}
    require(hashes_a.keys() == hashes_b.keys(), "artifact role sets differ; both runs must retain the same evidence types")
    changed = sorted(role for role in hashes_a.keys() & hashes_b.keys() if hashes_a[role] != hashes_b[role])
    if changed:
        findings.append("NOTE: byte-level artifact hash differs for " + ", ".join(changed) + "; geometry tolerance checks passed, so this is not by itself a workflow failure")
    else:
        findings.append("PASS: all shared artifact role hashes are byte-identical")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_case = sub.add_parser("validate-case", help="validate a frozen case manifest and source hashes")
    p_case.add_argument("case_dir", type=Path)
    p_run = sub.add_parser("validate-run", help="validate run provenance, artifacts, gates, and dimensions")
    p_run.add_argument("run_dir", type=Path)
    p_run.add_argument("--case-dir", type=Path, required=True)
    p_compare = sub.add_parser("compare-runs", help="compare repeat executions for one frozen case")
    p_compare.add_argument("run_a", type=Path)
    p_compare.add_argument("run_b", type=Path)
    p_compare.add_argument("--case-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate-case":
            case = validate_case(args.case_dir)
            print(f"PASS: case {case['case_id']} r{case['revision']}; source hashes verified")
        elif args.command == "validate-run":
            case, run = validate_run(args.run_dir, args.case_dir)
            print(f"PASS: run {run['run_id']} for {case['case_id']}; provenance/artifact hashes and recorded gates/dimensions meet the manifest")
        else:
            for finding in compare_runs(args.run_a, args.run_b, args.case_dir):
                print(finding)
    except (ValidationError, OSError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

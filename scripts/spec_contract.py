#!/usr/bin/env python3
"""Validate uncertainty-aware Object2CADSpec input without third-party modules."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


class SpecError(ValueError):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def confined_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise SpecError(f"input/evidence file is missing or escapes case directory: {relative}")
    return path


def validate_spec(case_dir: Path, spec_path: Path, *, require_ready: bool = False) -> dict[str, Any]:
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"cannot read valid spec JSON: {exc}") from exc
    if not isinstance(spec, dict) or spec.get("schema_version") != 1:
        raise SpecError("spec schema_version must be 1")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(spec.get("case_id", ""))):
        raise SpecError("case_id must be lowercase safe text")
    if not isinstance(spec.get("revision"), int) or spec["revision"] < 1 or spec.get("units") != "mm":
        raise SpecError("revision must be >=1 and units must be mm")
    images = spec.get("input_images")
    if not isinstance(images, list) or not images:
        raise SpecError("at least one pinned input image is required")
    image_hashes: dict[str, str] = {}
    for image in images:
        if not isinstance(image, dict) or not isinstance(image.get("path"), str):
            raise SpecError("each input_images item needs path, sha256 and view")
        path = confined_file(case_dir, image["path"])
        actual = digest(path)
        if image.get("sha256") != actual:
            raise SpecError(f"input image hash mismatch: {image['path']}")
        if image["path"] in image_hashes:
            raise SpecError(f"duplicate input image: {image['path']}")
        if image.get("view") not in {"front", "side", "top", "isometric", "drawing", "unknown"}:
            raise SpecError(f"invalid view label for {image['path']}")
        image_hashes[image["path"]] = actual
    parts = spec.get("parts")
    if not isinstance(parts, list) or not parts:
        raise SpecError("at least one part is required")
    ready = not bool(spec.get("unknowns"))
    ids: set[str] = set()
    for part in parts:
        if not isinstance(part, dict) or part.get("kind") != "rectangular_prism":
            raise SpecError("v1 supports rectangular_prism parts only")
        pid = part.get("id")
        if not isinstance(pid, str) or not pid or pid in ids:
            raise SpecError("part IDs must be unique non-empty strings")
        ids.add(pid)
        dims = part.get("dimensions")
        if not isinstance(dims, dict) or set(dims) != {"length", "width", "height"}:
            raise SpecError(f"part {pid} requires length, width, and height")
        measurements = list(dims.values())
        holes = part.get("holes", [])
        if not isinstance(holes, list):
            raise SpecError(f"part {pid} holes must be an array")
        hole_ids: set[str] = set()
        for hole in holes:
            if not isinstance(hole, dict) or set(hole) != {"id", "x", "y", "diameter", "through"}:
                raise SpecError(f"part {pid} contains an invalid hole record")
            if not isinstance(hole["id"], str) or not hole["id"] or hole["id"] in hole_ids:
                raise SpecError(f"part {pid} hole IDs must be unique")
            hole_ids.add(hole["id"])
            if not isinstance(hole["through"], bool):
                raise SpecError("hole through must be boolean")
            measurements += [hole[k] for k in ("x", "y", "diameter")]
        for measurement in measurements:
            if not isinstance(measurement, dict):
                raise SpecError(f"part {pid} has a non-object measurement")
            value, status, confidence, evidence = (measurement.get(k) for k in ("value", "status", "confidence", "evidence"))
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise SpecError(f"part {pid} has a non-finite measurement")
            if status not in {"observed", "inferred", "drawing_dimension", "user_confirmed", "unknown"}:
                raise SpecError(f"part {pid} has an invalid measurement status")
            if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise SpecError(f"part {pid} has invalid confidence")
            if not isinstance(evidence, list):
                raise SpecError(f"part {pid} evidence must be an array")
            for item in evidence:
                if not isinstance(item, dict) or not item.get("description"):
                    raise SpecError(f"part {pid} evidence must include a description")
                if item.get("type") == "image":
                    if item.get("image") not in image_hashes:
                        raise SpecError(f"part {pid} evidence must cite a pinned image")
                elif item.get("type") == "user_confirmation":
                    if not isinstance(item.get("reference"), str) or not item["reference"].strip():
                        raise SpecError("user confirmation evidence needs a reference")
                else:
                    raise SpecError("evidence type must be image or user_confirmation")
            if status in {"observed", "inferred"} and not evidence:
                raise SpecError(f"part {pid} observed/inferred dimensions must cite image evidence")
            if status == "unknown" or status not in {"drawing_dimension", "user_confirmed"}:
                ready = False
            if status == "drawing_dimension" and not any(item.get("type") == "image" for item in evidence):
                raise SpecError("drawing dimensions must cite the source drawing")
            if status == "user_confirmed" and not any(item.get("type") == "user_confirmation" for item in evidence):
                raise SpecError("user-confirmed measurements require a confirmation evidence record")
        for key in ("length", "width", "height"):
            if float(dims[key]["value"]) <= 0:
                raise SpecError(f"part {pid} dimension {key} must be positive")
        for hole in part.get("holes", []):
            if float(hole["diameter"]["value"]) <= 0:
                raise SpecError("hole diameter must be positive")
            if abs(float(hole["x"]["value"])) + float(hole["diameter"]["value"]) / 2 > float(dims["length"]["value"]) / 2:
                raise SpecError(f"hole {hole['id']} is outside the part length")
            if abs(float(hole["y"]["value"])) + float(hole["diameter"]["value"]) / 2 > float(dims["width"]["value"]) / 2:
                raise SpecError(f"hole {hole['id']} is outside the part width")
    if not isinstance(spec.get("unknowns"), list) or any(not isinstance(x, str) for x in spec["unknowns"]):
        raise SpecError("unknowns must be a list of strings")
    if require_ready and not ready:
        raise SpecError("spec is not model-ready: resolve unknowns and confirm/increase confidence in critical dimensions")
    spec["_model_ready"] = ready
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        spec = validate_spec(args.case_dir, args.spec, require_ready=args.require_ready)
        print(f"PASS: Object2CADSpec {spec['case_id']} r{spec['revision']}; model_ready={str(spec['_model_ready']).lower()}")
        return 0
    except SpecError as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a canonical parametric model, validate it, export/re-import STEP."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from generate_cad import source_for
from spec_contract import validate_spec


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cad(case_dir: Path, spec_path: Path, out_dir: Path, python: str, timeout: int) -> dict:
    spec = validate_spec(case_dir, spec_path, require_ready=True)
    if len(spec["parts"]) != 1:
        raise ValueError("v1 worker supports exactly one part")
    part = spec["parts"][0]
    dims = {name: float(part["dimensions"][name]["value"]) for name in ("length", "width", "height")}
    expected_volume = dims["length"] * dims["width"] * dims["height"]
    for hole in part.get("holes", []):
        if not hole["through"]:
            raise ValueError("v1 worker supports through-holes only")
        expected_volume -= math.pi * (float(hole["diameter"]["value"]) / 2) ** 2 * dims["height"]
    if expected_volume <= 0:
        raise ValueError("hole volume exceeds the part volume")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir.resolve()
    model = out_dir / "model.py"
    step = out_dir / "model.step"
    geometry = out_dir / "geometry.json"
    preview = out_dir / "preview.svg"
    report = out_dir / "validation_report.json"
    model.write_text(source_for(spec), encoding="utf-8")
    # Re-render from the canonical spec immediately before execution. User/model
    # supplied Python is never accepted or executed by this worker.
    if model.read_text(encoding="utf-8") != source_for(spec):
        raise ValueError("generated source does not match canonical Object2CADSpec")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"}
    python_path = Path(python)
    if python_path.is_absolute() or os.path.sep in python:
        # Preserve venv/bin/python symlinks; resolving them points back to the
        # base interpreter and drops that environment's site-packages.
        executable = os.path.abspath(str(python_path))
    else:
        executable = shutil.which(python) or python
    result = subprocess.run(
        [executable, "-I", str(model)],
        cwd=out_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"CAD worker exited {result.returncode}: {result.stderr[-2000:]}")
    if not step.is_file() or not geometry.is_file() or not preview.is_file():
        raise RuntimeError("CAD worker did not produce STEP, geometry, and preview artifacts")
    measured = json.loads(geometry.read_text(encoding="utf-8"))
    checks: dict[str, bool] = {
        "native_brep_valid": measured.get("native_valid") is True,
        "step_brep_valid": measured.get("valid") is True,
        "native_single_solid": measured.get("native_solid_count") == 1,
        "step_single_solid": measured.get("solid_count") == 1,
        "native_volume": isinstance(measured.get("native_volume"), (int, float)) and abs(measured["native_volume"] - expected_volume) <= max(0.02, expected_volume * 0.0002),
    }
    for name, expected in dims.items():
        actual = measured.get("dimensions", {}).get(name)
        checks[f"step_dimension_{name}"] = isinstance(actual, (int, float)) and abs(actual - expected) <= 0.02
        native_actual = measured.get("native_dimensions", {}).get(name)
        checks[f"native_dimension_{name}"] = isinstance(native_actual, (int, float)) and abs(native_actual - expected) <= 0.02
    volume = measured.get("volume")
    checks["step_volume"] = isinstance(volume, (int, float)) and abs(volume - expected_volume) <= max(0.02, expected_volume * 0.0002)
    result_report = {
        "schema_version": 1,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "expected": {"dimensions": dims, "volume": expected_volume, "solid_count": 1},
        "measured_after_step_roundtrip": measured,
        "tolerances": {"dimension_mm": 0.02, "volume_relative": 0.0002},
        "artifacts": {name: {"path": path.name, "sha256": sha256(path)} for name, path in (("model_source", model), ("step", step), ("preview", preview), ("geometry", geometry))},
        "execution": {"engine": "build123d", "engine_version": measured.get("engine_version"), "mode": "canonical-generated-source; isolated Python interpreter; timeout (not an OS sandbox)", "timeout_seconds": timeout},
    }
    report.write_text(json.dumps(result_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not all(checks.values()):
        raise RuntimeError("geometry gate failed: " + ", ".join(key for key, value in checks.items() if not value))
    print(json.dumps(result_report, indent=2, sort_keys=True))
    return result_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--python", default="python3", help="interpreter with pinned build123d/OCP installed")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        if args.timeout < 1 or args.timeout > 600:
            raise ValueError("--timeout must be between 1 and 600 seconds")
        run_cad(args.case_dir, args.spec, args.output_dir, args.python, args.timeout)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

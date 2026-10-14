#!/usr/bin/env python3
"""Inspect a STEP file with Open CASCADE and report basic solid metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def inspect_step(path: Path) -> dict[str, Any]:
    # Keep the CAD dependency lazy so --help and syntax checks work without the
    # optional CAD environment installed.
    from build123d import import_step

    shape = import_step(str(path))
    box = shape.bounding_box()
    solids = shape.solids()
    dimensions = {
        "x": float(box.max.X - box.min.X),
        "y": float(box.max.Y - box.min.Y),
        "z": float(box.max.Z - box.min.Z),
    }
    valid = bool(shape.is_valid)
    solid_volumes = [float(solid.volume) for solid in solids]
    return {
        "file": str(path),
        "status": "passed" if valid and solids and all(volume > 0 for volume in solid_volumes) else "failed",
        "brep_valid": valid,
        "solid_count": len(solids),
        "dimensions": dimensions,
        "volume": float(shape.volume),
        "solid_volumes": solid_volumes,
        "units": "model units (img2cad convention: mm)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step_file", type=Path, help="STEP file to import and inspect")
    args = parser.parse_args()
    path = args.step_file.expanduser().resolve()
    if not path.is_file():
        parser.error(f"STEP file does not exist: {path}")
    try:
        result = inspect_step(path)
    except Exception as exc:
        print(json.dumps({"status": "error", "file": str(path), "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

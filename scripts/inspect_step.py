#!/usr/bin/env python3
"""Inspect a STEP file with Open CASCADE and report basic solid metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def cylindrical_features(shape: Any) -> list[dict[str, Any]]:
    """Group cylindrical faces by axis and classify them as holes or bosses.

    A face whose outward normal points toward its axis has material outside the
    cylinder (a hole/bore); otherwise it is a boss/shaft. Faces split by the
    kernel on the same axis and diameter count once. Coaxial features with the
    same diameter at different depths also merge into one entry. ``sweep`` is the
    covered fraction of a full circle; fillet rounds and arcs report ``full: false``.
    """
    import math

    from build123d import GeomType

    features: dict[tuple[Any, ...], dict[str, Any]] = {}
    for face in shape.faces().filter_by(GeomType.CYLINDER):
        axis = face.axis_of_rotation
        direction = axis.direction.normalized()
        components = (direction.X, direction.Y, direction.Z)
        leading = next(value for value in components if abs(value) > 1e-9)
        if leading < 0:
            direction = -direction
        origin = axis.position - direction * axis.position.dot(direction)
        surface_point = face.position_at(0.5, 0.5)
        radial = surface_point - (axis.position + direction * (surface_point - axis.position).dot(direction))
        kind = "hole" if face.normal_at(surface_point).dot(radial) < 0 else "boss"
        diameter = 2 * float(face.radius)
        heights = [(vertex.center() - axis.position).dot(direction) for vertex in face.vertices()]
        axial_length = max(heights) - min(heights) if heights else 0.0
        sweep = float(face.area) / (math.pi * diameter * axial_length) if axial_length > 1e-9 else 0.0
        key = (kind, round(diameter, 3), *(round(value, 3) for value in (direction.X, direction.Y, direction.Z, origin.X, origin.Y, origin.Z)))
        features.setdefault(key, {
            "kind": kind,
            "diameter": round(diameter, 6),
            "axis_direction": [round(float(value), 6) for value in (direction.X, direction.Y, direction.Z)],
            "axis_point": [round(float(value), 6) for value in (origin.X, origin.Y, origin.Z)],
            "faces": 0,
            "sweep": 0.0,
        })
        feature = features[key]
        feature["faces"] += 1
        feature["sweep"] = round(min(1.0, feature["sweep"] + sweep), 3)
    for feature in features.values():
        feature["full"] = feature["sweep"] >= 0.95
    return sorted(features.values(), key=lambda item: (item["kind"], item["diameter"], item["axis_point"]))


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
        "cylindrical_features": cylindrical_features(shape),
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

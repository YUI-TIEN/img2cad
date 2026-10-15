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


MAX_TOUCH_CHECK_PARTS = 80
TOUCH_TOLERANCE = 0.01


def leaf_parts(shape: Any) -> list[Any]:
    """Leaf shapes of an assembly (a Compound with children), or the shape itself."""
    children = list(getattr(shape, "children", ()) or ())
    if not children:
        return [shape]
    return [leaf for child in children for leaf in leaf_parts(child)]


def color_rgba(shape: Any) -> list[float] | None:
    color = getattr(shape, "color", None)
    if color is None:
        return None
    try:
        return [round(float(value), 4) for value in tuple(color)]
    except TypeError:
        return None


def part_summaries(shape: Any) -> tuple[list[dict[str, Any]], list[str] | None]:
    """Per-part label/colour/solids, plus labels of parts that touch no other part."""
    parts = leaf_parts(shape)
    summaries = []
    for index, part in enumerate(parts):
        box = part.bounding_box()
        summaries.append({
            "label": getattr(part, "label", "") or f"part {index + 1}",
            "color": color_rgba(part),
            "solid_count": len(part.solids()),
            "volume": float(part.volume),
            "center": [round(float(value), 3) for value in (box.center().X, box.center().Y, box.center().Z)],
            "size": [round(float(value), 3) for value in (box.size.X, box.size.Y, box.size.Z)],
        })
    if len(parts) < 2:
        return summaries, []
    if len(parts) > MAX_TOUCH_CHECK_PARTS:
        return summaries, None
    # Group parts that touch (directly or through other parts); everything
    # outside the group holding the most volume is floating.
    group = list(range(len(parts)))

    def root(index: int) -> int:
        while group[index] != index:
            group[index] = group[group[index]]
            index = group[index]
        return index

    for first in range(len(parts)):
        for second in range(first + 1, len(parts)):
            if root(first) != root(second) and parts[first].distance_to(parts[second]) <= TOUCH_TOLERANCE:
                group[root(first)] = root(second)
    volumes: dict[int, float] = {}
    for index, summary in enumerate(summaries):
        volumes[root(index)] = volumes.get(root(index), 0.0) + summary["volume"]
    main = max(volumes, key=volumes.get)
    return summaries, [summaries[index]["label"] for index in range(len(parts)) if root(index) != main]


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
    parts, isolated_parts = part_summaries(shape)
    solid_summaries = []
    for solid in solids:
        solid_box = solid.bounding_box()
        solid_summaries.append({
            "volume": float(solid.volume),
            "center": [round(float(value), 3) for value in (solid_box.center().X, solid_box.center().Y, solid_box.center().Z)],
            "size": [round(float(value), 3) for value in (solid_box.size.X, solid_box.size.Y, solid_box.size.Z)],
        })
    return {
        "file": str(path),
        "status": "passed" if valid and solids and all(volume > 0 for volume in solid_volumes) else "failed",
        "brep_valid": valid,
        "solid_count": len(solids),
        "dimensions": dimensions,
        "volume": float(shape.volume),
        "solid_volumes": solid_volumes,
        "solids": solid_summaries,
        "parts": parts,
        "isolated_parts": isolated_parts,
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

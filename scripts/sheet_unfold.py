#!/usr/bin/env python3
"""Unfold a sheet-metal part into its flat pattern (DXF), bends about any axes, holes included.

    img2cad dfm bracket.step --process sheet --flat-dxf flat.dxf      # through the DFM check
    python scripts/sheet_unfold.py bracket.step flat.dxf --k-factor 0.44

The part must be one sheet of constant thickness: flat flanges joined by
cylindrical bends. One side of the sheet is followed from its largest flat
face across every bend (faces that meet tangentially); each flange is rotated
about its bend axis into the plane of the previous one and pushed out by the
bend allowance, angle x (inside radius + K x thickness). Holes, slots and
cut-outs in the flanges come along with their faces. The flat pattern is the
union of the flattened flanges and bend strips, written as DXF with the
outline on layer OUTLINE and bend centre lines on layer BEND.

Not handled: bends that meet other bends directly (no flange between),
cut-outs that cross a bend (the strip is drawn whole), and closed loops of
flanges (a box with welded corners): unfold those in sheet-metal CAD.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def _matrix_to_location(matrix: np.ndarray):
    from build123d import Location
    from OCP.gp import gp_Trsf

    trsf = gp_Trsf()
    trsf.SetValues(*matrix[0, :4], *matrix[1, :4], *matrix[2, :4])
    return Location(trsf)


def _rotation_about(point: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    u = axis / np.linalg.norm(axis)
    k = np.array([[0, -u[2], u[1]], [u[2], 0, -u[0]], [-u[1], u[0], 0]])
    r = np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * k @ k
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = point - r @ point
    return m


def _translation(offset: np.ndarray) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = offset
    return m


def _v(vector) -> np.ndarray:
    return np.array([vector.X, vector.Y, vector.Z], dtype=float)


def _apply(m: np.ndarray, point: np.ndarray) -> np.ndarray:
    return m[:3, :3] @ point + m[:3, 3]


def _upward(face):
    """Same orientation (+Z normal) for every flat piece, so coplanar pieces merge into one outline."""
    from build123d import Face
    from OCP.TopoDS import TopoDS

    if face.normal_at().Z >= 0:
        return face
    return Face(TopoDS.Face(face.wrapped.Reversed()))


def _tangent(face_a, face_b, edge) -> bool:
    middle = edge.center()
    try:
        return float(_v(face_a.normal_at(middle)) @ _v(face_b.normal_at(middle))) > 0.999
    except Exception:  # noqa: BLE001 - a face that cannot evaluate a normal there is not tangent
        return False


def unfold(solid, thickness: float, k_factor: float = 0.44) -> dict[str, Any]:
    """Flat pattern of one sheet, seen from the side its bends rise toward (the usual shop view):
    the flat face (in XY), bend lines and bend data."""
    from build123d import GeomType

    planes = sorted((f for f in solid.faces() if f.geom_type == GeomType.PLANE), key=lambda f: -f.area)
    results, errors = [], []
    for start in planes[:2]:  # the two sides of the largest flange
        try:
            results.append(_unfold_from(solid, start, thickness, k_factor))
        except ValueError as error:
            errors.append(str(error))
    if not results:
        raise ValueError(errors[0] if errors else "no flat face to start from")
    return max(results, key=lambda r: sum(b["direction"] == "up" for b in r["bends"]))


def _unfold_from(solid, start_face, thickness: float, k_factor: float) -> dict[str, Any]:
    from build123d import Edge, Face, GeomType, Plane, Polyline, make_face

    faces = list(solid.faces())
    edge_faces: dict[Any, list[int]] = {}
    for index, face in enumerate(faces):
        for edge in face.edges():
            edge_faces.setdefault(edge, []).append(index)
    neighbours: dict[int, list[tuple[int, Any]]] = {i: [] for i in range(len(faces))}
    for edge, owners in edge_faces.items():
        if len(owners) == 2 and _tangent(faces[owners[0]], faces[owners[1]], edge):
            a, b = owners
            neighbours[a].append((b, edge))
            neighbours[b].append((a, edge))

    start = next(i for i, f in enumerate(faces) if f.is_same(start_face))
    transform = {start: np.eye(4)}
    pieces = [faces[start]]
    bends, strips, bend_lines = [], [], []
    queue = [start]
    visited_bends: set[int] = set()
    while queue:
        flange = queue.pop(0)
        m_flange = transform[flange]
        normal = _v(faces[flange].normal_at(faces[flange].center()))
        for bend, shared in neighbours[flange]:
            if bend in visited_bends or faces[bend].geom_type != GeomType.CYLINDER:
                continue
            visited_bends.add(bend)
            cylinder = faces[bend]
            nexts = [(f, e) for f, e in neighbours[bend] if f != flange]
            if not nexts:
                continue
            if any(faces[f].geom_type != GeomType.PLANE for f, _ in nexts):
                raise ValueError("a bend runs straight into another bend; unfold it in sheet-metal CAD")
            other, other_edge = nexts[0]
            if other in transform:
                raise ValueError("the flanges form a closed loop (welded or overlapping corners)")
            axis = cylinder.axis_of_rotation
            point, direction = _v(axis.position), _v(axis.direction)
            direction /= np.linalg.norm(direction)
            radius = float(cylinder.radius)
            centre = _v(cylinder.center())
            foot = point + direction * float((centre - point) @ direction)
            concave = float(_v(cylinder.normal_at(cylinder.center())) @ (foot - centre)) > 0
            inside = radius if concave else radius - thickness
            other_normal = _v(faces[other].normal_at(faces[other].center()))
            angle = math.acos(max(-1.0, min(1.0, float(normal @ other_normal))))  # bend angle between the flanges
            # rotate the next flange about the bend axis until it lies in this flange's plane
            best = None
            for sign in (1, -1):
                rotation = _rotation_about(point, direction, sign * angle)
                aligned = float((rotation[:3, :3] @ other_normal) @ normal)
                if best is None or aligned > best[0]:
                    best = (aligned, rotation)
            rotation = best[1]
            allowance = angle * (inside + k_factor * thickness)
            line = [_v(v) for v in shared.vertices()]
            if len(line) != 2:
                raise ValueError("a bend edge is not a straight line")
            moved_centre = _apply(rotation, _v(faces[other].center()))
            outward = moved_centre - line[0]
            outward -= direction * float(outward @ direction) + normal * float(outward @ normal)
            outward /= np.linalg.norm(outward)
            shift = _translation(outward * allowance)
            transform[other] = m_flange @ shift @ rotation
            pieces.append(faces[other])
            queue.append(other)
            corners = [line[0], line[1], line[1] + outward * allowance, line[0] + outward * allowance]
            flat_corners = [_apply(m_flange, c) for c in corners]
            if allowance > 1e-9:
                strips.append(make_face(Polyline(*[tuple(c) for c in flat_corners], close=True)))
            middle = [_apply(m_flange, p + outward * allowance / 2) for p in line]
            bend_lines.append(Edge.make_line(tuple(middle[0]), tuple(middle[1])))
            bends.append({"angle_deg": round(math.degrees(angle), 3), "inside_radius_mm": round(inside, 3),
                          "allowance_mm": round(allowance, 4), "direction": "up" if concave else "down",
                          "at_mm": [round(float(v), 2) for v in (line[0] + line[1]) / 2]})
    flats = [face.moved(_matrix_to_location(transform[i])) if not np.allclose(transform[i], np.eye(4)) else face
             for i, face in zip(transform, pieces)]
    # into the XY plane of the start face
    base = Plane(faces[start])
    flat_faces = [_upward(piece) for f in flats + strips for piece in base.to_local_coords(f).faces()]
    lines = [base.to_local_coords(e) for e in bend_lines]
    pattern = flat_faces[0]
    for face in flat_faces[1:]:
        pattern = pattern.fuse(face)
    pattern = pattern.clean()
    outline_faces = pattern.faces() if hasattr(pattern, "faces") else [pattern]
    box = pattern.bounding_box()
    holes = sum(len(f.inner_wires()) for f in outline_faces)
    reached = len(transform)
    return {"pattern": pattern, "bend_lines": lines, "bends": bends, "size_mm": [round(box.size.X, 3), round(box.size.Y, 3)],
            "area_mm2": round(sum(f.area for f in outline_faces), 3), "holes": holes, "flanges_unfolded": reached,
            "pieces": len(outline_faces), "k_factor": k_factor, "thickness_mm": thickness}


def write_dxf(result: dict[str, Any], path: Path) -> None:
    from build123d import ExportDXF, LineType, Unit

    dxf = ExportDXF(unit=Unit.MM)
    dxf.add_layer("OUTLINE", line_weight=0.35)
    dxf.add_layer("BEND", line_weight=0.18, line_type=LineType.ISO_DASH)
    dxf.add_shape(result["pattern"], layer="OUTLINE")
    if result["bend_lines"]:
        dxf.add_shape(result["bend_lines"], layer="BEND")
    path.parent.mkdir(parents=True, exist_ok=True)
    dxf.write(str(path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", type=Path)
    parser.add_argument("dxf", type=Path)
    parser.add_argument("--thickness", type=float, required=True)
    parser.add_argument("--k-factor", type=float, default=0.44)
    args = parser.parse_args()
    from build123d import import_step

    solid = import_step(str(args.step)).solids()[0]
    result = unfold(solid, args.thickness, args.k_factor)
    write_dxf(result, args.dxf)
    print(json.dumps({k: v for k, v in result.items() if k not in ("pattern", "bend_lines")} | {"dxf": str(args.dxf)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

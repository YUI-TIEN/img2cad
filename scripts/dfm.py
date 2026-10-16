#!/usr/bin/env python3
"""Manufacturability checks for CNC milling and sheet metal, measured on the B-rep.

    img2cad dfm part.step --process cnc --tool-radius 1.5     # 3-axis milling from +Z
    img2cad dfm bracket.step --process sheet                  # thickness from the part

CNC (3-axis, tool along Z, part machined from the top):

* `sharp_internal_corners` vertical concave edges between two flat walls: an end mill leaves
                           its radius there, so the drawn sharp corner cannot be cut
* `small_internal_radii`   vertical concave arcs (pocket corners, slots) tighter than the tool
* `deep_holes`             holes deeper than 4x (warn) / 10x (fail) their diameter
* `tiny_holes`             holes under 1 mm diameter (drill, not mill; often impractical)
* `undercut_faces`         faces whose outward normal points down (-Z) above the bottom:
                           they need a second setup or a 5-axis machine

Sheet metal:

* `uniform_thickness`      sampled wall thickness agrees with the sheet thickness
* `small_holes`            holes smaller than the thickness (punching limit)
* `tight_bends`            inside bend radii under the thickness

Each check has a status (pass / warn / fail), a detail line and evidence
(locations in model millimetres). Rules are common shop guidance, not a
specific shop's limits; treat warnings as questions for the maker.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def _edge_faces(solid) -> dict:
    """edge -> the faces that share it (shapes hash and compare by topological identity)."""
    table: dict = {}
    for face in solid.faces():
        for edge in face.edges():
            table.setdefault(edge, []).append(face)
    return table


def _vertical(vector, tolerance: float = 1e-3) -> bool:
    return abs(abs(vector.Z) - 1) < tolerance


def _concave_cylinders(solid):
    """(face, radius, axis direction, sweep angle in degrees, axial length) for every concave cylindrical face."""
    from build123d import GeomType

    found = []
    for face in solid.faces():
        if face.geom_type != GeomType.CYLINDER:
            continue
        axis = face.axis_of_rotation
        point = face.center()
        normal = face.normal_at(point)
        to_axis = axis.position + axis.direction * (point - axis.position).dot(axis.direction) - point
        if normal.dot(to_axis) <= 0:
            continue  # convex: a boss or an outer round
        box = face.bounding_box()
        extent = np.array([box.size.X, box.size.Y, box.size.Z])
        direction = np.abs([axis.direction.X, axis.direction.Y, axis.direction.Z])
        length = float(extent @ direction)
        sweep = math.degrees(face.area / (face.radius * length)) if length > 1e-9 else 0.0
        found.append((face, float(face.radius), axis.direction, sweep, length))
    return found


def _round(vector) -> list[float]:
    return [round(vector.X, 2), round(vector.Y, 2), round(vector.Z, 2)]


def cnc_checks(solid, tool_radius: float) -> list[dict[str, Any]]:
    from build123d import GeomType

    checks: list[dict[str, Any]] = []

    def check(name, status, detail, evidence=()):
        checks.append({"name": name, "status": status, "detail": detail, "evidence": list(evidence)[:20]})

    sharp = []
    for edge, faces in _edge_faces(solid).items():
        if edge.geom_type != GeomType.LINE or len(faces) != 2 or not _vertical(edge.tangent_at(0.5)):
            continue
        if any(face.geom_type != GeomType.PLANE for face in faces):
            continue
        middle = edge.center()
        n1, n2 = (face.normal_at(middle) for face in faces)
        if abs(n1.dot(n2)) > 0.999:
            continue
        probe = middle + (n2 - n1).normalized() * 0.05
        if solid.is_inside(probe):  # behind face 1, in front of face 2: material wraps the corner, so it is concave
            sharp.append({"at_mm": _round(middle), "length_mm": round(edge.length, 2)})
    check("sharp_internal_corners", "fail" if sharp else "pass",
          f"{len(sharp)} vertical internal corners are sharp; add a radius >= {tool_radius:g} mm (tool radius) or a dog-bone relief"
          if sharp else "no sharp vertical internal corners", sharp)

    cylinders = _concave_cylinders(solid)
    tight = [{"at_mm": _round(face.center()), "radius_mm": round(radius, 3)}
             for face, radius, direction, sweep, _ in cylinders if _vertical(direction) and sweep < 359 and radius < tool_radius - 1e-6]
    check("small_internal_radii", "fail" if tight else "pass",
          f"{len(tight)} vertical internal radii are under the {tool_radius:g} mm tool radius" if tight
          else f"all vertical internal radii >= {tool_radius:g} mm", tight)

    holes = [(face, radius, length) for face, radius, _, sweep, length in cylinders if sweep >= 359]
    deep = [{"at_mm": _round(face.center()), "diameter_mm": round(2 * r, 3), "depth_mm": round(length, 2),
             "ratio": round(length / (2 * r), 1)} for face, r, length in holes if length / (2 * r) > 4]
    worst = max((d["ratio"] for d in deep), default=0)
    check("deep_holes", "fail" if worst > 10 else ("warn" if deep else "pass"),
          f"{len(deep)} holes deeper than 4x diameter (worst {worst:g}x)" if deep else "no hole deeper than 4x its diameter", deep)
    tiny = [{"at_mm": _round(face.center()), "diameter_mm": round(2 * r, 3)} for face, r, _ in holes if 2 * r < 1.0]
    check("tiny_holes", "warn" if tiny else "pass",
          f"{len(tiny)} holes under 1 mm diameter" if tiny else "no hole under 1 mm", tiny)

    bottom = solid.bounding_box().min.Z
    under = []
    for face in solid.faces():
        if face.geom_type != GeomType.PLANE:
            continue
        centre = face.center()
        if face.normal_at(centre).Z < -0.01 and centre.Z > bottom + 1e-3:
            under.append({"at_mm": _round(centre), "area_mm2": round(face.area, 1)})
    check("undercut_faces", "warn" if under else "pass",
          f"{len(under)} downward-facing faces above the bottom need another setup (flip the part) or 5-axis"
          if under else "every face is reachable from +Z (one setup plus the bottom)", under)
    return checks


def sheet_checks(solid, path: Path, thickness: float | None) -> list[dict[str, Any]]:
    from printcheck import load_parts, ray_hits, triangle_geometry

    checks: list[dict[str, Any]] = []

    def check(name, status, detail, evidence=(), **values):
        checks.append({"name": name, "status": status, "detail": detail, "evidence": list(evidence)[:20], **values})

    samples = []
    for _, vertices, triangles in load_parts(path):
        normals, areas, centres = triangle_geometry(vertices, triangles)
        pick = np.random.default_rng(0).choice(len(triangles), size=600, p=areas / areas.sum())  # area-weighted
        hits = ray_hits(centres[pick] - normals[pick] * 1e-3, -normals[pick], vertices, triangles)
        samples.extend(float(h) for h in hits if np.isfinite(h))
    samples = np.array(samples)
    measured = float(np.median(samples)) if len(samples) else None
    thickness = thickness or measured
    if thickness is None:
        check("uniform_thickness", "fail", "no wall samples")
        return checks
    share = float(np.mean(np.abs(samples - thickness) <= max(0.05 * thickness, 0.05))) if len(samples) else 0.0
    check("uniform_thickness", "pass" if share > 0.9 else ("warn" if share > 0.7 else "fail"),
          f"{share:.0%} of wall samples are {thickness:.3g} mm thick" + ("" if share > 0.9 else "; sheet parts are one thickness"),
          thickness_mm=round(thickness, 3), median_mm=None if measured is None else round(measured, 3), share=round(share, 3))

    cylinders = _concave_cylinders(solid)
    small = [{"at_mm": _round(face.center()), "diameter_mm": round(2 * r, 3)} for face, r, _, sweep, _ in cylinders
             if sweep >= 359 and 2 * r < thickness]
    check("small_holes", "warn" if small else "pass",
          f"{len(small)} holes smaller than the {thickness:.3g} mm thickness" if small else "every hole is at least the sheet thickness", small)
    bends = [{"at_mm": _round(face.center()), "inside_radius_mm": round(r, 3)} for face, r, _, sweep, length in cylinders
             if sweep < 359 and length > thickness and r < thickness - 1e-6]
    check("tight_bends", "warn" if bends else "pass",
          f"{len(bends)} inside bend radii under the thickness (cracking risk)" if bends else "inside bend radii >= thickness", bends)
    return checks


def dfm(path: Path, process: str, tool_radius: float = 1.5, thickness: float | None = None) -> dict[str, Any]:
    from build123d import import_step

    from inspect_step import leaf_parts

    parts = leaf_parts(import_step(str(path)))
    report = {"file": str(path), "process": process, "parts": []}
    for index, part in enumerate(parts):
        for solid in part.solids():
            checks = cnc_checks(solid, tool_radius) if process == "cnc" else sheet_checks(solid, path, thickness)
            report["parts"].append({"name": getattr(part, "label", "") or f"part {index + 1}", "checks": checks})
    statuses = [c["status"] for p in report["parts"] for c in p["checks"]]
    report["status"] = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", type=Path)
    parser.add_argument("--process", choices=("cnc", "sheet"), required=True)
    parser.add_argument("--tool-radius", type=float, default=1.5, help="smallest end mill radius, mm (cnc)")
    parser.add_argument("--thickness", type=float, help="sheet thickness, mm (sheet; default: measured)")
    parser.add_argument("--out", type=Path, help="also write the JSON report here")
    args = parser.parse_args()
    report = dfm(args.step, args.process, args.tool_radius, args.thickness)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

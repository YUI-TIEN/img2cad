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
* `hole_types`             each hole read as plain, counterbored, countersunk (with its angle) or
                           likely tapped (bore = an ISO tap drill); tapped deeper than 3x the
                           thread warns, countersinks off 82/90/100/120 degrees warn
* `undercut_faces`         faces whose outward normal points down (-Z) above the bottom:
                           they need a second setup or a 5-axis machine
* `setups`                 the fewest 3-axis setups (+-X, +-Y, +-Z) that reach every face and
                           hole, ignoring fixturing and occlusion by other features

Sheet metal:

* `uniform_thickness`      sampled wall thickness agrees with the sheet thickness
* `small_holes`            holes smaller than the thickness (punching limit)
* `tight_bends`            inside bend radii under the thickness
* `hole_to_bend`           holes closer to a bend than 2 x thickness + inside radius (they distort)
* `flat_blank`             for parts whose bends share one axis: developed length with
                           `--k-factor` (default 0.44), blank size, and each bend's angle,
                           allowance and deduction (hole positions are not unfolded)

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
        # the kernel often splits a hole into two half cylinders: merge faces on one axis and radius
        same = next((i for i, (f, r, d, _, _) in enumerate(found) if abs(r - face.radius) < 1e-6
                     and _coaxial(f.axis_of_rotation.position, d, axis.position, axis.direction)), None)
        if same is None:
            found.append((face, float(face.radius), axis.direction, sweep, length))
        else:
            f, r, d, total, longest = found[same]
            found[same] = (f, r, d, min(360.0, total + sweep), max(longest, length))
    return found


# ISO metric coarse tap drill -> thread
TAP_DRILLS = {1.6: "M2", 2.05: "M2.5", 2.5: "M3", 3.3: "M4", 4.2: "M5", 5.0: "M6", 6.8: "M8", 8.5: "M10", 10.2: "M12", 14.0: "M16"}
THREAD_MAJOR = {"M2": 2, "M2.5": 2.5, "M3": 3, "M4": 4, "M5": 5, "M6": 6, "M8": 8, "M10": 10, "M12": 12, "M16": 16}
COUNTERSINK_ANGLES = (82, 90, 100, 120)


def _concave_cones(solid):
    """(face, axis point, axis direction, included angle in degrees) for countersink-like cones."""
    from build123d import GeomType, Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    found = []
    for face in solid.faces():
        if face.geom_type != GeomType.CONE:
            continue
        cone = BRepAdaptor_Surface(face.wrapped).Cone()
        axis = cone.Axis()
        point = Vector(axis.Location().X(), axis.Location().Y(), axis.Location().Z())
        direction = Vector(axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z())
        centre = face.center()
        to_axis = point + direction * (centre - point).dot(direction) - centre
        if face.normal_at(centre).dot(to_axis) > 0:  # material outside the cone: a countersink, not a point
            found.append((face, point, direction, abs(2 * __import__("math").degrees(cone.SemiAngle()))))
    return found


def _coaxial(point_a, direction_a, point_b, direction_b) -> bool:
    if abs(abs(direction_a.dot(direction_b)) - 1) > 1e-4:
        return False
    offset = point_b - point_a
    return (offset - direction_a * offset.dot(direction_a)).length < 1e-3


def hole_types(solid, cylinders) -> list[dict[str, Any]]:
    """Group coaxial concave cylinders and cones into holes and name each one."""
    groups: list[dict[str, Any]] = []
    for face, radius, direction, sweep, length in cylinders:
        if sweep < 359:
            continue
        point = face.axis_of_rotation.position
        group = next((g for g in groups if _coaxial(g["point"], g["direction"], point, direction)), None)
        if group is None:
            group = {"point": point, "direction": direction, "steps": [], "cones": [], "faces": []}
            groups.append(group)
        group["steps"].append((2 * radius, length))
        group["faces"].append(face)
    for face, point, direction, angle in _concave_cones(solid):
        group = next((g for g in groups if _coaxial(g["point"], g["direction"], point, direction)), None)
        if group is not None:
            group["cones"].append(angle)
    holes = []
    for group in groups:
        diameters = sorted({round(d, 3) for d, _ in group["steps"]})
        bore = diameters[0]
        depth = sum(length for d, length in group["steps"] if round(d, 3) == bore)
        centre = group["faces"][0].center()
        on_axis = group["point"] + group["direction"] * (centre - group["point"]).dot(group["direction"])
        entry = {"at_mm": _round(on_axis), "axis": _round(group["direction"]), "bore_mm": bore,
                 "bore_depth_mm": round(depth, 3), "type": "plain", "notes": []}
        if len(diameters) > 1:
            entry["type"] = "counterbore"
            entry["counterbore_mm"] = diameters[-1]
            entry["counterbore_depth_mm"] = round(sum(l for d, l in group["steps"] if round(d, 3) == diameters[-1]), 3)
        if group["cones"]:
            entry["type"] = "countersink" if entry["type"] == "plain" else entry["type"] + "+countersink"
            angle = round(group["cones"][0], 1)
            entry["countersink_deg"] = angle
            if not any(abs(angle - a) <= 1 for a in COUNTERSINK_ANGLES):
                entry["notes"].append(f"countersink {angle:g} deg is not a standard tool (82, 90, 100, 120)")
        thread = next((t for drill, t in TAP_DRILLS.items() if abs(drill - bore) <= 0.05), None)
        if thread:
            entry["likely_thread"] = thread
            entry["type"] = "tapped" if entry["type"] == "plain" else entry["type"] + "+tapped"
            if depth > 3 * THREAD_MAJOR[thread] + 1e-6:
                entry["notes"].append(f"{thread} tapped {depth:.3g} mm deep (> 3 x {THREAD_MAJOR[thread]:g}); taps break, use a shorter thread or thread milling")
        holes.append(entry)
    return holes


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
    found = hole_types(solid, cylinders)
    kinds = sorted({h["type"] for h in found})
    flagged = [h for h in found if h["notes"]]
    check("hole_types", "warn" if flagged else "pass",
          (f"{len(found)} holes: " + ", ".join(f"{sum(h['type'] == k for h in found)} {k}" for k in kinds) if found else "no holes")
          + (f"; {len(flagged)} need attention" if flagged else ""), flagged + [h for h in found if not h["notes"]])

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

    plan, unreachable = plan_setups(solid, cylinders)
    status = "fail" if unreachable else ("pass" if len(plan) <= 2 else "warn")
    detail = (f"{len(unreachable)} faces are not reachable from any axis direction (5-axis or a redesign)" if unreachable else
              f"{len(plan)} setup{'s' if len(plan) != 1 else ''}: " + ", ".join(f"{p['direction']} ({p['features']} features)" for p in plan))
    check("setups", status, detail, unreachable)
    checks[-1]["plan"] = plan
    return checks


DIRECTIONS = {"+Z": (0, 0, 1), "-Z": (0, 0, -1), "+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0)}


def plan_setups(solid, cylinders) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Greedy cover of faces and holes by tool directions. A flat face is cut from a direction it faces; a wall
    parallel to the tool is side-milled from any direction along it; a hole is drilled along its axis."""
    from build123d import GeomType, Vector

    features: list[tuple[str, set[str]]] = []
    for index, face in enumerate(solid.faces()):
        if face.geom_type != GeomType.PLANE:
            continue
        normal = face.normal_at(face.center())
        reach = {name for name, d in DIRECTIONS.items() if normal.dot(Vector(*d)) > 0.01}
        walls = {name for name, d in DIRECTIONS.items() if abs(normal.dot(Vector(*d))) <= 0.01}
        features.append((f"face {index} at {_round(face.center())}", reach | walls))
    for face, radius, direction, sweep, _ in cylinders:
        if sweep >= 359:
            reach = {name for name, d in DIRECTIONS.items() if abs(abs(direction.dot(Vector(*d))) - 1) < 1e-3}
            features.append((f"hole d{2 * radius:.3g} at {_round(face.center())}", reach))
    unreachable = [{"feature": name} for name, reach in features if not reach]
    remaining = [reach for _, reach in features if reach]
    plan = []
    while remaining:
        best = max(DIRECTIONS, key=lambda d: (sum(d in reach for reach in remaining), d == "+Z"))
        plan.append({"direction": best, "features": sum(best in reach for reach in remaining)})
        remaining = [reach for reach in remaining if best not in reach]
    return plan, unreachable


def sheet_checks(solid, path: Path, thickness: float | None, k_factor: float = 0.44) -> list[dict[str, Any]]:
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

    inner = [(face, r, direction, sweep) for face, r, direction, sweep, length in cylinders if sweep < 359 and length > thickness]
    holes = [(face, r) for face, r, _, sweep, _ in cylinders if sweep >= 359]
    close = []
    for hole, hole_r in holes:
        for bend, bend_r, _, _ in inner:
            gap = hole.distance_to(bend)
            if gap < 2 * thickness + bend_r - 1e-6:
                close.append({"hole_at_mm": _round(hole.center()), "bend_at_mm": _round(bend.center()),
                              "distance_mm": round(gap, 2), "minimum_mm": round(2 * thickness + bend_r, 2)})
    check("hole_to_bend", "warn" if close else "pass",
          f"{len(close)} holes closer to a bend than 2 x thickness + bend radius" if close else "holes clear of bends", close)
    checks.append(flat_blank(solid, inner, thickness, k_factor))
    return checks


def flat_blank(solid, inner, thickness: float, k_factor: float) -> dict[str, Any]:
    """Developed blank for bends about one shared axis: the mid-surface length from the cross-section area,
    corrected from k = 0.5 to the given K-factor per bend."""
    from build123d import Plane, section

    result = {"name": "flat_blank", "evidence": [], "k_factor": k_factor}
    if not inner:
        return {**result, "status": "pass", "detail": "no bends: the part is its own blank"}
    axis = inner[0][2]
    if any(abs(abs(direction.dot(axis)) - 1) > 1e-3 for _, _, direction, _ in inner):
        return {**result, "status": "warn", "detail": "bends about different axes: unfold it in a sheet-metal CAD tool"}
    box = solid.bounding_box()
    centre = box.center()
    extents = [v.X * axis.X + v.Y * axis.Y + v.Z * axis.Z for v in solid.vertices()]
    lo, hi = min(extents), max(extents)
    width = hi - lo
    areas = []
    for fraction in (0.13, 0.29, 0.47, 0.61, 0.83):
        origin = centre + axis * ((lo + fraction * width) - centre.dot(axis))
        try:
            areas.append(section(solid, Plane(origin=origin, z_dir=axis)).area)
        except Exception:  # noqa: BLE001 - a section that misses is just skipped
            continue
    if not areas:
        return {**result, "status": "warn", "detail": "could not section the part across its bends"}
    area = max(areas)  # a section through a hole is smaller
    mid_length = area / thickness
    bend_list = []
    correction = 0.0
    for face, radius, _, sweep in inner:
        angle = math.radians(sweep)
        allowance = angle * (radius + k_factor * thickness)
        deduction = 2 * (radius + thickness) * math.tan(angle / 2) - allowance if sweep < 179 else None
        correction += (k_factor - 0.5) * thickness * angle
        bend_list.append({"at_mm": _round(face.center()), "angle_deg": round(sweep, 2), "inside_radius_mm": round(radius, 3),
                          "bend_allowance_mm": round(allowance, 3), "bend_deduction_mm": None if deduction is None else round(deduction, 3)})
    length = mid_length + correction
    prismatic = max(areas) - min(areas) < 1e-3 * max(areas) + 1e-6
    note = "" if prismatic else "; sections differ along the bend axis (holes or notches), so the blank is the outer rectangle"
    return {**result, "status": "pass", "detail": f"blank {length:.2f} x {width:.2f} mm, {len(bend_list)} bends{note}",
            "length_mm": round(length, 3), "width_mm": round(width, 3), "thickness_mm": round(thickness, 3), "bends": bend_list}


def dfm(path: Path, process: str, tool_radius: float = 1.5, thickness: float | None = None, k_factor: float = 0.44) -> dict[str, Any]:
    from build123d import import_step

    from inspect_step import leaf_parts

    parts = leaf_parts(import_step(str(path)))
    report = {"file": str(path), "process": process, "parts": []}
    for index, part in enumerate(parts):
        for solid in part.solids():
            checks = cnc_checks(solid, tool_radius) if process == "cnc" else sheet_checks(solid, path, thickness, k_factor)
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
    parser.add_argument("--k-factor", type=float, default=0.44, help="sheet: neutral-axis position for the flat blank (0.3-0.5)")
    parser.add_argument("--out", type=Path, help="also write the JSON report here")
    args = parser.parse_args()
    report = dfm(args.step, args.process, args.tool_radius, args.thickness, args.k_factor)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

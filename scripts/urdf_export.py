#!/usr/bin/env python3
"""Robot description (URDF, SDF or MuJoCo MJCF) from a coloured STEP assembly.

    img2cad urdf model.step --out robot/                    # every part fixed to the largest
    img2cad urdf model.step --out robot/ --joints joints.json --density 2.7e-6
    img2cad urdf model.step --out robot/ --joints joints.json --format sdf    # Gazebo
    img2cad urdf model.step --out robot/ --joints joints.json --format mjcf   # MuJoCo
    img2cad urdf model.step --out robot/ --guess-joints --material base=aluminium

Each assembly part becomes a link: its mesh (meshes/<link>.stl, millimetres
scaled to metres), its colour, a collision mesh (`--collision hull`, the
default, is the part's convex hull, meshes/<link>_collision.stl; `mesh` reuses
the visual mesh) and exact inertial values from the B-rep (mass = volume x
density, centre of mass, inertia tensor about it). joints.json says how links
move; parts it does not mention are fixed to the root link (the largest part,
or "root" in the file):

    {"root": "base",
     "joints": [{"name": "shoulder", "type": "revolute", "parent": "base", "child": "arm",
                 "origin": [0, 0, 120], "axis": [0, 0, 1], "frame": "axis",
                 "limit": {"lower": -1.57, "upper": 1.57, "effort": 5, "velocity": 2}}]}

`origin` is the joint's position and `axis` its direction, both in the model
frame (millimetres); the robot appears exactly as modelled at zero joint
values. A link's frame is world-aligned at its joint origin unless the joint
says `"frame": "axis"` (the frame's z axis along the joint axis, the ROS
convention for tilted joints) or gives `"rpy": [roll, pitch, yaw]` in radians
(fixed X-Y-Z, as URDF). Guessed joints use `"frame": "axis"`. Inertia, meshes
and child joints are expressed in each link's own frame. Link names are the
part labels, made URDF-safe.

Materials: `--density` (kg/mm^3, default 1.24e-6: PLA) applies to every part
unless the part has its own, from `--material arm=aluminium` (repeatable) or
`"materials": {"arm": "aluminium", "shaft": 7.85e-6}` in joints.json. Names:
abs, aluminium/aluminum, brass, carbon_fibre, copper, nylon, petg, pla, resin,
stainless, steel, titanium, wood.

`--guess-joints` proposes joints for parts the joints file does not connect:

* revolute where one part's shaft or boss sits in another's bore on the same
  axis (diameters within 1 mm). Its limits come from turning the child both
  ways in 5-degree steps (refined to 0.5 degree) until it hits another part;
  a part that turns freely all the way round becomes `continuous`;
* prismatic where flat faces of two parts lie against each other (opposed,
  within 0.25 mm) and one part's contact face is at least 1.5 x longer than
  the other part along one direction: the slide runs along it, limited by
  the ends of the longer face.

The tree grows outward from the root. Guessed joints are marked
`"guessed": true` in the report and written to joints_guessed.json beside
the robot, so they can be reviewed and passed back with `--joints`.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import struct
from typing import Any
from xml.sax.saxutils import quoteattr

import numpy as np

JOINT_TYPES = ("fixed", "revolute", "continuous", "prismatic")
MATERIALS = {"pla": 1.24e-6, "petg": 1.27e-6, "abs": 1.04e-6, "nylon": 1.14e-6, "resin": 1.15e-6, "wood": 0.6e-6,
             "aluminium": 2.7e-6, "aluminum": 2.7e-6, "steel": 7.85e-6, "stainless": 8.0e-6, "brass": 8.5e-6,
             "copper": 8.96e-6, "titanium": 4.43e-6, "carbon_fibre": 1.6e-6}
FIT_CLEARANCE_MM = 1.0  # bore diameter minus shaft diameter, at most
AXIS_TOLERANCE_MM = 0.05
CONTACT_GAP_MM = 0.25  # flat faces this close (and opposed) count as sliding contact
SLIDE_RATIO = 1.5
SWEEP_STEP_DEG, SWEEP_REFINE_DEG = 5.0, 0.5


def density_of(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    if isinstance(value, str) and value.lower() in MATERIALS:
        return MATERIALS[value.lower()]
    raise ValueError(f"material {value!r}: give a density in kg/mm^3 or one of {', '.join(sorted(MATERIALS))}")


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "part"


def vec(values) -> str:
    return " ".join(f"{0.0 if abs(float(v)) < 1e-12 else float(v):.6g}" for v in values)


# ---------- rotations ----------

def rpy_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """URDF fixed-axis X-Y-Z: R = Rz(yaw) Ry(pitch) Rx(roll)."""
    cr, sr, cp, sp, cy, sy = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def matrix_rpy(r: np.ndarray) -> list[float]:
    pitch = math.asin(max(-1.0, min(1.0, -r[2, 0])))
    if abs(math.cos(pitch)) > 1e-9:
        return [math.atan2(r[2, 1], r[2, 2]), pitch, math.atan2(r[1, 0], r[0, 0])]
    return [math.atan2(-r[1, 2], r[1, 1]), pitch, 0.0]  # gimbal lock


def matrix_quat(r: np.ndarray) -> list[float]:
    """(w, x, y, z), as MuJoCo wants it."""
    w = math.sqrt(max(0.0, 1 + r[0, 0] + r[1, 1] + r[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + r[0, 0] - r[1, 1] - r[2, 2])) / 2, r[2, 1] - r[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - r[0, 0] + r[1, 1] - r[2, 2])) / 2, r[0, 2] - r[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - r[0, 0] - r[1, 1] + r[2, 2])) / 2, r[1, 0] - r[0, 1])
    return [w, x, y, z]


def axis_frame(axis: list[float]) -> np.ndarray:
    """A rotation whose z column is `axis` (x as close to world X as possible)."""
    z = np.array(axis, dtype=float)
    z /= np.linalg.norm(z)
    helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x = helper - z * helper.dot(z)
    x /= np.linalg.norm(x)
    return np.column_stack([x, np.cross(z, x), z])


# ---------- joint guessing ----------

def _line_distance(point_a, direction_a, point_b) -> float:
    offset = [point_b[i] - point_a[i] for i in range(3)]
    along = sum(offset[i] * direction_a[i] for i in range(3))
    return sum((offset[i] - along * direction_a[i]) ** 2 for i in range(3)) ** 0.5


def _revolute_fits(links: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    from inspect_step import cylindrical_features

    features = {name: [f for f in cylindrical_features(part) if f.get("sweep", 0) >= 0.5] for name, part in links.items()}
    fits: dict[tuple[str, str], dict[str, Any]] = {}
    names = list(links)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            best = None
            for shaft_part, bore_part in ((a, b), (b, a)):
                for shaft in (f for f in features[shaft_part] if f["kind"] == "boss"):
                    for bore in (f for f in features[bore_part] if f["kind"] == "hole"):
                        clearance = bore["diameter"] - shaft["diameter"]
                        parallel = abs(sum(x * y for x, y in zip(shaft["axis_direction"], bore["axis_direction"])))
                        if not (-0.05 <= clearance <= FIT_CLEARANCE_MM and parallel > 0.9999):
                            continue
                        if _line_distance(bore["axis_point"], bore["axis_direction"], shaft["axis_point"]) > AXIS_TOLERANCE_MM:
                            continue
                        if best is None or clearance < best["clearance"]:
                            best = {"type": "revolute", "clearance": clearance, "axis_point": bore["axis_point"],
                                    "axis": bore["axis_direction"], "diameter": bore["diameter"]}
            if best:
                fits[(a, b)] = fits[(b, a)] = best
    return fits


def _planar_faces(part) -> list[tuple[np.ndarray, float, Any]]:
    from build123d import GeomType

    found = []
    for face in part.faces():
        if face.geom_type != GeomType.PLANE:
            continue
        centre = face.center()
        normal = face.normal_at(centre)
        n = np.array([normal.X, normal.Y, normal.Z])
        found.append((n, float(n.dot([centre.X, centre.Y, centre.Z])), face))
    return found


def _extent(shape, direction: np.ndarray) -> tuple[float, float]:
    values = [float(np.dot([v.X, v.Y, v.Z], direction)) for v in shape.vertices()]
    return min(values), max(values)


def _prismatic_fits(links: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Slides: two parts held against each other on flat faces with at least two non-parallel contact normals
    (a groove's floor and wall, a rail's top and side), so only one direction is free; the slide runs along it
    when the guide's contact faces are much longer than the slider in that direction."""
    faces = {name: _planar_faces(part) for name, part in links.items()}
    fits: dict[tuple[str, str], dict[str, Any]] = {}
    names = list(links)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            best = None
            for guide, slider in ((a, b), (b, a)):
                contacts = []
                for n1, d1, f1 in faces[guide]:
                    for n2, d2, f2 in faces[slider]:
                        if n1.dot(n2) < -0.9999 and abs(d1 + d2) <= CONTACT_GAP_MM:  # opposed and touching
                            try:
                                touching = f1.distance_to(f2) <= CONTACT_GAP_MM
                            except Exception:  # noqa: BLE001
                                touching = False
                            if touching:
                                contacts.append((n1, f1))
                normals = [n for n, _ in contacts]
                pair = next(((p, q) for p in normals for q in normals if np.linalg.norm(np.cross(p, q)) > 0.5), None)
                if pair is None:
                    continue  # resting on one plane leaves it free in two directions: not a slide
                axis = np.cross(*pair)
                axis /= np.linalg.norm(axis)
                if any(abs(n.dot(axis)) > 1e-3 for n in normals):
                    continue  # some contact blocks motion along the would-be slide
                g_lo = min(_extent(f, axis)[0] for _, f in contacts)
                g_hi = max(_extent(f, axis)[1] for _, f in contacts)
                p_lo, p_hi = _extent(links[slider], axis)
                if (g_hi - g_lo) >= SLIDE_RATIO * (p_hi - p_lo) and (best is None or g_hi - g_lo > best["travel"]):
                    if axis[np.argmax(np.abs(axis))] < 0:
                        axis = -axis
                        g_lo, g_hi, p_lo, p_hi = -g_hi, -g_lo, -p_hi, -p_lo
                    best = {"type": "prismatic", "guide": guide, "slider": slider, "axis": [round(float(v), 6) for v in axis],
                            "lower": g_lo - p_lo, "upper": g_hi - p_hi, "travel": g_hi - g_lo}
            if best:
                fits[(a, b)] = fits[(b, a)] = best
    return fits


def _overlap(moved, others, tolerance: float) -> bool:
    for other in others:
        try:
            common = moved & other
        except Exception:  # noqa: BLE001 - a failed boolean is treated as no contact
            continue
        if common is not None and float(getattr(common, "volume", 0.0)) > tolerance:
            return True
    return False


def revolute_limits(child, others: list[Any], point: list[float], axis: list[float]) -> tuple[float, float] | None:
    """Turn `child` about the axis both ways until it hits one of `others`; None if it turns all the way round."""
    from build123d import Axis

    tolerance = max(1e-3, float(child.volume) * 1e-4)
    if _overlap(child, others, tolerance):
        return None  # already interfering as modelled: no meaningful sweep
    hinge = Axis(tuple(point), tuple(axis))
    result = []
    for sign in (1, -1):
        free, hit = 0.0, None
        angle = SWEEP_STEP_DEG
        while angle <= 180 + 1e-9:
            if _overlap(child.rotate(hinge, sign * angle), others, tolerance):
                hit = angle
                break
            free = angle
            angle += SWEEP_STEP_DEG
        if hit is None:
            result.append(None)
            continue
        while hit - free > SWEEP_REFINE_DEG:
            middle = (hit + free) / 2
            if _overlap(child.rotate(hinge, sign * middle), others, tolerance):
                hit = middle
            else:
                free = middle
        result.append(sign * math.radians(free))
    upper, lower = result
    if upper is None and lower is None:
        return None
    return (lower if lower is not None else -math.pi, upper if upper is not None else math.pi)


def guess_joints(links: dict[str, Any], root: str, connected: set[str], limits: bool = True) -> list[dict[str, Any]]:
    """Revolute and prismatic joints as a tree grown from the root over parts not yet connected."""
    from build123d import CenterOf

    revolute = _revolute_fits(links)
    prismatic = _prismatic_fits(links)
    names = list(links)
    joints = []
    reached = {root} | (connected & set(names))
    frontier = [root]
    while frontier:
        parent = frontier.pop(0)
        for child in names:
            if child in reached:
                continue
            fit = revolute.get((parent, child)) or prismatic.get((parent, child))
            if fit is None:
                continue
            centre = links[child].center(CenterOf.MASS)
            centre = [centre.X, centre.Y, centre.Z]
            if fit["type"] == "revolute":
                point, axis = fit["axis_point"], fit["axis"]
                along = sum((c - p) * d for c, p, d in zip(centre, point, axis))  # origin: nearest the child's centre
                origin = [round(p + along * d, 4) for p, d in zip(point, axis)]
                joint = {"name": f"{parent}_to_{child}", "type": "revolute", "parent": parent, "child": child,
                         "origin": origin, "axis": [round(v, 6) for v in axis], "frame": "axis", "guessed": True,
                         "evidence": f"shaft/bore D{fit['diameter']:g} mm, clearance {fit['clearance']:.3g} mm"}
                if limits:
                    # parts touching the child (other than its parent) ride along with it, so they are not obstacles
                    others = [links[n] for n in names if n != child and (n == parent or links[child].distance_to(links[n]) > 0.05)]
                    found = revolute_limits(links[child], others, origin, axis)
                    if found is None:
                        joint["type"] = "continuous"
                        joint["evidence"] += "; turns freely all the way round"
                    else:
                        joint["limit"] = {"lower": round(found[0], 4), "upper": round(found[1], 4)}
                        joint["evidence"] += f"; stops at {math.degrees(found[0]):.1f} / {math.degrees(found[1]):.1f} deg"
            else:
                sign = 1.0 if fit["slider"] == child else -1.0  # limits are for the slider moving along +axis
                lower, upper = (fit["lower"], fit["upper"]) if sign > 0 else (-fit["upper"], -fit["lower"])
                joint = {"name": f"{parent}_to_{child}", "type": "prismatic", "parent": parent, "child": child,
                         "origin": [round(v, 4) for v in centre], "axis": fit["axis"], "frame": "axis", "guessed": True,
                         "limit": {"lower": round(lower / 1000, 6), "upper": round(upper / 1000, 6)},
                         "evidence": f"flat contact; guide {fit['travel']:.1f} mm long, travel {upper - lower:.1f} mm"}
            joints.append(joint)
            reached.add(child)
            frontier.append(child)
    return joints


# ---------- meshes ----------

def _write_stl(path: Path, vertices: np.ndarray, triangles: np.ndarray) -> None:
    a, b, c = (vertices[triangles[:, i]] for i in range(3))
    normals = np.cross(b - a, c - a)
    normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-12)[:, None]
    with path.open("wb") as handle:
        handle.write(b"img2cad".ljust(80, b" ") + struct.pack("<I", len(triangles)))
        for n, tri in zip(normals, triangles):
            handle.write(struct.pack("<12fH", *n, *vertices[tri].reshape(-1), 0))


def convex_hull_stl(part, path: Path, tolerance: float) -> None:
    from scipy.spatial import ConvexHull

    vertices, _ = part.tessellate(tolerance, 0.3)
    points = np.array([(v.X, v.Y, v.Z) for v in vertices])
    hull = ConvexHull(points)
    triangles = hull.simplices.copy()
    centre = points[hull.vertices].mean(axis=0)
    for row, tri in enumerate(triangles):  # outward winding
        a, b, c = points[tri]
        if np.dot(np.cross(b - a, c - a), a - centre) < 0:
            triangles[row] = tri[[0, 2, 1]]
    _write_stl(path, points, triangles)


# ---------- export ----------

def export_urdf(step_path: Path, out_dir: Path, joints_spec: dict[str, Any] | None = None, density: float = 1.24e-6,
                robot_name: str | None = None, fmt: str = "urdf", materials: dict[str, Any] | None = None,
                guess: bool = False, collision: str = "hull", limits: bool = True) -> dict[str, Any]:
    from build123d import CenterOf, export_stl, import_step

    from inspect_step import color_rgba, leaf_parts
    from mesh_export import default_tolerance

    shape = import_step(str(step_path))
    parts = leaf_parts(shape)
    if not parts:
        raise ValueError("no parts in the STEP file")
    names, links = [], {}
    for index, part in enumerate(parts):
        name = safe(getattr(part, "label", "") or f"part_{index + 1}")
        while name in names:
            name += "_"
        names.append(name)
        links[name] = part
    spec = joints_spec or {}
    root = spec.get("root") or max(links, key=lambda n: links[n].volume)
    if root not in links:
        raise ValueError(f"root {root!r} is not a part ({', '.join(links)})")
    joints = {}
    for joint in spec.get("joints", []):
        if joint.get("type", "fixed") not in JOINT_TYPES:
            raise ValueError(f"joint {joint.get('name')!r}: type must be one of {', '.join(JOINT_TYPES)}")
        for key in ("parent", "child"):
            if joint.get(key) not in links:
                raise ValueError(f"joint {joint.get('name')!r}: {key} {joint.get(key)!r} is not a part ({', '.join(links)})")
        if joint["child"] == root or joint["child"] in joints:
            raise ValueError(f"link {joint['child']!r} has more than one parent (or is the root)")
        joints[joint["child"]] = joint
    material_of = {**spec.get("materials", {}), **(materials or {})}
    unknown = [name for name in material_of if name not in links]
    if unknown:
        raise ValueError(f"materials for unknown parts {', '.join(unknown)} ({', '.join(links)})")
    densities = {name: density_of(material_of[name]) if name in material_of else density for name in links}
    guessed = []
    if guess:
        connected = set(joints) | {j["parent"] for j in joints.values()}
        for joint in guess_joints(links, root, connected, limits):
            if joint["child"] not in joints:
                joints[joint["child"]] = joint
                guessed.append(joint)
    for name in links:
        if name != root and name not in joints:
            joints[name] = {"name": f"{root}_to_{name}", "type": "fixed", "parent": root, "child": name, "origin": [0, 0, 0]}

    # Link frames in the world: position (m) and rotation. The root sits at the world origin, world-aligned.
    position = {root: np.zeros(3)}
    rotation = {root: np.eye(3)}
    pending = dict(joints)
    while pending:
        progressed = False
        for child, joint in list(pending.items()):
            parent = joint["parent"]
            if parent not in position:
                continue
            origin = joint.get("origin")
            position[child] = np.array(origin, dtype=float) * 1e-3 if origin is not None else position[parent].copy()
            if "rpy" in joint:
                rotation[child] = rpy_matrix(*[float(v) for v in joint["rpy"]])
            elif joint.get("frame") == "axis" and joint.get("type", "fixed") != "fixed":
                rotation[child] = axis_frame(joint.get("axis", [0, 0, 1]))
            else:
                rotation[child] = np.eye(3)
            del pending[child]
            progressed = True
        if not progressed:
            raise ValueError(f"joints form a loop or a detached chain: {', '.join(pending)}")

    meshes = out_dir / "meshes"
    meshes.mkdir(parents=True, exist_ok=True)
    robot = robot_name or safe(step_path.stem if step_path.stem != "model" else step_path.parent.name)
    tolerance = default_tolerance(shape)
    data = {}
    for name, part in links.items():
        export_stl(part, str(meshes / f"{name}.stl"))
        collision_file = f"{name}.stl"
        if collision == "hull":
            convex_hull_stl(part, meshes / f"{name}_collision.stl", tolerance)
            collision_file = f"{name}_collision.stl"
        p, r = position[name], rotation[name]
        com = part.center(CenterOf.MASS)
        k = densities[name] * 1e-6  # mm^5 x kg/mm^3 -> kg m^2
        inertia_world = np.array(part.matrix_of_inertia, dtype=float) * k
        data[name] = {"rgba": color_rgba(part) or [0.7, 0.7, 0.7, 1.0], "mass": float(part.volume) * densities[name],
                      "com": r.T @ (np.array([com.X, com.Y, com.Z]) * 1e-3 - p),
                      "inertia": r.T @ inertia_world @ r,
                      "position": p, "rotation": r,
                      "mesh_xyz": r.T @ (-p), "mesh_rotation": r.T,  # world mesh placed in the link frame
                      "collision": collision_file}
    for child, joint in joints.items():
        parent = joint["parent"]
        rp, rc = rotation[parent], rotation[child]
        joint["_xyz"] = rp.T @ (position[child] - position[parent])
        joint["_rotation"] = rp.T @ rc
        axis = np.array(joint.get("axis", [0, 0, 1]), dtype=float)
        joint["_axis"] = rc.T @ (axis / np.linalg.norm(axis))
    writer = {"urdf": _urdf, "sdf": _sdf, "mjcf": _mjcf}[fmt]
    path = out_dir / f"{robot}.{ {'urdf': 'urdf', 'sdf': 'sdf', 'mjcf': 'xml'}[fmt] }"
    path.write_text(writer(robot, root, data, joints), encoding="utf-8")
    report = {fmt: str(path), "format": fmt, "root": root, "collision": collision,
              "links": [{"link": n, "mass_kg": round(d["mass"], 6), "density": densities[n]} for n, d in data.items()],
              "joints": [{"name": j.get("name"), "type": j.get("type", "fixed"), "parent": j["parent"], "child": c,
                          **({"limit": j["limit"]} if "limit" in j else {}),
                          **({"guessed": True, "evidence": j["evidence"]} if j.get("guessed") else {})} for c, j in joints.items()]}
    if guess:
        explicit = list((joints_spec or {}).get("joints", []))
        clean = [{k: v for k, v in j.items() if not k.startswith("_")} for j in explicit + guessed]
        guessed_file = out_dir / "joints_guessed.json"
        guessed_file.write_text(json.dumps({"root": root, "materials": material_of, "joints": clean}, indent=2) + "\n", encoding="utf-8")
        report["joints_guessed"] = str(guessed_file)
    return report


def _joint_name(joint: dict) -> str:
    return safe(joint.get("name") or f"{joint['parent']}_to_{joint['child']}")


def _limit(joint: dict) -> dict:
    limit = joint.get("limit", {})
    prismatic = joint.get("type") == "prismatic"
    return {"lower": limit.get("lower", -0.1 if prismatic else -3.14159), "upper": limit.get("upper", 0.1 if prismatic else 3.14159),
            "effort": limit.get("effort", 10), "velocity": limit.get("velocity", 1)}


def _urdf(robot: str, root: str, data: dict, joints: dict) -> str:
    xml = ['<?xml version="1.0"?>', f"<robot name={quoteattr(robot)}>"]
    for name, d in data.items():
        i = d["inertia"]
        mesh_origin = f'<origin xyz="{vec(d["mesh_xyz"])}" rpy="{vec(matrix_rpy(d["mesh_rotation"]))}"/>'
        mesh = f'<mesh filename="meshes/{name}.stl" scale="0.001 0.001 0.001"/>'
        collision = f'<mesh filename="meshes/{d["collision"]}" scale="0.001 0.001 0.001"/>'
        xml += [f"  <link name={quoteattr(name)}>",
                f"    <inertial><origin xyz=\"{vec(d['com'])}\" rpy=\"0 0 0\"/><mass value=\"{d['mass']:.6g}\"/>",
                f"      <inertia ixx=\"{i[0][0]:.6g}\" ixy=\"{i[0][1]:.6g}\" ixz=\"{i[0][2]:.6g}\" "
                f"iyy=\"{i[1][1]:.6g}\" iyz=\"{i[1][2]:.6g}\" izz=\"{i[2][2]:.6g}\"/></inertial>",
                f"    <visual>{mesh_origin}<geometry>{mesh}</geometry>",
                f"      <material name={quoteattr(name + '_material')}><color rgba=\"{vec(d['rgba'])}\"/></material></visual>",
                f"    <collision>{mesh_origin}<geometry>{collision}</geometry></collision>",
                "  </link>"]
    for child, joint in joints.items():
        parent, kind = joint["parent"], joint.get("type", "fixed")
        xml += [f"  <joint name={quoteattr(_joint_name(joint))} type=\"{kind}\">",
                f"    <parent link={quoteattr(parent)}/><child link={quoteattr(child)}/>",
                f"    <origin xyz=\"{vec(joint['_xyz'])}\" rpy=\"{vec(matrix_rpy(joint['_rotation']))}\"/>"]
        if kind != "fixed":
            xml.append(f"    <axis xyz=\"{vec(joint['_axis'])}\"/>")
        if kind in ("revolute", "prismatic"):
            limit = _limit(joint)
            xml.append(f"    <limit lower=\"{limit['lower']}\" upper=\"{limit['upper']}\" effort=\"{limit['effort']}\" velocity=\"{limit['velocity']}\"/>")
        xml.append("  </joint>")
    return "\n".join(xml + ["</robot>"]) + "\n"


def _sdf(robot: str, root: str, data: dict, joints: dict) -> str:
    """SDFormat 1.9 (Gazebo): link poses in the model frame; each joint sits at its child's origin, axis in the child frame."""
    xml = ['<?xml version="1.0"?>', '<sdf version="1.9">', f"  <model name={quoteattr(robot)}>"]
    for name, d in data.items():
        i = d["inertia"]
        mesh_pose = f"<pose>{vec(d['mesh_xyz'])} {vec(matrix_rpy(d['mesh_rotation']))}</pose>"
        mesh = f"<mesh><uri>meshes/{name}.stl</uri><scale>0.001 0.001 0.001</scale></mesh>"
        collision = f"<mesh><uri>meshes/{d['collision']}</uri><scale>0.001 0.001 0.001</scale></mesh>"
        rgba = vec(d["rgba"])
        xml += [f"    <link name={quoteattr(name)}>",
                f"      <pose>{vec(d['position'])} {vec(matrix_rpy(d['rotation']))}</pose>",
                f"      <inertial><pose>{vec(d['com'])} 0 0 0</pose><mass>{d['mass']:.6g}</mass>",
                f"        <inertia><ixx>{i[0][0]:.6g}</ixx><ixy>{i[0][1]:.6g}</ixy><ixz>{i[0][2]:.6g}</ixz>"
                f"<iyy>{i[1][1]:.6g}</iyy><iyz>{i[1][2]:.6g}</iyz><izz>{i[2][2]:.6g}</izz></inertia></inertial>",
                f"      <visual name=\"visual\">{mesh_pose}<geometry>{mesh}</geometry>",
                f"        <material><ambient>{rgba}</ambient><diffuse>{rgba}</diffuse></material></visual>",
                f"      <collision name=\"collision\">{mesh_pose}<geometry>{collision}</geometry></collision>",
                "    </link>"]
    for child, joint in joints.items():
        kind = joint.get("type", "fixed")
        xml += [f"    <joint name={quoteattr(_joint_name(joint))} type=\"{kind}\">",
                f"      <parent>{joint['parent']}</parent><child>{child}</child>"]
        if kind != "fixed":
            limit = _limit(joint)
            lim = (f"<limit><lower>{limit['lower']}</lower><upper>{limit['upper']}</upper><effort>{limit['effort']}</effort>"
                   f"<velocity>{limit['velocity']}</velocity></limit>") if kind != "continuous" else ""
            xml.append(f"      <axis><xyz>{vec(joint['_axis'])}</xyz>{lim}</axis>")
        xml.append("    </joint>")
    return "\n".join(xml + ["  </model>", "</sdf>"]) + "\n"


def _mjcf(robot: str, root: str, data: dict, joints: dict) -> str:
    """MuJoCo MJCF: bodies nested along the joint tree, each placed relative to its parent."""
    children: dict[str, list[str]] = {}
    for child, joint in joints.items():
        children.setdefault(joint["parent"], []).append(child)
    kinds = {"revolute": "hinge", "continuous": "hinge", "prismatic": "slide"}
    xml = [f"<mujoco model={quoteattr(robot)}>", '  <compiler angle="radian" meshdir="meshes"/>', "  <asset>"]
    for name, d in data.items():
        xml.append(f"    <mesh name={quoteattr(name)} file=\"{name}.stl\" scale=\"0.001 0.001 0.001\"/>")
        if d["collision"] != f"{name}.stl":
            xml.append(f"    <mesh name={quoteattr(name + '_collision')} file=\"{d['collision']}\" scale=\"0.001 0.001 0.001\"/>")
    xml += ["  </asset>", "  <worldbody>"]

    def body(name: str, depth: int) -> None:
        d, pad = data[name], "  " * depth
        joint = joints.get(name)
        pos, quat = (d["position"], matrix_quat(d["rotation"])) if joint is None else (joint["_xyz"], matrix_quat(joint["_rotation"]))
        i = d["inertia"]
        xml.append(f"{pad}<body name={quoteattr(name)} pos=\"{vec(pos)}\" quat=\"{vec(quat)}\">")
        xml.append(f"{pad}  <inertial pos=\"{vec(d['com'])}\" mass=\"{d['mass']:.6g}\" "
                   f"fullinertia=\"{i[0][0]:.6g} {i[1][1]:.6g} {i[2][2]:.6g} {i[0][1]:.6g} {i[0][2]:.6g} {i[1][2]:.6g}\"/>")
        if joint and joint.get("type", "fixed") in kinds:
            extra = ""
            if joint["type"] != "continuous":
                limit = _limit(joint)
                extra = f" range=\"{limit['lower']} {limit['upper']}\" limited=\"true\""
            xml.append(f"{pad}  <joint name={quoteattr(_joint_name(joint))} type=\"{kinds[joint['type']]}\" "
                       f"axis=\"{vec(joint['_axis'])}\"{extra}/>")
        mesh_pose = f"pos=\"{vec(d['mesh_xyz'])}\" quat=\"{vec(matrix_quat(d['mesh_rotation']))}\""
        if d["collision"] != f"{name}.stl":
            xml.append(f"{pad}  <geom type=\"mesh\" mesh={quoteattr(name)} {mesh_pose} rgba=\"{vec(d['rgba'])}\" contype=\"0\" conaffinity=\"0\" group=\"1\"/>")
            xml.append(f"{pad}  <geom type=\"mesh\" mesh={quoteattr(name + '_collision')} {mesh_pose} group=\"3\" rgba=\"0 0 0 0\"/>")
        else:
            xml.append(f"{pad}  <geom type=\"mesh\" mesh={quoteattr(name)} {mesh_pose} rgba=\"{vec(d['rgba'])}\"/>")
        for child in children.get(name, []):
            body(child, depth + 1)
        xml.append(f"{pad}</body>")

    body(root, 2)
    return "\n".join(xml + ["  </worldbody>", "</mujoco>"]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--joints", type=Path, help="joints.json (default: every part fixed to the largest)")
    parser.add_argument("--density", type=float, default=1.24e-6, help="kg/mm^3 (PLA 1.24e-6, aluminium 2.7e-6, steel 7.85e-6)")
    parser.add_argument("--name", help="robot name (default: from the file)")
    parser.add_argument("--format", choices=("urdf", "sdf", "mjcf"), default="urdf")
    parser.add_argument("--material", action="append", default=[], metavar="PART=MATERIAL",
                        help="per-part material name or density, e.g. arm=aluminium or shaft=7.85e-6 (repeatable)")
    parser.add_argument("--guess-joints", action="store_true", help="add revolute and prismatic joints found from the geometry")
    parser.add_argument("--no-limits", action="store_true", help="with --guess-joints: skip the collision sweep for revolute limits")
    parser.add_argument("--collision", choices=("hull", "mesh"), default="hull", help="collision geometry per link")
    args = parser.parse_args()
    spec = json.loads(args.joints.read_text(encoding="utf-8")) if args.joints else None
    try:
        materials = {}
        for item in args.material:
            part, _, value = item.partition("=")
            try:
                materials[part] = float(value)
            except ValueError:
                materials[part] = value
        print(json.dumps(export_urdf(args.step, args.out, spec, args.density, args.name, args.format, materials,
                                     args.guess_joints, args.collision, not args.no_limits), indent=2))
    except ValueError as error:
        parser.exit(2, f"FAIL: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

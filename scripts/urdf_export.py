#!/usr/bin/env python3
"""Robot description (URDF, SDF or MuJoCo MJCF) from a coloured STEP assembly.

    img2cad urdf model.step --out robot/                    # every part fixed to the largest
    img2cad urdf model.step --out robot/ --joints joints.json --density 2.7e-6
    img2cad urdf model.step --out robot/ --joints joints.json --format sdf    # Gazebo
    img2cad urdf model.step --out robot/ --joints joints.json --format mjcf   # MuJoCo

Each assembly part becomes a link: its mesh (meshes/<link>.stl, millimetres
scaled to metres in the URDF), its colour, and exact inertial values from the
B-rep (mass = volume x density, centre of mass, inertia tensor about it).
joints.json says how links move; parts it does not mention are fixed to the
root link (the largest part, or "root" in the file):

    {"root": "base",
     "joints": [{"name": "shoulder", "type": "revolute", "parent": "base", "child": "arm",
                 "origin": [0, 0, 120], "axis": [0, 0, 1],
                 "limit": {"lower": -1.57, "upper": 1.57, "effort": 5, "velocity": 2}}]}

`origin` is the joint's position in model millimetres (world frame); the
exporter turns it into parent-relative metres and offsets each child's
mesh so the robot appears exactly as modelled at zero joint angles. Link
names are the part labels, made URDF-safe.

Materials: `--density` (kg/mm^3, default 1.24e-6: PLA) applies to every part
unless the part has its own, from `--material arm=aluminium` (repeatable) or
`"materials": {"arm": "aluminium", "shaft": 7.85e-6}` in joints.json. Names:
abs, aluminium/aluminum, brass, carbon_fibre, copper, nylon, petg, pla, resin,
stainless, steel, titanium, wood.

`--guess-joints` proposes a revolute joint wherever one part's shaft or boss
sits in another part's bore on the same axis (diameters within 1 mm), for
parts the joints file does not already connect. The tree grows outward from
the root; guessed joints are marked `"guessed": true` in the report and
written to joints_guessed.json beside the robot, so they can be reviewed,
given limits, and passed back with `--joints`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any
from xml.sax.saxutils import quoteattr

JOINT_TYPES = ("fixed", "revolute", "continuous", "prismatic")
MATERIALS = {"pla": 1.24e-6, "petg": 1.27e-6, "abs": 1.04e-6, "nylon": 1.14e-6, "resin": 1.15e-6, "wood": 0.6e-6,
             "aluminium": 2.7e-6, "aluminum": 2.7e-6, "steel": 7.85e-6, "stainless": 8.0e-6, "brass": 8.5e-6,
             "copper": 8.96e-6, "titanium": 4.43e-6, "carbon_fibre": 1.6e-6}
FIT_CLEARANCE_MM = 1.0  # bore diameter minus shaft diameter, at most
AXIS_TOLERANCE_MM = 0.05


def density_of(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    if isinstance(value, str) and value.lower() in MATERIALS:
        return MATERIALS[value.lower()]
    raise ValueError(f"material {value!r}: give a density in kg/mm^3 or one of {', '.join(sorted(MATERIALS))}")


def _line_distance(point_a, direction_a, point_b) -> float:
    offset = [point_b[i] - point_a[i] for i in range(3)]
    along = sum(offset[i] * direction_a[i] for i in range(3))
    return sum((offset[i] - along * direction_a[i]) ** 2 for i in range(3)) ** 0.5


def guess_joints(links: dict[str, Any], root: str, connected: set[str]) -> list[dict[str, Any]]:
    """Revolute joints from shaft-in-bore fits, as a tree grown from the root over parts not yet connected."""
    from build123d import CenterOf

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
                            best = {"clearance": clearance, "axis_point": bore["axis_point"], "axis": bore["axis_direction"],
                                    "diameter": bore["diameter"]}
            if best:
                fits[(a, b)] = fits[(b, a)] = best
    joints = []
    reached = {root} | (connected & set(names))
    frontier = [root]
    while frontier:
        parent = frontier.pop(0)
        for child in names:
            fit = fits.get((parent, child))
            if child in reached or fit is None:
                continue
            centre = links[child].center(CenterOf.MASS)
            point, axis = fit["axis_point"], fit["axis"]
            # the joint origin: the point on the axis nearest the child's centre of mass
            along = sum((c - p) * d for c, p, d in zip((centre.X, centre.Y, centre.Z), point, axis))
            origin = [round(p + along * d, 4) for p, d in zip(point, axis)]
            joints.append({"name": f"{parent}_to_{child}", "type": "revolute", "parent": parent, "child": child,
                           "origin": origin, "axis": [round(v, 6) for v in axis], "guessed": True,
                           "evidence": f"shaft/bore D{fit['diameter']:g} mm, clearance {fit['clearance']:.3g} mm"})
            reached.add(child)
            frontier.append(child)
    return joints


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "part"


def vec(values) -> str:
    return " ".join(f"{float(v):.6g}" for v in values)


def export_urdf(step_path: Path, out_dir: Path, joints_spec: dict[str, Any] | None = None, density: float = 1.24e-6,
                robot_name: str | None = None, fmt: str = "urdf", materials: dict[str, Any] | None = None,
                guess: bool = False) -> dict[str, Any]:
    from build123d import CenterOf, export_stl, import_step

    from inspect_step import color_rgba, leaf_parts

    parts = leaf_parts(import_step(str(step_path)))
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
        for joint in guess_joints(links, root, connected):
            if joint["child"] not in joints:
                joints[joint["child"]] = joint
                guessed.append(joint)
    for name in links:
        if name != root and name not in joints:
            joints[name] = {"name": f"{root}_to_{name}", "type": "fixed", "parent": root, "child": name, "origin": [0, 0, 0]}
    # each link's frame sits at its joint origin (world mm); the root's at the world origin
    frame = {root: [0.0, 0.0, 0.0]}
    pending = dict(joints)
    while pending:
        progressed = False
        for child, joint in list(pending.items()):
            if joint["parent"] in frame:
                frame[child] = [float(v) for v in joint.get("origin", frame[joint["parent"]])]
                del pending[child]
                progressed = True
        if not progressed:
            raise ValueError(f"joints form a loop or a detached chain: {', '.join(pending)}")

    meshes = out_dir / "meshes"
    meshes.mkdir(parents=True, exist_ok=True)
    robot = robot_name or safe(step_path.stem if step_path.stem != "model" else step_path.parent.name)
    data = {}
    for name, part in links.items():
        export_stl(part, str(meshes / f"{name}.stl"))
        com = part.center(CenterOf.MASS)
        k = densities[name] * 1e-6  # mm^5 x kg/mm^3 -> kg m^2
        data[name] = {"rgba": color_rgba(part) or [0.7, 0.7, 0.7, 1.0], "mass": float(part.volume) * densities[name],
                      "com": [(c - f) * 1e-3 for c, f in zip((com.X, com.Y, com.Z), frame[name])],
                      "inertia": [[v * k for v in row] for row in part.matrix_of_inertia],
                      "frame_m": [v * 1e-3 for v in frame[name]]}
    writer = {"urdf": _urdf, "sdf": _sdf, "mjcf": _mjcf}[fmt]
    path = out_dir / f"{robot}.{ {'urdf': 'urdf', 'sdf': 'sdf', 'mjcf': 'xml'}[fmt] }"
    path.write_text(writer(robot, root, data, joints), encoding="utf-8")
    report = {fmt: str(path), "format": fmt, "root": root,
              "links": [{"link": n, "mass_kg": round(d["mass"], 6), "density": densities[n]} for n, d in data.items()],
              "joints": [{"name": j.get("name"), "type": j.get("type", "fixed"), "parent": j["parent"], "child": c,
                          **({"guessed": True, "evidence": j["evidence"]} if j.get("guessed") else {})} for c, j in joints.items()]}
    if guess:
        explicit = [j for j in (joints_spec or {}).get("joints", [])]
        guessed_file = out_dir / "joints_guessed.json"
        guessed_file.write_text(json.dumps({"root": root, "materials": material_of, "joints": explicit + guessed}, indent=2) + "\n", encoding="utf-8")
        report["joints_guessed"] = str(guessed_file)
    return report


def _joint_name(joint: dict) -> str:
    return safe(joint.get("name") or f"{joint['parent']}_to_{joint['child']}")


def _limit(joint: dict) -> dict:
    limit = joint.get("limit", {})
    return {"lower": limit.get("lower", -3.14159), "upper": limit.get("upper", 3.14159),
            "effort": limit.get("effort", 10), "velocity": limit.get("velocity", 1)}


def _urdf(robot: str, root: str, data: dict, joints: dict) -> str:
    xml = ['<?xml version="1.0"?>', f"<robot name={quoteattr(robot)}>"]
    for name, d in data.items():
        i = d["inertia"]
        offset = [-v for v in d["frame_m"]]
        mesh = f'<mesh filename="meshes/{name}.stl" scale="0.001 0.001 0.001"/>'
        xml += [f"  <link name={quoteattr(name)}>",
                f"    <inertial><origin xyz=\"{vec(d['com'])}\" rpy=\"0 0 0\"/><mass value=\"{d['mass']:.6g}\"/>",
                f"      <inertia ixx=\"{i[0][0]:.6g}\" ixy=\"{i[0][1]:.6g}\" ixz=\"{i[0][2]:.6g}\" "
                f"iyy=\"{i[1][1]:.6g}\" iyz=\"{i[1][2]:.6g}\" izz=\"{i[2][2]:.6g}\"/></inertial>",
                f"    <visual><origin xyz=\"{vec(offset)}\" rpy=\"0 0 0\"/><geometry>{mesh}</geometry>",
                f"      <material name={quoteattr(name + '_material')}><color rgba=\"{vec(d['rgba'])}\"/></material></visual>",
                f"    <collision><origin xyz=\"{vec(offset)}\" rpy=\"0 0 0\"/><geometry>{mesh}</geometry></collision>",
                "  </link>"]
    for child, joint in joints.items():
        parent, kind = joint["parent"], joint.get("type", "fixed")
        origin = [c - p for c, p in zip(data[child]["frame_m"], data[parent]["frame_m"])]
        xml += [f"  <joint name={quoteattr(_joint_name(joint))} type=\"{kind}\">",
                f"    <parent link={quoteattr(parent)}/><child link={quoteattr(child)}/>",
                f"    <origin xyz=\"{vec(origin)}\" rpy=\"0 0 0\"/>"]
        if kind != "fixed":
            xml.append(f"    <axis xyz=\"{vec(joint.get('axis', [0, 0, 1]))}\"/>")
        if kind in ("revolute", "prismatic"):
            limit = _limit(joint)
            xml.append(f"    <limit lower=\"{limit['lower']}\" upper=\"{limit['upper']}\" effort=\"{limit['effort']}\" velocity=\"{limit['velocity']}\"/>")
        xml.append("  </joint>")
    return "\n".join(xml + ["</robot>"]) + "\n"


def _sdf(robot: str, root: str, data: dict, joints: dict) -> str:
    """SDFormat 1.9 (Gazebo): link poses in the model frame, joint poses in the child frame (its origin)."""
    xml = ['<?xml version="1.0"?>', '<sdf version="1.9">', f"  <model name={quoteattr(robot)}>"]
    for name, d in data.items():
        i = d["inertia"]
        offset = [-v for v in d["frame_m"]]
        mesh = f"<mesh><uri>meshes/{name}.stl</uri><scale>0.001 0.001 0.001</scale></mesh>"
        rgba = vec(d["rgba"])
        xml += [f"    <link name={quoteattr(name)}>",
                f"      <pose>{vec(d['frame_m'])} 0 0 0</pose>",
                f"      <inertial><pose>{vec(d['com'])} 0 0 0</pose><mass>{d['mass']:.6g}</mass>",
                f"        <inertia><ixx>{i[0][0]:.6g}</ixx><ixy>{i[0][1]:.6g}</ixy><ixz>{i[0][2]:.6g}</ixz>"
                f"<iyy>{i[1][1]:.6g}</iyy><iyz>{i[1][2]:.6g}</iyz><izz>{i[2][2]:.6g}</izz></inertia></inertial>",
                f"      <visual name=\"visual\"><pose>{vec(offset)} 0 0 0</pose><geometry>{mesh}</geometry>",
                f"        <material><ambient>{rgba}</ambient><diffuse>{rgba}</diffuse></material></visual>",
                f"      <collision name=\"collision\"><pose>{vec(offset)} 0 0 0</pose><geometry>{mesh}</geometry></collision>",
                "    </link>"]
    for child, joint in joints.items():
        kind = joint.get("type", "fixed")
        xml += [f"    <joint name={quoteattr(_joint_name(joint))} type=\"{kind}\">",
                f"      <parent>{joint['parent']}</parent><child>{child}</child>"]
        if kind != "fixed":
            limit = _limit(joint)
            lim = (f"<limit><lower>{limit['lower']}</lower><upper>{limit['upper']}</upper><effort>{limit['effort']}</effort>"
                   f"<velocity>{limit['velocity']}</velocity></limit>") if kind != "continuous" else ""
            xml.append(f"      <axis><xyz>{vec(joint.get('axis', [0, 0, 1]))}</xyz>{lim}</axis>")
        xml.append("    </joint>")
    return "\n".join(xml + ["  </model>", "</sdf>"]) + "\n"


def _mjcf(robot: str, root: str, data: dict, joints: dict) -> str:
    """MuJoCo MJCF: bodies nested along the joint tree, each at its joint origin relative to its parent."""
    children: dict[str, list[str]] = {}
    for child, joint in joints.items():
        children.setdefault(joint["parent"], []).append(child)
    kinds = {"revolute": "hinge", "continuous": "hinge", "prismatic": "slide"}
    xml = [f"<mujoco model={quoteattr(robot)}>", '  <compiler angle="radian" meshdir="meshes"/>', "  <asset>"]
    xml += [f"    <mesh name={quoteattr(name)} file=\"{name}.stl\" scale=\"0.001 0.001 0.001\"/>" for name in data]
    xml += ["  </asset>", "  <worldbody>"]

    def body(name: str, parent: str | None, depth: int) -> None:
        d, pad = data[name], "  " * depth
        pos = d["frame_m"] if parent is None else [c - p for c, p in zip(d["frame_m"], data[parent]["frame_m"])]
        i = d["inertia"]
        xml.append(f"{pad}<body name={quoteattr(name)} pos=\"{vec(pos)}\">")
        xml.append(f"{pad}  <inertial pos=\"{vec(d['com'])}\" mass=\"{d['mass']:.6g}\" "
                   f"fullinertia=\"{i[0][0]:.6g} {i[1][1]:.6g} {i[2][2]:.6g} {i[0][1]:.6g} {i[0][2]:.6g} {i[1][2]:.6g}\"/>")
        joint = joints.get(name)
        if joint and joint.get("type", "fixed") in kinds:
            limited = joint.get("type") != "continuous"
            limit = _limit(joint)
            extra = f" range=\"{limit['lower']} {limit['upper']}\" limited=\"true\"" if limited else ""
            xml.append(f"{pad}  <joint name={quoteattr(_joint_name(joint))} type=\"{kinds[joint['type']]}\" "
                       f"axis=\"{vec(joint.get('axis', [0, 0, 1]))}\"{extra}/>")
        xml.append(f"{pad}  <geom type=\"mesh\" mesh={quoteattr(name)} pos=\"{vec([-v for v in d['frame_m']])}\" rgba=\"{vec(d['rgba'])}\"/>")
        for child in children.get(name, []):
            body(child, name, depth + 1)
        xml.append(f"{pad}</body>")

    body(root, None, 2)
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
    parser.add_argument("--guess-joints", action="store_true", help="add revolute joints at shaft-in-bore fits")
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
        print(json.dumps(export_urdf(args.step, args.out, spec, args.density, args.name, args.format, materials, args.guess_joints), indent=2))
    except ValueError as error:
        parser.exit(2, f"FAIL: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

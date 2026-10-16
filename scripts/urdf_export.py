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
names are the part labels, made URDF-safe. Density is kg/mm^3 (default
1.24e-6: PLA).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any
from xml.sax.saxutils import quoteattr

JOINT_TYPES = ("fixed", "revolute", "continuous", "prismatic")


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "part"


def vec(values) -> str:
    return " ".join(f"{float(v):.6g}" for v in values)


def export_urdf(step_path: Path, out_dir: Path, joints_spec: dict[str, Any] | None = None, density: float = 1.24e-6,
                robot_name: str | None = None, fmt: str = "urdf") -> dict[str, Any]:
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
        k = density * 1e-6  # mm^5 x kg/mm^3 -> kg m^2
        data[name] = {"rgba": color_rgba(part) or [0.7, 0.7, 0.7, 1.0], "mass": float(part.volume) * density,
                      "com": [(c - f) * 1e-3 for c, f in zip((com.X, com.Y, com.Z), frame[name])],
                      "inertia": [[v * k for v in row] for row in part.matrix_of_inertia],
                      "frame_m": [v * 1e-3 for v in frame[name]]}
    writer = {"urdf": _urdf, "sdf": _sdf, "mjcf": _mjcf}[fmt]
    path = out_dir / f"{robot}.{ {'urdf': 'urdf', 'sdf': 'sdf', 'mjcf': 'xml'}[fmt] }"
    path.write_text(writer(robot, root, data, joints), encoding="utf-8")
    return {fmt: str(path), "format": fmt, "root": root,
            "links": [{"link": n, "mass_kg": round(d["mass"], 6)} for n, d in data.items()],
            "joints": [{"name": j.get("name"), "type": j.get("type", "fixed"), "parent": j["parent"], "child": c} for c, j in joints.items()]}


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
    args = parser.parse_args()
    spec = json.loads(args.joints.read_text(encoding="utf-8")) if args.joints else None
    try:
        print(json.dumps(export_urdf(args.step, args.out, spec, args.density, args.name, args.format), indent=2))
    except ValueError as error:
        parser.exit(2, f"FAIL: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

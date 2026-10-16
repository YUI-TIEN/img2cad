#!/usr/bin/env python3
"""Robot description (URDF) from a coloured STEP assembly.

    img2cad urdf model.step --out robot/                    # every part fixed to the largest
    img2cad urdf model.step --out robot/ --joints joints.json --density 2.7e-6

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
                robot_name: str | None = None) -> dict[str, Any]:
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
    xml = [f'<?xml version="1.0"?>', f"<robot name={quoteattr(robot)}>"]
    summary = []
    for name, part in links.items():
        export_stl(part, str(meshes / f"{name}.stl"))
        rgba = color_rgba(part) or [0.7, 0.7, 0.7, 1.0]
        mass = float(part.volume) * density
        com = part.center(CenterOf.MASS)
        inertia = part.matrix_of_inertia  # mm^5 about the centre of mass
        k = density * 1e-6  # -> kg m^2
        offset = [-frame[name][i] * 1e-3 for i in range(3)]
        com_local = [(c - f) * 1e-3 for c, f in zip((com.X, com.Y, com.Z), frame[name])]
        mesh = f'<mesh filename="meshes/{name}.stl" scale="0.001 0.001 0.001"/>'
        xml += [f"  <link name={quoteattr(name)}>",
                f"    <inertial><origin xyz=\"{vec(com_local)}\" rpy=\"0 0 0\"/><mass value=\"{mass:.6g}\"/>",
                f"      <inertia ixx=\"{inertia[0][0] * k:.6g}\" ixy=\"{inertia[0][1] * k:.6g}\" ixz=\"{inertia[0][2] * k:.6g}\" "
                f"iyy=\"{inertia[1][1] * k:.6g}\" iyz=\"{inertia[1][2] * k:.6g}\" izz=\"{inertia[2][2] * k:.6g}\"/></inertial>",
                f"    <visual><origin xyz=\"{vec(offset)}\" rpy=\"0 0 0\"/><geometry>{mesh}</geometry>",
                f"      <material name={quoteattr(name + '_material')}><color rgba=\"{vec(rgba)}\"/></material></visual>",
                f"    <collision><origin xyz=\"{vec(offset)}\" rpy=\"0 0 0\"/><geometry>{mesh}</geometry></collision>",
                "  </link>"]
        summary.append({"link": name, "mass_kg": round(mass, 6)})
    for child, joint in joints.items():
        parent = joint["parent"]
        origin = [(frame[child][i] - frame[parent][i]) * 1e-3 for i in range(3)]
        lines = [f"  <joint name={quoteattr(safe(joint.get('name') or parent + '_to_' + child))} type=\"{joint.get('type', 'fixed')}\">",
                 f"    <parent link={quoteattr(parent)}/><child link={quoteattr(child)}/>",
                 f"    <origin xyz=\"{vec(origin)}\" rpy=\"0 0 0\"/>"]
        if joint.get("type", "fixed") != "fixed":
            lines.append(f"    <axis xyz=\"{vec(joint.get('axis', [0, 0, 1]))}\"/>")
        if joint.get("type") in ("revolute", "prismatic"):
            limit = joint.get("limit", {})
            lines.append(f"    <limit lower=\"{limit.get('lower', -3.14159)}\" upper=\"{limit.get('upper', 3.14159)}\" "
                         f"effort=\"{limit.get('effort', 10)}\" velocity=\"{limit.get('velocity', 1)}\"/>")
        lines.append("  </joint>")
        xml += lines
    xml.append("</robot>")
    urdf = out_dir / f"{robot}.urdf"
    urdf.write_text("\n".join(xml) + "\n", encoding="utf-8")
    return {"urdf": str(urdf), "root": root, "links": summary,
            "joints": [{"name": j.get("name"), "type": j.get("type", "fixed"), "parent": j["parent"], "child": c} for c, j in joints.items()]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--joints", type=Path, help="joints.json (default: every part fixed to the largest)")
    parser.add_argument("--density", type=float, default=1.24e-6, help="kg/mm^3 (PLA 1.24e-6, aluminium 2.7e-6, steel 7.85e-6)")
    parser.add_argument("--name", help="robot name (default: from the file)")
    args = parser.parse_args()
    spec = json.loads(args.joints.read_text(encoding="utf-8")) if args.joints else None
    try:
        print(json.dumps(export_urdf(args.step, args.out, spec, args.density, args.name), indent=2))
    except ValueError as error:
        parser.exit(2, f"FAIL: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

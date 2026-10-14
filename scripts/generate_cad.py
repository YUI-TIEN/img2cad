#!/usr/bin/env python3
"""Generate canonical, editable build123d source from a validated v1 spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from spec_contract import validate_spec


def source_for(
    spec: dict[str, Any],
    step_name: str = "model.step",
    report_name: str = "geometry.json",
    preview_name: str = "preview.svg",
) -> str:
    if len(spec["parts"]) != 1:
        raise ValueError("v1 deterministic generator supports exactly one part")
    part = spec["parts"][0]
    d = part["dimensions"]
    lengths = {key: float(d[key]["value"]) for key in ("length", "width", "height")}
    holes = part.get("holes", [])
    if any(not hole["through"] for hole in holes):
        raise ValueError("v1 supports through-holes only")
    lines = [
        '"""Generated editable CAD source; regenerate from Object2CADSpec to change geometry."""',
        "import json",
        "import math",
        "import sys",
        "from importlib.metadata import version",
        "from build123d import Align, BuildPart, Box, Cylinder, Locations, Mode, export_step, import_step",
        f"LENGTH = {lengths['length']!r}",
        f"WIDTH = {lengths['width']!r}",
        f"HEIGHT = {lengths['height']!r}",
        "with BuildPart() as model:",
        "    Box(LENGTH, WIDTH, HEIGHT, align=(Align.CENTER, Align.CENTER, Align.CENTER))",
    ]
    for hole in holes:
        x, y = float(hole["x"]["value"]), float(hole["y"]["value"])
        diameter = float(hole["diameter"]["value"])
        lines.extend([
            f"    with Locations(({x!r}, {y!r}, 0)):",
            f"        Cylinder({diameter / 2!r}, HEIGHT + 2, align=(Align.CENTER, Align.CENTER, Align.CENTER), mode=Mode.SUBTRACT)",
        ])
    lines.extend([
        f"export_step(model.part, {step_name!r})",
        f"roundtrip = import_step({step_name!r})",
        "native_box = model.part.bounding_box()",
        "box = roundtrip.bounding_box()",
        "metrics = {",
        "    'engine_version': version('build123d'),",
        "    'valid': bool(roundtrip.is_valid),",
        "    'native_valid': bool(model.part.is_valid),",
        "    'solid_count': len(roundtrip.solids()),",
        "    'native_solid_count': len(model.part.solids()),",
        "    'native_volume': float(model.part.volume),",
        "    'native_dimensions': {'length': float(native_box.max.X - native_box.min.X), 'width': float(native_box.max.Y - native_box.min.Y), 'height': float(native_box.max.Z - native_box.min.Z)},",
        "    'volume': float(roundtrip.volume),",
        "    'dimensions': {'length': float(box.max.X - box.min.X), 'width': float(box.max.Y - box.min.Y), 'height': float(box.max.Z - box.min.Z)},",
        "}",
        f"with open({report_name!r}, 'w', encoding='utf-8') as stream:",
        "    json.dump(metrics, stream, indent=2, sort_keys=True)",
        "    stream.write('\\n')",
        "vertices, triangles = roundtrip.tessellate(0.15, 0.15)",
        "views = {'front': lambda p: (p.X, p.Z), 'side': lambda p: (p.Y, p.Z), 'top': lambda p: (p.X, p.Y)}",
        "svg = ['<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"900\" height=\"330\" viewBox=\"0 0 900 330\">', '<rect width=\"100%\" height=\"100%\" fill=\"#f5f7fa\"/>']",
        "for panel, (name, project) in enumerate(views.items()):",
        "    points = [project(point) for point in vertices]",
        "    xs, ys = [p[0] for p in points], [p[1] for p in points]",
        "    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)",
        "    scale = 205 / span",
        "    ox, oy = panel * 300 + 150, 170",
        "    ordered = sorted(triangles, key=lambda tri: sum(vertices[i].Z for i in tri))",
        "    for tri in ordered:",
        "        pts = [(ox + (points[i][0] - (min(xs) + max(xs)) / 2) * scale, oy - (points[i][1] - (min(ys) + max(ys)) / 2) * scale) for i in tri]",
        "        poly = ' '.join(f'{x:.2f},{y:.2f}' for x, y in pts)",
        "        svg.append(f'<polygon points=\"{poly}\" fill=\"#91b6d9\" stroke=\"#29445f\" stroke-width=\"1\"/>')",
        "    svg.append(f'<text x=\"{panel * 300 + 150}\" y=\"315\" text-anchor=\"middle\" font-family=\"sans-serif\" font-size=\"16\">{name}</text>')",
        "svg.append('</svg>')",
        f"with open({preview_name!r}, 'w', encoding='utf-8') as stream:",
        "    stream.write('\\n'.join(svg) + '\\n')",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    spec = validate_spec(args.case_dir, args.spec, require_ready=True)
    generated = source_for(spec)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generated, encoding="utf-8")
    print(f"PASS: generated editable build123d source at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    hole_profiles = [
        {"x": float(hole["x"]["value"]), "y": float(hole["y"]["value"]), "r": float(hole["diameter"]["value"]) / 2}
        for hole in holes
    ]
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
        "svg = ['<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"900\" height=\"330\" viewBox=\"0 0 900 330\">', '<rect width=\"100%\" height=\"100%\" fill=\"#f5f7fa\"/>']",
        "views = [('front', LENGTH, HEIGHT, 'x'), ('side', WIDTH, HEIGHT, 'y'), ('top', LENGTH, WIDTH, 'top')]",
        "for panel, (name, span_x, span_y, projection) in enumerate(views):",
        "    scale = 205 / max(span_x, span_y)",
        "    ox, oy = panel * 300 + 150, 170",
        "    left, top = ox - span_x * scale / 2, oy - span_y * scale / 2",
        "    svg.append(f'<rect x=\"{left:.2f}\" y=\"{top:.2f}\" width=\"{span_x * scale:.2f}\" height=\"{span_y * scale:.2f}\" fill=\"#91b6d9\" stroke=\"#29445f\" stroke-width=\"2\"/>')",
        f"    for hole in {json.dumps(hole_profiles)}:",
        "        if projection == 'x':",
        "            for x in (hole['x'] - hole['r'], hole['x'] + hole['r']):",
        "                px = ox + x * scale",
        "                svg.append(f'<line x1=\"{px:.2f}\" y1=\"{top:.2f}\" x2=\"{px:.2f}\" y2=\"{top + span_y * scale:.2f}\" stroke=\"#29445f\" stroke-width=\"1.5\" stroke-dasharray=\"5 4\"/>')",
        "        elif projection == 'y':",
        "            for y in (hole['y'] - hole['r'], hole['y'] + hole['r']):",
        "                py = oy - y * scale",
        "                svg.append(f'<line x1=\"{left:.2f}\" y1=\"{py:.2f}\" x2=\"{left + span_x * scale:.2f}\" y2=\"{py:.2f}\" stroke=\"#29445f\" stroke-width=\"1.5\" stroke-dasharray=\"5 4\"/>')",
        "        else:",
        "            cx, cy = ox + hole['x'] * scale, oy - hole['y'] * scale",
        "            svg.append(f'<circle cx=\"{cx:.2f}\" cy=\"{cy:.2f}\" r=\"{hole[\"r\"] * scale:.2f}\" fill=\"#f5f7fa\" stroke=\"#29445f\" stroke-width=\"2\"/>')",
        "    svg.append(f'<text x=\"{ox}\" y=\"315\" text-anchor=\"middle\" font-family=\"sans-serif\" font-size=\"16\">{name}</text>')",
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

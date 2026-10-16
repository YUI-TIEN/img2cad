#!/usr/bin/env python3
"""Engineering drawing from a STEP file: three views, overall dimensions, hole table.

    img2cad drawing model.step out_dir            # writes drawing.svg, drawing.dxf and drawing.pdf
    img2cad drawing model.step out_dir --name "Mounting plate" --formats svg

Third-angle layout: front view (looking along +Y) bottom left, top view above
it, right view to its right. Visible edges are solid, hidden edges dashed.
Overall width, height and depth are dimensioned. Every full cylindrical hole
and boss along X, Y or Z is tagged (H1, B1, ...) with its diameter in the view
that looks down its axis, and its centre is dimensioned from that view's
lower-left edges (baseline dimensions, so each value reads from one datum).
The notes list every hole and boss with its diameter, axis and position, so a
drawing's callouts can be checked against the model (and vice versa).
Units are millimetres at 1:1; the SVG viewBox fits the sheet.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

# (camera position direction, view up) for each view; positions are scaled by the model size.
VIEWS = {
    "front": ((0, -1, 0), (0, 0, 1)),
    "top": ((0, 0, 1), (0, 1, 0)),
    "right": ((1, 0, 0), (0, 0, 1)),
}


def project(shape: Any, name: str) -> tuple[list[Any], list[Any]]:
    """Visible and hidden edges of one view, centred on the view's own origin."""
    from build123d import Compound, Pos

    direction, up = VIEWS[name]
    center = shape.bounding_box().center()
    look_at = (center.X, center.Y, center.Z)
    distance = shape.bounding_box().diagonal * 10
    origin = tuple(look_at[i] + direction[i] * distance for i in range(3))
    visible, hidden = shape.project_to_viewport(origin, up, look_at)
    box = Compound(list(visible) + list(hidden)).bounding_box()
    shift = Pos(-box.center().X, -box.center().Y, 0)
    return [shift * edge for edge in visible], [shift * edge for edge in hidden]


def hole_rows(features: list[dict[str, Any]]) -> list[str]:
    """One line per (kind, diameter, axis) group of full cylinders."""
    groups: Counter[tuple[str, float, str]] = Counter()
    positions: dict[tuple[str, float, str], list[str]] = {}
    for feature in features:
        if not feature.get("full"):
            continue
        axis = "XYZ"[max(range(3), key=lambda i: abs(feature["axis_direction"][i]))]
        key = (feature["kind"], feature["diameter"], axis)
        groups[key] += 1
        positions.setdefault(key, []).append("(" + ", ".join(f"{value:g}" for value in feature["axis_point"]) + ")")
    rows = []
    for (kind, diameter, axis), count in sorted(groups.items()):
        where = ", ".join(positions[(kind, diameter, axis)][:6]) + (" ..." if count > 6 else "")
        rows.append(f"{count}x {kind} D{diameter:g} along {axis} at {where}")
    return rows


# view -> (axis its circles are seen along, model index of screen right, model index of screen up)
FEATURE_VIEWS = {"front": (1, 0, 2), "top": (2, 0, 1), "right": (0, 1, 2)}
MAX_FEATURE_DIMENSIONS = 10  # per direction per view; the notes carry the rest


def feature_layout(features: list[dict[str, Any]], low: Any, high: Any) -> dict[str, list[dict[str, Any]]]:
    """Tag full holes/bosses and place each in the view along its axis, measured from that view's lower-left corner."""
    lows, highs = (low.X, low.Y, low.Z), (high.X, high.Y, high.Z)
    placed: dict[str, list[dict[str, Any]]] = {name: [] for name in FEATURE_VIEWS}
    counters = {"hole": 0, "boss": 0}
    for feature in features:
        if not feature.get("full"):
            continue
        direction = feature["axis_direction"]
        axis = max(range(3), key=lambda i: abs(direction[i]))
        if abs(abs(direction[axis]) - 1) > 1e-3:
            continue  # oblique: listed in the notes only
        view = next(name for name, (along, _, _) in FEATURE_VIEWS.items() if along == axis)
        _, u, v = FEATURE_VIEWS[view]
        counters[feature["kind"]] += 1
        tag = ("H" if feature["kind"] == "hole" else "B") + str(counters[feature["kind"]])
        point = feature["axis_point"]
        placed[view].append({"tag": tag, "kind": feature["kind"], "diameter": feature["diameter"], "view": view,
                             "from_datum": [round(point[u] - lows[u], 3), round(point[v] - lows[v], 3)],
                             "screen": [point[u] - (lows[u] + highs[u]) / 2, point[v] - (lows[v] + highs[v]) / 2]})
    return placed


def unique_values(values: list[float]) -> list[float]:
    found: list[float] = []
    for value in sorted(values):
        if value > 1e-6 and not any(abs(value - seen) < 1e-3 for seen in found):
            found.append(value)
    return found[:MAX_FEATURE_DIMENSIONS]


def _polyline(edge: Any, tolerance: float) -> list[tuple[float, float]]:
    """An edge as points (straight edges: two points; curves: enough to stay within tolerance)."""
    if edge.geom_type.name == "LINE":
        points = [edge.position_at(0), edge.position_at(1)]
    else:
        count = max(8, min(400, int(edge.length / max(tolerance, 1e-6)) + 1))
        points = [edge.position_at(i / count) for i in range(count + 1)]
    return [(p.X, p.Y) for p in points]


def write_pdf(path: Path, visible: list[Any], hidden: list[Any], dimensions: list[Any], labels: list[Any]) -> None:
    """Vector PDF of the sheet (1 mm = 1 mm on paper), written directly: no extra dependencies.

    Visible edges 0.35 mm, hidden edges 0.18 mm dashed, dimensions and notes
    filled (text and arrowheads are faces) with a thin outline.
    """
    from build123d import Compound

    everything = Compound(children=[*visible, *hidden, *dimensions, *labels])
    box = everything.bounding_box()
    margin = max(box.size.X, box.size.Y) * 0.04 + 5
    tolerance = max(box.size.X, box.size.Y) / 2000
    pt = 72 / 25.4
    width, height = (box.size.X + 2 * margin) * pt, (box.size.Y + 2 * margin) * pt

    def xy(point: tuple[float, float]) -> str:
        return f"{(point[0] - box.min.X + margin) * pt:.2f} {(point[1] - box.min.Y + margin) * pt:.2f}"

    def stroke(edges: list[Any]) -> list[str]:
        ops = []
        for edge in edges:
            points = _polyline(edge, tolerance)
            ops.append(f"{xy(points[0])} m " + " ".join(f"{xy(p)} l" for p in points[1:]) + " S")
        return ops

    ops = ["1 J 1 j", f"{0.35 * pt:.3f} w []0 d"]
    ops += stroke([e for shape in visible for e in shape.edges()])
    ops += [f"{0.18 * pt:.3f} w [{3 * pt:.2f} {1.5 * pt:.2f}] 0 d"]
    ops += stroke([e for shape in hidden for e in shape.edges()])
    ops += [f"{0.13 * pt:.3f} w []0 d", "0 g"]
    for shape in [*dimensions, *labels]:
        for face in shape.faces():
            loops = []
            for wire in face.wires():
                points = [p for edge in wire.edges() for p in _polyline(edge, tolerance)]
                loops.append(f"{xy(points[0])} m " + " ".join(f"{xy(p)} l" for p in points[1:]) + " h")
            ops.append(" ".join(loops) + " f*")
        face_edges = {id(e.wrapped) for f in shape.faces() for e in f.edges()}
        ops += stroke([e for e in shape.edges() if id(e.wrapped) not in face_edges] if shape.faces() else shape.edges())
    content = "\n".join(ops).encode("latin-1")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] /Contents 4 0 R >>".encode(),
               b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def make_drawing(step_path: Path, out_dir: Path, formats: tuple[str, ...] = ("svg", "dxf"), name: str | None = None) -> dict[str, Any]:
    from build123d import Align, Draft, ExportDXF, ExportSVG, ExtensionLine, LineType, Pos, Text, Unit, import_step

    from inspect_step import cylindrical_features

    shape = import_step(str(step_path))
    size = shape.bounding_box().size
    width, depth, height = size.X, size.Y, size.Z
    scale_ref = max(width, depth, height)
    font = max(2.5, scale_ref / 28)
    features = cylindrical_features(shape)
    bounds = shape.bounding_box()
    placed = feature_layout(features, bounds.min, bounds.max)
    step = font * 2.2
    front_across = len(unique_values([f["from_datum"][0] for f in placed["front"]]))
    gap = scale_ref * 0.35
    gap_up = gap + step * front_across  # front-view position dimensions sit between the front and top views
    draft = Draft(font_size=font, arrow_length=font, line_width=font / 12, pad_around_text=font / 3,
                  decimal_precision=2, display_units=False, extension_gap=font / 2)

    front_visible, front_hidden = project(shape, "front")
    top_visible, top_hidden = project(shape, "top")
    right_visible, right_hidden = project(shape, "right")
    top_at = Pos(0, height / 2 + gap_up + depth / 2)
    right_at = Pos(width / 2 + gap + depth / 2, 0)
    visible = front_visible + [top_at * e for e in top_visible] + [right_at * e for e in right_visible]
    hidden = front_hidden + [top_at * e for e in top_hidden] + [right_at * e for e in right_hidden]

    offset = font * 2.5
    dimensions = [
        # width under the front view, height left of it, depth under the right view
        ExtensionLine(border=[(-width / 2, -height / 2), (width / 2, -height / 2)], offset=offset, draft=draft),
        ExtensionLine(border=[(-width / 2, height / 2), (-width / 2, -height / 2)], offset=offset, draft=draft),
        ExtensionLine(border=[(right_at.position.X - depth / 2, -height / 2), (right_at.position.X + depth / 2, -height / 2)],
                      offset=offset, draft=draft),
    ]

    # Feature tags and baseline position dimensions, per view.
    halves = {"front": (width / 2, height / 2, 0.0, 0.0), "top": (width / 2, depth / 2, 0.0, top_at.position.Y),
              "right": (depth / 2, height / 2, right_at.position.X, 0.0)}
    # (horizontal dims above?, first slot), (vertical dims left?, first slot): keep clear of the overall dimensions and notes
    sides = {"front": ((True, 0), (True, 1)), "top": ((True, 0), (True, 0)), "right": ((False, 1), (False, 0))}
    tags = []
    feature_dimensions = []
    for view, items in placed.items():
        if not items:
            continue
        half_w, half_h, cx, cy = halves[view]
        left, bottom, right, top = cx - half_w, cy - half_h, cx + half_w, cy + half_h
        for item in items:
            x, y = cx + item["screen"][0], cy + item["screen"][1]
            radius = item["diameter"] / 2
            tags.append(Pos(x + radius * 0.75 + font * 0.2, y + radius * 0.75) *
                        Text(f"{item['tag']} \u00d8{item['diameter']:g}", font_size=font * 0.8, align=(Align.MIN, Align.MIN)))
            feature_dimensions.append({key: item[key] for key in ("tag", "kind", "diameter", "view", "from_datum")})
        (above, first_h), (on_left, first_v) = sides[view]
        for slot, du in enumerate(unique_values([item["from_datum"][0] for item in items]), start=first_h):
            x = left + du
            border = [(x, top), (left, top)] if above else [(left, bottom), (x, bottom)]
            dimensions.append(ExtensionLine(border=border, offset=offset + (slot - first_h) * step + (step * first_h), draft=draft))
        for slot, dv in enumerate(unique_values([item["from_datum"][1] for item in items]), start=first_v):
            y = bottom + dv
            border = [(left, y), (left, bottom)] if on_left else [(right, bottom), (right, y)]
            dimensions.append(ExtensionLine(border=border, offset=offset + (slot - first_v) * step + (step * first_v), draft=draft))
    title = name or (step_path.parent.name if step_path.stem == "model" else step_path.stem)
    notes = [title, f"Overall {width:.2f} x {depth:.2f} x {height:.2f} mm (X x Y x Z)",
             "Units mm, scale 1:1, third-angle projection",
             "Hole/boss centres dimensioned from each view's lower-left edges", *hole_rows(features)]
    note_x = right_at.position.X - depth / 2
    note_y = top_at.position.Y + depth / 2
    labels = [Pos(note_x, note_y - index * font * 1.6) * Text(line, font_size=font if index else font * 1.3, align=(Align.MIN, Align.MAX))
              for index, line in enumerate(notes)] + tags

    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    if "svg" in formats:
        svg = ExportSVG(unit=Unit.MM, margin=font * 2, line_weight=0.35)
        svg.add_layer("visible", line_weight=0.35)
        svg.add_layer("hidden", line_weight=0.18, line_type=LineType.ISO_DASH)
        svg.add_layer("dimensions", line_weight=0.13, fill_color=(0, 0, 0))
        svg.add_layer("notes", line_weight=0.05, fill_color=(0, 0, 0))
        svg.add_shape(visible, layer="visible")
        if hidden:
            svg.add_shape(hidden, layer="hidden")
        for dimension in dimensions:
            svg.add_shape(dimension, layer="dimensions")
        for label in labels:
            svg.add_shape(label, layer="notes")
        written["svg"] = str(out_dir / "drawing.svg")
        svg.write(written["svg"])
    if "dxf" in formats:
        dxf = ExportDXF(unit=Unit.MM)
        dxf.add_layer("visible", line_weight=0.35)
        dxf.add_layer("hidden", line_weight=0.18, line_type=LineType.ISO_DASH)
        dxf.add_layer("dimensions", line_weight=0.13)
        dxf.add_layer("notes", line_weight=0.05)
        dxf.add_shape(visible, layer="visible")
        if hidden:
            dxf.add_shape(hidden, layer="hidden")
        for dimension in dimensions:
            dxf.add_shape(dimension, layer="dimensions")
        for label in labels:
            dxf.add_shape(label, layer="notes")
        written["dxf"] = str(out_dir / "drawing.dxf")
        dxf.write(written["dxf"])
    if "pdf" in formats:
        written["pdf"] = str(out_dir / "drawing.pdf")
        write_pdf(Path(written["pdf"]), visible, hidden, dimensions, labels)
    return {"files": written, "overall_mm": {"x": round(width, 3), "y": round(depth, 3), "z": round(height, 3)},
            "notes": notes, "feature_dimensions": feature_dimensions, "visible_edges": len(visible), "hidden_edges": len(hidden)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--formats", default="svg,dxf,pdf", help="comma-separated: svg,dxf,pdf")
    parser.add_argument("--name", help="title shown on the sheet (default: the STEP file name)")
    args = parser.parse_args()
    formats = tuple(item.strip().lower() for item in args.formats.split(",") if item.strip())
    unknown = [item for item in formats if item not in ("svg", "dxf", "pdf")]
    if unknown:
        parser.error(f"unknown formats {unknown}")
    print(json.dumps(make_drawing(args.step, args.out_dir, formats, args.name), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Engineering drawing from a STEP file: three views, overall dimensions, hole table.

    img2cad drawing model.step out_dir            # writes drawing.svg, drawing.dxf and drawing.pdf
    img2cad drawing model.step out_dir --name "Mounting plate" --formats svg
    img2cad drawing model.step out_dir --section x@12 --tolerance-class f

Third-angle layout: front view (looking along +Y) bottom left, top view above
it, right view to its right, and section A-A beside the right view. The
section plane is `--section y` (default: the XZ plane through the centre, seen
from the front), `x` (seen from the right) or `z` (seen from above), at the
centre or at `@offset` mm; it is marked on the top view (x, y) or front view
(z) and its cut faces are hatched. `--section none` leaves it out. Visible
edges are solid, hidden edges dashed.
Overall width, height and depth are dimensioned. Every full cylindrical hole
and boss along X, Y or Z is tagged (H1, B1, ...) with its diameter in the view
that looks down its axis, and its centre is dimensioned from that view's
lower-left edges (baseline dimensions, so each value reads from one datum).
Hole tags carry their callout: tapped holes (bore = ISO tap drill) read
`M3x0.5`, counterbores `CBORE D8x3`, countersinks `CSK 90deg`, and modelled
thread geometry is named too. Pockets, slots and steps (flat floors facing up
below the top) are tagged P1, P2 ... in the top view with size and depth, and
their corners dimensioned from the same datum. Holes on oblique axes get an
auxiliary view looking down their axis (VIEW B, C) below the front view.
The notes list every hole, boss and pocket and the general tolerance (ISO
2768-1, `--tolerance-class f|m|c|v`, default m) with its table for the part's
size range, so untoleranced dimensions have a defined tolerance.
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


def project(shape: Any, name: str, frame: Any = None) -> tuple[list[Any], list[Any]]:
    """Visible and hidden edges of one view, centred on the view's own origin.

    `frame` (from `view_frame` of another shape) projects in that shape's frame
    instead, so a cut-away half lines up with the whole part's view."""
    from build123d import Compound, Pos

    direction, up = VIEWS[name]
    look_at, distance, shift = frame or (None, None, None)
    if look_at is None:
        center = shape.bounding_box().center()
        look_at = (center.X, center.Y, center.Z)
        distance = shape.bounding_box().diagonal * 10
    origin = tuple(look_at[i] + direction[i] * distance for i in range(3))
    visible, hidden = shape.project_to_viewport(origin, up, look_at)
    if shift is None:
        box = Compound(list(visible) + list(hidden)).bounding_box()
        shift = Pos(-box.center().X, -box.center().Y, 0)
    return [shift * edge for edge in visible], [shift * edge for edge in hidden]


def view_frame(shape: Any, name: str) -> tuple[Any, float, Any]:
    from build123d import Compound, Pos

    direction, up = VIEWS[name]
    center = shape.bounding_box().center()
    look_at = (center.X, center.Y, center.Z)
    distance = shape.bounding_box().diagonal * 10
    origin = tuple(look_at[i] + direction[i] * distance for i in range(3))
    visible, hidden = shape.project_to_viewport(origin, up, look_at)
    box = Compound(list(visible) + list(hidden)).bounding_box()
    return look_at, distance, Pos(-box.center().X, -box.center().Y, 0)


SECTION_VIEWS = {  # cut normal -> (view it is seen in, plane x_dir, plane z_dir (kept half lies opposite))
    "y": ("front", (1, 0, 0), (0, -1, 0)),
    "x": ("right", (0, 1, 0), (1, 0, 0)),
    "z": ("top", (1, 0, 0), (0, 0, 1)),
}


def parse_section(text: str | None) -> tuple[str, float | None] | None:
    if text is None or text.lower() == "none":
        return None
    axis, _, where = text.lower().partition("@")
    if axis not in SECTION_VIEWS:
        raise ValueError("--section takes x, y or z, optionally @offset (mm), or none")
    return axis, float(where) if where else None


def section_view(shape: Any, spacing: float, axis: str = "y", offset: float | None = None) -> tuple[list[Any], list[Any], float]:
    """The part cut by the plane square to `axis` (through the centre, or at `offset`), seen from the matching
    view with the cut faces hatched at 45 degrees. Returns (visible edges, hatch lines, cut area) in that view's coordinates."""
    from build123d import Edge, Keep, Plane, section, split

    view, x_dir, z_dir = SECTION_VIEWS[axis]
    center = shape.bounding_box().center()
    origin = [center.X, center.Y, center.Z]
    if offset is not None:
        origin["xyz".index(axis)] = offset
    plane = Plane(origin=tuple(origin), x_dir=x_dir, z_dir=z_dir)
    cut = section(shape, plane)
    if not cut.faces():
        return [], [], 0.0
    behind = split(shape, bisect_by=plane, keep=Keep.BOTTOM)  # the half the viewer looks at, beyond the cut
    visible, _ = project(behind, view, view_frame(shape, view))
    local = plane.to_local_coords(cut)
    # plane origin is offset only along its normal from the centre, so local x/y are the view's centred coordinates
    flat = local
    box = flat.bounding_box()
    hatch = []
    reach = box.size.X + box.size.Y
    start = box.min.Y - box.max.X - spacing
    while start < box.max.Y - box.min.X + spacing:
        line = Edge.make_line((box.min.X - 1, box.min.X - 1 + start), (box.min.X - 1 + reach + 2, box.min.X - 1 + start + reach + 2))
        for face in flat.faces():
            hatch += [edge for edge in face.intersect(line) or [] if hasattr(edge, "length") and edge.length > 1e-6]
        start += spacing
    return visible, hatch, float(cut.area)


def hole_rows(features: list[dict[str, Any]]) -> list[str]:
    """One line per (kind, diameter, axis) group of full cylinders."""
    groups: Counter[tuple[str, float, str]] = Counter()
    positions: dict[tuple[str, float, str], list[str]] = {}
    for feature in features:
        if not feature.get("full"):
            continue
        direction = feature["axis_direction"]
        axis = "XYZ"[max(range(3), key=lambda i: abs(direction[i]))]
        if max(abs(v) for v in direction) < 1 - 1e-3:
            axis = "(" + ", ".join(f"{v:.3f}" for v in direction) + ")"
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
                             "axis_point": point, "axis_direction": direction,
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


ISO_2768 = {  # general tolerances for linear sizes, +/- mm, by nominal range (ISO 2768-1)
    "ranges": [(0.5, 3), (3, 6), (6, 30), (30, 120), (120, 400), (400, 1000), (1000, 2000), (2000, 4000)],
    "f": [0.05, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, None],
    "m": [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0],
    "c": [0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 4.0],
    "v": [None, 0.5, 1.0, 1.5, 2.5, 4.0, 6.0, 8.0],
}
THREAD_PITCH = {"M2": 0.4, "M2.5": 0.45, "M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0, "M8": 1.25, "M10": 1.5, "M12": 1.75, "M16": 2.0}


def tolerance_notes(tolerance_class: str, largest: float) -> list[str]:
    values = ISO_2768[tolerance_class]
    rows = []
    for (low, high), value in zip(ISO_2768["ranges"], values):
        if low > largest:
            break
        if value is not None:
            rows.append(f"{low:g}-{high:g}: +/-{value:g}")
    return [f"General tolerances ISO 2768-{tolerance_class} unless stated", "Linear (mm) " + ", ".join(rows)]


def hole_callouts(shape: Any) -> list[dict[str, Any]]:
    """Hole types (counterbore, countersink, tapped) and modelled threads, from the CNC checks."""
    from dfm import _concave_cylinders, hole_types, modelled_threads

    callouts = []
    for solid in shape.solids():
        callouts += [{"source": "hole", **h} for h in hole_types(solid, _concave_cylinders(solid))]
        callouts += [{"source": "thread", **t} for t in modelled_threads(solid)]
    return callouts


def callout_text(feature: dict[str, Any], callouts: list[dict[str, Any]]) -> str:
    """'D6', 'M3x0.5', 'D4 CBORE D8x3', 'D4 CSK 90deg' for the hole whose axis matches."""
    import math as _math

    text = f"\u00d8{feature['diameter']:g}"
    point, direction = feature["axis_point"], feature["axis_direction"]
    for item in callouts:
        axis = item.get("axis")
        if not axis or abs(abs(sum(a * b for a, b in zip(axis, direction))) - 1) > 1e-3:
            continue
        if item["source"] == "hole":
            at = item["at_mm"]
            offset = [at[i] - point[i] for i in range(3)]
            along = sum(offset[i] * direction[i] for i in range(3))
            if _math.sqrt(sum((offset[i] - along * direction[i]) ** 2 for i in range(3))) > 0.05:
                continue
            if abs(item["bore_mm"] - feature["diameter"]) > 1e-3 and abs(item.get("counterbore_mm", -1) - feature["diameter"]) > 1e-3:
                continue
            thread = item.get("likely_thread")
            if thread:
                text = f"{thread}x{THREAD_PITCH.get(thread, 0):g}"
                if item.get("bore_depth_mm"):
                    text += f" {item['bore_depth_mm']:g} deep"
            else:
                text = f"\u00d8{item['bore_mm']:g}"
            if "counterbore_mm" in item:
                text += f" CBORE \u00d8{item['counterbore_mm']:g}x{item['counterbore_depth_mm']:g}"
            if "countersink_deg" in item:
                text += f" CSK {item['countersink_deg']:g}deg"
            return text
        if item["source"] == "thread" and abs(item["major_mm"] - feature["diameter"]) <= 1.0:
            return f"{item['thread']}x{THREAD_PITCH.get(item['thread'], 0):g} ({item['kind']} thread)"
    return text


def is_counterbore_of_other(feature: dict[str, Any], callouts: list[dict[str, Any]]) -> bool:
    for item in callouts:
        if item["source"] != "hole" or "counterbore_mm" not in item or abs(item["counterbore_mm"] - feature["diameter"]) > 1e-3:
            continue
        direction, point, at = feature["axis_direction"], feature["axis_point"], item["at_mm"]
        offset = [at[i] - point[i] for i in range(3)]
        along = sum(offset[i] * direction[i] for i in range(3))
        if sum((offset[i] - along * direction[i]) ** 2 for i in range(3)) ** 0.5 <= 0.05:
            return True
    return False


def pocket_layout(shape: Any) -> list[dict[str, Any]]:
    """Upward-facing flat floors below the top (pockets, slots, steps), as seen in the top view."""
    from inspect_step import planar_faces

    box = shape.bounding_box()
    top = box.max.Z
    pockets = []
    for face in planar_faces(shape):
        if face["normal"] != "+z" or face["offset"] > top - 1e-6 or face.get("round"):
            continue
        (cx, cy), (sx, sy) = face["center"], face["size"]
        pockets.append({"tag": f"P{len(pockets) + 1}", "size": [round(sx, 3), round(sy, 3)], "depth": round(top - face["offset"], 3),
                        "from_datum": [round(cx - sx / 2 - box.min.X, 3), round(cy - sy / 2 - box.min.Y, 3)],
                        "screen": [cx - (box.min.X + box.max.X) / 2, cy - (box.min.Y + box.max.Y) / 2]})
    return pockets[:12]


def oblique_groups(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for feature in features:
        if not feature.get("full"):
            continue
        direction = feature["axis_direction"]
        if max(abs(v) for v in direction) > 1 - 1e-3:
            continue
        group = next((g for g in groups if abs(sum(a * b for a, b in zip(g["direction"], direction))) > 1 - 1e-4), None)
        if group is None:
            group = {"direction": direction, "features": []}
            groups.append(group)
        group["features"].append(feature)
    return groups[:2]


def auxiliary_view(shape: Any, direction: list[float]) -> tuple[list[Any], list[Any], Any]:
    """Edges seen looking down `direction`, centred; returns (visible, hidden, function point -> screen xy)."""
    import numpy as np
    from build123d import Compound, Pos

    d = np.array(direction, dtype=float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
    up = up - d * (up @ d)
    up /= np.linalg.norm(up)
    center = shape.bounding_box().center()
    look_at = np.array([center.X, center.Y, center.Z])
    distance = shape.bounding_box().diagonal * 10
    visible, hidden = shape.project_to_viewport(tuple(look_at + d * distance), tuple(up), tuple(look_at))
    box = Compound(list(visible) + list(hidden)).bounding_box()
    shift = np.array([box.center().X, box.center().Y])
    screen_x = np.cross(up, d)
    screen_y = np.cross(d, screen_x)

    def to_screen(point: list[float]) -> tuple[float, float]:
        rel = np.array(point) - look_at
        return float(rel @ screen_x - shift[0]), float(rel @ screen_y - shift[1])

    move = Pos(-shift[0], -shift[1], 0)
    return [move * e for e in visible], [move * e for e in hidden], (to_screen, box.size.X, box.size.Y)


def make_drawing(step_path: Path, out_dir: Path, formats: tuple[str, ...] = ("svg", "dxf"), name: str | None = None,
                 with_section: bool | str | None = True, tolerance_class: str = "m") -> dict[str, Any]:
    from build123d import Align, Draft, Edge, ExportDXF, ExportSVG, ExtensionLine, LineType, Pos, Text, Unit, import_step

    from inspect_step import cylindrical_features

    if with_section is True:
        section = ("y", None)
    elif not with_section:
        section = None
    else:
        section = parse_section(with_section)
    if tolerance_class not in ("f", "m", "c", "v"):
        raise ValueError("tolerance class must be f, m, c or v (ISO 2768-1)")

    shape = import_step(str(step_path))
    size = shape.bounding_box().size
    width, depth, height = size.X, size.Y, size.Z
    scale_ref = max(width, depth, height)
    font = max(2.5, scale_ref / 28)
    features = cylindrical_features(shape)
    bounds = shape.bounding_box()
    placed = feature_layout(features, bounds.min, bounds.max)
    callouts = hole_callouts(shape)
    pockets = pocket_layout(shape)
    step = font * 2.2
    front_across = len(unique_values([f["from_datum"][0] for f in placed["front"]]))
    top_across = len(unique_values([f["from_datum"][0] for f in placed["top"]] + [p["from_datum"][0] for p in pockets]))
    gap = scale_ref * 0.35
    gap_up = gap + step * front_across  # front-view position dimensions sit between the front and top views
    draft = Draft(font_size=font, arrow_length=font, line_width=font / 12, pad_around_text=font / 3,
                  decimal_precision=2, display_units=False, extension_gap=font / 2)

    front_visible, front_hidden = project(shape, "front")
    top_visible, top_hidden = project(shape, "top")
    right_visible, right_hidden = project(shape, "right")
    top_at = Pos(0, height / 2 + gap_up + depth / 2)
    right_at = Pos(width / 2 + gap + depth / 2, 0)
    at = {"front": Pos(0, 0), "top": top_at, "right": right_at}
    visible = front_visible + [top_at * e for e in top_visible] + [right_at * e for e in right_visible]
    hidden = front_hidden + [top_at * e for e in top_hidden] + [right_at * e for e in right_hidden]
    hatch: list[Any] = []
    section_labels: list[Any] = []
    section_area = 0.0
    section_report = None
    if section:
        axis, where = section
        cut_visible, cut_hatch, section_area = section_view(shape, max(font * 0.6, scale_ref / 60), axis, where)
        if cut_visible:
            view = SECTION_VIEWS[axis][0]
            view_w = {"front": width, "right": depth, "top": width}[view]
            view_h = {"front": height, "right": height, "top": depth}[view]
            right_dims = len(unique_values([f["from_datum"][1] for f in placed["right"]]))
            section_at = Pos(right_at.position.X + depth / 2 + gap + step * right_dims + view_w / 2, 0)
            visible += [section_at * e for e in cut_visible]
            hatch = [section_at * e for e in cut_hatch]
            centre = {"x": (bounds.min.X + bounds.max.X) / 2, "y": (bounds.min.Y + bounds.max.Y) / 2, "z": (bounds.min.Z + bounds.max.Z) / 2}[axis]
            shift = (where if where is not None else centre) - centre
            # the cutting plane: a chain line past both ends of the view it is seen edge-on in, labelled A
            if axis in ("x", "y"):
                reach = (depth if axis == "x" else width) / 2 + font * 1.5
                ends = [(shift, -reach), (shift, reach)] if axis == "x" else [(-reach, shift), (reach, shift)]
                host = top_at
            else:
                reach = width / 2 + font * 1.5
                ends = [(-reach, shift), (reach, shift)]
                host = Pos(0, 0)
            hidden.append(host * Edge.make_line(ends[0], ends[1]))
            section_labels = [host * Pos(x, y + font * 0.4) * Text("A", font_size=font, align=(Align.CENTER, Align.MIN)) for x, y in ends]
            section_labels.append(Pos(section_at.position.X, -max(view_h, height) / 2 - font * 4) *
                                  Text("SECTION A-A", font_size=font, align=(Align.CENTER, Align.MAX)))
            section_report = {"plane": f"{axis} = {centre + shift:.3f}", "seen_in": view, "cut_area_mm2": round(section_area, 2),
                              "hatch_lines": len(hatch)}

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
        view_pockets = pockets if view == "top" else []
        if not items and not view_pockets:
            continue
        half_w, half_h, cx, cy = halves[view]
        left, bottom, right, top = cx - half_w, cy - half_h, cx + half_w, cy + half_h
        for item in items:
            if is_counterbore_of_other(item, callouts):
                continue  # the counterbore step is part of its hole's callout
            x, y = cx + item["screen"][0], cy + item["screen"][1]
            radius = item["diameter"] / 2
            label = callout_text(item, callouts)
            tags.append(Pos(x + radius * 0.75 + font * 0.2, y + radius * 0.75) *
                        Text(f"{item['tag']} {label}", font_size=font * 0.8, align=(Align.MIN, Align.MIN)))
            feature_dimensions.append({**{key: item[key] for key in ("tag", "kind", "diameter", "view", "from_datum")}, "callout": label})
        for pocket in view_pockets:
            x, y = cx + pocket["screen"][0], cy + pocket["screen"][1]
            label = f"{pocket['tag']} {pocket['size'][0]:g}x{pocket['size'][1]:g} depth {pocket['depth']:g}"
            tags.append(Pos(x, y) * Text(label, font_size=font * 0.7, align=(Align.CENTER, Align.CENTER)))
            feature_dimensions.append({"tag": pocket["tag"], "kind": "pocket", "view": "top", "from_datum": pocket["from_datum"],
                                       "size": pocket["size"], "depth": pocket["depth"], "callout": label})
        (above, first_h), (on_left, first_v) = sides[view]
        across = [item["from_datum"][0] for item in items] + [p["from_datum"][0] for p in view_pockets]
        across += [p["from_datum"][0] + p["size"][0] for p in view_pockets]
        upward = [item["from_datum"][1] for item in items] + [p["from_datum"][1] for p in view_pockets]
        upward += [p["from_datum"][1] + p["size"][1] for p in view_pockets]
        for slot, du in enumerate(unique_values(across), start=first_h):
            x = left + du
            border = [(x, top), (left, top)] if above else [(left, bottom), (x, bottom)]
            dimensions.append(ExtensionLine(border=border, offset=offset + (slot - first_h) * step + (step * first_h), draft=draft))
        for slot, dv in enumerate(unique_values(upward), start=first_v):
            y = bottom + dv
            border = [(left, y), (left, bottom)] if on_left else [(right, bottom), (right, y)]
            dimensions.append(ExtensionLine(border=border, offset=offset + (slot - first_v) * step + (step * first_v), draft=draft))

    # Auxiliary views for holes on oblique axes, in a row below the front view.
    aux_report = []
    row_y = -height / 2 - offset - step * 3 - gap
    x_cursor = -width / 2
    for letter, group in zip("BC", oblique_groups(features)):
        aux_visible, aux_hidden, (to_screen, aux_w, aux_h) = auxiliary_view(shape, group["direction"])
        place = Pos(x_cursor + aux_w / 2, row_y - aux_h / 2)
        visible += [place * e for e in aux_visible]
        hidden += [place * e for e in aux_hidden]
        names = []
        for feature in group["features"]:
            sx, sy = to_screen(feature["axis_point"])
            radius = feature["diameter"] / 2
            label = callout_text(feature, callouts)
            tags.append(place * Pos(sx + radius * 0.75 + font * 0.2, sy + radius * 0.75) *
                        Text(f"{letter}{len(names) + 1} {label}", font_size=font * 0.8, align=(Align.MIN, Align.MIN)))
            names.append(f"{letter}{len(names) + 1}")
        direction = ", ".join(f"{v:.3f}" for v in group["direction"])
        section_labels.append(place * Pos(0, -aux_h / 2 - font * 1.5) *
                              Text(f"VIEW {letter} (along {direction})", font_size=font, align=(Align.CENTER, Align.MAX)))
        aux_report.append({"view": letter, "direction": group["direction"], "holes": names})
        x_cursor += aux_w + gap

    title = name or (step_path.parent.name if step_path.stem == "model" else step_path.stem)
    notes = [title, f"Overall {width:.2f} x {depth:.2f} x {height:.2f} mm (X x Y x Z)",
             "Units mm, scale 1:1, third-angle projection",
             *tolerance_notes(tolerance_class, scale_ref),
             "Hole/boss/pocket positions dimensioned from each view's lower-left edges", *hole_rows(features)]
    notes += [f"{p['tag']} pocket/step {p['size'][0]:g} x {p['size'][1]:g}, {p['depth']:g} below the top, corner at "
              f"({p['from_datum'][0]:g}, {p['from_datum'][1]:g}) from the datum" for p in pockets]
    note_x = right_at.position.X - depth / 2
    note_y = top_at.position.Y + depth / 2
    labels = [Pos(note_x, note_y - index * font * 1.6) * Text(line, font_size=font if index else font * 1.3, align=(Align.MIN, Align.MAX))
              for index, line in enumerate(notes)] + tags + section_labels

    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    if "svg" in formats:
        svg = ExportSVG(unit=Unit.MM, margin=font * 2, line_weight=0.35)
        svg.add_layer("visible", line_weight=0.35)
        svg.add_layer("hidden", line_weight=0.18, line_type=LineType.ISO_DASH)
        svg.add_layer("dimensions", line_weight=0.13, fill_color=(0, 0, 0))
        svg.add_layer("notes", line_weight=0.05, fill_color=(0, 0, 0))
        svg.add_layer("hatch", line_weight=0.13)
        svg.add_shape(visible, layer="visible")
        if hatch:
            svg.add_shape(hatch, layer="hatch")
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
        dxf.add_layer("hatch", line_weight=0.13)
        dxf.add_shape(visible, layer="visible")
        if hatch:
            dxf.add_shape(hatch, layer="hatch")
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
        write_pdf(Path(written["pdf"]), visible, hidden, dimensions + hatch, labels)
    return {"files": written, "overall_mm": {"x": round(width, 3), "y": round(depth, 3), "z": round(height, 3)},
            "notes": notes, "feature_dimensions": feature_dimensions, "section": section_report if hatch else None,
            "auxiliary_views": aux_report, "tolerance_class": tolerance_class,
            "visible_edges": len(visible), "hidden_edges": len(hidden)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--formats", default="svg,dxf,pdf", help="comma-separated: svg,dxf,pdf")
    parser.add_argument("--name", help="title shown on the sheet (default: the STEP file name)")
    parser.add_argument("--section", default="y", help="section plane: x, y or z, optionally @offset mm (e.g. x@12), or none")
    parser.add_argument("--no-section", action="store_true", help="leave out section A-A (same as --section none)")
    parser.add_argument("--tolerance-class", choices=("f", "m", "c", "v"), default="m", help="ISO 2768-1 general tolerance class")
    args = parser.parse_args()
    formats = tuple(item.strip().lower() for item in args.formats.split(",") if item.strip())
    unknown = [item for item in formats if item not in ("svg", "dxf", "pdf")]
    if unknown:
        parser.error(f"unknown formats {unknown}")
    try:
        report = make_drawing(args.step, args.out_dir, formats, args.name, "none" if args.no_section else args.section, args.tolerance_class)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

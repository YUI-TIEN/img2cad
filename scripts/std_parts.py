#!/usr/bin/env python3
"""Standard parts: fasteners, bearings, a stepper motor and aluminium extrusion.

    img2cad parts list
    img2cad parts make screw --size M3 --length 12 --out m3x12.step
    img2cad parts make bearing --size 608 --out 608.step

Or from model.py (the worker puts this directory on sys.path):

    from std_parts import socket_head_screw, hex_nut, washer, ball_bearing, nema17, extrusion_2020
    screw = Pos(0, 0, 6) * socket_head_screw("M3", 12)

Dimensions follow the standards' nominal values (ISO 4762 socket head cap
screws, ISO 4032 hex nuts, ISO 7089 washers, ISO 15 deep-groove bearings,
NEMA 17 frame, 20 mm T-slot extrusion). Threads are plain cylinders at the
nominal diameter; bearings are solid rings (no balls). Good for fit checks,
assemblies and drawings, not for manufacturing the part itself. Every part
sits with its mounting face on z = 0 (screws hang down from their head).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from build123d import (Align, Box, Color, Compound, Cylinder, Location, Plane, Pos, RegularPolygon, Rot, Sketch, export_step,
                       extrude, Rectangle)

STEEL = Color(0.72, 0.73, 0.75)
BLACK_OXIDE = Color(0.16, 0.16, 0.17)
ALUMINIUM = Color(0.80, 0.81, 0.83)
MOTOR_BLACK = Color(0.10, 0.10, 0.11)

# ISO 4762: size -> (thread d, head diameter dk, head height k, hex key s)
SCREWS = {"M2": (2, 3.8, 2, 1.5), "M2.5": (2.5, 4.5, 2.5, 2), "M3": (3, 5.5, 3, 2.5), "M4": (4, 7, 4, 3),
          "M5": (5, 8.5, 5, 4), "M6": (6, 10, 6, 5), "M8": (8, 13, 8, 6), "M10": (10, 16, 10, 8), "M12": (12, 18, 12, 10)}
# ISO 4032: size -> (thread d, across flats s, height m)
NUTS = {"M2": (2, 4, 1.6), "M2.5": (2.5, 5, 2), "M3": (3, 5.5, 2.4), "M4": (4, 7, 3.2), "M5": (5, 8, 4.7),
        "M6": (6, 10, 5.2), "M8": (8, 13, 6.8), "M10": (10, 16, 8.4), "M12": (12, 18, 10.8)}
# ISO 7089: size -> (inner d1, outer d2, thickness h)
WASHERS = {"M2": (2.2, 5, 0.3), "M2.5": (2.7, 6, 0.5), "M3": (3.2, 7, 0.5), "M4": (4.3, 9, 0.8), "M5": (5.3, 10, 1),
           "M6": (6.4, 12, 1.6), "M8": (8.4, 16, 1.6), "M10": (10.5, 20, 2), "M12": (13, 24, 2.5)}
# ISO 15 deep-groove ball bearings: designation -> (bore d, outer D, width B)
BEARINGS = {"623": (3, 10, 4), "624": (4, 13, 5), "625": (5, 16, 5), "626": (6, 19, 6), "604": (4, 12, 4), "605": (5, 14, 5),
            "606": (6, 17, 6), "608": (8, 22, 7), "6000": (10, 26, 8), "6001": (12, 28, 8), "6200": (10, 30, 9),
            "6201": (12, 32, 10), "6202": (15, 35, 11), "6203": (17, 40, 12), "6204": (20, 47, 14), "6205": (25, 52, 15)}


def _labelled(shape, label: str, color: Color):
    shape.label, shape.color = label, color
    return shape


def socket_head_screw(size: str, length: float):
    """ISO 4762 socket head cap screw; head on top of z = 0, shank down to z = -length."""
    d, dk, k, s = SCREWS[size]
    head = Cylinder(dk / 2, k, align=(Align.CENTER, Align.CENTER, Align.MIN))
    socket = Pos(0, 0, k - 0.6 * k) * extrude(Sketch() + RegularPolygon(s / math.sqrt(3), 6), amount=0.6 * k + 0.01)
    shank = Cylinder(d / 2, length, align=(Align.CENTER, Align.CENTER, Align.MAX))
    return _labelled((head - socket) + shank, f"{size}x{length:g} socket head screw", BLACK_OXIDE)


def hex_nut(size: str):
    """ISO 4032 hex nut, sitting on z = 0."""
    d, s, m = NUTS[size]
    body = extrude(Sketch() + RegularPolygon(s / math.sqrt(3), 6), amount=m)
    return _labelled(body - Cylinder(d / 2, m, align=(Align.CENTER, Align.CENTER, Align.MIN)), f"{size} hex nut", STEEL)


def washer(size: str):
    """ISO 7089 plain washer, sitting on z = 0."""
    d1, d2, h = WASHERS[size]
    ring = Cylinder(d2 / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(d1 / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return _labelled(ring, f"{size} washer", STEEL)


def ball_bearing(designation: str):
    """Deep-groove ball bearing as one solid ring (shield face recessed 0.3 mm), sitting on z = 0."""
    d, D, B = BEARINGS[designation]
    ring = Cylinder(D / 2, B, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(d / 2, B, align=(Align.CENTER, Align.CENTER, Align.MIN))
    gap_outer, gap_inner = D / 2 - (D - d) * 0.18, d / 2 + (D - d) * 0.18
    for z in (B - 0.3, 0):
        ring -= Pos(0, 0, z) * (Cylinder(gap_outer, 0.3, align=(Align.CENTER, Align.CENTER, Align.MIN))
                                - Cylinder(gap_inner, 0.3, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    return _labelled(ring, f"{designation} bearing", STEEL)


def nema17(length: float = 40.0):
    """NEMA 17 stepper: 42.3 mm square body below z = 0, 22 mm pilot and 5 mm shaft above; M3 holes 31 mm apart."""
    body = Box(42.3, 42.3, length, align=(Align.CENTER, Align.CENTER, Align.MAX))
    for x in (-15.5, 15.5):
        for y in (-15.5, 15.5):
            body -= Pos(x, y, 0) * Cylinder(1.5, 4.5, align=(Align.CENTER, Align.CENTER, Align.MAX))
    body = body.fillet(3, body.edges().filter_by(lambda e: abs(e.tangent_at(0.5).Z) > 0.99 and e.length > length - 1e-3))
    body = _labelled(body + Cylinder(11, 2, align=(Align.CENTER, Align.CENTER, Align.MIN)), "NEMA17 body", MOTOR_BLACK)
    shaft = _labelled(Pos(0, 0, 2) * Cylinder(2.5, 22, align=(Align.CENTER, Align.CENTER, Align.MIN)), "NEMA17 shaft", STEEL)
    return Compound(children=[body, shaft])


def extrusion_2020(length: float):
    """20 x 20 mm T-slot aluminium extrusion (simplified 6 mm slots, 4.2 mm core bore) from z = 0 up."""
    profile = Sketch() + Rectangle(20, 20)
    for angle in (0, 90, 180, 270):
        profile -= Rot(0, 0, angle) * Pos(10 - 3, 0) * Rectangle(6.01, 6.2)
    profile -= Sketch() + RegularPolygon(2.1, 32)
    return _labelled(extrude(profile, amount=length), f"2020 extrusion {length:g} mm", ALUMINIUM)


CATALOG = {
    "screw": ("ISO 4762 socket head cap screw", sorted(SCREWS, key=lambda s: SCREWS[s][0]), "needs --length"),
    "nut": ("ISO 4032 hex nut", sorted(NUTS, key=lambda s: NUTS[s][0]), ""),
    "washer": ("ISO 7089 plain washer", sorted(WASHERS, key=lambda s: WASHERS[s][0]), ""),
    "bearing": ("ISO 15 deep-groove ball bearing", sorted(BEARINGS, key=lambda s: BEARINGS[s][1]), ""),
    "nema17": ("NEMA 17 stepper motor", [], "--length = body length (default 40)"),
    "extrusion2020": ("20x20 T-slot extrusion", [], "needs --length"),
}


def make(kind: str, size: str | None = None, length: float | None = None):
    if kind == "screw":
        if length is None:
            raise ValueError("screw needs --length")
        return socket_head_screw(size or "M3", length)
    if kind == "nut":
        return hex_nut(size or "M3")
    if kind == "washer":
        return washer(size or "M3")
    if kind == "bearing":
        return ball_bearing(size or "608")
    if kind == "nema17":
        return nema17(length or 40.0)
    if kind == "extrusion2020":
        if length is None:
            raise ValueError("extrusion2020 needs --length")
        return extrusion_2020(length)
    raise ValueError(f"unknown part {kind!r}; choose from {', '.join(CATALOG)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the part kinds and sizes")
    build = commands.add_parser("make", help="write one part as STEP")
    build.add_argument("kind", choices=list(CATALOG))
    build.add_argument("--size", help="M3, 608, ... (see list)")
    build.add_argument("--length", type=float, help="screw / extrusion length or motor body length, mm")
    build.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps({kind: {"standard": standard, "sizes": sizes, "note": note} for kind, (standard, sizes, note) in CATALOG.items()}, indent=2))
        return 0
    try:
        part = make(args.kind, args.size, args.length)
    except (KeyError, ValueError) as error:
        parser.error(f"{error}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    export_step(part, str(args.out))
    box = part.bounding_box()
    print(json.dumps({"file": str(args.out), "label": getattr(part, "label", "") or args.kind,
                      "size_mm": [round(box.size.X, 3), round(box.size.Y, 3), round(box.size.Z, 3)], "volume_mm3": round(part.volume, 2)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

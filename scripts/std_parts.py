#!/usr/bin/env python3
"""Standard parts: fasteners, bearings, gears, pulleys, rails, motors, servos, extrusion.

    img2cad parts list
    img2cad parts make screw --size M3 --length 12 --out m3x12.step
    img2cad parts make bearing --size 608 --out 608.step
    img2cad parts make gear --module 1 --teeth 24 --width 6 --bore 5 --out gear.step
    img2cad parts make screw --size M3 --length 12 --threads --out m3x12_threaded.step

Or from model.py (the worker puts this directory on sys.path):

    from std_parts import socket_head_screw, hex_nut, washer, ball_bearing, nema17, extrusion_2020
    from std_parts import spur_gear, gt2_pulley, mgn_rail, servo
    screw = Pos(0, 0, 6) * socket_head_screw("M3", 12)

Dimensions follow the standards' nominal values (ISO 4762 socket head cap
screws, ISO 4032 hex nuts, ISO 7089 washers, ISO 15 deep-groove bearings,
NEMA 17 frame, 20 mm T-slot extrusion, ISO 53 involute spur gears, GT2
pulleys with the Gates groove profile, MGN rails with counterbored rail holes
and tapped carriage holes (HIWIN catalogue), SG90 / MG996R hobby servos).
Servo bodies vary between vendors: check the one you buy before a tight fit. Threads are plain
cylinders at the nominal diameter unless you ask for `threads=True` (a real
ISO metric helix: slower, use it for close-ups and prints, not big
assemblies); bearings are solid rings (no balls). Good for fit checks,
assemblies and drawings, not for manufacturing the part itself. Every part
sits with its mounting face on z = 0 (screws hang down from their head).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from build123d import (Align, Box, Color, Compound, Cylinder, Helix, Plane, Polygon, Polyline, Pos, RegularPolygon, Rot, Sketch,
                       Solid, Vector, Wire, export_step, extrude, make_face, Rectangle, sweep)

STEEL = Color(0.72, 0.73, 0.75)
BLACK_OXIDE = Color(0.16, 0.16, 0.17)
ALUMINIUM = Color(0.80, 0.81, 0.83)
MOTOR_BLACK = Color(0.10, 0.10, 0.11)

# ISO 4762: size -> (thread d, head diameter dk, head height k, hex key s)
SCREWS = {"M2": (2, 3.8, 2, 1.5), "M2.5": (2.5, 4.5, 2.5, 2), "M3": (3, 5.5, 3, 2.5), "M4": (4, 7, 4, 3),
          "M5": (5, 8.5, 5, 4), "M6": (6, 10, 6, 5), "M8": (8, 13, 8, 6), "M10": (10, 16, 10, 8), "M12": (12, 18, 12, 10)}
# ISO 261 coarse pitch
PITCH = {"M2": 0.4, "M2.5": 0.45, "M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0, "M8": 1.25, "M10": 1.5, "M12": 1.75}
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


def threaded_rod(diameter: float, pitch: float, length: float):
    """External ISO metric thread from z = 0 up to z = length (core plus a swept 60-degree helix)."""
    h = 0.5413 * pitch  # thread depth (5/8 of the fundamental triangle height)
    core = diameter / 2 - h
    turns = Helix(pitch, length - pitch, core, center=(0, 0, pitch / 2))
    profile = Plane.XZ * Polygon((core - 0.05 * pitch, -0.42 * pitch), (diameter / 2, -0.06 * pitch), (diameter / 2, 0.06 * pitch),
                                 (core - 0.05 * pitch, 0.42 * pitch), align=None)
    profile = Pos(0, 0, pitch / 2) * profile
    return Cylinder(core, length, align=(Align.CENTER, Align.CENTER, Align.MIN)) + sweep(profile, turns, is_frenet=True)


def socket_head_screw(size: str, length: float, threads: bool = False):
    """ISO 4762 socket head cap screw; head on top of z = 0, shank down to z = -length."""
    d, dk, k, s = SCREWS[size]
    head = Cylinder(dk / 2, k, align=(Align.CENTER, Align.CENTER, Align.MIN))
    socket = Pos(0, 0, k - 0.6 * k) * extrude(Sketch() + RegularPolygon(s / math.sqrt(3), 6), amount=0.6 * k + 0.01)
    if threads:
        shank = Pos(0, 0, -length) * threaded_rod(d, PITCH[size], length)
    else:
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


def _involute_outline(module: float, teeth: int, pressure_deg: float = 20.0, points: int = 8,
                      shift: float = 0.0) -> list[tuple[float, float]]:
    """Transverse tooth outline; `shift` is the profile shift coefficient x (ISO 21771)."""
    pitch_r = module * teeth / 2
    alpha = math.radians(pressure_deg)
    base_r = pitch_r * math.cos(alpha)
    tip_r, root_r = pitch_r + module * (1 + shift), pitch_r - module * (1.25 - shift)

    def inv(r: float) -> float:
        t = math.sqrt(max((r / base_r) ** 2 - 1, 0.0))
        return t - math.atan(t)

    half = (math.pi / 2 + 2 * shift * math.tan(alpha)) / teeth + inv(pitch_r)  # half tooth angle at the base circle
    start = max(base_r, root_r)
    radii = [start + (tip_r - start) * i / points for i in range(points + 1)]
    flank = [(r, half - inv(r)) for r in radii]
    if root_r < base_r:
        flank.insert(0, (root_r, half))
    outline = []
    for k in range(teeth):
        centre = 2 * math.pi * k / teeth
        right = [(r * math.cos(centre - a), r * math.sin(centre - a)) for r, a in flank]
        left = [(r * math.cos(centre + a), r * math.sin(centre + a)) for r, a in reversed(flank)]
        outline += right + left
    return outline


def spur_gear(module: float, teeth: int, width: float, bore: float = 0.0, pressure_deg: float = 20.0,
              helix_deg: float = 0.0, shift: float = 0.0):
    """ISO 53 involute gear centred on the Z axis from z = 0 up.

    `module` is the normal module. Spur (helix_deg = 0): pitch diameter = module x teeth.
    Helical: pitch diameter = module x teeth / cos(helix); a positive helix is right-handed.
    `shift` is the profile shift coefficient x (positive: thicker teeth, larger tip; use it
    against undercut below about 17 teeth or to set a centre distance)."""
    if teeth < 6:
        raise ValueError("a gear needs at least 6 teeth")
    beta = math.radians(helix_deg)
    transverse_module = module / math.cos(beta)
    transverse_pressure = math.degrees(math.atan(math.tan(math.radians(pressure_deg)) / math.cos(beta)))
    outline = _involute_outline(transverse_module, teeth, transverse_pressure, shift=shift)
    if helix_deg:
        pitch_r = transverse_module * teeth / 2
        twist = math.degrees(width * math.tan(beta) / pitch_r)
        wire = Wire.make_polygon([Vector(x, y, 0) for x, y in outline], close=True)
        gear = Solid.extrude_linear_with_rotation(wire, (0, 0, 0), (0, 0, width), twist)
    else:
        gear = extrude(make_face(Polyline(*outline, close=True)), amount=width)
    if bore:
        gear -= Cylinder(bore / 2, width, align=(Align.CENTER, Align.CENTER, Align.MIN))
    kind = f"helical gear m{module:g} z{teeth} {helix_deg:g}deg" if helix_deg else f"spur gear m{module:g} z{teeth}"
    return _labelled(gear, kind + (f" x{shift:+g}" if shift else ""), STEEL)


def centre_distance(module: float, teeth_a: int, teeth_b: int, helix_deg: float = 0.0) -> float:
    """Centre distance of two meshing gears without profile shift: m (z1 + z2) / (2 cos helix)."""
    return module * (teeth_a + teeth_b) / (2 * math.cos(math.radians(helix_deg)))


GT2_PLD = 0.254          # pitch line differential: belt pitch line sits this far outside the pulley OD
GT2_TOOTH_HEIGHT = 0.75  # groove depth below the OD
GT2_TOOTH_RADIUS = 0.555  # belt tooth (groove) radius
GT2_ROOT_RADIUS = 0.15   # fillet where the groove meets the OD


def _gt2_outline(teeth: int, points: int = 10) -> list[tuple[float, float]]:
    """Pulley cross-section: OD arcs, a circular groove of the GT2 belt tooth radius and depth per tooth,
    blended into the OD by the root radius (Gates GT2 2 mm dimensions)."""
    outer_r = teeth * 2.0 / math.pi / 2 - GT2_PLD
    centre_r = outer_r - GT2_TOOTH_HEIGHT + GT2_TOOTH_RADIUS
    # fillet circle tangent to the OD (inside it) and to the groove circle (outside it)
    fillet_r = outer_r - GT2_ROOT_RADIUS
    reach = GT2_TOOTH_RADIUS + GT2_ROOT_RADIUS
    cos_phi = (fillet_r ** 2 + centre_r ** 2 - reach ** 2) / (2 * fillet_r * centre_r)
    phi = math.acos(max(-1.0, min(1.0, cos_phi)))  # angle from the groove centre to the fillet centre
    pitch = 2 * math.pi / teeth
    outline = []
    for k in range(teeth):
        c = k * pitch
        fc = (fillet_r * math.cos(c - phi), fillet_r * math.sin(c - phi))
        gc = (centre_r * math.cos(c), centre_r * math.sin(c))
        fd = (fillet_r * math.cos(c + phi), fillet_r * math.sin(c + phi))
        # fillet 1: from its OD tangent point to its groove tangent point
        a0 = c - phi
        a1 = math.atan2(gc[1] - fc[1], gc[0] - fc[0])
        g0 = math.atan2(fc[1] - gc[1], fc[0] - gc[0])
        g1 = math.atan2(fd[1] - gc[1], fd[0] - gc[0])
        if g1 > g0:
            g1 -= 2 * math.pi
        arcs = []
        arcs += [(fc[0] + GT2_ROOT_RADIUS * math.cos(a0 + (_wrap(a1 - a0) * i / points)),
                  fc[1] + GT2_ROOT_RADIUS * math.sin(a0 + (_wrap(a1 - a0) * i / points))) for i in range(points + 1)]
        arcs += [(gc[0] + GT2_TOOTH_RADIUS * math.cos(g0 + (g1 - g0) * i / (2 * points)),
                  gc[1] + GT2_TOOTH_RADIUS * math.sin(g0 + (g1 - g0) * i / (2 * points))) for i in range(1, 2 * points)]
        e0 = math.atan2(gc[1] - fd[1], gc[0] - fd[0])
        e1 = c + phi
        arcs += [(fd[0] + GT2_ROOT_RADIUS * math.cos(e0 + _wrap(e1 - e0) * i / points),
                  fd[1] + GT2_ROOT_RADIUS * math.sin(e0 + _wrap(e1 - e0) * i / points)) for i in range(points + 1)]
        outline += arcs
        # OD land up to the next tooth's first fillet
        start, end = c + phi, c + pitch - phi
        outline += [(outer_r * math.cos(start + (end - start) * i / points), outer_r * math.sin(start + (end - start) * i / points))
                    for i in range(1, points)]
    return outline


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def gt2_pulley(teeth: int = 20, width: float = 6.0, bore: float = 5.0):
    """GT2 (2 mm pitch) timing pulley with flanges and a hub, from z = 0 up: hub, flange, toothed section, flange.
    The teeth follow the Gates GT2 groove: belt tooth radius 0.555, depth 0.75, root radius 0.15, PLD 0.254."""
    outer_r = teeth * 2.0 / math.pi / 2 - GT2_PLD
    hub_h, flange_t = 7.0, 1.0
    hub = Cylinder(max(outer_r + 1.5, bore / 2 + 3), hub_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    flange = Cylinder(outer_r + 2.0, flange_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
    teeth_body = extrude(make_face(Polyline(*_gt2_outline(teeth), close=True)), amount=width)
    pulley = hub + Pos(0, 0, hub_h) * flange + Pos(0, 0, hub_h + flange_t) * teeth_body + Pos(0, 0, hub_h + flange_t + width) * flange
    pulley -= Cylinder(bore / 2, hub_h + 2 * flange_t + width, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return _labelled(pulley, f"GT2 {teeth}T pulley", ALUMINIUM)


# MGN miniature rail (HIWIN catalogue, H carriage): size -> (rail width, rail height, hole pitch, carriage width,
# carriage length, height rail bottom -> carriage top)
RAILS = {"MGN7": (7, 5, 15, 17, 30.8, 8), "MGN9": (9, 6, 20, 20, 39.9, 10), "MGN12": (12, 8, 25, 27, 45.4, 13), "MGN15": (15, 10, 40, 32, 58.8, 16)}
# rail bolt holes: (through d, counterbore d, counterbore depth); carriage: (hole spacing across, along, tap drill, thread)
RAIL_HOLES = {"MGN7": (2.4, 4.2, 2.3), "MGN9": (3.5, 6.0, 3.5), "MGN12": (3.5, 6.0, 4.5), "MGN15": (3.5, 6.0, 4.5)}
CARRIAGE_HOLES = {"MGN7": (12, 13, 1.6, "M2"), "MGN9": (15, 16, 2.5, "M3"), "MGN12": (20, 20, 2.5, "M3"), "MGN15": (25, 25, 2.5, "M3")}


def mgn_rail(size: str = "MGN12", length: float = 200.0):
    """MGN linear rail along X (bottom on z = 0, centred) with one H carriage in the middle; two labelled parts."""
    rw, rh, pitch, cw, cl, top = RAILS[size]
    through, cbore, cbore_depth = RAIL_HOLES[size]
    across, along, tap, _ = CARRIAGE_HOLES[size]
    rail = Box(length, rw, rh, align=(Align.CENTER, Align.CENTER, Align.MIN))
    count = int(length // pitch)
    for i in range(count):
        x = -((count - 1) * pitch) / 2 + i * pitch
        rail -= Pos(x, 0, 0) * Cylinder(through / 2, rh, align=(Align.CENTER, Align.CENTER, Align.MIN))
        rail -= Pos(x, 0, rh - cbore_depth) * Cylinder(cbore / 2, cbore_depth, align=(Align.CENTER, Align.CENTER, Align.MIN))
    carriage = Pos(0, 0, rh * 0.45) * Box(cl, cw, top - rh * 0.45, align=(Align.CENTER, Align.CENTER, Align.MIN))
    carriage -= Box(cl, rw + 0.4, rh * 0.55 + 0.2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    depth = min(4.0, top - rh - 0.5)
    for x in (-along / 2, along / 2):
        for y in (-across / 2, across / 2):  # tapped mounting holes (tap drill diameter)
            carriage -= Pos(x, y, top - depth) * Cylinder(tap / 2, depth, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Compound(children=[_labelled(rail, f"{size} rail {length:g} mm", STEEL), _labelled(carriage, f"{size}H carriage", STEEL)])


# hobby servo: (body L, W, H, flange length, flange thickness, flange top height, shaft offset from body centre, horn spline d)
SERVOS = {"SG90": (22.8, 12.2, 22.7, 32.2, 2.5, 18.0, 5.9, 4.8), "MG996R": (40.7, 19.7, 37.0, 54.0, 2.8, 29.0, 10.2, 5.8)}


def servo(model: str = "SG90"):
    """Hobby servo body (bottom on z = 0, long side along X) with mounting flanges and the output spline on top."""
    length, width, height, flange_l, flange_t, flange_top, shaft_dx, spline = SERVOS[model]
    body = Box(length, width, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    flange = Pos(0, 0, flange_top - flange_t) * Box(flange_l, width, flange_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for x in (-(flange_l + length) / 4, (flange_l + length) / 4):
        flange -= Pos(x, 0, 0) * Cylinder(1.0, 100)
    boss = Pos(-length / 2 + shaft_dx, 0, height) * Cylinder(width / 2 * 0.95, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))
    shaft = Pos(-length / 2 + shaft_dx, 0, height + 4) * Cylinder(spline / 2, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Compound(children=[_labelled(body + flange + boss, f"{model} servo", MOTOR_BLACK), _labelled(shaft, f"{model} output spline", Color(0.95, 0.95, 0.95))])


CATALOG = {
    "screw": ("ISO 4762 socket head cap screw", sorted(SCREWS, key=lambda s: SCREWS[s][0]), "needs --length"),
    "nut": ("ISO 4032 hex nut", sorted(NUTS, key=lambda s: NUTS[s][0]), ""),
    "washer": ("ISO 7089 plain washer", sorted(WASHERS, key=lambda s: WASHERS[s][0]), ""),
    "bearing": ("ISO 15 deep-groove ball bearing", sorted(BEARINGS, key=lambda s: BEARINGS[s][1]), ""),
    "nema17": ("NEMA 17 stepper motor", [], "--length = body length (default 40)"),
    "extrusion2020": ("20x20 T-slot extrusion", [], "needs --length"),
    "gear": ("ISO 53 involute spur or helical gear", [], "--module, --teeth, --width, --bore, --helix, --shift"),
    "pulley": ("GT2 timing pulley (Gates groove profile)", [], "--teeth (default 20), --width (6), --bore (5)"),
    "rail": ("MGN linear rail + H carriage", sorted(RAILS, key=lambda s: RAILS[s][0]), "--length (default 200)"),
    "servo": ("hobby servo", sorted(SERVOS), ""),
}


def make(kind: str, size: str | None = None, length: float | None = None, threads: bool = False, module: float = 1.0,
         teeth: int | None = None, width: float | None = None, bore: float | None = None, helix: float = 0.0, shift: float = 0.0):
    if kind == "screw":
        if length is None:
            raise ValueError("screw needs --length")
        return socket_head_screw(size or "M3", length, threads)
    if kind == "gear":
        return spur_gear(module, teeth or 20, width or 6.0, bore or 0.0, helix_deg=helix, shift=shift)
    if kind == "pulley":
        return gt2_pulley(teeth or 20, width or 6.0, 5.0 if bore is None else bore)
    if kind == "rail":
        return mgn_rail(size or "MGN12", length or 200.0)
    if kind == "servo":
        return servo(size or "SG90")
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
    build.add_argument("--length", type=float, help="screw / extrusion / rail length or motor body length, mm")
    build.add_argument("--threads", action="store_true", help="screw: model the ISO thread helix")
    build.add_argument("--module", type=float, default=1.0, help="gear module, mm")
    build.add_argument("--teeth", type=int, help="gear / pulley teeth")
    build.add_argument("--width", type=float, help="gear / pulley face width, mm")
    build.add_argument("--bore", type=float, help="gear / pulley bore diameter, mm")
    build.add_argument("--helix", type=float, default=0.0, help="gear helix angle, degrees (0 = spur; positive = right hand)")
    build.add_argument("--shift", type=float, default=0.0, help="gear profile shift coefficient x")
    build.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps({kind: {"standard": standard, "sizes": sizes, "note": note} for kind, (standard, sizes, note) in CATALOG.items()}, indent=2))
        return 0
    try:
        part = make(args.kind, args.size, args.length, args.threads, args.module, args.teeth, args.width, args.bore, args.helix, args.shift)
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

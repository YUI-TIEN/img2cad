"""Espresso cup, saucer and spoon from a real photo (scikit-image `coffee`, CC0, Rachel Michetti).

Measured, not eyeballed:

* Camera: the rims and the cup's foot are circles. A perspective frame
  fitted by least squares to 8 cup-rim, 10 saucer-rim and 5 foot-arc edge
  points (fit_camera.py) gives elevation 57 deg, camera 0.63 m away,
  0.301 mm/px, the cup rim (r 34.0 mm at z 53.7) and foot (r 27.7 mm), with
  2.3 px RMS. The foot arc matters: without it, cup depth and height trade
  off and the cup came out 10 mm too tall. The saucer (r 60 mm, rim z 12) is
  an assumed typical size and sets the scale.
* Cup profile: left and right silhouette edges at four image rows, solved
  through the same frame for (r, z) (fit_profile.py); both sides agree within
  2 mm.
* Crema level: where the far edge and the side edges of the crema give the
  same radius (z 28, r 24.3).
* Handle: its pixel is mapped back to 3D with the frame and the ring is
  placed on the cup wall there.
* Spoon: small, shiny and partly hidden, so it is NOT measured: a typical
  teaspoon (105 mm) lies on the saucer as the scene shows, anchored on the
  bowl and handle-end pixels. Solving its depth from pixels cost several
  failed previews and put it upright against the cup; see LESSONS.md
  "Measure the main bodies; use typical sizes for small parts".
"""

import math

from build123d import *
from img2cad_lib import ImageFrame

ELEVATION = 57.153
IMAGE_FRAME = ImageFrame(mm_per_px=0.301, origin_px=(276.009, 235.405),
                         view=(0.0, -math.cos(math.radians(ELEVATION)), math.sin(math.radians(ELEVATION))), distance=629.5)

# Saucer: (r, z) of the top surface from the centre of the well to the rim; underside 3.5 mm below.
SAUCER_TOP = [(0, 4.0), (30, 4.0), (40, 5.0), (50, 8.0), (57, 11.0), (59.2, 12.0)]
SAUCER_FOOT = (30.0, 34.0)  # foot ring radii, 0..1.5 mm

# Cup: outer profile (r, z) from the foot up to the rim (fit_profile.py), cavity from the rim down.
CUP_X, CUP_Y = 4.42, 7.63
CUP_OUTER = [(25.5, 4.0), (27.6, 5.0), (28.4, 9.0), (30.5, 19.7), (31.6, 35.1), (32.7, 49.9), (34.0, 53.75)]
CUP_INNER = [(30.3, 53.75), (28.6, 46.0), (24.3, 28.0), (19.5, 18.0), (11.0, 12.5), (0.0, 11.5)]
GLAZE = 1.5  # [0.5, 3] white glaze thickness inside and on the rim, mm
COFFEE_Z = 28.0  # [15, 45] crema level above the table, mm
HANDLE_PX = (228, 266)  # centre of the handle loop in the photo
HANDLE = dict(radius=8.5, tube=(3.4, 4.4))  # ring radius; tube half-sizes across the ring and sideways
SPOON_PX = dict(bowl=(366, 280), tip=(410, 72))  # bowl centre, handle end
SPOON_LENGTH = 105.0  # [85, 130] teaspoon length (typical size, not measured), mm (typical teaspoon (prior, not measured))
SPOON_BOWL = (17.0, 12.0, 2.6)  # half-length, half-width, half-thickness of a typical bowl
SPOON_ROD = 1.8  # [1, 3] spoon handle radius, mm

RED = Color(0.58, 0.12, 0.04)
WHITE = Color(0.95, 0.90, 0.84)
CREMA = Color(0.80, 0.50, 0.24)
STEEL = Color(0.70, 0.70, 0.71)


def revolve_region(points):
    """Closed (r, z) polygon -> solid of revolution about Z, seam turned to the back (+Y)."""
    with BuildPart() as part:
        with BuildSketch(Plane.XZ):
            Polygon(*points, align=None)
        revolve(axis=Axis.Z)
    return Rot(0, 0, 90) * part.part


def revolve_path(segments):
    """Revolve a closed (r, z) outline made of ("line", [p, q, ...]) and ("spline", [p, ...]) pieces.

    Splines keep each wall one smooth surface, so later fuses (the handle) see
    a few clean faces instead of dozens of polygon facets.
    """
    with BuildPart() as part:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                for kind, pts in segments:
                    if kind == "spline":
                        Spline(*pts)
                    else:
                        for p, q in zip(pts, pts[1:]):
                            Line(p, q)
            make_face()
        revolve(axis=Axis.Z)
    return Rot(0, 0, 90) * part.part


def saucer():
    """Top surface spline from the well to the rim, a rounded lip, the underside 3.5 mm below, and a foot ring."""
    rim_r, rim_z = SAUCER_TOP[-1]
    under = [(r, z - 3.5) for r, z in reversed(SAUCER_TOP) if r > SAUCER_FOOT[1]]
    body = revolve_path([
        ("line", [(0.0, SAUCER_TOP[0][1]), SAUCER_TOP[1]]),
        ("spline", SAUCER_TOP[1:]),
        ("line", [(rim_r, rim_z), (rim_r + 0.8, rim_z - 1.5), under[0]]),
        ("spline", under + [(SAUCER_FOOT[1], 1.5)]),
        ("line", [(SAUCER_FOOT[1], 1.5), (SAUCER_FOOT[1], 0.0), (SAUCER_FOOT[0], 0.0), (SAUCER_FOOT[0], 1.5),
                  (0.0, 1.5), (0.0, SAUCER_TOP[0][1])]),
    ])
    body.color, body.label = RED, "saucer"
    return body


def interpolate(points, z):
    """Radius of an (r, z) polyline listed from the top down, at height z."""
    for (r0, z0), (r1, z1) in zip(points, points[1:]):
        if z1 <= z <= z0:
            return r0 + (r1 - r0) * (z - z0) / (z1 - z0)
    raise ValueError(z)


def place_handle():
    """(azimuth deg, height) of the handle ring centre whose projection is closest to HANDLE_PX."""
    best = None
    for angle in range(180, 360):
        for height in [8 + 0.5 * k for k in range(80)]:
            reach = interpolate(list(reversed(CUP_OUTER)), height) + HANDLE["radius"] - 1.0
            a = math.radians(angle)
            px, py = IMAGE_FRAME.project(CUP_X + reach * math.cos(a), CUP_Y + reach * math.sin(a), height)
            error = math.hypot(px - HANDLE_PX[0], py - HANDLE_PX[1])
            if best is None or error < best[0]:
                best = (error, angle, height)
    return best[1], best[2]


def cup():
    top = CUP_OUTER[-1][1]
    base = CUP_OUTER[0][1]
    rim_in = CUP_INNER[0][0]
    floor = CUP_INNER[-1][1]
    # Glaze outer surface: the cavity wall pushed out by GLAZE, below the glazed rim top.
    glaze_wall = [(r + GLAZE, z) for r, z in CUP_INNER[1:-1]]
    glaze_top = (interpolate(CUP_INNER, top - GLAZE) + GLAZE, top - GLAZE)
    # The red body stops GLAZE below the rim; the glaze covers the rim top.
    outer_body = CUP_OUTER[:-1] + [(interpolate(list(reversed(CUP_OUTER)), top - GLAZE), top - GLAZE)]
    body = revolve_path([
        ("line", [(0.0, base), CUP_OUTER[0]]),
        ("spline", outer_body),
        ("line", [outer_body[-1], glaze_top]),
        ("spline", [glaze_top] + glaze_wall + [(0.0, floor - GLAZE)]),
        ("line", [(0.0, floor - GLAZE), (0.0, base)]),
    ])
    glaze = revolve_path([
        ("line", [(rim_in, top), CUP_OUTER[-1], outer_body[-1], glaze_top]),
        ("spline", [glaze_top] + glaze_wall + [(0.0, floor - GLAZE)]),
        ("line", [(0.0, floor - GLAZE), (0.0, floor)]),
        ("spline", list(reversed(CUP_INNER))),
    ])
    # Handle: a ring of elliptical tube in the vertical plane through the cup axis.
    # Its azimuth and height are solved so the ring centre lands on the handle in the photo;
    # the ring overlaps the wall by 1 mm so it fuses into the body.
    angle, height = place_handle()
    reach = interpolate(list(reversed(CUP_OUTER)), height) + HANDLE["radius"] - 1.0
    with BuildPart() as ring:
        # Tube section in the XY plane (it contains the ring's axis, Y), swept round Y:
        # the ring lies in the XZ plane, i.e. the vertical plane through the cup axis.
        with BuildSketch(Plane.XY):
            with Locations((HANDLE["radius"], 0)):
                Ellipse(*HANDLE["tube"])
        revolve(axis=Axis.Y)
    a = math.radians(angle)
    handle = Pos(reach * math.cos(a), reach * math.sin(a), height) * Rot(0, 0, angle) * ring.part
    body = Pos(CUP_X, CUP_Y, 0) * body.fuse(handle).clean()
    body.color, body.label = RED, "cup"
    glaze = Pos(CUP_X, CUP_Y, 0) * glaze
    glaze.color, glaze.label = WHITE, "cup glaze"
    r_level = interpolate(CUP_INNER, COFFEE_Z)
    below = [(r, z) for r, z in CUP_INNER if z < COFFEE_Z]
    coffee = Pos(CUP_X, CUP_Y, 0) * revolve_path([
        ("line", [(0.0, COFFEE_Z), (r_level, COFFEE_Z)]),
        ("spline", [(r_level, COFFEE_Z)] + below),
        ("line", [(0.0, floor), (0.0, COFFEE_Z)]),
    ])
    coffee.color, coffee.label = CREMA, "espresso"
    return body, glaze, coffee


def saucer_z(r):
    """Height of the saucer's top surface at radius r (linear between profile points)."""
    pts = SAUCER_TOP
    if r >= pts[-1][0]:
        return pts[-1][1]
    for (r0, z0), (r1, z1) in zip(pts, pts[1:]):
        if r0 <= r <= r1:
            return z0 + (z1 - z0) * (r - r0) / (r1 - r0)
    return pts[0][1]


def resting(px, lift):
    """The 3D point seen at pixel px that sits `lift` mm above the saucer surface."""
    z = 8.0
    for _ in range(30):
        x, y, _ = IMAGE_FRAME.on_plane_z(*px, z)
        z = saucer_z(math.hypot(x, y)) + lift
    return IMAGE_FRAME.on_plane_z(*px, z)


def cup_radius(z):
    return interpolate(list(reversed(CUP_OUTER)), min(max(z, CUP_OUTER[0][1]), CUP_OUTER[-1][1]))


def on_ray(px, z):
    return IMAGE_FRAME.on_plane_z(*px, z)


def spoon():
    """A typical teaspoon lying on the saucer, placed from what the scene shows.

    The spoon is small, shiny and partly hidden, so it is not measured. Read
    as a scene: it lies in the saucer, bowl at the front right, handle running
    back to rest on the saucer rim. The bowl starts at its pixel on the
    saucer and moves straight out from the cup until it clears it (the pixel
    alone would put it under the cup's overhang); the handle points at the
    handle-end pixel's point on the rim. A typical size (SPOON_LENGTH, bowl
    SPOON_BOWL) is used rather than solving its depth.
    """
    half_l, half_w, half_t = SPOON_BOWL
    rim_z = SAUCER_TOP[-1][1]
    end = on_ray(SPOON_PX["tip"], rim_z + SPOON_ROD)

    def place(push):
        x, y, _ = resting(SPOON_PX["bowl"], half_t)
        dx, dy = x - CUP_X, y - CUP_Y
        d = math.hypot(dx, dy)
        x, y = x + push * dx / d, y + push * dy / d
        z = saucer_z(math.hypot(x, y)) + half_t - 0.2
        heading = math.atan2(end[1] - y, end[0] - x)
        return (x, y, z), heading

    for k in range(200):
        centre, heading = place(0.25 * k)
        u = (math.cos(heading), math.sin(heading))
        clear = True
        for i in range(24):
            t = 2 * math.pi * i / 24
            px = centre[0] + half_l * math.cos(t) * u[0] - half_w * math.sin(t) * u[1]
            py = centre[1] + half_l * math.cos(t) * u[1] + half_w * math.sin(t) * u[0]
            if math.hypot(px - CUP_X, py - CUP_Y) < cup_radius(centre[2] + half_t) + 0.5:
                clear = False
        if clear:
            break
    angle = math.degrees(heading)
    bowl = Pos(*centre) * Rot(0, 0, angle) * Sphere(1).scale((half_l, half_w, half_t))
    start = (centre[0] + 0.8 * half_l * u[0], centre[1] + 0.8 * half_l * u[1], centre[2])
    tip = (start[0] + (SPOON_LENGTH - 1.8 * half_l) * u[0], start[1] + (SPOON_LENGTH - 1.8 * half_l) * u[1], end[2])
    stem = Plane(origin=start, z_dir=[tip[i] - start[i] for i in range(3)]) * Cylinder(
        SPOON_ROD, math.dist(start, tip), align=(Align.CENTER, Align.CENTER, Align.MIN))
    # Two parts, not one fuse: fusing the scaled-sphere bowl to the stem wrote a
    # bowl that STEP readers dropped (the runner now fails on such a loss).
    bowl.color, bowl.label = STEEL, "spoon bowl"
    stem.color, stem.label = STEEL, "spoon handle"
    return bowl, stem


def build_model():
    cup_body, glaze, coffee = cup()
    return Compound(children=[saucer(), cup_body, glaze, coffee, *spoon()])

from math import sqrt

from build123d import Align, BuildPart, BuildSketch, Cone, Cylinder, Ellipse, Locations, Plane, Pos, Rot, Sphere, loft

# Visual approximation of a side-view illustration (head toward -X, camera on
# the -Y side, so near-side legs are at -Y). Scale assumed: 1 px = 4 mm, and
# image (px, py) maps to x = (px - 450) * 4, z = (560 - py) * 4 (ground z = 0).
# Widths along Y are not visible and are estimated.
BARREL_CENTER_Z = 880
BARREL_HALF_LENGTH = 840
BARREL_HALF_HEIGHT = 320
BARREL_HALF_WIDTH = 250
LEG_SPACING_Y = 150
# Each leg: list of (x, z) joints from the body down to the hoof, radius at each.
LEGS = [
    ("near fore", -LEG_SPACING_Y, [(-480, 680), (-512, 340), (-496, 20)], [60, 48, 44]),
    ("far fore", LEG_SPACING_Y, [(-600, 720), (-640, 360), (-620, 20)], [56, 46, 42]),
    ("near hind", -LEG_SPACING_Y, [(440, 720), (648, 420), (540, 20)], [70, 50, 44]),
    ("far hind", LEG_SPACING_Y, [(560, 720), (700, 400), (600, 20)], [66, 48, 42]),
]
HOOF_RADIUS = 60
HOOF_HEIGHT = 56
NECK = ((-600, 0, 1020), (-808, 0, 1580), 110, 70)
HEAD_CENTER, HEAD_RADII = (-960, 0, 1552), (250, 110, 135)
MUZZLE_CENTER, MUZZLE_RADII = (-1172, 0, 1484), (110, 80, 84)
EAR_BASE_Z, EAR_TIP_Z, EAR_X, EAR_Y = 1630, 1792, -832, 50
EYE_CENTER, EYE_RADIUS = (-1008, 92, 1584), 16
TAIL = ((800, 0, 920), (1020, 0, 440), 75, 55)


def segment(start, end, start_radius, end_radius):
    """Tapered cone from point start to point end (a limb, neck, or tail piece)."""
    direction = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    length = sqrt(sum(value * value for value in direction))
    return Plane(origin=start, z_dir=direction) * Cone(start_radius, end_radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))


def ellipsoid(center, radii):
    return Pos(*center) * Sphere(1).scale(radii)


def build_model():
    # Barrel: loft through ellipse sections whose size follows an ellipse profile.
    with BuildPart() as barrel:
        for t in (-0.97, -0.8, -0.4, 0, 0.4, 0.8, 0.97):
            factor = sqrt(1 - t * t)
            with BuildSketch(Plane.YZ.offset(t * BARREL_HALF_LENGTH)):
                with Locations((0, BARREL_CENTER_Z)):
                    Ellipse(BARREL_HALF_WIDTH * factor, BARREL_HALF_HEIGHT * factor)
        loft()
    parts = [segment(*NECK), ellipsoid(HEAD_CENTER, HEAD_RADII), ellipsoid(MUZZLE_CENTER, MUZZLE_RADII), segment(*TAIL)]
    for side in (1, -1):
        parts.append(segment((EAR_X, side * EAR_Y, EAR_BASE_Z), (EAR_X, side * EAR_Y, EAR_TIP_Z), 25, 3))
        parts.append(Pos(EYE_CENTER[0], side * EYE_CENTER[1], EYE_CENTER[2]) * Sphere(EYE_RADIUS))
    for _name, y, joints, radii in LEGS:
        points = [(x, y, z) for x, z in joints]
        for index in range(len(points) - 1):
            parts.append(segment(points[index], points[index + 1], radii[index], radii[index + 1]))
        for index in range(1, len(points)):
            # Ball joint slightly larger than the limb so the pieces overlap. A
            # default Sphere has its poles on Z, i.e. on the axis of these
            # near-vertical legs, and that fuse silently leaves extra solids;
            # Rot(90, 0, 0) turns the poles to Y, across the leg.
            parts.append(Pos(*points[index]) * Rot(90, 0, 0) * Sphere(radii[index] * 1.1))
        hoof_x, _, _ = points[-1]
        parts.append(Pos(hoof_x, y, HOOF_HEIGHT / 2) * Cylinder(HOOF_RADIUS, HOOF_HEIGHT))
    horse = barrel.part
    for part in parts:
        horse = horse.fuse(part)
    return horse

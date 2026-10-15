from build123d import Align, Box, BuildPart, BuildSketch, Cone, Cylinder, Plane, Pos, Rectangle, loft

# Visual approximation of a front-elevation illustration. Scale assumed:
# 1 px = 25 mm; image (px, py) maps to x = (px - 320) * 25, z = (740 - py) * 25.
# The plan is assumed square (depth = width) because only the front is shown.
PX = 25
BASE_BOTTOM_HALF, BASE_TOP_HALF, BASE_HEIGHT = 170 * PX, 145 * PX, 70 * PX
# Each tier: wall half-width, wall bottom/top heights, eave half-width, roof-top half-width, roof-top height (all px).
TIERS = [
    (120, 70, 150, 175, 70, 195),
    (95, 195, 265, 145, 55, 305),
    (70, 305, 365, 115, 40, 405),
]
EAVE_THICKNESS = 12   # px; the eave edge flares out by EAVE_FLARE over this height
EAVE_FLARE = 10       # px
WALL_OVERLAP = 4      # px; walls start below the roof top under them so tiers fuse
FINIAL_RADIUS, FINIAL_BOTTOM, FINIAL_TOP = 6, 400, 485
FINIAL_TIP_RADIUS, FINIAL_TIP_TOP = 12, 515


def square_frustum(sections):
    """Ruled loft through centered squares given as (half-width, height) pairs."""
    with BuildPart() as solid:
        for half, height in sections:
            with BuildSketch(Plane.XY.offset(height)):
                Rectangle(2 * half, 2 * half)
        loft(ruled=True)
    return solid.part


def build_model():
    pagoda = square_frustum([(BASE_BOTTOM_HALF, 0), (BASE_TOP_HALF, BASE_HEIGHT)])
    for wall_half, wall_bottom, wall_top, eave_half, top_half, roof_top in TIERS:
        bottom = (wall_bottom - WALL_OVERLAP) * PX
        wall = Pos(0, 0, bottom) * Box(2 * wall_half * PX, 2 * wall_half * PX, wall_top * PX - bottom, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # Roof: eave underside, flared eave edge, then a straight hip slope to the top square.
        roof = square_frustum([
            (eave_half * PX, (wall_top - EAVE_THICKNESS / 2) * PX),
            ((eave_half + EAVE_FLARE) * PX, (wall_top + EAVE_THICKNESS / 2) * PX),
            (top_half * PX, roof_top * PX),
        ])
        pagoda = pagoda.fuse(wall).fuse(roof)
    finial = Pos(0, 0, FINIAL_BOTTOM * PX) * Cylinder(FINIAL_RADIUS * PX, (FINIAL_TOP - FINIAL_BOTTOM) * PX, align=(Align.CENTER, Align.CENTER, Align.MIN))
    tip = Pos(0, 0, FINIAL_TOP * PX) * Cone(FINIAL_TIP_RADIUS * PX, 0, (FINIAL_TIP_TOP - FINIAL_TOP) * PX, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return pagoda.fuse(finial).fuse(tip)

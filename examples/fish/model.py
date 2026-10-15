from build123d import BuildPart, BuildSketch, Ellipse, Locations, Plane, Polygon, Sphere, extrude, loft

# Visual approximation of a side-view illustration. 1 px ~ 0.4 mm, so the body
# is 180 mm long. Thickness (Y) is not visible and is estimated.
# Each section: (x position along the body, half-height in Z, half-width in Y).
BODY_SECTIONS = [
    (-90, 4, 2),
    (-80, 22, 10),
    (-50, 36, 16),
    (0, 40, 18),
    (50, 32, 14),
    (80, 16, 7),
    (90, 3, 2),
]
FIN_THICKNESS = 2
TAIL = [(70, 0), (130, 36), (118, 0), (130, -36)]
DORSAL_FIN = [(-25, 30), (22, 60), (42, 30)]
# Revision r002: the r001 review found the eye and pectoral fin missing.
PECTORAL_FIN = [(-6, -16), (18, -28), (2, -34)]
PECTORAL_SIDE_OFFSET = 13  # just inside the body surface at that height
EYE_POSITION = (-58, 12.5, 10)
EYE_RADIUS = 4


def build_model():
    with BuildPart() as fish:
        # Loft through elliptical cross-sections placed along X.
        for x, half_height, half_width in BODY_SECTIONS:
            with BuildSketch(Plane.YZ.offset(x)):
                Ellipse(half_width, half_height)
        loft()
        # Thin fins are polygons on the side (XZ) plane extruded symmetrically.
        with BuildSketch(Plane.XZ):
            Polygon(*TAIL)
            Polygon(*DORSAL_FIN)
        extrude(amount=FIN_THICKNESS / 2, both=True)
        # Plane.XZ faces -Y, so offset(+d) moves the sketch to y = -d. One fin
        # per side, extruded outward from just inside the body.
        for side in (1, -1):
            with BuildSketch(Plane.XZ.offset(-side * PECTORAL_SIDE_OFFSET)):
                Polygon(*PECTORAL_FIN)
            extrude(amount=side * -FIN_THICKNESS)
        eye_x, eye_y, eye_z = EYE_POSITION
        with Locations((eye_x, eye_y, eye_z), (eye_x, -eye_y, eye_z)):
            Sphere(EYE_RADIUS)
    return fish.part

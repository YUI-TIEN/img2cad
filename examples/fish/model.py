from build123d import BuildPart, BuildSketch, Color, Compound, Ellipse, Plane, Polygon, Pos, Sphere, extrude, loft

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
EYE_RADIUS = 6
PUPIL_RADIUS = 3.2
# Colours sampled from the reference image (RGB / 255).
BODY_COLOR = Color(240 / 255, 140 / 255, 60 / 255)
FIN_COLOR = Color(226 / 255, 120 / 255, 52 / 255)
PECTORAL_COLOR = Color(214 / 255, 108 / 255, 44 / 255)
EYE_COLOR = Color(1, 1, 1)
PUPIL_COLOR = Color(30 / 255, 30 / 255, 30 / 255)


def colored(shape, color, label):
    shape.color, shape.label = color, label
    return shape


def build_model():
    with BuildPart() as body:
        # Loft through elliptical cross-sections placed along X.
        for x, half_height, half_width in BODY_SECTIONS:
            with BuildSketch(Plane.YZ.offset(x)):
                Ellipse(half_width, half_height)
        loft()
    parts = [colored(body.part, BODY_COLOR, "body")]
    for points, label in ((TAIL, "tail"), (DORSAL_FIN, "dorsal fin")):
        # Thin fins are polygons on the side (XZ) plane extruded symmetrically.
        # Each is its own part: the tail and dorsal fin only connect through
        # the body, so one part holding both would be two separate solids.
        with BuildPart() as fin:
            with BuildSketch(Plane.XZ):
                Polygon(*points)
            extrude(amount=FIN_THICKNESS / 2, both=True)
        parts.append(colored(fin.part, FIN_COLOR, label))
    for side in (1, -1):
        # Plane.XZ faces -Y, so offset(+d) moves the sketch to y = -d. One fin
        # per side, extruded outward from just inside the body.
        with BuildPart() as pectoral:
            with BuildSketch(Plane.XZ.offset(-side * PECTORAL_SIDE_OFFSET)):
                Polygon(*PECTORAL_FIN)
            extrude(amount=side * -FIN_THICKNESS)
        eye_x, eye_y, eye_z = EYE_POSITION
        eye = Pos(eye_x, side * eye_y, eye_z) * Sphere(EYE_RADIUS)
        # The pupil sits on the outer side of the eye ball.
        pupil = Pos(eye_x, side * (eye_y + EYE_RADIUS - PUPIL_RADIUS * 0.5), eye_z) * Sphere(PUPIL_RADIUS)
        name = "left" if side > 0 else "right"
        parts += [colored(pectoral.part, PECTORAL_COLOR, f"{name} pectoral fin"),
                  colored(eye, EYE_COLOR, f"{name} eye"), colored(pupil, PUPIL_COLOR, f"{name} pupil")]
    # A coloured assembly: each part keeps its colour in the STEP file.
    return Compound(children=parts, label="fish")

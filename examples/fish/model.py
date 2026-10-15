from build123d import BuildPart, BuildSketch, Color, Compound, Ellipse, Plane, Polygon, extrude, loft, mirror

from img2cad_lib import ImageFrame, projected_decal

# Visual approximation of a side-view illustration. 1 px = 0.4 mm, image pixel
# (375, 260) is the model origin (body centre); camera on -Y. The body is
# 180 mm long; thickness (Y) is not visible and is estimated.
IMAGE_FRAME = ImageFrame(mm_per_px=0.4, origin_px=(375, 260))
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
PAINT_THICKNESS = 0.8
# Paint outlines traced from the image with scripts/trace_regions.py (image pixels).
EYE_WHITE = [(227.0, 220.0), (233.0, 220.0), (238.0, 222.0), (243.0, 227.0), (245.0, 232.0), (245.0, 238.0), (243.0, 243.0), (238.0, 248.0), (233.0, 250.0), (227.0, 250.0), (222.0, 248.0), (217.0, 243.0), (215.0, 238.0), (215.0, 232.0), (217.0, 227.0), (222.0, 222.0)]
PUPIL = [(231.0, 228.0), (237.0, 229.0), (241.0, 234.0), (240.0, 240.0), (235.0, 244.0), (229.0, 243.0), (225.0, 238.0), (226.0, 232.0)]
PECTORAL_FIN = [(362.0, 301.0), (416.0, 328.0), (418.0, 330.0), (415.0, 332.0), (410.0, 333.0), (407.0, 335.0), (402.0, 336.0), (383.0, 344.0), (380.0, 344.0), (361.0, 303.0)]
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
    # Painted details: traced outlines projected onto the visible (-Y) side,
    # then mirrored to the hidden side (the body is symmetric about XZ).
    paint = [
        (projected_decal(body.part, PECTORAL_FIN, IMAGE_FRAME, PAINT_THICKNESS), PECTORAL_COLOR, "pectoral fin"),
        (projected_decal(body.part, EYE_WHITE, IMAGE_FRAME, PAINT_THICKNESS, [PUPIL]), EYE_COLOR, "eye"),
        (projected_decal(body.part, PUPIL, IMAGE_FRAME, PAINT_THICKNESS), PUPIL_COLOR, "pupil"),
    ]
    for decal, color, label in paint:
        parts.append(colored(decal, color, f"{label} (visible side)"))
        parts.append(colored(mirror(decal, about=Plane.XZ), color, f"{label} (hidden side)"))
    # A coloured assembly: each part keeps its colour in the STEP file.
    return Compound(children=parts, label="fish")

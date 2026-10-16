from build123d import Axis, Box, BuildPart, GridLocations, Hole, fillet

# Every value is read from the dimensioned drawing (units: mm).
LENGTH = 80  # [50, 160] plate length (X), mm
WIDTH = 50  # [30, 100] plate width (Y), mm
THICKNESS = 6  # [2, 15] plate thickness, mm
CORNER_RADIUS = 4  # [0, 12] corner fillet radius, mm
HOLE_PITCH_X = 64  # [30, 140] mounting hole spacing along X, mm
HOLE_PITCH_Y = 34  # [15, 90] mounting hole spacing along Y, mm
MOUNT_HOLE_DIAMETER = 6  # [3, 12] mounting hole diameter, mm
CENTER_HOLE_DIAMETER = 10  # [0, 30] centre hole diameter, mm


def build_model():
    with BuildPart() as plate:
        Box(LENGTH, WIDTH, THICKNESS)
        # Round only the four vertical corner edges, before drilling, so the
        # selector cannot pick up hole edges.
        fillet(plate.edges().filter_by(Axis.Z), radius=CORNER_RADIUS)
        with GridLocations(HOLE_PITCH_X, HOLE_PITCH_Y, 2, 2):
            Hole(radius=MOUNT_HOLE_DIAMETER / 2)
        Hole(radius=CENTER_HOLE_DIAMETER / 2)
    return plate.part

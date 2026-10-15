from build123d import Axis, Box, BuildPart, GridLocations, Hole, fillet

# Every value is read from the dimensioned drawing (units: mm).
LENGTH = 80
WIDTH = 50
THICKNESS = 6
CORNER_RADIUS = 4
HOLE_PITCH_X = 64
HOLE_PITCH_Y = 34
MOUNT_HOLE_DIAMETER = 6
CENTER_HOLE_DIAMETER = 10


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

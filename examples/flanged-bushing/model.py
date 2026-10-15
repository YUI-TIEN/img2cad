from build123d import Axis, BuildLine, BuildPart, BuildSketch, Plane, Polyline, make_face, revolve

# Every value is read from the dimensioned drawing (units: mm).
FLANGE_DIAMETER = 40
FLANGE_THICKNESS = 5
BODY_DIAMETER = 24
OVERALL_LENGTH = 25
BORE_DIAMETER = 12


def build_model():
    # Half cross-section drawn on Plane.XZ: sketch X is the radius, sketch Y is
    # the bushing axis (global Z). Starting the profile at the bore radius
    # instead of at the axis leaves the bore open after the revolve.
    profile = [
        (BORE_DIAMETER / 2, 0),
        (FLANGE_DIAMETER / 2, 0),
        (FLANGE_DIAMETER / 2, FLANGE_THICKNESS),
        (BODY_DIAMETER / 2, FLANGE_THICKNESS),
        (BODY_DIAMETER / 2, OVERALL_LENGTH),
        (BORE_DIAMETER / 2, OVERALL_LENGTH),
    ]
    with BuildPart() as bushing:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline(*profile, close=True)
            make_face()
        revolve(axis=Axis.Z)
    return bushing.part

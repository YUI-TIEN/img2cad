from build123d import Axis, BuildLine, BuildPart, BuildSketch, Plane, Polyline, make_face, revolve

# Every value is read from the dimensioned drawing (units: mm).
FLANGE_DIAMETER = 40  # [30, 70] flange outer diameter, mm
FLANGE_THICKNESS = 5  # [2, 12] flange thickness, mm
BODY_DIAMETER = 24  # [14, 36] body outer diameter, mm
OVERALL_LENGTH = 25  # [12, 60] overall length, mm
BORE_DIAMETER = 12  # [4, 20] bore diameter, mm


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

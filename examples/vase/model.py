from build123d import Axis, BuildLine, BuildPart, BuildSketch, Line, Plane, Spline, make_face, offset, revolve

# Visual approximation. The illustration has no scale; 1 px ~ 0.4 mm was
# assumed so the vase is 200 mm tall. Each (radius, height) pair is half the
# silhouette width measured at that height in the reference image.
HEIGHT = 200
PROFILE = [
    (24, 0),      # foot
    (45, 37.5),
    (54, 75),     # widest belly
    (45, 112.5),
    (24, 150),    # shoulder meets neck
    (18, 170),
    (14.5, 190),  # narrowest neck
    (20, HEIGHT),  # flared lip
]
WALL = 2.5


def build_model():
    outline = PROFILE
    with BuildPart() as vase:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Line((0, 0), outline[0])
                Spline(*outline)
                Line(outline[-1], (0, HEIGHT))
                Line((0, HEIGHT), (0, 0))
            make_face()
        revolve(axis=Axis.Z)
        # Hollow the solid, leaving the top disc open as the mouth.
        offset(amount=-WALL, openings=vase.faces().sort_by(Axis.Z)[-1])
    return vase.part

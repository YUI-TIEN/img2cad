"""Helpers that model.py can import (`from img2cad_lib import ...`).

The CAD worker puts this directory on `sys.path`, so a model can use these
helpers directly. They cover the recurring steps of turning a front image
into CAD:

* `ImageFrame` registers image pixels to model millimetres: a front view by
  default (camera on -Y, image x -> +X, image y down -> -Z), or any camera
  direction for angled photos (`view=(x, y, z)`, the direction from the model
  toward the camera, plus `roll`). Assign one to the module-level name
  `IMAGE_FRAME` and the runner draws the CAD on the photo from that camera and
  scores each colour region against it. `project` and `on_plane_z` measure
  real positions from pixels in an angled photo.
* `revolved_profile` builds a smooth body of revolution from measured
  (radius, height) points.
* `segment` makes a tapered limb between two 3D points; `ball_joint` makes a
  joint sphere that fuses reliably onto it.
* `projected_decal` turns a traced outline (see scripts/trace_regions.py)
  into an exact, thin painted layer on a curved surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable, Sequence

from build123d import (Align, Axis, BuildLine, BuildPart, BuildSketch, Compound, Cone, Line, Location, Mode, Plane, Polygon, Pos, Rot,
                       Sphere, Spline, extrude, loft, make_face, offset, revolve)

Point2 = Sequence[float]
_SHELLS: dict = {}


def _shell(surface, thickness: float):
    """Offset shell over `surface`, cached because offsetting is the slow step."""
    key = (id(surface), thickness)
    if key not in _SHELLS:
        # offset() fails on any shape placed with Pos/moved (even a sphere) in
        # the pinned build123d, so offset it at the identity location and put
        # the result back where the surface is.
        placement = surface.location
        grown = offset(surface.located(Location()), amount=thickness).located(placement)
        _SHELLS[key] = (surface, grown.cut(surface))
    return _SHELLS[key][1]


@dataclass(frozen=True)
class ImageFrame:
    """Maps image pixels to model coordinates through an orthographic camera.

    `origin_px` is the image pixel where model point (0, 0, 0) appears (for
    example the centre of the subject at floor level) and `mm_per_px` the
    assumed or measured scale.

    `view` is the direction from the model toward the camera (Z up), the same
    convention as `--reference-view`: the default (0, -1, 0) is a front view;
    a photo taken from the front and 40 degrees above is about (0, -1, 0.84).
    `roll` turns the image clockwise by that many degrees (a tilted horizon).

    `distance` (mm from the model origin to the camera) turns on perspective:
    nearer parts image larger, as in a close-up photo. `mm_per_px` then holds
    at the origin's depth. Leave it None (orthographic) for drawings and
    distant shots; for a close photo, fit it together with the view to two
    known circles at different heights (see examples/espresso-cup).
    """

    mm_per_px: float
    origin_px: tuple[float, float]
    view: tuple[float, float, float] = (0.0, -1.0, 0.0)
    roll: float = 0.0
    distance: float | None = None

    def basis(self) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
        """(screen right, screen up, toward camera) as unit vectors in model space."""
        return camera_basis(self.view, self.roll)

    def scale_at(self, x: float, y: float, z: float) -> float:
        """Perspective magnification of a point relative to the origin's depth (1 when orthographic)."""
        if self.distance is None:
            return 1.0
        _, _, toward = self.basis()
        return self.distance / (self.distance - (x * toward[0] + y * toward[1] + z * toward[2]))

    def project(self, x: float, y: float, z: float) -> tuple[float, float]:
        """Model point -> image pixel."""
        right, up, _ = self.basis()
        factor = self.scale_at(x, y, z)
        a = (x * right[0] + y * right[1] + z * right[2]) * factor
        b = (x * up[0] + y * up[1] + z * up[2]) * factor
        return self.origin_px[0] + a / self.mm_per_px, self.origin_px[1] - b / self.mm_per_px

    def screen(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> (right, up) in mm on the image plane through the model origin."""
        return (px - self.origin_px[0]) * self.mm_per_px, (self.origin_px[1] - py) * self.mm_per_px

    def on_plane_z(self, px: float, py: float, z: float = 0.0) -> tuple[float, float, float]:
        """The model point at height `z` seen at image pixel (px, py) (for angled views)."""
        right, up, toward = self.basis()
        if abs(toward[2]) < 1e-9:
            raise ValueError("a horizontal camera sees every height along one pixel ray; use to_model for front views")
        a, b = self.screen(px, py)
        base = [a * right[i] + b * up[i] for i in range(3)]
        if self.distance is None:
            t = (z - base[2]) / toward[2]
            return base[0] + t * toward[0], base[1] + t * toward[1], z
        # Ray from the camera through the pixel's point on the origin's image plane.
        camera = [self.distance * value for value in toward]
        ray = [base[i] - camera[i] for i in range(3)]
        if abs(ray[2]) < 1e-12:
            raise ValueError("pixel ray is parallel to the plane")
        t = (z - camera[2]) / ray[2]
        return camera[0] + t * ray[0], camera[1] + t * ray[1], z

    def to_model(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> model (x, z), for front views."""
        return (px - self.origin_px[0]) * self.mm_per_px, (self.origin_px[1] - py) * self.mm_per_px

    def to_image(self, x: float, z: float) -> tuple[float, float]:
        """Model (x, z) -> image pixel, for front views."""
        return self.project(x, 0.0, z)

    def as_dict(self) -> dict:
        data = {"view": "front (camera on -Y)", "mm_per_px": self.mm_per_px, "origin_px": list(self.origin_px)}
        if tuple(self.view) != (0.0, -1.0, 0.0) or self.roll or self.distance is not None:
            right, up, toward = self.basis()
            data.update(view=f"camera toward {tuple(self.view)}, roll {self.roll:g}", view_direction=list(toward),
                        screen_right=list(right), screen_up=list(up))
        if self.distance is not None:
            data["camera_distance"] = self.distance
        return data


def camera_basis(view: Sequence[float], roll: float = 0.0):
    """Screen right, screen up and toward-camera unit vectors for an orthographic camera (Z up)."""
    from math import cos, radians, sin

    length = sqrt(sum(value * value for value in view))
    toward = [value / length for value in view]
    world_up = (0.0, 1.0, 0.0) if abs(toward[2]) > 0.98 else (0.0, 0.0, 1.0)
    right = _cross(world_up, toward)
    norm = sqrt(sum(value * value for value in right))
    right = [value / norm for value in right]
    up = _cross(toward, right)
    if roll:
        c, s = cos(radians(roll)), sin(radians(roll))
        right, up = [c * r - s * u for r, u in zip(right, up)], [s * r + c * u for r, u in zip(right, up)]
    return tuple(right), tuple(up), tuple(toward)


def _cross(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def revolved_profile(points: Sequence[Point2], seam_angle: float = 90):
    """Solid of revolution about Z through (radius, z) points.

    The first and last points should lie on the axis (radius 0); the spline
    meets the axis horizontally there, so the top and bottom are smooth. The
    revolve seam is turned by `seam_angle` degrees about Z (default: to the
    back, +Y) so parts fused on the front and sides do not land on it.
    """
    with BuildPart() as part:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Spline(*points, tangents=((1, 0), (-1, 0)))
                Line(points[-1], points[0])
            make_face()
        revolve(axis=Axis.Z)
    return Rot(0, 0, seam_angle) * part.part


def segment(start: Sequence[float], end: Sequence[float], start_radius: float, end_radius: float):
    """Tapered cone from point `start` to point `end` (limb, neck, tail, strut)."""
    direction = tuple(end[index] - start[index] for index in range(3))
    length = sqrt(sum(value * value for value in direction))
    return Plane(origin=tuple(start), z_dir=direction) * Cone(start_radius, end_radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))


def ball_joint(point: Sequence[float], radius: float):
    """Joint sphere with its poles along Y, so it fuses onto near-vertical or horizontal limbs."""
    return Pos(*point) * Rot(90, 0, 0) * Sphere(radius)


def outline_to_model(outline_px: Iterable[Point2], frame: ImageFrame) -> list[tuple[float, float]]:
    """Image pixels -> (right, up) mm on the frame's image plane (model (x, z) for a front view)."""
    return [frame.screen(px, py) for px, py in outline_px]


def projected_decal(surface, outline_px: Sequence[Point2], frame: ImageFrame, thickness: float = 2.0,
                    holes_px: Sequence[Sequence[Point2]] = ()):
    """A thin layer of `surface` inside a traced outline, seen from the frame's camera.

    The outline (image pixels, e.g. from trace_regions.py) is projected along
    the camera direction (along Y for a front view) onto the side of
    `surface` facing the camera; the result is the part of a `thickness` shell
    over the surface that falls inside it, so the paint follows the curvature
    exactly and touches the surface. `holes_px` are cut out (for example the
    highlight inside an eye); trace the hole as its own decal to fill it with
    another colour.
    """
    box = surface.bounding_box()
    right, _, toward = frame.basis()
    reach = 2 * (box.diagonal + thickness) + sqrt(box.center().X ** 2 + box.center().Y ** 2 + box.center().Z ** 2)
    shell = _shell(surface, thickness)
    outline = outline_to_model(outline_px, frame)
    holes = [outline_to_model(hole, frame) for hole in holes_px]

    def section(offset: float):
        """The outline as a face on the image plane `offset` mm toward the camera, scaled to follow the pixel rays."""
        factor = 1.0 if frame.distance is None else (frame.distance - offset) / frame.distance
        plane = Plane(origin=tuple(offset * value for value in toward), x_dir=right, z_dir=toward)
        face = Polygon(*[(a * factor, b * factor) for a, b in outline], align=None)
        for hole in holes:
            face -= Polygon(*[(a * factor, b * factor) for a, b in hole], align=None)
        return plane * face

    # Sketch planes: x along screen right, normal toward the camera, so their y is screen up.
    if frame.distance is None:
        prism = extrude(section(0.0), amount=reach, both=True)
    else:
        # Perspective: the pixel rays fan out from the camera, so the projector is a frustum.
        reach = min(reach, 0.95 * frame.distance)
        prism = loft([section(reach), section(-reach)])
    layer = prism.cut(prism.cut(shell))
    # The prism passes through the whole body; keep the side facing the camera.
    def facing(point) -> float:
        return point.X * toward[0] + point.Y * toward[1] + point.Z * toward[2]

    middle = facing(box.center())
    front = [solid for solid in layer.solids() if facing(solid.center()) > middle]
    if not front:
        raise ValueError("decal outline does not cover the camera side of the surface; check the frame and outline")
    return front[0] if len(front) == 1 else Compound(children=front)


_HULL_PLANES = {
    # view: (screen right, screen up, toward camera) -- the comparison panels' conventions, Z up
    "front": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "right": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    "top": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
}


def visual_hull(views: Sequence[dict]):
    """Intersection of silhouettes extruded through the model (a blockout).

    Each view is {"view": "front"|"right"|"top", "outline_mm": [[right, up], ...]}
    in that view's screen millimetres (see scripts/visual_hull.py). The result
    contains the object but fills every concavity no view sees.
    """
    if len(views) < 2:
        raise ValueError("a visual hull needs at least two views")
    reach = 4 * max(abs(value) for view in views for point in view["outline_mm"] for value in point) + 1
    hull = None
    for view in views:
        right, _, toward = _HULL_PLANES[view["view"]]
        plane = Plane(origin=(0, 0, 0), x_dir=right, z_dir=toward)
        prism = extrude(plane * Polygon(*[tuple(p) for p in view["outline_mm"]], align=None), amount=reach, both=True)
        hull = prism if hull is None else hull & prism
    solids = hull.solids()
    if not solids:
        raise ValueError("the silhouettes do not overlap; check each view's origin_px and mm_per_px")
    return max(solids, key=lambda solid: solid.volume) if len(solids) > 1 else solids[0]

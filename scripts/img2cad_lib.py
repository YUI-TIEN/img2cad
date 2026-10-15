"""Helpers that model.py can import (`from img2cad_lib import ...`).

The CAD worker puts this directory on `sys.path`, so a model can use these
helpers directly. They cover the recurring steps of turning a front image
into CAD:

* `ImageFrame` registers image pixels to model millimetres for a front view
  (camera on -Y, image x -> +X, image y down -> -Z). Assign one to the
  module-level name `IMAGE_FRAME` and the runner draws a registered overlay
  on the photo and scores each colour region against it.
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
                       Sphere, Spline, extrude, make_face, offset, revolve)

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
    """Maps front-view image pixels to model coordinates.

    `origin_px` is the image pixel that sits at model x = 0, z = 0 (for
    example the centre of the subject at floor level) and `mm_per_px` the
    assumed or measured scale.
    """

    mm_per_px: float
    origin_px: tuple[float, float]

    def to_model(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> model (x, z)."""
        return (px - self.origin_px[0]) * self.mm_per_px, (self.origin_px[1] - py) * self.mm_per_px

    def to_image(self, x: float, z: float) -> tuple[float, float]:
        """Model (x, z) -> image pixel."""
        return self.origin_px[0] + x / self.mm_per_px, self.origin_px[1] - z / self.mm_per_px

    def as_dict(self) -> dict:
        return {"view": "front (camera on -Y)", "mm_per_px": self.mm_per_px, "origin_px": list(self.origin_px)}


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
    return [frame.to_model(px, py) for px, py in outline_px]


def projected_decal(surface, outline_px: Sequence[Point2], frame: ImageFrame, thickness: float = 2.0,
                    holes_px: Sequence[Sequence[Point2]] = ()):
    """A thin layer of `surface` inside a traced front-view outline.

    The outline (image pixels, e.g. from trace_regions.py) is projected along
    Y onto the front of `surface`; the result is the part of a `thickness`
    shell over the surface that falls inside it, so the paint follows the
    curvature exactly and touches the surface. `holes_px` are cut out (for
    example the highlight inside an eye); trace the hole as its own decal to
    fill it with another colour.
    """
    box = surface.bounding_box()
    depth = 4 * (box.size.Y + thickness)
    shell = _shell(surface, thickness)
    with BuildPart() as prism:
        with BuildSketch(Plane.XZ):
            Polygon(*outline_to_model(outline_px, frame), align=None)
            for hole in holes_px:
                Polygon(*outline_to_model(hole, frame), align=None, mode=Mode.SUBTRACT)
        extrude(amount=depth, both=True)
    layer = prism.part.cut(prism.part.cut(shell))
    # The prism passes through the whole body; keep the front (-Y) side only.
    middle = box.center().Y
    front = [solid for solid in layer.solids() if solid.center().Y < middle]
    if not front:
        raise ValueError("decal outline does not cover the front of the surface; check the frame and outline")
    return front[0] if len(front) == 1 else Compound(children=front)

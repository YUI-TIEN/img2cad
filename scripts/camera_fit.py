#!/usr/bin/env python3
"""Fit a photo's camera (an IMAGE_FRAME) to features you know the 3D shape of.

    img2cad camera camera.json --out fit/          # writes fit.json, frame.py, overlay.png

Pick edge points on things whose real shape you know, then let the fit solve
the camera instead of guessing it:

* `circle`: points on a circular rim or edge (a cup rim, a wheel, a dish).
  Each of `center` [x, y], `z` and `radius` is either a number (known) or
  "fit" (solved). `center` may also name another circle to share its axis
  (a cup's rim and foot). `arc: "front"` uses only the near half (for a foot
  whose back is hidden), `arc: "back"` the far part (a liquid surface whose
  front is hidden behind a rim).
* `point`: one pixel whose model position `xyz` is known (a rocket's tip).

Unknown camera values: elevation, roll, scale, image origin, and (for
perspective) the camera distance. Azimuth is fixed at 0 (the camera looks
along +Y) unless `fit_azimuth` is true, because round things look the same
from every side and the model frame is defined by the camera. `fixed` holds
camera values you know instead of fitting them, e.g. {"roll": 0} for a level
camera or {"distance": 600} when you know it.

`priors` state assumptions the photo cannot settle, with their uncertainty:
{"cup rim.center_y": [0, 5]} means 0 ± 5 mm. They are reported with the fit,
and their uncertainty carries into it, so an assumption never reads as a
measurement.

`revolve_edge` features are not fitted: after the fit, each of their pixels
(on the left or right silhouette of a body of revolution around a fitted
circle's axis) is solved for the (radius, height) that images there. That is
how a profile is measured through the camera.

The fit refuses to give a frame (exit 1) when:

* the picked points are fitted poorly (RMS above `max_rms_px`, default 3 px),
  so the features or the projection are wrong; or
* a parameter is not pinned down: a size or distance with over 25 % relative
  uncertainty, a position or height with an uncertainty over 2 % of the
  scene, an angle over 3°, or a singular fit. More or different features are
  needed (typically one at another height).

It always writes `overlay.png`: the fitted curves over the photo, with the
picked points. Look at it; a low RMS on badly picked points is still wrong.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np

SAMPLES = 720
T = np.linspace(0.0, 2 * math.pi, SAMPLES, endpoint=False)


def camera_basis(elevation: float, azimuth: float, roll: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Screen right, screen up, toward-camera; the same convention as img2cad_lib.camera_basis."""
    e, a = math.radians(elevation), math.radians(azimuth)
    toward = np.array([math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)])
    world_up = np.array([0.0, 1.0, 0.0]) if abs(toward[2]) > 0.98 else np.array([0.0, 0.0, 1.0])
    right = np.cross(world_up, toward)
    right /= np.linalg.norm(right)
    up = np.cross(toward, right)
    if roll:
        c, s = math.cos(math.radians(roll)), math.sin(math.radians(roll))
        right, up = c * right - s * up, s * right + c * up
    return right, up, toward


class Camera:
    def __init__(self, elevation: float, azimuth: float, roll: float, mm_per_px: float, origin: tuple[float, float], distance: float | None):
        self.elevation, self.azimuth, self.roll = elevation, azimuth, roll
        self.mm_per_px, self.origin, self.distance = mm_per_px, origin, distance
        self.right, self.up, self.toward = camera_basis(elevation, azimuth, roll)

    def project(self, points: np.ndarray) -> np.ndarray:
        points = np.atleast_2d(points)
        factor = 1.0 if self.distance is None else self.distance / (self.distance - points @ self.toward)
        a = points @ self.right * factor
        b = points @ self.up * factor
        return np.stack([self.origin[0] + a / self.mm_per_px, self.origin[1] - b / self.mm_per_px], axis=1)

    def view(self) -> tuple[float, float, float]:
        return tuple(round(float(v), 6) for v in self.toward)


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    features = spec.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("spec needs a nonempty features list")
    names = set()
    for feature in features:
        if feature.get("type") not in ("circle", "point", "revolve_edge"):
            raise ValueError(f"feature {feature.get('name')!r}: type must be circle, point or revolve_edge")
        if not feature.get("name") or feature["name"] in names:
            raise ValueError("every feature needs a unique name")
        names.add(feature["name"])
    return spec


class Model:
    """Packs the unknowns into one vector and builds the residuals."""

    def __init__(self, spec: dict[str, Any], perspective: bool):
        self.spec = spec
        self.perspective = perspective
        self.fit_azimuth = bool(spec.get("fit_azimuth", False))
        self.circles = [f for f in spec["features"] if f["type"] == "circle"]
        self.points = [f for f in spec["features"] if f["type"] == "point"]
        self.fixed = dict(spec.get("fixed", {}))
        unknown = [name for name in ("elevation", "roll") if name not in self.fixed]
        self.names: list[str] = unknown + ["log_mm_per_px", "origin_x", "origin_y"]
        if self.fit_azimuth:
            self.names.append("azimuth")
        if perspective and "distance" not in self.fixed:
            self.names.append("log_distance")
        for circle in self.circles:
            centre = circle.get("center", "fit")
            if centre == "fit":
                self.names += [f"{circle['name']}.center_x", f"{circle['name']}.center_y"]
            for key in ("z", "radius"):
                if circle.get(key, "fit") == "fit":
                    self.names.append(f"{circle['name']}.{key}")
        self.index = {name: i for i, name in enumerate(self.names)}
        self.priors = {}
        for name, value in dict(self.spec.get("priors", {})).items():
            if name not in self.index:
                raise ValueError(f"prior {name!r} is not a fitted parameter ({', '.join(self.names)})")
            mean, sigma = float(value[0]), float(value[1])
            if sigma <= 0:
                raise ValueError(f"prior {name!r} needs a positive sigma")
            self.priors[name] = (mean, sigma)
        known_scale = any(isinstance(c.get("radius"), (int, float)) for c in self.circles) or len(self.points) >= 2
        if not known_scale:
            raise ValueError("no known size: give at least one circle a numeric radius, or two points with known xyz")

    def camera(self, v: np.ndarray) -> Camera:
        g = lambda name, default=0.0: v[self.index[name]] if name in self.index else float(self.fixed.get(name, default))  # noqa: E731
        distance = None
        if self.perspective:
            distance = float(self.fixed["distance"]) if "distance" in self.fixed else math.exp(g("log_distance"))
        return Camera(g("elevation"), g("azimuth"), g("roll"), math.exp(g("log_mm_per_px")), (g("origin_x"), g("origin_y")), distance)

    def circle_values(self, v: np.ndarray, circle: dict[str, Any], depth: int = 0) -> tuple[float, float, float, float]:
        centre = circle.get("center", "fit")
        if isinstance(centre, str) and centre != "fit":
            if depth > 3:
                raise ValueError("circular center references")
            other = next((c for c in self.circles if c["name"] == centre), None)
            if other is None:
                raise ValueError(f"circle {circle['name']!r}: center refers to unknown circle {centre!r}")
            cx, cy, _, _ = self.circle_values(v, other, depth + 1)
        elif centre == "fit":
            cx, cy = v[self.index[f"{circle['name']}.center_x"]], v[self.index[f"{circle['name']}.center_y"]]
        else:
            cx, cy = float(centre[0]), float(centre[1])
        z = v[self.index[f"{circle['name']}.z"]] if circle.get("z", "fit") == "fit" else float(circle["z"])
        r = v[self.index[f"{circle['name']}.radius"]] if circle.get("radius", "fit") == "fit" else float(circle["radius"])
        return cx, cy, z, r

    def circle_curve(self, v: np.ndarray, circle: dict[str, Any], camera: Camera | None = None) -> np.ndarray:
        camera = camera or self.camera(v)
        cx, cy, z, r = self.circle_values(v, circle)
        t = T
        if circle.get("arc") in ("front", "back"):
            # near (front) or far (back) part: toward / away from the camera's horizontal direction
            ty = camera.toward[:2] / max(1e-9, np.linalg.norm(camera.toward[:2]))
            facing = np.cos(T) * ty[0] + np.sin(T) * ty[1]
            t = T[facing > 0.3] if circle["arc"] == "front" else T[facing < 0.3]
        points = np.stack([cx + r * np.cos(t), cy + r * np.sin(t), np.full_like(t, z)], axis=1)
        return camera.project(points)

    def residuals(self, v: np.ndarray) -> np.ndarray:
        camera = self.camera(v)
        out = []
        for circle in self.circles:
            curve = self.circle_curve(v, circle, camera)
            picked = np.asarray(circle["points"], dtype=float)
            d = np.hypot(picked[:, None, 0] - curve[None, :, 0], picked[:, None, 1] - curve[None, :, 1])
            out.extend(d.min(axis=1))
        for point in self.points:
            p = camera.project(np.asarray([point["xyz"]], dtype=float))[0]
            out.extend([p[0] - point["pixel"][0], p[1] - point["pixel"][1]])
        # Priors: stated assumptions, weighted like a picked point (pick_error_px) per sigma.
        pick = float(self.spec.get("pick_error_px", 2.0))
        for name, (mean, sigma) in self.priors.items():
            value = v[self.index[name]]
            out.append((value - mean) / sigma * pick)
        return np.asarray(out, dtype=float)

    def initial(self, image_size: tuple[int, int]) -> np.ndarray:
        v = np.zeros(len(self.names))
        guess = self.spec.get("initial", {})
        if "elevation" in self.index:
            v[self.index["elevation"]] = guess.get("elevation", 45.0)
        if "roll" in self.index:
            v[self.index["roll"]] = guess.get("roll", 0.0)
        # scale: the widest picked circle with a known radius
        scale = guess.get("mm_per_px")
        for circle in self.circles:
            if scale is None and isinstance(circle.get("radius"), (int, float)) and len(circle["points"]) >= 2:
                xs = [p[0] for p in circle["points"]]
                scale = 2 * float(circle["radius"]) / max(1.0, max(xs) - min(xs))
        v[self.index["log_mm_per_px"]] = math.log(scale or 1.0)
        v[self.index["origin_x"]] = guess.get("origin_x", image_size[0] / 2)
        v[self.index["origin_y"]] = guess.get("origin_y", image_size[1] / 2)
        if "log_distance" in self.index:
            v[self.index["log_distance"]] = math.log(guess.get("distance", 20 * (scale or 1.0) * max(image_size)))
        for circle in self.circles:
            for key, value in (("z", 0.0), ("radius", (scale or 1.0) * 50)):
                name = f"{circle['name']}.{key}"
                if name in self.index:
                    v[self.index[name]] = guess.get(name, value)
            for key in ("center_x", "center_y"):
                name = f"{circle['name']}.{key}"
                if name in self.index:
                    v[self.index[name]] = guess.get(name, 0.0)
        return v


def fit(spec: dict[str, Any], perspective: bool, image_size: tuple[int, int]) -> dict[str, Any]:
    from scipy.optimize import least_squares

    model = Model(spec, perspective)
    v0 = model.initial(image_size)
    lower = np.full(len(v0), -np.inf)
    upper = np.full(len(v0), np.inf)
    if "log_distance" in model.index:
        # between half the scene and 1000 scenes away (beyond that the photo is orthographic)
        scene = math.exp(v0[model.index["log_mm_per_px"]]) * math.hypot(*image_size)
        lower[model.index["log_distance"]], upper[model.index["log_distance"]] = math.log(0.5 * scene), math.log(1000 * scene)
        v0[model.index["log_distance"]] = min(max(v0[model.index["log_distance"]], lower[model.index["log_distance"]] + 1e-6), upper[model.index["log_distance"]] - 1e-6)
    starts = [None]
    if "elevation" in model.index:
        lower[model.index["elevation"]], upper[model.index["elevation"]] = -89.0, 89.0
        # several starts: elevation is the parameter least-squares most easily gets stuck on
        starts = sorted({v0[model.index["elevation"]], 20.0, 45.0, 70.0})
    best = None
    for elevation in starts:
        start = v0.copy()
        if elevation is not None:
            start[model.index["elevation"]] = elevation
        result = least_squares(model.residuals, start, bounds=(lower, upper), x_scale="jac")
        if best is None or result.cost < best.cost:
            best = result
    residuals = best.fun[:len(best.fun) - len(model.priors)] if model.priors else best.fun
    dof = max(1, len(residuals) - len(best.x))
    sigma2 = max(float(residuals @ residuals) / dof, float(spec.get("pick_error_px", 2.0)) ** 2 / 4)
    jtj = best.jac.T @ best.jac
    try:
        covariance = np.linalg.inv(jtj) * sigma2
        std = np.sqrt(np.clip(np.diag(covariance), 0, None))
        singular = not np.all(np.isfinite(std)) or np.linalg.cond(jtj) > 1e12
    except np.linalg.LinAlgError:
        std, singular = np.full(len(best.x), np.inf), True
    return {"model": model, "x": best.x, "std": std, "singular": singular, "residuals": residuals,
            "rms": float(math.sqrt(float(np.mean(residuals ** 2)))), "max": float(np.max(np.abs(residuals))),
            "dof": int(dof)}


def describe(result: dict[str, Any], max_rms: float, max_relative: float, image_size: tuple[int, int], max_position: float = 0.02) -> dict[str, Any]:
    model, x, std = result["model"], result["x"], result["std"]
    camera = model.camera(x)
    values, problems = {}, []
    scene = camera.mm_per_px * math.hypot(*image_size)  # mm across the image diagonal
    for name, value, error in zip(model.names, x, std):
        if name.startswith("log_"):
            real, real_error = math.exp(value), math.exp(value) * error  # relative error carries over
            label = name[4:]
        else:
            real, real_error, label = float(value), float(error), name
        values[label] = {"value": round(real, 4), "std": round(real_error, 4)}
        scale = abs(real) if label in ("mm_per_px", "distance") or label.endswith(".radius") else None
        if scale and real_error > max_relative * scale:
            problems.append(f"{label} is not pinned down: {real:.3g} ± {real_error:.2g}")
        if label in ("elevation", "roll", "azimuth") and real_error > 3.0:
            problems.append(f"{label} is not pinned down: {real:.1f}° ± {real_error:.1f}°")
        if label.endswith((".center_x", ".center_y", ".z", ".radius")) and real_error > max_position * scene:
            problems.append(f"{label} is not pinned down: {real:.3g} ± {real_error:.2g} mm (limit {max_position * scene:.2g} mm, "
                            f"{max_position:.0%} of the scene); depth and height trade off along the pixel rays — add a feature at another height")
        if label in ("origin_x", "origin_y") and real_error > 0.01 * math.hypot(*image_size):
            problems.append(f"{label} is not pinned down: {real:.1f} ± {real_error:.1f} px")
    if result["singular"]:
        problems.append("the features cannot separate some parameters (singular fit); add a feature at another height or a known point")
    if result["rms"] > max_rms:
        problems.append(f"poor fit: RMS {result['rms']:.2f} px > {max_rms} px; re-pick points or check the feature types and known values")
    if model.perspective and "distance" in values and values["distance"]["value"] > 999 * scene:
        problems.append("camera distance ran to its limit: the photo is effectively orthographic")
    per_feature = {}
    offset = 0
    for feature in model.circles:
        n = len(feature["points"])
        per_feature[feature["name"]] = round(float(math.sqrt(np.mean(result["residuals"][offset:offset + n] ** 2))), 2)
        offset += n
    for feature in model.points:
        per_feature[feature["name"]] = round(float(np.hypot(*result["residuals"][offset:offset + 2])), 2)
        offset += 2
    frame = {"mm_per_px": round(camera.mm_per_px, 6), "origin_px": [round(camera.origin[0], 3), round(camera.origin[1], 3)],
             "view": list(camera.view()), "roll": round(camera.roll, 3), "distance": None if camera.distance is None else round(camera.distance, 2)}
    return {"projection": "perspective" if model.perspective else "orthographic", "rms_px": round(result["rms"], 3), "max_px": round(result["max"], 3),
            "per_feature_rms_px": per_feature, "frame": frame,
            "assumptions": {**{f"fixed {k}": v for k, v in model.fixed.items()}, **{f"prior {k}": f"{m} ± {sd}" for k, (m, sd) in model.priors.items()}}, "values": values, "problems": problems, "status": "ok" if not problems else "refused"}


def revolve_edges(result: dict[str, Any]) -> dict[str, list[dict[str, float]]]:
    """(radius, z) for each pixel on a revolve_edge feature's silhouette, through the fitted camera."""
    from scipy.optimize import least_squares

    model, x = result["model"], result["x"]
    camera = model.camera(x)
    out = {}
    for feature in model.spec["features"]:
        if feature["type"] != "revolve_edge":
            continue
        axis = next((c for c in model.circles if c["name"] == feature["axis"]), None)
        if axis is None:
            raise ValueError(f"revolve_edge {feature['name']!r}: axis must name a circle")
        cx, cy, _, _ = model.circle_values(x, axis)
        side = 1 if feature.get("side", "right") == "right" else -1
        rows = []
        for px, py in feature["points"]:
            def silhouette(rz: np.ndarray) -> np.ndarray:
                r, z = rz
                pts = np.stack([cx + r * np.cos(T), cy + r * np.sin(T), np.full_like(T, z)], axis=1)
                proj = camera.project(pts)
                k = np.argmax(side * proj[:, 0])
                return proj[k] - np.array([px, py])
            r0 = abs(px - camera.project(np.array([[cx, cy, 0.0]]))[0, 0]) * camera.mm_per_px
            solved = least_squares(silhouette, [max(r0, 1e-3), 0.0])
            rows.append({"px": px, "py": py, "radius": round(float(solved.x[0]), 3), "z": round(float(solved.x[1]), 3),
                         "error_px": round(float(np.hypot(*solved.fun)), 3)})
        out[feature["name"]] = rows
    return out


def draw_overlay(image_path: Path, result: dict[str, Any], output: Path) -> None:
    from PIL import Image, ImageDraw

    model, x = result["model"], result["x"]
    image = Image.open(image_path).convert("RGB")
    scale = max(1, round(1200 / max(image.size)))
    image = image.resize((image.width * scale, image.height * scale))
    draw = ImageDraw.Draw(image)
    camera = model.camera(x)
    for circle in model.circles:
        curve = model.circle_curve(x, circle, camera) * scale
        draw.line([tuple(p) for p in curve] + ([tuple(curve[0])] if circle.get("arc") not in ("front", "back") else []), fill=(40, 230, 90), width=2)
        for px, py in circle["points"]:
            draw.ellipse((px * scale - 4, py * scale - 4, px * scale + 4, py * scale + 4), outline=(255, 40, 40), width=2)
    for point in model.points:
        p = camera.project(np.asarray([point["xyz"]], dtype=float))[0] * scale
        draw.line((p[0] - 6, p[1], p[0] + 6, p[1]), fill=(40, 230, 90), width=2)
        draw.line((p[0], p[1] - 6, p[0], p[1] + 6), fill=(40, 230, 90), width=2)
        px, py = point["pixel"]
        draw.ellipse((px * scale - 4, py * scale - 4, px * scale + 4, py * scale + 4), outline=(255, 40, 40), width=2)
    image.save(output)


def frame_snippet(report: dict[str, Any]) -> str:
    frame = report["frame"]
    distance = "" if frame["distance"] is None else f", distance={frame['distance']}"
    return (f"# Fitted by `img2cad camera` ({report['projection']}, RMS {report['rms_px']} px)\n"
            f"IMAGE_FRAME = ImageFrame(mm_per_px={frame['mm_per_px']}, origin_px=({frame['origin_px'][0]}, {frame['origin_px'][1]}),\n"
            f"                         view={tuple(frame['view'])}, roll={frame['roll']}{distance})\n")


def run(spec_path: Path, out_dir: Path, projection: str | None = None) -> dict[str, Any]:
    from PIL import Image

    spec = load_spec(spec_path)
    image_path = (spec_path.parent / spec["image"]).resolve()
    size = Image.open(image_path).size
    projection = projection or spec.get("projection", "auto")
    max_rms = float(spec.get("max_rms_px", 3.0))
    max_relative = float(spec.get("max_relative_std", 0.25))
    candidates = {}
    for name in (["orthographic", "perspective"] if projection == "auto" else [projection]):
        result = fit(spec, name == "perspective", size)
        candidates[name] = (result, describe(result, max_rms, max_relative, size, float(spec.get("max_position_std", 0.02))))
    if projection == "auto":
        ortho, persp = candidates["orthographic"][1], candidates["perspective"][1]
        # perspective must earn its extra parameter: clearly lower error and a pinned-down distance
        use_perspective = persp["status"] == "ok" and persp["rms_px"] < 0.9 * ortho["rms_px"]
        chosen = "perspective" if use_perspective or ortho["status"] != "ok" and persp["status"] == "ok" else "orthographic"
    else:
        chosen = projection
    result, report = candidates[chosen]
    report["alternatives"] = {name: {"rms_px": item[1]["rms_px"], "status": item[1]["status"], "problems": item[1]["problems"]}
                              for name, item in candidates.items() if name != chosen}
    if report["status"] == "ok":
        report["revolve_edges"] = revolve_edges(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    draw_overlay(image_path, result, out_dir / "overlay.png")
    report["overlay"] = str(out_dir / "overlay.png")
    (out_dir / "fit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["status"] == "ok":
        (out_dir / "frame.py").write_text(frame_snippet(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="camera.json: image path (relative to it) and features")
    parser.add_argument("--out", type=Path, required=True, help="directory for fit.json, frame.py and overlay.png")
    parser.add_argument("--projection", choices=("auto", "orthographic", "perspective"), help="override the spec's projection")
    args = parser.parse_args()
    try:
        report = run(args.spec, args.out, args.projection)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    print(json.dumps({key: report[key] for key in ("status", "projection", "rms_px", "max_px", "per_feature_rms_px", "frame", "assumptions", "problems", "alternatives", "overlay")}, indent=2))
    if report["status"] == "ok":
        print(frame_snippet(report))
        return 0
    print("REFUSED: no frame written; fix the problems above (look at overlay.png)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

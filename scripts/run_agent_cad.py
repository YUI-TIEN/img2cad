#!/usr/bin/env python3
"""Build reviewed agent-authored build123d source and produce STEP + previews."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import numpy as np
from build123d import import_step
from PIL import Image, ImageDraw, ImageFont

from agent_cad_worker import parse_model_source
from cli_args import join_negative_option_values, parse_view
from inspect_step import color_rgba, inspect_step, leaf_parts
from mesh_export import export_meshes, parse_formats
from silhouette import compare as compare_silhouettes, reference_foreground


ROOT = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).with_name("agent_cad_worker.py")
MAX_TIMEOUT = 600
DEFAULT_PART_COLOR = (202, 156, 102)   # parts without a colour
PANEL_BACKGROUND = (226, 232, 238)     # light grey so white parts are visible
OUTLINE_COLOR = (60, 68, 80)
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_mesh(step_path: Path, tolerance: float) -> tuple[np.ndarray, np.ndarray, list[int], list[tuple[int, int, int]]]:
    """Tessellate every part of a STEP file: vertices, triangles, triangle->part, part colours."""
    shape = import_step(str(step_path))
    all_coords: list[tuple[float, float, float]] = []
    all_faces: list[tuple[int, int, int]] = []
    face_parts: list[int] = []
    part_colors: list[tuple[int, int, int]] = []
    for part in leaf_parts(shape):
        vertices, triangles = part.tessellate(tolerance, 0.12)
        if not vertices or not triangles:
            continue
        rgba = color_rgba(part)
        part_colors.append(tuple(int(round(channel * 255)) for channel in rgba[:3]) if rgba else DEFAULT_PART_COLOR)
        offset = len(all_coords)
        all_coords.extend((float(p.X), float(p.Y), float(p.Z)) for p in vertices)
        all_faces.extend((a + offset, b + offset, c + offset) for a, b, c in triangles)
        face_parts.extend([len(part_colors) - 1] * len(triangles))
    coords = np.array(all_coords, dtype=np.float64)
    faces = np.array(all_faces, dtype=np.int32)
    if not len(coords) or not len(faces):
        raise RuntimeError("STEP tessellation produced no preview mesh")
    return coords, faces, face_parts, part_colors


def rasterize(tx: np.ndarray, ty: np.ndarray, depth: np.ndarray, coords: np.ndarray, faces: np.ndarray, face_parts: list[int],
              part_colors: list[tuple[int, int, int]], light_vec: np.ndarray, width: int, height: int,
              background: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-buffered flat-shaded triangles; tx/ty are pixel coordinates, larger depth is nearer the camera."""
    zbuffer = np.full((height, width), -np.inf, dtype=np.float64)
    pixels = np.full((height, width, 3), background, dtype=np.uint8)
    part_ids = np.full((height, width), -1, dtype=np.int32)
    for face_index, face in enumerate(faces):
        ids = face.tolist()
        fx, fy = tx[ids], ty[ids]
        x0, x1 = max(0, int(fx.min())), min(width - 1, int(fx.max()))
        y0, y1 = max(0, int(fy.min())), min(height - 1, int(fy.max()))
        if x0 > x1 or y0 > y1:
            continue
        ax, ay = fx[0], fy[0]
        bx, by = fx[1], fy[1]
        cx, cy = fx[2], fy[2]
        denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denom) < 1e-8:
            continue
        grid_x, grid_y = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        w0 = ((by - cy) * (grid_x - cx) + (cx - bx) * (grid_y - cy)) / denom
        w1 = ((cy - ay) * (grid_x - cx) + (ax - cx) * (grid_y - cy)) / denom
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -0.001) & (w1 >= -0.001) & (w2 >= -0.001)
        depths = w0 * depth[ids[0]] + w1 * depth[ids[1]] + w2 * depth[ids[2]]
        region_z = zbuffer[y0:y1 + 1, x0:x1 + 1]
        visible = inside & (depths > region_z)
        if not np.any(visible):
            continue
        world = coords[ids]
        normal = np.cross(world[1] - world[0], world[2] - world[0])
        normal_len = float(np.linalg.norm(normal)) or 1.0
        brightness = 0.64 + 0.36 * abs(float(np.dot(normal / normal_len, light_vec)))
        part_id = face_parts[face_index]
        region_z[visible] = depths[visible]
        pixels[y0:y1 + 1, x0:x1 + 1][visible] = np.asarray([int(channel * brightness) for channel in part_colors[part_id]], dtype=np.uint8)
        part_ids[y0:y1 + 1, x0:x1 + 1][visible] = part_id
    return pixels, part_ids, zbuffer


def part_boundaries(part_ids: np.ndarray) -> np.ndarray:
    """Pixels on the silhouette or between two different parts."""
    height, width = part_ids.shape
    padded = np.pad(part_ids, 1, constant_values=-1)
    boundary = np.zeros(part_ids.shape, dtype=bool)
    for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
        boundary |= padded[dy:dy + height, dx:dx + width] != part_ids
    return boundary & (part_ids >= 0)


def camera_light(view_direction: np.ndarray, screen_up: np.ndarray, screen_right: np.ndarray) -> np.ndarray:
    # Key light from the camera side, slightly above and to the left, so every
    # view shows the faces it looks at.
    light = 0.75 * view_direction + 0.5 * screen_up - 0.3 * screen_right
    return light / np.linalg.norm(light)


def raster_preview(step_path: Path, output_path: Path, tolerance: float, reference_view: tuple[float, float, float] | None = None) -> dict[str, np.ndarray]:
    """Render four shaded orthographic panels in part colours and return each panel's silhouette mask."""
    coords, faces, face_parts, part_colors = load_mesh(step_path, tolerance)
    inv_sqrt2 = 1 / math.sqrt(2)
    inv_sqrt3 = 1 / math.sqrt(3)
    inv_sqrt6 = 1 / math.sqrt(6)
    views = [
        # (title, model-to-camera direction, screen right, screen up). Each is a
        # true camera view: the camera sits along the direction and looks back.
        ("Front · from -Y (X right, Z up)", (0, -1, 0), (1, 0, 0), (0, 0, 1)),
        ("Right · from +X (Y right, Z up)", (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ("Top · from +Z (X right, Y up)", (0, 0, 1), (1, 0, 0), (0, 1, 0)),
        ("Isometric · from +X -Y +Z", (inv_sqrt3, -inv_sqrt3, inv_sqrt3), (inv_sqrt2, inv_sqrt2, 0), (-inv_sqrt6, inv_sqrt6, 2 * inv_sqrt6)),
    ]
    if reference_view is not None:
        direction = np.asarray(reference_view, dtype=np.float64)
        direction /= np.linalg.norm(direction)
        world_up = np.array((0.0, 0.0, 1.0))
        if abs(float(np.dot(direction, world_up))) > 0.98:
            world_up = np.array((0.0, 1.0, 0.0))
        screen_right = np.cross(world_up, direction)
        screen_right /= np.linalg.norm(screen_right)
        screen_up = np.cross(direction, screen_right)
        label = ", ".join(f"{value:g}" for value in reference_view)
        views[-1] = (f"Reference view · from ({label})", tuple(direction), tuple(screen_right), tuple(screen_up))
    width, height = 1280, 900
    image = Image.new("RGB", (width, height), "#f3f6fa")
    draw = ImageDraw.Draw(image)
    font = load_font(19)
    title_font = load_font(25)
    masks: dict[str, np.ndarray] = {}
    draw.text((40, 24), "img2cad · STEP preview", fill="#18324b", font=title_font)

    for index, (title, direction, right, up) in enumerate(views):
        col, row = index % 2, index // 2
        left, top = 25 + col * 635, 75 + row * 405
        panel_w, panel_h = 610, 380
        draw.rounded_rectangle((left, top, left + panel_w, top + panel_h), radius=12, fill=PANEL_BACKGROUND, outline="#ccd7e2", width=2)
        draw.text((left + 18, top + 12), title, fill="#18324b", font=font)
        screen_right = np.asarray(right, dtype=np.float64)
        screen_up = np.asarray(up, dtype=np.float64)
        view_direction = np.asarray(direction, dtype=np.float64)
        projected_x = coords @ screen_right
        projected_y = coords @ screen_up
        projected_depth = coords @ view_direction
        min_x, max_x = float(projected_x.min()), float(projected_x.max())
        min_y, max_y = float(projected_y.min()), float(projected_y.max())
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        scale = min((panel_w - 70) / span_x, (panel_h - 70) / span_y)
        offset_x = left + (panel_w - span_x * scale) / 2 - min_x * scale
        offset_y = top + 40 + (panel_h - 45 - span_y * scale) / 2 + max_y * scale
        screen_x = np.rint(offset_x + projected_x * scale).astype(np.int32)
        screen_y = np.rint(offset_y - projected_y * scale).astype(np.int32)
        pixels, part_ids, zbuffer = rasterize(screen_x - left, screen_y - top, projected_depth, coords, faces, face_parts, part_colors,
                                              camera_light(view_direction, screen_up, screen_right), panel_w, panel_h, PANEL_BACKGROUND)
        # Dark outline on the silhouette and between parts, so white or
        # same-tone parts stay readable against the panel and each other.
        pixels[part_boundaries(part_ids)] = OUTLINE_COLOR
        masks[title] = np.isfinite(zbuffer)
        panel = Image.fromarray(pixels)
        image.paste(panel, (left, top))
        draw = ImageDraw.Draw(image)
        draw.text((left + 18, top + 12), title, fill="#18324b", font=font)
        draw.rectangle((left + 1, top + 1, left + panel_w - 1, top + panel_h - 1), outline="#ccd7e2", width=2)

    image.save(output_path, format="PNG", optimize=True)
    return masks


def shading_tolerant_features(rgb: np.ndarray) -> np.ndarray:
    """Luminance (down-weighted) plus two chroma axes, so shading changes the
    match less than a change of hue does (shaded white stays white, not pink)."""
    rgb = rgb.astype(np.float64)
    luminance = rgb.mean(axis=-1)
    return np.stack([0.5 * luminance, rgb[..., 0] - rgb[..., 1], rgb[..., 1] - rgb[..., 2]], axis=-1)


def nearest_palette(pixels: np.ndarray, palette: list[tuple[int, int, int]]) -> np.ndarray:
    centres = shading_tolerant_features(np.array(palette))
    features = shading_tolerant_features(pixels)
    return np.argmin(np.linalg.norm(features[:, :, None, :] - centres[None, None, :, :], axis=3), axis=2)


def registered_overlay(step_path: Path, reference: Path, frame: dict[str, Any], tolerance: float, output_path: Path,
                       mask_path: Path | None = None, auto_subject: bool = False) -> dict[str, Any]:
    """Render the front view in the reference image's own pixel frame and score it.

    `frame` (written by the model as IMAGE_FRAME) maps image pixels to model
    mm, so the CAD lands exactly where the model claims it is. The overlay
    shows the CAD outline and part boundaries on the photo next to a 50/50
    blend. Each part colour is scored by IoU against the photo pixels whose
    nearest model colour it is, inside the subject (the mask when given,
    otherwise the automatic segmentation when it is reliable, otherwise the
    CAD silhouette); `silhouette_iou` is unnormalised, so scale and position
    errors count.
    """
    photo = Image.open(reference).convert("RGB")
    width, height = photo.size
    scale = float(frame["mm_per_px"])
    origin_x, origin_y = (float(value) for value in frame["origin_px"])
    coords, faces, face_parts, part_colors = load_mesh(step_path, tolerance)
    tx = origin_x + coords[:, 0] / scale
    ty = origin_y - coords[:, 2] / scale
    depth = -coords[:, 1]  # camera on -Y: smaller y is nearer
    light = camera_light(np.array((0.0, -1.0, 0.0)), np.array((0.0, 0.0, 1.0)), np.array((1.0, 0.0, 0.0)))
    render, part_ids, _ = rasterize(tx, ty, depth, coords, faces, face_parts, part_colors, light, width, height, PANEL_BACKGROUND)
    cad_mask = part_ids >= 0
    photo_pixels = np.asarray(photo)
    subject = cad_mask
    result: dict[str, Any] = {"frame": frame, "advisory": True}
    subject_source = "CAD silhouette"
    if mask_path is not None:
        subject = np.asarray(Image.open(mask_path).convert("L").resize((width, height))) > 127
        subject_source = "reference mask"
    elif auto_subject:
        automatic = reference_foreground(reference)
        subject = np.asarray(Image.fromarray(automatic.astype(np.uint8) * 255).resize((width, height), Image.Resampling.NEAREST)) > 127
        # The segmentation runs on a downscaled copy, so its upscaled edge is
        # blocky; drop pixels that match the background (median border colour).
        border = np.concatenate([photo_pixels[0], photo_pixels[-1], photo_pixels[:, 0], photo_pixels[:, -1]])
        background = shading_tolerant_features(np.median(border, axis=0))
        subject &= np.linalg.norm(shading_tolerant_features(photo_pixels) - background, axis=-1) > 12
        subject_source = "automatic segmentation"
    result["subject"] = subject_source
    if subject_source != "CAD silhouette":
        union = np.logical_or(subject, cad_mask).sum()
        result["silhouette_iou"] = round(float(np.logical_and(subject, cad_mask).sum() / union), 4) if union else 0.0
    palette = sorted(set(part_colors))
    if len(palette) > 1:
        nearest = nearest_palette(photo_pixels, palette)
        part_palette = np.array([palette.index(color) for color in part_colors])
        cad_class = np.where(cad_mask, part_palette[np.maximum(part_ids, 0)], -1)
        regions = {}
        for index, color in enumerate(palette):
            photo_region = subject & (nearest == index)
            cad_region = cad_class == index
            union = np.logical_or(photo_region, cad_region).sum()
            regions["#%02x%02x%02x" % color] = {
                "iou": round(float(np.logical_and(photo_region, cad_region).sum() / union), 4) if union else None,
                "photo_px": int(photo_region.sum()), "cad_px": int(cad_region.sum()),
            }
        result["color_regions"] = regions
    edges = part_boundaries(part_ids)
    outlined = photo_pixels.copy()
    padded = np.pad(cad_mask, 1)
    interior = padded[2:, 1:-1] & padded[:-2, 1:-1] & padded[1:-1, 2:] & padded[1:-1, :-2]
    silhouette_edge = cad_mask & ~interior
    outlined[edges] = (255, 220, 0)
    outlined[silhouette_edge] = (230, 30, 30)
    blend = np.where(cad_mask[:, :, None], (photo_pixels.astype(np.uint16) + render) // 2, photo_pixels).astype(np.uint8)
    canvas = Image.new("RGB", (width * 2 + 30, height + 60), "#f3f6fa")
    draw = ImageDraw.Draw(canvas)
    font = load_font(max(14, width // 45))
    draw.text((10, 15), "Photo + CAD outline (red) and part edges (yellow)", fill="#18324b", font=font)
    draw.text((width + 20, 15), "Photo / CAD 50:50 blend", fill="#18324b", font=font)
    canvas.paste(Image.fromarray(outlined), (10, 50))
    canvas.paste(Image.fromarray(blend), (width + 20, 50))
    canvas.save(output_path, format="PNG", optimize=True)
    return result


def make_comparison(reference: Path, preview: Path, output_path: Path) -> None:
    """Place the reference and the CAD views side by side at the same height."""
    ref = Image.open(reference).convert("RGB")
    cad = Image.open(preview).convert("RGB")
    content_h, margin, header = 900, 24, 64
    cad = cad.resize((round(cad.width * content_h / cad.height), content_h), Image.Resampling.LANCZOS)
    ref_scale = min(content_h / ref.height, 1100 / ref.width)
    ref = ref.resize((max(1, round(ref.width * ref_scale)), max(1, round(ref.height * ref_scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (margin * 3 + ref.width + cad.width, header + content_h + margin), "#f3f6fa")
    draw = ImageDraw.Draw(canvas)
    font = load_font(26)
    draw.text((margin, 18), "Reference image", fill="#18324b", font=font)
    draw.text((margin * 2 + ref.width, 18), "Generated CAD views (not camera-aligned)", fill="#18324b", font=font)
    canvas.paste(ref, (margin, header + (content_h - ref.height) // 2))
    canvas.paste(cad, (margin * 2 + ref.width, header))
    canvas.save(output_path, format="PNG", optimize=True)


def check_part_structure(inspection: dict[str, Any]) -> None:
    """Each part must be one solid, and in an assembly every part must touch another.

    A part that splits into several solids is a floating piece or a fuse that
    silently failed; a part touching nothing else is floating in the assembly.
    """
    parts = inspection["parts"]
    if len(parts) == 1 and inspection["solid_count"] > 1:
        details = "; ".join(f"solid {index + 1}: volume {item['volume']:.1f}, center {item['center']}, size {item['size']}" for index, item in enumerate(inspection["solids"]))
        raise RuntimeError(
            f"model has {inspection['solid_count']} disjoint solids, expected 1. Either parts do not touch/overlap "
            f"(a floating part) or a boolean fuse silently failed. Make parts overlap and fuse them, return a coloured "
            f"assembly (Compound(children=[...])) if the pieces are meant to stay separate, or declare "
            f"\"allow_multiple_solids\": true in the plan. {details}")
    split = [part for part in parts if part["solid_count"] != 1]
    if split:
        details = "; ".join(f"part '{part['label']}' has {part['solid_count']} solids (center {part['center']}, size {part['size']})" for part in split)
        raise RuntimeError(f"each assembly part must be one solid: {details}. A fuse inside that part failed or a piece floats; "
                           f"fix it, or declare \"allow_multiple_solids\": true in the plan.")
    if inspection.get("isolated_parts"):
        raise RuntimeError(f"assembly parts touch no other part (floating): {', '.join(inspection['isolated_parts'])}. "
                           f"Move them onto or into the body, or declare \"allow_multiple_solids\": true in the plan.")


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_path = args.model_source.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if args.timeout < 1 or args.timeout > MAX_TIMEOUT:
        raise ValueError(f"--timeout must be between 1 and {MAX_TIMEOUT} seconds")
    source = source_path.read_text(encoding="utf-8")
    parse_model_source(source, str(source_path), args.strict)

    run_dir = args.run_dir.expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    cad_python = Path(args.cad_python).expanduser()
    if not cad_python.is_absolute():
        cad_python = Path.cwd() / cad_python if (Path.cwd() / cad_python).exists() else ROOT / cad_python
    # Preserve venv symlinks: resolving to the base interpreter would bypass
    # pyvenv.cfg and make installed CAD packages appear missing under -I.
    cad_python = Path(os.path.abspath(cad_python))
    if not cad_python.is_file():
        raise FileNotFoundError(f"CAD interpreter not found: {cad_python}")
    local_source = run_dir / "model.py"
    shutil.copyfile(source_path, local_source)
    worker_result = subprocess.run(
        [str(cad_python), "-I", str(WORKER), str(local_source), str(run_dir), *(["--strict"] if args.strict else [])],
        cwd=run_dir,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=args.timeout,
        check=False,
    )
    (run_dir / "worker.stdout.log").write_text(worker_result.stdout, encoding="utf-8")
    (run_dir / "worker.stderr.log").write_text(worker_result.stderr, encoding="utf-8")
    if worker_result.returncode:
        raise RuntimeError(f"CAD worker exited {worker_result.returncode}: {worker_result.stderr[-2500:] or worker_result.stdout[-2500:]}")

    step_path = run_dir / "model.step"
    inspection = inspect_step(step_path)
    (run_dir / "inspection.json").write_text(json.dumps(inspection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if inspection["status"] != "passed":
        raise RuntimeError("STEP inspection failed: B-rep invalid or no positive-volume solid")
    if not args.allow_multiple_solids:
        check_part_structure(inspection)
    meshes = export_meshes(step_path, run_dir, args.mesh_formats) if args.mesh_formats else {}
    preview_path = run_dir / "preview.png"
    view_masks = raster_preview(step_path, preview_path, args.mesh_tolerance, args.reference_view)

    reference_path = args.reference.expanduser().resolve() if args.reference else None
    if reference_path:
        if not reference_path.is_file():
            raise FileNotFoundError(reference_path)
        extension = reference_path.suffix.lower()
        if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("--reference must be a PNG, JPEG, or WebP image")
        local_reference = run_dir / f"reference{extension}"
        shutil.copyfile(reference_path, local_reference)
        comparison_path = run_dir / "comparison.png"
        make_comparison(local_reference, preview_path, comparison_path)
        silhouette_path = run_dir / "silhouette.png"
        local_mask = None
        if args.reference_mask:
            mask_source = args.reference_mask.expanduser().resolve()
            if not mask_source.is_file():
                raise FileNotFoundError(mask_source)
            local_mask = run_dir / "reference_mask.png"
            shutil.copyfile(mask_source, local_mask)
        silhouette = compare_silhouettes(local_reference, view_masks, silhouette_path, local_mask)
        frame_path = run_dir / "frame.json"
        registered = None
        if frame_path.is_file():
            registered = registered_overlay(step_path, local_reference, json.loads(frame_path.read_text(encoding="utf-8")),
                                            args.mesh_tolerance, run_dir / "registered.png", local_mask,
                                            auto_subject=bool(silhouette and silhouette.get("reliable")))
    else:
        local_reference = None
        comparison_path = None
        silhouette = None

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "passed",
        "status_scope": "geometry_and_step_only",
        "visual_review": "not_reviewed",
        "reference_view": {"direction": args.reference_view, "alignment": "manual_approximation"} if args.reference_view else None,
        "model_source": {"path": local_source.name, "sha256": sha256(local_source)},
        "step": {"path": step_path.name, "sha256": sha256(step_path)},
        "preview": {"path": preview_path.name, "sha256": sha256(preview_path)},
        "inspection": inspection,
        **{name: {"path": path.name, "sha256": sha256(path)} for name, path in meshes.items()},
        "source_policy": ("allowlisted build123d/Python subset (strict)" if args.strict else "unrestricted Python (open)") + "; isolated subprocess with timeout; not an OS sandbox",
        "execution": {"interpreter": str(cad_python), "timeout_seconds": args.timeout},
    }
    if local_reference and comparison_path:
        report["reference"] = {"path": local_reference.name, "sha256": sha256(local_reference)}
        report["comparison"] = {"path": comparison_path.name, "sha256": sha256(comparison_path)}
        report["silhouette"] = silhouette
        if registered is not None:
            report["registered"] = registered
            report["registered_overlay"] = {"path": "registered.png", "sha256": sha256(run_dir / "registered.png")}
        if local_mask is not None:
            report["reference_mask"] = {"path": local_mask.name, "sha256": sha256(local_mask)}
        if silhouette_path.is_file():
            report["silhouette_overlay"] = {"path": silhouette_path.name, "sha256": sha256(silhouette_path)}
    report_path = run_dir / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_source", type=Path, help="reviewed Python source defining build_model()")
    parser.add_argument("run_dir", type=Path, help="new output directory; must not already exist")
    parser.add_argument("--reference", type=Path, help="optional local reference image for a side-by-side comparison")
    parser.add_argument("--cad-python", default=sys.executable, help="Python interpreter with build123d and Pillow installed")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--mesh-tolerance", type=float, default=0.45)
    parser.add_argument("--reference-view", type=parse_view, help="direction from the model toward the camera as x,y,z (Z up); replaces the isometric panel")
    parser.add_argument("--reference-mask", type=Path, help="optional PNG mask of the object in the reference image (white = object), same size as the reference")
    parser.add_argument("--allow-multiple-solids", action="store_true", help="accept parts made of several solids and floating parts")
    parser.add_argument("--mesh-formats", type=parse_formats, default=("glb", "stl", "3mf"),
                        help="meshes to export next to model.step: any of glb,stl,3mf, or none (default: all)")
    parser.add_argument("--strict", action="store_true", help="apply the allowlist source policy (for untrusted model source)")
    args = parser.parse_args(join_negative_option_values(sys.argv[1:], ("--reference-view",)))
    try:
        if not math.isfinite(args.mesh_tolerance) or args.mesh_tolerance <= 0:
            raise ValueError("--mesh-tolerance must be positive")
        report = run(args)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

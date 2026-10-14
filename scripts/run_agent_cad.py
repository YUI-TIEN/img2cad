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
from inspect_step import inspect_step


ROOT = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).with_name("agent_cad_worker.py")
MAX_TIMEOUT = 600


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def raster_preview(step_path: Path, output_path: Path, tolerance: float) -> None:
    shape = import_step(str(step_path))
    vertices, triangles = shape.tessellate(tolerance, 0.12)
    coords = np.array([(float(p.X), float(p.Y), float(p.Z)) for p in vertices], dtype=np.float64)
    faces = np.array(triangles, dtype=np.int32)
    if not len(coords) or not len(faces):
        raise RuntimeError("STEP tessellation produced no preview mesh")

    inv_sqrt2 = 1 / math.sqrt(2)
    inv_sqrt3 = 1 / math.sqrt(3)
    inv_sqrt6 = 1 / math.sqrt(6)
    views = [
        ("Side · X/Z", (0, 1, 0), (1, 0, 0), (0, 0, 1)),
        ("Front · Y/Z", (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        ("Top · X/Y", (0, 0, 1), (1, 0, 0), (0, 1, 0)),
        ("Isometric", (inv_sqrt3, -inv_sqrt3, inv_sqrt3), (inv_sqrt2, inv_sqrt2, 0), (-inv_sqrt6, inv_sqrt6, 2 * inv_sqrt6)),
    ]
    width, height = 1280, 900
    image = Image.new("RGB", (width, height), "#f3f6fa")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 19)
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 25)
    except OSError:
        font = ImageFont.load_default()
        title_font = font
    draw.text((40, 24), "img2cad · STEP preview", fill="#18324b", font=title_font)
    light = (0.42, 0.58, 0.70)
    light_len = math.sqrt(sum(value * value for value in light))
    light = tuple(value / light_len for value in light)
    base = (202, 156, 102)

    for index, (title, direction, right, up) in enumerate(views):
        col, row = index % 2, index // 2
        left, top = 25 + col * 635, 75 + row * 405
        panel_w, panel_h = 610, 380
        draw.rounded_rectangle((left, top, left + panel_w, top + panel_h), radius=12, fill="white", outline="#ccd7e2", width=2)
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
        zbuffer = np.full((panel_h, panel_w), -np.inf, dtype=np.float64)
        pixels = np.full((panel_h, panel_w, 3), (255, 255, 255), dtype=np.uint8)
        light_vec = np.asarray(light, dtype=np.float64)
        for face in faces:
            ids = face.tolist()
            tri_x = screen_x[ids]
            tri_y = screen_y[ids]
            # Screen-space coordinates are converted to panel-local values.
            tx = tri_x - left
            ty = tri_y - top
            x0, x1 = max(0, int(tx.min())), min(panel_w - 1, int(tx.max()))
            y0, y1 = max(0, int(ty.min())), min(panel_h - 1, int(ty.max()))
            if x0 > x1 or y0 > y1:
                continue
            ax, ay = tx[0], ty[0]
            bx, by = tx[1], ty[1]
            cx, cy = tx[2], ty[2]
            denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(denom) < 1e-8:
                continue
            grid_x, grid_y = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
            w0 = ((by - cy) * (grid_x - cx) + (cx - bx) * (grid_y - cy)) / denom
            w1 = ((cy - ay) * (grid_x - cx) + (ax - cx) * (grid_y - cy)) / denom
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -0.001) & (w1 >= -0.001) & (w2 >= -0.001)
            depths = w0 * projected_depth[ids[0]] + w1 * projected_depth[ids[1]] + w2 * projected_depth[ids[2]]
            region_z = zbuffer[y0:y1 + 1, x0:x1 + 1]
            visible = inside & (depths > region_z)
            if not np.any(visible):
                continue
            world = coords[ids]
            normal = np.cross(world[1] - world[0], world[2] - world[0])
            normal_len = float(np.linalg.norm(normal)) or 1.0
            diffuse = max(0.0, float(np.dot(normal / normal_len, light_vec)))
            brightness = 0.64 + 0.36 * diffuse
            color = np.asarray([int(channel * brightness) for channel in base], dtype=np.uint8)
            region_z[visible] = depths[visible]
            pixels[y0:y1 + 1, x0:x1 + 1][visible] = color
        panel = Image.fromarray(pixels)
        image.paste(panel, (left, top))
        draw = ImageDraw.Draw(image)
        draw.text((left + 18, top + 12), title, fill="#18324b", font=font)
        draw.rectangle((left + 1, top + 1, left + panel_w - 1, top + panel_h - 1), outline="#ccd7e2", width=2)

    image.save(output_path, format="PNG", optimize=True)


def make_comparison(reference: Path, preview: Path, output_path: Path) -> None:
    ref = Image.open(reference).convert("RGB")
    cad = Image.open(preview).convert("RGB")
    panel_w, panel_h = 720, 800
    canvas = Image.new("RGB", (panel_w * 2, panel_h + 80), "#f3f6fa")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((28, 24), "Reference image", fill="#18324b", font=font)
    draw.text((panel_w + 28, 24), "Generated CAD views", fill="#18324b", font=font)
    ref.thumbnail((panel_w - 36, panel_h - 30), Image.Resampling.LANCZOS)
    cad.thumbnail((panel_w - 36, panel_h - 30), Image.Resampling.LANCZOS)
    canvas.paste(ref, (18 + (panel_w - 36 - ref.width) // 2, 70 + (panel_h - 30 - ref.height) // 2))
    canvas.paste(cad, (panel_w + 18, 70))
    canvas.save(output_path, format="PNG", optimize=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_path = args.model_source.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if args.timeout < 1 or args.timeout > MAX_TIMEOUT:
        raise ValueError(f"--timeout must be between 1 and {MAX_TIMEOUT} seconds")
    source = source_path.read_text(encoding="utf-8")
    parse_model_source(source, str(source_path))

    run_dir = args.run_dir.expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    cad_python = Path(args.cad_python).expanduser()
    if not cad_python.is_absolute():
        cad_python = ROOT / cad_python
    # Preserve venv symlinks: resolving to the base interpreter would bypass
    # pyvenv.cfg and make installed CAD packages appear missing under -I.
    cad_python = Path(os.path.abspath(cad_python))
    if not cad_python.is_file():
        raise FileNotFoundError(f"CAD interpreter not found: {cad_python}")
    local_source = run_dir / "model.py"
    shutil.copyfile(source_path, local_source)
    worker_result = subprocess.run(
        [str(cad_python), "-I", str(WORKER), str(local_source), str(run_dir)],
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
    if inspection["status"] != "passed":
        raise RuntimeError("STEP inspection failed: B-rep invalid or no positive-volume solid")
    preview_path = run_dir / "preview.png"
    raster_preview(step_path, preview_path, args.mesh_tolerance)

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
    else:
        local_reference = None
        comparison_path = None

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "passed",
        "model_source": {"path": local_source.name, "sha256": sha256(local_source)},
        "step": {"path": step_path.name, "sha256": sha256(step_path)},
        "preview": {"path": preview_path.name, "sha256": sha256(preview_path)},
        "inspection": inspection,
        "source_policy": "restricted Python AST and allowlisted build123d API; subprocess timeout; not an OS sandbox",
        "execution": {"interpreter": str(cad_python), "timeout_seconds": args.timeout},
    }
    if local_reference and comparison_path:
        report["reference"] = {"path": local_reference.name, "sha256": sha256(local_reference)}
        report["comparison"] = {"path": comparison_path.name, "sha256": sha256(comparison_path)}
    report_path = run_dir / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_source", type=Path, help="reviewed Python source defining build_model()")
    parser.add_argument("run_dir", type=Path, help="new output directory; must not already exist")
    parser.add_argument("--reference", type=Path, help="optional local reference image for a side-by-side comparison")
    parser.add_argument("--cad-python", default=sys.executable, help="Python interpreter with build123d and Pillow installed")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--mesh-tolerance", type=float, default=0.45)
    args = parser.parse_args()
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

#!/usr/bin/env python3
"""img2cad: turn images into editable, coloured CAD with an agent-friendly workflow.

One command for every tool in this repository. Each subcommand runs the
matching script with the remaining arguments; `img2cad <command> --help`
shows its options.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent

COMMANDS = {
    "workflow": ("agent_workflow.py", "staged, resumable image -> CAD workflow (init, observations, plan, preview, source-review, run, review, new-revision, promote, status)"),
    "build": ("run_agent_cad.py", "build one model.py: STEP + GLB/STL/3MF, checks, previews, comparison and registered overlay"),
    "camera": ("camera_fit.py", "fit the photo's camera (IMAGE_FRAME) to known circles/points; refuses when the fit is poor or under-constrained"),
    "mask": ("make_mask.py", "make a subject mask from polygons, ellipses and colour seeds"),
    "trace": ("trace_regions.py", "trace colour regions of a reference image into pixel outlines"),
    "inspect": ("inspect_step.py", "measure a STEP file: validity, solids, parts and colours, bounds, volume, holes/bosses"),
    "export": ("mesh_export.py", "export a STEP file to GLB, STL and 3MF"),
    "review": ("record_visual_review.py", "bind visual review notes to one CAD run"),
    "view": ("viewer.py", "3D viewer; open a model.py to edit its parameters live (no AI round trip), or STEP/GLB/STL/3MF files"),
    "params": ("model_params.py", "list or set a model.py's parameters (module-level UPPERCASE numbers)"),
    "mcp": ("mcp_server.py", "run the img2cad MCP server (stdio) for agent hosts"),
    "drawing": ("drawing.py", "engineering drawing (SVG + DXF) with three views and overall dimensions from a STEP file"),
    "printcheck": ("printcheck.py", "3D-printability check of a STEP/STL: watertight, overhangs, thin features, build volume"),
}


def version() -> str:
    # A clone's VERSION file wins: stale build metadata (an egg-info) can otherwise shadow it.
    version_file = SCRIPTS.parent / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    try:
        return importlib.metadata.version("img2cad")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def doctor() -> int:
    """Check that this interpreter can build CAD and render previews."""
    checks = []

    def check(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, **({"fix": fix} if fix and not ok else {})})

    check("python", sys.version_info >= (3, 10), f"{platform.python_version()} at {sys.executable}", "use Python 3.10 or newer")
    for module, fix in (("build123d", "pip install build123d==0.13.0 (or the repository's requirements-cad.lock)"),
                        ("OCP", "install cadquery-ocp (pulled in by build123d); on Windows 11 Smart App Control can block it"),
                        ("numpy", "pip install numpy"), ("scipy", "pip install scipy"), ("PIL", "pip install pillow")):
        try:
            imported = __import__(module)
            check(module, True, getattr(imported, "__version__", "imported"))
        except Exception as error:  # noqa: BLE001 - report any import failure
            check(module, False, f"{type(error).__name__}: {error}", fix)
    try:
        from build123d import Box, export_step, import_step
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "probe.step"
            export_step(Box(1, 2, 3), str(path))
            size = import_step(str(path)).bounding_box().size
        check("kernel round trip", abs(size.Z - 3) < 1e-6, "Box(1, 2, 3) -> STEP -> re-import")
    except Exception as error:  # noqa: BLE001
        check("kernel round trip", False, f"{type(error).__name__}: {error}", "fix the build123d/OCP installation above")
    fonts = [path for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf") if Path(path).is_file()]
    check("preview font", True, fonts[0] if fonts else "none found; previews use Pillow's default font")
    check("img2cad", True, f"{version()} from {SCRIPTS}")
    ok = all(item["ok"] for item in checks)
    print(json.dumps({"ok": ok, "checks": checks}, indent=2))
    return 0 if ok else 1


def usage() -> str:
    width = max(len(name) for name in COMMANDS)
    lines = [__doc__.strip(), "", "usage: img2cad <command> [args]", "", "commands:"]
    lines += [f"  {name.ljust(width)}  {help_text}" for name, (_, help_text) in COMMANDS.items()]
    lines += [f"  {'doctor'.ljust(width)}  check that this environment can build CAD and render previews",
              f"  {'version'.ljust(width)}  print the img2cad version"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    command, rest = argv[0], argv[1:]
    if command == "doctor":
        return doctor()
    if command in ("version", "--version"):
        print(version())
        return 0
    if command not in COMMANDS:
        print(f"img2cad: unknown command {command!r}\n\n{usage()}", file=sys.stderr)
        return 2
    script = SCRIPTS / COMMANDS[command][0]
    if not script.is_file():
        print(f"img2cad: {command} is not available in this installation ({script.name} missing)", file=sys.stderr)
        return 2
    # Run the script as __main__ in this interpreter, with its own directory
    # first on sys.path so its sibling imports resolve.
    sys.argv = [f"img2cad {command}", *rest]
    sys.path.insert(0, str(SCRIPTS))
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exit_:
        code = exit_.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Slice a model to G-code (or a sliced 3MF) with an installed slicer.

    img2cad slice model.3mf --out model.gcode                        # first slicer found on PATH
    img2cad slice model.stl --out part.gcode --config my_printer.ini  # PrusaSlicer / SuperSlicer profile
    img2cad slice model.3mf --out plate.3mf --slicer orca --settings machine.json,process.json,filament.json

Supported slicers (command-line mode): PrusaSlicer, SuperSlicer, OrcaSlicer
and Bambu Studio. `--slicer-path` points at the executable when it is not on
PATH. Profiles are the slicer's own: an exported .ini for Prusa/SuperSlicer,
machine/process/filament .json files for Orca/Bambu Studio. Without a
profile the slicer's defaults apply, which rarely match your printer.

Printing is the last step and stays with you: send the G-code from your
slicer or printer app (Bambu Studio / Handy, OctoPrint, PrusaLink, an SD
card). Open model.3mf directly in Bambu Studio or OrcaSlicer to check the
plate before printing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

SLICERS = {
    "prusa": ("prusa-slicer", "PrusaSlicer", "prusaslicer"),
    "superslicer": ("superslicer", "SuperSlicer"),
    "orca": ("orca-slicer", "OrcaSlicer", "orcaslicer"),
    "bambu": ("bambu-studio", "BambuStudio", "bambustudio"),
}


def find_slicer(kind: str | None = None, path: str | None = None) -> tuple[str, str]:
    """(kind, executable) of the requested or first available slicer."""
    if path:
        name = Path(path).name.lower()
        guess = kind or next((k for k, names in SLICERS.items() if any(n.lower().replace("-", "") in name.replace("-", "") for n in names)), "prusa")
        return guess, path
    for candidate in ([kind] if kind else list(SLICERS)):
        for name in SLICERS[candidate]:
            found = shutil.which(name)
            if found:
                return candidate, found
    wanted = kind or "PrusaSlicer, SuperSlicer, OrcaSlicer or Bambu Studio"
    raise FileNotFoundError(f"no slicer found ({wanted}); install one or pass --slicer-path")


def command(kind: str, executable: str, model: Path, out: Path, config: Path | None, settings: str | None) -> list[str]:
    if kind in ("prusa", "superslicer"):
        args = [executable, "--export-gcode", "--output", str(out)]
        if config:
            args += ["--load", str(config)]
        return args + [str(model)]
    # OrcaSlicer and Bambu Studio share a command line
    args = [executable, "--slice", "0", "--arrange", "1", "--orient", "1"]
    if settings:
        machine, *rest = settings.split(",")
        args += ["--load-settings", ";".join([machine] + rest[:1])]
        if rest[1:]:
            args += ["--load-filaments", ";".join(rest[1:])]
    if out.suffix.lower() == ".3mf":
        args += ["--export-3mf", str(out)]
    else:
        args += ["--outputdir", str(out.parent)]
    return args + [str(model)]


def slice_model(model: Path, out: Path, slicer: str | None = None, slicer_path: str | None = None, config: Path | None = None,
                settings: str | None = None, timeout_s: float = 900) -> dict[str, Any]:
    kind, executable = find_slicer(slicer, slicer_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    args = command(kind, executable, model, out, config, settings)
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)
    produced = out if out.exists() else next(iter(sorted(out.parent.glob("*.gcode"), key=lambda p: p.stat().st_mtime, reverse=True)), None)
    report = {"slicer": kind, "executable": executable, "command": args, "returncode": result.returncode,
              "output": str(produced) if produced else None, "log_tail": (result.stdout + result.stderr)[-2000:]}
    if result.returncode != 0 or produced is None:
        raise RuntimeError(f"{kind} failed (exit {result.returncode}): {report['log_tail'][-600:]}")
    if produced.suffix.lower() == ".gcode":
        report.update(gcode_summary(produced))
    return report


def gcode_summary(path: Path) -> dict[str, Any]:
    """Estimated time and filament from the comments slicers write."""
    summary: dict[str, Any] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            low = line.lower()
            if "estimated printing time" in low and "=" in line:
                summary.setdefault("estimated_time", line.split("=", 1)[1].strip())
            elif ("filament used [g]" in low or "total filament weight [g]" in low) and "=" in line:
                summary.setdefault("filament_g", line.split("=", 1)[1].strip())
            elif "filament used [mm]" in low and "=" in line:
                summary.setdefault("filament_mm", line.split("=", 1)[1].strip())
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", type=Path, help="STL or 3MF (img2cad build writes both)")
    parser.add_argument("--out", type=Path, required=True, help=".gcode, or .3mf for a sliced project (Orca/Bambu)")
    parser.add_argument("--slicer", choices=list(SLICERS), help="which slicer (default: the first one found)")
    parser.add_argument("--slicer-path", help="slicer executable when it is not on PATH")
    parser.add_argument("--config", type=Path, help="PrusaSlicer/SuperSlicer .ini profile")
    parser.add_argument("--settings", help="Orca/Bambu: machine.json,process.json[,filament.json...]")
    args = parser.parse_args()
    try:
        report = slice_model(args.model, args.out, args.slicer, args.slicer_path, args.config, args.settings)
    except (FileNotFoundError, RuntimeError) as error:
        parser.exit(2, f"FAIL: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

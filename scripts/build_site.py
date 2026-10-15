#!/usr/bin/env python3
"""Build the img2cad website (GitHub Pages) from site/ and examples/.

    .venv-cad/bin/python scripts/build_site.py --out _site
    python3 -m http.server -d _site 8000

Every example's `model.py` is rebuilt with the CAD runner, so the 3D models on
the site always come from the committed source: GLB for the interactive viewer,
an engineering drawing for dimension-constrained examples, and the recorded
scores from `example.json`. Also writes `examples.json`, `llms.txt` and copies
the bundled three.js so the page works without a CDN.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
REPO = "https://github.com/YUI-TIEN/img2cad"
ORDER = ["fish", "standing-horse", "pagoda", "vase", "mounting-plate", "flanged-bushing"]
COPY = ["reference.png", "comparison.png", "silhouette.png", "registered.png", "model.py"]


def cad_python(requested: str | None) -> str:
    for candidate in (requested, os.environ.get("IMG2CAD_CAD_PYTHON"), str(ROOT / ".venv-cad/bin/python")):
        if candidate and Path(candidate).is_file():
            return candidate
    return sys.executable


def example_summary(directory: Path) -> dict[str, Any]:
    data = json.loads((directory / "example.json").read_text(encoding="utf-8"))
    readme = (directory / "README.md").read_text(encoding="utf-8")
    title = re.match(r"# (.+)", readme)
    heading = title.group(1) if title else directory.name
    name, _, subtitle = heading.partition(" (")
    silhouette = data.get("silhouette") or {}
    registered = data.get("registered") or {}
    dims = data["geometry"]["dimensions"]
    checks = data.get("dimension_checks")
    return {
        "name": directory.name,
        "title": name,
        "subtitle": subtitle.rstrip(")"),
        "target_type": data["target_type"],
        "techniques": data.get("techniques", []),
        "size_mm": [round(dims[axis], 1) for axis in ("x", "y", "z")],
        "volume_mm3": round(data["geometry"]["volume"]),
        "parts": data["geometry"].get("solid_count"),
        "silhouette_iou": silhouette.get("best_iou") if silhouette.get("reliable") else None,
        "registered_iou": registered.get("silhouette_iou"),
        "color_iou": {color: region["iou"] for color, region in (registered.get("color_regions") or {}).items()},
        "dimension_checks": [
            {"name": check["name"], "expected": check["expected"], "measured": round(check["measured"], 3), "passed": check["passed"],
             **({"diameter": check["diameter"]} if "diameter" in check else {})}
            for check in checks
        ] if isinstance(checks, list) else [],
        "revisions": [{"id": rev["id"], "review": rev.get("visual_review"), "reason": rev.get("reason")} for rev in data.get("revisions", [])],
        "source": f"{REPO}/tree/main/examples/{directory.name}",
    }


def build_example(directory: Path, out: Path, python: str, work: Path) -> dict[str, Any]:
    summary = example_summary(directory)
    target = out / "examples" / directory.name
    target.mkdir(parents=True, exist_ok=True)
    run = work / directory.name
    result = subprocess.run([python, "-B", str(SCRIPTS / "run_agent_cad.py"), str(directory / "model.py"), str(run),
                             "--cad-python", python, "--mesh-formats", "glb"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{directory.name}: CAD build failed\n{result.stdout}\n{result.stderr}")
    shutil.copy2(run / "model.glb", target / "model.glb")
    files = {"glb": f"examples/{directory.name}/model.glb"}
    for name in COPY:
        if (directory / name).is_file():
            shutil.copy2(directory / name, target / name)
            files[name.split(".")[0]] = f"examples/{directory.name}/{name}"
    if summary["target_type"] == "dimension_constrained":
        drawing = subprocess.run([python, "-B", str(SCRIPTS / "drawing.py"), str(run / "model.step"), str(target),
                                  "--formats", "svg", "--name", summary["title"]], capture_output=True, text=True, check=False)
        if drawing.returncode != 0:
            raise SystemExit(f"{directory.name}: drawing failed\n{drawing.stderr}")
        files["drawing"] = f"examples/{directory.name}/drawing.svg"
    summary["files"] = files
    return summary


def llms_txt(examples: list[dict[str, Any]]) -> str:
    raw = f"{REPO.replace('github.com', 'raw.githubusercontent.com')}/main"
    lines = [
        "# img2cad",
        "",
        "> Agent workflow that turns images, photos, sketches and engineering drawings into editable, coloured CAD "
        "(build123d source, STEP with part colours, GLB, 3MF, STL), with geometry gates, registered overlays and a review loop.",
        "",
        "Start with the skill; it is the workflow contract. Every tool is a subcommand of the `img2cad` CLI "
        "(`uvx --python 3.13 --from git+https://github.com/YUI-TIEN/img2cad img2cad --help`).",
        "",
        "## Agent docs",
        f"- [SKILL.md]({raw}/skills/img2cad/SKILL.md): staged workflow, commands, review rules",
        f"- [MODELING.md]({raw}/skills/img2cad/MODELING.md): build123d placement, techniques by object type, precision tools",
        f"- [LESSONS.md]({raw}/skills/img2cad/LESSONS.md): verified pitfalls from real runs",
        f"- [cad-output SKILL.md]({raw}/skills/cad-output/SKILL.md): viewer, mesh export, drawings, printability",
        f"- [README.md]({raw}/README.md): scope, install, CLI",
        "",
        "## Worked examples",
    ]
    for example in examples:
        lines.append(f"- [{example['title']}]({raw}/examples/{example['name']}/README.md): {example['target_type'].replace('_', ' ')}; "
                     + "; ".join(example["techniques"][:3]))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "_site")
    parser.add_argument("--cad-python")
    args = parser.parse_args()
    python = cad_python(args.cad_python)
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)
    shutil.copytree(SCRIPTS / "vendor" / "three", out / "vendor" / "three")
    names = [name for name in ORDER if (ROOT / "examples" / name / "example.json").is_file()]
    names += sorted(path.parent.name for path in (ROOT / "examples").glob("*/example.json") if path.parent.name not in names)
    with tempfile.TemporaryDirectory(prefix="img2cad-site-") as temp:
        examples = [build_example(ROOT / "examples" / name, out, python, Path(temp)) for name in names]
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    (out / "examples.json").write_text(json.dumps({"version": version, "repository": REPO, "examples": examples}, indent=2), encoding="utf-8")
    (out / "llms.txt").write_text(llms_txt(examples), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps({"out": str(out), "examples": names}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

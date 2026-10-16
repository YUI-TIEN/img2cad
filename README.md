<div align="center">

# img2cad

**Turn a photo, sketch or engineering drawing into editable, coloured CAD — with your coding agent.**

[![PyPI](https://img.shields.io/pypi/v/img2cad?color=0a84ff)](https://pypi.org/project/img2cad/)
[![Python](https://img.shields.io/pypi/pyversions/img2cad)](https://pypi.org/project/img2cad/)
[![Tests](https://github.com/YUI-TIEN/img2cad/actions/workflows/test.yml/badge.svg)](https://github.com/YUI-TIEN/img2cad/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[Website & 3D examples](https://yui-tien.github.io/img2cad/) · [Get started](#get-started) · [Manual install](#manual-install) · [Commands](#commands) · [Examples](examples/) · [How it works](docs/DESIGN.md)

<img src="examples/espresso-cup/comparison.png" alt="A photo of an espresso cup beside the CAD model img2cad built from it, in four views" width="820">

</div>

img2cad gives Claude Code, Codex, Cursor, Gemini CLI or any MCP host a **staged, checked workflow** for image → CAD. The agent reads the image, records what it sees and plans the parts, writes [build123d](https://github.com/gumyr/build123d) source, and the local runner builds it, measures it, and overlays it on the image — refusing to move on until geometry, dimensions and a visual review pass.

You get a parametric `model.py` you can keep editing, plus **STEP** (named, coloured parts), **GLB**, **STL** and **3MF**.

## Get started

Use an image-capable coding agent that can run local commands.

### 1. Ask your agent to install img2cad

Paste this into your agent:

```text
Install img2cad from https://github.com/YUI-TIEN/img2cad for this agent. Follow the host-specific setup in its README, set up the local CAD runtime, and run the documented doctor check. Then verify that this agent can access and use the img2cad Skill/plugin workflow. If it requires a restart or reload, do that and verify again before telling me everything is ready.
```

Your agent will choose the setup for its host and confirm both the CAD environment and its own access to the img2cad workflow before you start. Prefer to install it yourself? See [Manual install](#manual-install).

### 2. Attach an image and describe what you want

For example:

> Use img2cad to make editable CAD from this image. Unless I provide dimensions, make a visual approximation. Show me a preview and provide the editable `model.py` and a STEP file; list important assumptions.

The CAD geometry and exports are built locally; your agent reviews a comparison preview. Check the preview and measured geometry before manufacturing—a visual approximation is not a dimensionally verified part.

## Highlights

- 🧭 **Agent workflow, not a one-shot guess** — observe → plan → build → compare → revise, with hash-bound gates and resumable revisions.
- 📐 **Real dimensions** — fit the photo's camera to known features (`img2cad camera`), register the model on the image, trace outlines in millimetres.
- 📷 **Any input** — product photos, several photos from any angle (visual hull from fitted cameras), hand sketches, dimensioned drawings.
- ✂️ **Masks in one click** — colour seeds, polygons, or optional [SAM 2](https://github.com/facebookresearch/sam2) segmentation.
- 🎛️ **Live parameter panel** — `img2cad view model.py` opens a 3D viewer with sliders; changes rebuild locally and save back to the source.
- 🏭 **Ready to make** — 3D-print check, slicing and sending to your printer, CNC / sheet-metal DFM with flat blanks, engineering drawings (SVG/DXF/PDF), a standard parts library, URDF / SDF / MJCF for robots.

## Manual install

### In your agent

| Host | Install |
|---|---|
| **Claude Code** | `/plugin marketplace add YUI-TIEN/img2cad` then `/plugin install img2cad@img2cad` |
| **Gemini CLI** | `gemini extensions install https://github.com/YUI-TIEN/img2cad` |
| **Codex, Cursor or another agent with skills** | `npx skills add YUI-TIEN/img2cad` |
| **Any MCP host** | command `uvx img2cad mcp` (see below) |

<details>
<summary>MCP server config (Claude Desktop, Cursor, VS Code, …)</summary>

```json
{
  "mcpServers": {
    "img2cad": { "command": "uvx", "args": ["--python", "3.13", "img2cad", "mcp"] }
  }
}
```

</details>

### Command line

```sh
pip install img2cad              # or: uv tool install img2cad
img2cad doctor                   # checks the CAD stack (build123d / OCP)

uvx img2cad doctor               # run without installing
pip install "img2cad[sam]"       # optional: SAM 2 segmentation for `img2cad mask --sam`
```

Python 3.10–3.13. Latest from GitHub: `pip install git+https://github.com/YUI-TIEN/img2cad`.

<details>
<summary>From a clone (contributors)</summary>

```sh
git clone https://github.com/YUI-TIEN/img2cad && cd img2cad
python3 -m venv .venv-cad && .venv-cad/bin/pip install -r requirements-cad.lock -e .
.venv-cad/bin/img2cad doctor
```

</details>

## Commands

| Command | What it does |
|---|---|
| `workflow` | staged, resumable image → CAD workflow (`init`, `observations`, `plan`, `run`, `review`, `new-revision`, `promote`, `status`) |
| `build model.py out/` | STEP + GLB/STL/3MF, checks, previews, comparison and registered overlay |
| `camera camera.json` | fit the photo's camera to known circles/points; refuses poor fits |
| `mask photo.png mask.png` | subject mask from polygons, ellipses, colour seeds, `--auto` (busy backgrounds) or `--sam` |
| `hull views.json` | blockout from 2+ silhouettes (front/right/top or photos at any angle), hollows cut from declared openings |
| `trace image.png` | colour regions → pixel outlines (`--quantize` / `--shading-tolerant` for shaded photos) |
| `inspect model.step` | validity, parts, colours, bounds, volume, holes |
| `view` · `params` | 3D viewer with live parameters · list/set parameters |
| `export model.step out/` | GLB (coloured), 3MF (coloured parts), STL |
| `drawing model.step out/` | three views + section (any axis/offset) in SVG/DXF/PDF: thread/counterbore/countersink callouts, pockets, auxiliary views for oblique holes, baseline positions, ISO 2768 tolerances |
| `printcheck model.step [--orient]` | watertight, overhangs, bed contact, thin walls, build volume; `--orient` picks the orientation needing the least support, respecting `--load-axis` and `--cosmetic` faces |
| `slice model.3mf --out x.gcode` | G-code via installed PrusaSlicer / SuperSlicer / OrcaSlicer / Bambu Studio |
| `send x.gcode --printer octoprint --host …` | upload to OctoPrint, PrusaLink, Moonraker (Klipper) or Bambu LAN; `--start` prints |
| `dfm model.step --process cnc\|sheet` | CNC (3, 3+2, 5-axis): setups with tool access, corners, radii, holes, threads · sheet: thickness, bends, flat pattern DXF (any bend axes, holes included) |
| `parts make screw --size M3 --length 12` | ISO screws (real threads with `--threads`), nuts, washers, bearings, spur/helical gears, GT2 pulleys, MGN rails, servos, NEMA 17, 2020 extrusion |
| `urdf model.step --out robot/` | URDF, SDF or MuJoCo MJCF; revolute and prismatic joints guessed with limits, axis-aligned frames, hull collisions, a material per part, exact inertia |
| `mcp` · `doctor` · `version` | MCP server (stdio) · environment check · version |

`img2cad <command> --help` shows every option. Full CLI reference: [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Examples

| | Input | Technique |
|---|---|---|
| [espresso-cup](examples/espresso-cup/) | real photo | camera fitted to three circles, profile from silhouette edges |
| [falcon9-pad](examples/falcon9-pad/) | real photo (NASA) | known dimensions as scale, lattice towers |
| [mounting-plate](examples/mounting-plate/) | dimensioned drawing | fillets, hole patterns, dimension gates |
| [flanged-bushing](examples/flanged-bushing/) | drawing | half-profile revolve |
| [vase](examples/vase/) · [fish](examples/fish/) · [standing-horse](examples/standing-horse/) · [pagoda](examples/pagoda/) | sketches | splines, lofts, limbs, roofs, projected paint |

Each one keeps the whole chain — reference, observations, plan, `model.py`, comparison and review. Browse them in 3D on the [website](https://yui-tien.github.io/img2cad/).

## How it compares

Text-to-CAD tools start from words; mesh generators give you triangles. img2cad starts from **your image** and ends at **editable B-rep source** with measured checks — a workflow your agent runs, not a hosted model. See [docs/DESIGN.md](docs/DESIGN.md) for the design and related projects.

## Documentation

- [docs/DESIGN.md](docs/DESIGN.md) — problem, design principles, acceptance criteria
- [docs/WORKFLOW.md](docs/WORKFLOW.md) — workflow CLI reference and learning material
- [skills/img2cad/SKILL.md](skills/img2cad/SKILL.md) — the agent contract · [MODELING.md](skills/img2cad/MODELING.md) · [LESSONS.md](skills/img2cad/LESSONS.md)
- [skills/cad-output/SKILL.md](skills/cad-output/SKILL.md) — drawings, printing, DFM, parts, robots
- [benchmark/](benchmark/README.md) · [CHANGELOG](CHANGELOG.md) · [ROADMAP](ROADMAP.md) · [CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md)

> **Status:** beta. Reviews are agent reviews (`human_acceptance: not_verified`); check the measured geometry and previews before you manufacture anything.

## License

[MIT](LICENSE)

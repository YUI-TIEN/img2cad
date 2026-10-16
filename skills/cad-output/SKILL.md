---
name: cad-output
description: Turn a finished STEP model into deliverables - interactive 3D view, GLB/STL/3MF meshes, a dimensioned engineering drawing (SVG/DXF/PDF), a 3D-printability report, slicing to G-code, CNC/sheet-metal DFM checks, standard parts (screws, bearings, motors, extrusion) and URDF for robots. Use after img2cad produced a model, or for any STEP the user supplies.
---

# cad-output — view, export, draw, and print-check a CAD model

Use the `img2cad` command described in [`../img2cad/SKILL.md`](../img2cad/SKILL.md) ("The `img2cad` command"). All commands read the saved STEP, so every deliverable matches the checked B-rep.

## View and tune parameters

```sh
img2cad view model.py                            # parameter panel: drag, type, live rebuild, Save
img2cad view model.step [more files...]          # opens the browser
img2cad view model.step --no-open --json         # prints {"url": ...}; keeps serving
```

Opening a `model.py` builds it and lists its **parameters**, the module-level UPPERCASE numbers. Write them so the panel is useful:

```python
FLANGE_DIAMETER = 40.0  # [30, 70] flange outer diameter, mm
SPOKES = 6              # [3, 12]
```

`[min, max]` sets the slider range and the rest of the comment is the label. Derived values (tuples, expressions) are not parameters; expose their inputs instead. In the panel:
- Drag a label to scrub the value (Shift ×10, Alt ÷10), or type a value (arithmetic works, ↑/↓ step).
- With **Live rebuild** on, the model rebuilds locally after each change, without an AI round trip.
- **Save** (⌘/Ctrl+S) writes the values into `model.py` and keeps `model.py.bak`. **Reset** returns to the saved values.

`img2cad params model.py [--set NAME=VALUE ...]` does the same from the shell. Shortcuts: `1`–`4` views, `M` measure, `S` section, `W` wireframe, `F` fit, `Tab` hide panels, `Esc` clear.

The viewer shows STEP, GLB, STL and 3MF with part colours. Use the standard views (Front from −Y, Right from +X, Top from +Z, Iso), the part list (click to select, toggle visibility), **Measure** (pick two points; reports distance and ΔX/ΔY/ΔZ in model mm), **Section** along X/Y/Z, wireframe, and screenshot. Through MCP, `img2cad_show` returns the same URL.

## Export meshes

`img2cad workflow run` and `preview` already write `model.glb`, `model.stl` and `model.3mf` next to `model.step` (turn off with `--mesh-formats none`). For any other STEP:

```sh
img2cad export model.step out/ --formats glb,stl,3mf [--tolerance 0.05]
```

| Format | Keeps | Use for |
|---|---|---|
| GLB | part names and colours (glTF, metres, Y-up) | web, viewers, AR |
| 3MF | one object per part with its colour, mm | slicers, multi-colour printing |
| STL | one uncoloured mesh, mm | tools that only read STL |

The tessellation tolerance defaults to 1/2000 of the model diagonal (at least 0.01 mm).

## Engineering drawing

```sh
img2cad drawing model.step out/ --name "Mounting plate"      # out/drawing.svg, drawing.dxf and drawing.pdf
```

Third-angle sheet: front view (looking along +Y), top view above it, right view beside it; visible edges solid, hidden edges dashed; overall width, height and depth dimensioned; and a note block listing every full cylindrical hole/boss with diameter, axis and position. Check the hole table against the source drawing: it is the fastest way to catch a hole in the wrong place, which the dimension gate does not check. The DXF opens in any 2D CAD tool for further dimensioning.

## 3D-printability check

```sh
img2cad printcheck model.step [--build-volume 220,220,250] [--min-wall 0.8] [--overhang 45]
```

Orient the model as it will print (Z up, bed at the lowest point). The report gives `pass`/`warn`/`fail` per check and an overall status (exit code 1 on fail):

- `watertight` — every part closed and manifold; `solids` — no loose pieces inside a part;
- `build_volume` — fits the printer; `bed_contact` — enough area on the bed to stay put;
- `overhangs` — downward area steeper than the limit (needs supports);
- `thin_walls` — sampled wall thickness under `--min-wall`.

Visual-approximation models usually warn: organic undersides overhang, and projected paint decals (`projected_decal`) are deliberately about 0.5 mm thick. For a print, either thicken the paint (`depth=`), print it as a separate colour (3MF keeps parts), or drop it; add a flat base by cutting the bottom (`part.cut(Pos(0, 0, z0 - big / 2) * Box(big, big, big))`). Report warnings to the user rather than claiming a model is print-ready.

## Slice for printing

```sh
img2cad slice model.3mf --out model.gcode [--slicer prusa|superslicer|orca|bambu] [--slicer-path PATH]
img2cad slice model.stl --out part.gcode --config my_printer.ini                       # Prusa/SuperSlicer profile
img2cad slice model.3mf --out plate.3mf --slicer orca --settings machine.json,process.json,filament.json
```

Runs the slicer the user already has, in command-line mode, and reports estimated time and filament. Without a profile the slicer's defaults apply, which rarely match the printer: ask for the user's profile. If no slicer is installed the command says so; then hand over `model.3mf` (opens in Bambu Studio, OrcaSlicer, PrusaSlicer, Cura). Do not claim the part was printed: sending the job stays with the user.

## CNC and sheet-metal checks

```sh
img2cad dfm part.step --process cnc --tool-radius 1.5     # 3-axis, tool along Z, machined from +Z
img2cad dfm bracket.step --process sheet [--thickness 2]
```

Orient the part as it will be fixtured (Z = spindle). Every check has `pass`/`warn`/`fail` and evidence locations in model mm (exit 1 on fail). CNC: `sharp_internal_corners` (add a radius ≥ tool radius or dog-bones), `small_internal_radii`, `deep_holes` (> 4× warn, > 10× fail), `tiny_holes`, `undercut_faces` (need another setup). Sheet: `uniform_thickness`, `small_holes` (< thickness), `tight_bends` (inside radius < thickness). The rules are common shop guidance; report warnings as questions for the maker.

## Standard parts

```sh
img2cad parts list
img2cad parts make screw --size M3 --length 12 --out m3x12.step
```

In `model.py`, `from std_parts import socket_head_screw, hex_nut, washer, ball_bearing, nema17, extrusion_2020` (the worker puts the scripts directory on the path). Nominal ISO dimensions; threads are plain cylinders, bearings solid rings. Each part sits on z = 0 (a screw's head on top, shank down), has a label and a colour, so it shows up as its own part in STEP, 3MF and the drawing. Use them for fit checks and assemblies instead of modelling fasteners by eye.

## Robot description (URDF)

```sh
img2cad urdf model.step --out robot/ [--joints joints.json] [--density 2.7e-6]
```

One link per labelled part (`meshes/<link>.stl`, colour, mass from volume × density in kg/mm³, centre of mass and inertia from the B-rep). `joints.json` lists `{"name", "type": fixed|revolute|continuous|prismatic, "parent", "child", "origin": [x, y, z] mm in the model frame, "axis", "limit"}`; parts it omits are fixed to the root (the largest part, or `"root"`). The robot appears as modelled at zero joint angles. Model each moving body as its own labelled part.

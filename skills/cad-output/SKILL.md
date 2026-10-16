---
name: cad-output
description: Turn a finished STEP model into deliverables - interactive 3D view, GLB/STL/3MF meshes, a dimensioned engineering drawing (SVG/DXF/PDF), a 3D-printability report, slicing and sending to a printer, CNC/sheet-metal DFM checks with flat blanks, standard parts (screws, bearings, gears, pulleys, rails, servos, motors, extrusion) and URDF/SDF/MJCF for robots. Use after img2cad produced a model, or for any STEP the user supplies.
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

Third-angle sheet: front view (looking along +Y), top view above it, right view beside it; visible edges solid, hidden edges dashed; overall width, height and depth dimensioned. Every full hole/boss along X, Y or Z is tagged (`H1 Ø6`, `B1 Ø12`) in the view looking down its axis, and its centre is dimensioned from that view's lower-left edges (baseline dimensions; up to 10 per direction per view, the rest in the notes). The report's `feature_dimensions` lists each tag with its view and datum distances. A note block lists every full cylindrical hole/boss with diameter, axis and position. Section A-A cuts the part through its centre on the XZ plane (marked on the top view), seen from the front with cut faces hatched; `--no-section` leaves it out, and the report's `section` gives the cut area. Not drawn: other section planes, tolerances, thread callouts, slot/pocket dimensions; add them in a 2D CAD tool from the DXF before sending to a shop. Check the hole table against the source drawing: it is the fastest way to catch a hole in the wrong place, which the dimension gate does not check. The DXF opens in any 2D CAD tool for further dimensioning.

## 3D-printability check

```sh
img2cad printcheck model.step [--build-volume 220,220,250] [--min-wall 0.8] [--overhang 45]
```

Orient the model as it will print (Z up, bed at the lowest point), or let the tool choose:

```sh
img2cad printcheck model.step --orient --write-oriented oriented.step   # or .stl
```

`--orient` tries each axis direction and the largest flat faces as the bottom, picks the one with the least support area (then the most bed contact, then the lowest height), and checks that orientation. The report's `orientation` gives the face that goes down, the rotation (axis and degrees, and a matrix), the scores as given and for the top candidates. Strength along layers and cosmetic faces are not scored; say so when a part is loaded or visible. The report gives `pass`/`warn`/`fail` per check and an overall status (exit code 1 on fail):

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

Runs the slicer the user already has, in command-line mode, and reports estimated time and filament. Without a profile the slicer's defaults apply, which rarely match the printer: ask for the user's profile. If no slicer is installed the command says so; then hand over `model.3mf` (opens in Bambu Studio, OrcaSlicer, PrusaSlicer, Cura).

## Send to a printer

```sh
export IMG2CAD_PRINTER_KEY=...        # API key (OctoPrint, PrusaLink, Moonraker) or Bambu LAN access code
img2cad send model.gcode --printer octoprint --host 192.168.1.20               # upload only
img2cad send model.gcode --printer moonraker --host klipper.local --start       # upload and print
img2cad send plate.gcode.3mf --printer bambu --host 192.168.1.30 --serial SN --start   # needs paho-mqtt for --start
```

Upload is the default. **Only pass `--start` when the user asked to start the print in this conversation**, after they confirmed the plate is clear and the right filament is loaded: a print is a physical action nobody may be watching. Never put the key on the command line or in a file; read it from the environment. Bambu needs LAN mode and a sliced `.gcode.3mf`.

## CNC and sheet-metal checks

```sh
img2cad dfm part.step --process cnc --tool-radius 1.5     # 3-axis, tool along Z, machined from +Z
img2cad dfm bracket.step --process sheet [--thickness 2]
```

Orient the part as it will be fixtured (Z = spindle). Every check has `pass`/`warn`/`fail` and evidence locations in model mm (exit 1 on fail). CNC: `sharp_internal_corners` (add a radius ≥ tool radius or dog-bones), `small_internal_radii`, `deep_holes` (> 4× warn, > 10× fail), `tiny_holes`, `hole_types` (plain, counterbore, countersink with its angle, or likely tapped when the bore is an ISO tap drill; warns on taps deeper than 3 × the thread and on non-standard countersink angles; modelled threads are not read), `undercut_faces` (need another setup), `setups` (the fewest ±X/±Y/±Z setups that reach every face and hole; ignores fixturing and occlusion). Sheet: `uniform_thickness`, `small_holes` (< thickness), `tight_bends` (inside radius < thickness), `hole_to_bend` (< 2 × thickness + radius), `flat_blank` (for bends about one axis: blank length × width with `--k-factor`, default 0.44, and each bend's angle, allowance and deduction; holes are not unfolded, so place them from the 3D model). The rules are common shop guidance; report warnings as questions for the maker.

## Standard parts

```sh
img2cad parts list
img2cad parts make screw --size M3 --length 12 --out m3x12.step
```

```sh
img2cad parts make gear --module 1.5 --teeth 30 --width 8 --bore 8 --out gear.step
img2cad parts make screw --size M4 --length 16 --threads --out m4.step
img2cad parts make rail --size MGN12 --length 300 --out rail.step
```

In `model.py`, `from std_parts import socket_head_screw, hex_nut, washer, ball_bearing, spur_gear, gt2_pulley, mgn_rail, servo, nema17, extrusion_2020` (the worker puts the scripts directory on the path). Nominal dimensions: ISO 4762/4032/7089/15, ISO 53 involute gears (pitch diameter = module × teeth, so two gears mesh at (z1 + z2) × m / 2 apart), GT2 2 mm pitch, MGN rails, SG90/MG996R servos. Threads are plain cylinders unless `threads=True` (a real ISO helix; slower), bearings are solid rings. Each part sits on z = 0 (a screw's head on top, shank down), has a label and a colour, so it shows up as its own part in STEP, 3MF and the drawing. Use them for fit checks and assemblies instead of modelling fasteners by eye.

## Robot description (URDF)

```sh
img2cad urdf model.step --out robot/ [--joints joints.json] [--density 2.7e-6] [--format urdf|sdf|mjcf]
img2cad urdf model.step --out robot/ --guess-joints --material base=aluminium --material shaft=steel
```

One link per labelled part (`meshes/<link>.stl`, colour, mass from volume × density in kg/mm³, centre of mass and inertia from the B-rep). `joints.json` lists `{"name", "type": fixed|revolute|continuous|prismatic, "parent", "child", "origin": [x, y, z] mm in the model frame, "axis", "limit"}`; parts it omits are fixed to the root (the largest part, or `"root"`). The robot appears as modelled at zero joint angles. `--format sdf` writes SDFormat 1.9 for Gazebo, `--format mjcf` a MuJoCo model (bodies nested along the joint tree). Model each moving body as its own labelled part.

Materials: `--density` sets the default; `--material PART=NAME|DENSITY` (or `"materials"` in joints.json) overrides it per part (pla, petg, abs, nylon, resin, wood, aluminium, steel, stainless, brass, copper, titanium, carbon_fibre). `--guess-joints` adds a revolute joint wherever a shaft/boss sits coaxially in another part's bore (diameters within 1 mm), growing the tree from the root over parts the joints file leaves unconnected, and writes `joints_guessed.json`. Guessed joints have default ±π limits and no prismatic or ball joints: review them, set limits, and pass the file back with `--joints` before using the robot.

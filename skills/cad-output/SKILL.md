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

Opening a `model.py` builds it and lists its **parameters**: module-level UPPERCASE numbers, bools (shown as switches) and number tuples/lists (one entry per element, `SIZE[0]`), plus any assignment anywhere, in any case, whose comment starts with `[min, max]` or `@param` (inside a function it is named `function.name`). Write them so the panel is useful:

```python
FLANGE_DIAMETER = 40.0  # [30, 70] flange outer diameter, mm
SPOKES = 6              # [3, 12]
```

```python
HOLLOW = True           # hollow body
def build_model():
    wall = 1.2          # [0.8, 3] wall inside the function
    ribs = 4            # @param rib count
```

`[min, max]` sets the slider range and the rest of the comment is the label. Computed values (expressions) are not parameters; expose their inputs instead. In the panel:
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

Third-angle sheet: front view (looking along +Y), top view above it, right view beside it; visible edges solid, hidden edges dashed; overall width, height and depth dimensioned. Every full hole/boss along X, Y or Z is tagged (`H1 Ø6`, `B1 Ø12`) in the view looking down its axis, and its centre is dimensioned from that view's lower-left edges (baseline dimensions; up to 10 per direction per view, the rest in the notes). The report's `feature_dimensions` lists each tag with its view and datum distances. A note block lists every full cylindrical hole/boss with diameter, axis and position. Hole tags carry their callout: `M3x0.5 8 deep` for a tapped hole (bore = ISO tap drill), `Ø4 CBORE Ø8x3`, `Ø4 CSK 90deg`, and modelled thread geometry by name. Pockets, slots and steps (upward floors below the top) are tagged `P1 30x16 depth 4` in the top view and their corners dimensioned from the same datum. Holes on oblique axes get an auxiliary view looking down their axis (VIEW B, C) below the front view. Section A-A is `--section y` by default (XZ plane through the centre, seen from the front), or `x`/`z`, at the centre or `@offset` (e.g. `--section x@12`); it is marked on the top view (x, y) or front view (z) with hatched cut faces; `--section none` leaves it out. The notes state the general tolerance, ISO 2768-1 class `--tolerance-class f|m|c|v` (default m), with its table for the part's size. Not drawn: geometric tolerances (flatness, position), surface finish, and fits on specific features; add them in a 2D CAD tool from the DXF when the part needs them. Check the hole table against the source drawing, and declare hole `positions` and pocket `face` constraints in the plan so the dimension gate checks them too. The DXF opens in any 2D CAD tool for further dimensioning.

## 3D-printability check

```sh
img2cad printcheck model.step [--build-volume 220,220,250] [--min-wall 0.8] [--overhang 45]
```

Orient the model as it will print (Z up, bed at the lowest point), or let the tool choose:

```sh
img2cad printcheck model.step --orient --write-oriented oriented.step   # or .stl
```

`--orient` tries each axis direction and the largest flat faces as the bottom, picks the one with the least support area (then the most bed contact, then the lowest height), and checks that orientation. The report's `orientation` gives the face that goes down, the rotation (axis and degrees, and a matrix), the scores as given and for the top candidates. `--load-axis x,y,z` (the main load direction in the model frame) keeps that load in the layer plane, since FDM layers are weakest pulled apart; the report gives `load_across_layers` (0 = in the layers, 1 = pulling them apart). `--cosmetic x,y,z` (repeatable) names faces that must look good by their outward normal and keeps them off the bed and free of supports (`cosmetic_area_scarred_mm2`). Ask the user which faces are visible and where the load goes before printing a functional part. The report gives `pass`/`warn`/`fail` per check and an overall status (exit code 1 on fail):

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

Every check has `pass`/`warn`/`fail` and evidence locations in model mm (exit 1 on fail). CNC (`--axes 3`, `3+2` or `5`): `setups` plans the fewest setups that reach every flat face and hole; a feature only counts as reachable from a direction when a ray from it along the tool leaves the part (a face under a ledge is not reachable from above). `3` uses ±X/±Y/±Z, `3+2` adds every face normal and hole axis as an indexed setup, `5` plans table orientations each reaching 110° of tilt. Each setup suggests vise jaws (largest opposed side faces and the opening) or says a fixture is needed. Then `sharp_internal_corners` (concave edges along a planned tool axis: add a radius ≥ tool radius or dog-bones), `inaccessible_corners` (concave edges no end mill reaches: ball mill radius, EDM or redesign), `small_internal_radii`, `deep_holes` (> 4× warn, > 10× fail), `tiny_holes`, `hole_types` (plain, counterbore, countersink with its angle, or likely tapped when the bore is an ISO tap drill; warns on taps deeper than 3 × the thread and on non-standard countersink angles), `modelled_threads` (helical geometry named M-size, internal/external), `undercut_faces`. Tool length, holder and fixture collisions are not simulated. Sheet: `uniform_thickness`, `small_holes` (< thickness), `tight_bends` (inside radius < thickness), `hole_to_bend` (< 2 × thickness + radius), `flat_blank`: the real flat pattern, every flange unfolded across its bends (any axes, viewed from the side the bends rise toward) with holes and cut-outs, `--k-factor` (default 0.44), blank size and area, and each bend's angle, direction, allowance and deduction; `--flat-dxf flat.dxf` writes the outline (layer OUTLINE) and bend centre lines (BEND). Bends running straight into bends and closed boxes fall back to a single-axis estimate and say why. The rules are common shop guidance; report warnings as questions for the maker.

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

In `model.py`, `from std_parts import socket_head_screw, hex_nut, washer, ball_bearing, spur_gear, centre_distance, gt2_pulley, mgn_rail, servo, nema17, extrusion_2020` (the worker puts the scripts directory on the path). Dimensions: ISO 4762/4032/7089/15; ISO 53 involute gears, spur or helical (`helix_deg`, normal module) with profile shift (`shift`, against undercut below ~17 teeth or to set a centre distance), `centre_distance(m, z1, z2, helix)` for meshing pairs; GT2 pulleys with the Gates groove (belt tooth radius 0.555, depth 0.75, root radius 0.15, PLD 0.254); MGN rails (HIWIN catalogue) with counterbored rail holes and tapped carriage holes; SG90/MG996R servos (vendors differ: check the one bought before a tight fit). Threads are plain cylinders unless `threads=True` (a real ISO helix; slower), bearings are solid rings. Each part sits on z = 0 (a screw's head on top, shank down), has a label and a colour, so it shows up as its own part in STEP, 3MF and the drawing. Use them for fit checks and assemblies instead of modelling fasteners by eye.

## Robot description (URDF)

```sh
img2cad urdf model.step --out robot/ [--joints joints.json] [--density 2.7e-6] [--format urdf|sdf|mjcf]
img2cad urdf model.step --out robot/ --guess-joints --material base=aluminium --material shaft=steel
```

One link per labelled part (`meshes/<link>.stl`, colour, mass from volume × density in kg/mm³, centre of mass and inertia from the B-rep). `joints.json` lists `{"name", "type": fixed|revolute|continuous|prismatic, "parent", "child", "origin": [x, y, z] mm in the model frame, "axis", "limit"}`; parts it omits are fixed to the root (the largest part, or `"root"`). The robot appears as modelled at zero joint angles. `--format sdf` writes SDFormat 1.9 for Gazebo, `--format mjcf` a MuJoCo model (bodies nested along the joint tree). Model each moving body as its own labelled part.

Materials: `--density` sets the default; `--material PART=NAME|DENSITY` (or `"materials"` in joints.json) overrides it per part (pla, petg, abs, nylon, resin, wood, aluminium, steel, stainless, brass, copper, titanium, carbon_fibre). `--guess-joints` adds a revolute joint wherever a shaft/boss sits coaxially in another part's bore (diameters within 1 mm), growing the tree from the root over parts the joints file leaves unconnected, and writes `joints_guessed.json`. It also adds prismatic joints where two parts touch on flat faces with two non-parallel contact normals (a channel's floor and wall, a rail's top and side) and the guide is ≥ 1.5 × longer than the slider; travel limits come from the guide's ends. Revolute limits come from turning the child both ways (5° steps, refined to 0.5°) until it hits another part; a part that turns all the way round becomes `continuous`. Guessed joints use the ROS frame convention (`"frame": "axis"`: the child frame's z along the joint axis); any joint can say `"frame": "axis"` or give `"rpy"` for a tilted frame, and inertia, meshes and child joints are written in each link's own frame. Collision geometry is each part's convex hull (`meshes/<link>_collision.stl`; `--collision mesh` keeps the visual mesh for concave parts that need it). Ball joints and closed loops are not guessed: review `joints_guessed.json`, adjust, and pass it back with `--joints`.

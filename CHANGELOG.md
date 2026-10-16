# Changelog

All notable changes. Versions follow `VERSION`; plugin manifests carry the same number.

## 0.17.0

- **Image to CAD.** `img2cad hull` takes `cavities` (an opening's mask in a view plus a depth) and cuts hollows that silhouettes cannot see. `img2cad mask --auto [--box]` separates an object from a busy background by colour, with no extra install. `--reference-mask auto` builds the silhouette mask in the runner. `img2cad trace --shading-tolerant` and `--quantize K --trace all` handle shaded photos.
- **Dimension gate.** `face` constraints find pocket and slot floors, steps and ledges by normal, offset, centre and size. `img2cad inspect` lists `planar_faces`.
- **Drawings.** The section plane is now a choice: `--section x|y|z[@offset]`. Hole tags carry callouts (`M3x0.5`, `CBORE`, `CSK`, modelled threads). Pockets and steps are tagged and dimensioned. Oblique holes get auxiliary views. ISO 2768-1 general tolerances are noted (`--tolerance-class`).
- **Printing.** `printcheck --orient --load-axis x,y,z --cosmetic x,y,z` keeps the load in the layer plane and keeps visible faces off the bed and free of supports.
- **CNC.** `dfm --axes 3|3+2|5` plans setups with ray-tested tool access and suggests vise jaws or a fixture. Concave edges are classed against the planned tool axes (sharp, or inaccessible). Modelled threads are named. Tilted and split holes are measured by their own parameters.
- **Sheet metal.** A real unfolder (`sheet_unfold.py`) handles bends about any axes and carries holes and cut-outs along. `dfm --flat-dxf` writes the flat pattern and bend lines.
- **Robots.** Prismatic joints are guessed from guided flat contacts. Revolute limits come from a collision sweep (`continuous` when free). Joint frames can align with the joint axis (`"frame": "axis"`) or take `rpy`, and inertia and meshes are written in each link's frame. Convex-hull collision meshes are the default.
- **Parts.** Helical gears and profile shift (`--helix`, `--shift`, `centre_distance`). The GT2 pulley uses the Gates groove profile. MGN rails get counterbored rail holes and tapped carriage holes.
- **Parameter panel.** Bools as switches, tuple elements, and marked parameters inside functions (`# [min, max]` or `# @param`).

## 0.16.0

- **Section view on drawings.** Section A-A cuts the part through its centre (XZ plane), marked on the top view, with hatched cut faces; `--no-section` leaves it out.
- **CNC hole types.** `dfm --process cnc` names each hole: plain, counterbore, countersink (with its angle) or likely tapped (bore = ISO tap drill). It warns on taps deeper than 3 × the thread and on non-standard countersink angles. Holes the kernel splits into half cylinders now count as full holes in every check.
- **Robots: materials and joint guessing.** `img2cad urdf --material PART=NAME|DENSITY` (or `"materials"` in joints.json) sets density per part. `--guess-joints` adds revolute joints at shaft-in-bore fits and writes `joints_guessed.json` for review.
- **Website** lists hole position checks, `printcheck --orient`, the section view, hole types and joint guessing.

## 0.15.0

- **Hole and boss positions in the dimension gate.** `hole`/`boss` constraints take `axis` and `positions`; each expected centre must have its own feature whose axis passes within `position_tolerance` (default 0.05 mm). The check reports each offset.
- **`img2cad printcheck --orient`.** Tries each axis and the largest flat faces as the bottom, picks the least support area (then bed contact, then height), and checks that orientation. `--write-oriented` saves it as STEP (parts and colours kept) or STL, resting on z = 0.
- **Feature dimensions on drawings.** Holes and bosses are tagged with their diameter in the view along their axis and dimensioned from that view's lower-left edges (baseline). The report lists them as `feature_dimensions`.

## 0.14.0

- **`img2cad send`.** Uploads G-code to OctoPrint, PrusaLink, Moonraker (Klipper) or a Bambu printer in LAN mode (FTPS; `--start` over MQTT with `paho-mqtt`). Upload is the default; printing needs `--start`. Keys come from `IMG2CAD_PRINTER_KEY`. Not exposed over MCP.
- **More standard parts.** ISO 53 involute spur gears, GT2 pulleys, MGN rails with a carriage, SG90 / MG996R servos, and real ISO metric threads (`--threads`).
- **SDF and MJCF.** `img2cad urdf --format sdf|mjcf` writes Gazebo and MuJoCo models from the same joints file. The MJCF loads in MuJoCo with each part where it was modelled.
- **DFM.** CNC `setups` plans the fewest ±X/±Y/±Z setups; sheet metal adds `hole_to_bend` and a K-factor `flat_blank` (blank size, bend allowances and deductions) for bends about one axis.
- **Website** shows the new outputs and installs from PyPI.

## 0.13.0

- **SAM 2 masks.** `img2cad mask --sam --point x,y [--negative x,y] [--box x0,y0,x1,y1]` adds Meta's SAM 2 segmentation (optional extra: `pip install "img2cad[sam]"`). Without it, `--sam` fails with the install hint; the polygon/seed tools are unchanged.
- **Visual hull from photos at any angle.** `img2cad hull` views may carry a fitted camera (`"frame"`: an `img2cad camera` fit.json or the frame inline) instead of front/right/top. Perspective cameras extrude a silhouette cone, not a prism.
- **`img2cad parts`.** Standard parts as build123d solids or STEP: ISO 4762 screws, ISO 4032 nuts, ISO 7089 washers, ISO 15 bearings, NEMA 17 motor, 2020 extrusion.
- **`img2cad urdf`.** URDF plus STL meshes from a coloured STEP assembly: one link per part, joints from `joints.json`, exact mass, centre of mass and inertia from the B-rep.
- **`img2cad dfm`.** CNC (sharp internal corners, radii under the tool, deep and tiny holes, undercuts) and sheet-metal (thickness, small holes, tight bends) checks with evidence locations.
- **`img2cad slice`.** Slices STL/3MF to G-code (or a sliced 3MF) with an installed PrusaSlicer, SuperSlicer, OrcaSlicer or Bambu Studio, and reports time and filament.
- **Docs.** New README (PyPI install first, badges, command table); the design notes moved to `docs/DESIGN.md` and the CLI reference to `docs/WORKFLOW.md`.

## 0.12.0

- **`img2cad hull`.** A visual-hull blockout from two or three silhouettes (front, right, top), plus `img2cad_lib.visual_hull`. It writes `hull.step`, the traced outlines, and a `model_hull.py` to carve from.
- **PDF engineering drawings.** `img2cad drawing` writes a vector `drawing.pdf` (no extra dependencies) next to SVG and DXF.
- **Category checklists** in MODELING.md for filling the detail inventory (mechanical, tableware, vehicles, animals, characters, buildings, products).
- **Example parameters** carry `[min, max] label` ranges for the parameter panel. Comments only; geometry unchanged.
- **Release workflow.** Pushing a `vX.Y.Z` tag builds and smoke-tests the wheel, publishes to PyPI via trusted publishing, and creates a GitHub release from this file.
- **Verified the plugin path.** `claude plugin validate` passes for the plugin, marketplace and skills. The plugin installs in Claude Code (2 skills, 1 MCP server). The MCP server and `img2cad doctor` run from `uvx --from git+https://github.com/YUI-TIEN/img2cad`. Added a marketplace description.

## 0.11.0

- **Parameter panel.** `img2cad view model.py` builds the model and lists its parameters (module-level UPPERCASE numbers, with `# [min, max] label` ranges). You can drag labels Figma-style or type values, and the model rebuilds locally without an AI round trip. Save writes the values back (with `model.py.bak`). `img2cad params` does the same from the shell.
- **Viewer redesign.** Liquid-glass panels (blur, specular sheen, refracting rim, SVG refraction on Chromium) in light and dark. Layers panel with show/hide. Properties panel with Parameters and Inspect tabs. Floating toolbar with shortcuts, section popover, toasts, animated camera moves, soft shadows, and a mobile bottom sheet.

## 0.10.0

- **Decomposition gate.** Visual-approximation plans must list `parts` (each with a technique and a size source: measured, known or estimated), a `detail_inventory` (every identity-defining detail with its part and handling: modelled, painted, or omitted with a reason), and ordered build `passes`.
- **Staged passes.** `workflow preview --stage blockout|form|detail|colour` and `workflow pass-review`. Passes cannot be skipped, the detail pass must check every non-omitted detail, and `source-review` is refused until all passes pass.
- **`img2cad camera`.** Fits an `IMAGE_FRAME` (orthographic or perspective) to picked points on known circles and points, and solves silhouette pixels into a revolve profile. It refuses when the fit is poor or any value is not pinned down, reports priors as assumptions, and always writes a check overlay.
- **`img2cad mask`.** Subject masks from polygons, ellipses and colour seeds.

## 0.9.x

- Real-photo examples: `espresso-cup` (perspective registration fitted to three circles) and `falcon9-pad` (known dimensions, lattice towers).
- `ImageFrame` gains `view`, `roll` and `distance`, plus `project()` and `on_plane_z()`. Decals and the registered overlay use the photo's camera.
- The worker re-imports the STEP and fails when the export lost geometry.
- SKILL.md rule: measure the main bodies, use typical sizes for small parts, time-box a part to two previews.
- `img2cad` CLI (pip/uvx), `doctor`, GLB/3MF/STL exports, local 3D viewer, MCP server, engineering drawings, printability check, plugin manifests, GitHub Pages site, CI.

## 0.8 and earlier

- Staged, hash-bound workflow; geometry gate (one solid per part, touching assemblies); coloured assemblies; traced decals; registered per-colour overlay; worked examples; LESSONS.md.

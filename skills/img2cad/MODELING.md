# img2cad modeling reference

How to write `model.py` for `scripts/agent_workflow.py`. Read this, the closest example in [`examples/`](../../examples/README.md), and [`LESSONS.md`](LESSONS.md) before authoring a model.

## Source contract

- Define `build_model()` that returns one build123d shape. **It must be one valid solid**: the geometry gate fails a model with several disjoint solids, which is how a floating part or a silently failed `fuse` shows up. Fuse parts that overlap (builder mode or `.fuse`). For an intentional multi-body result (an assembly, or a `Compound` of overlapping primitives like the benchmark dog), set `"allow_multiple_solids": true` in `plan.json`.
- Units are millimetres. Z is up. Put named parameters at the top of the file with a comment saying where each value came from: a drawing label, a measurement from the image, or an assumption.
- Only the constructs below pass the source check (`scripts/agent_cad_worker.py`). The check is a restricted Python AST plus an API allowlist and a timeout; it is **not an OS sandbox**. `tests/test_model_source_policy.py` keeps this file in sync with the allowlist.

## Allowed build123d names

Import these with `from build123d import ...` (no `as` aliases, no `*`):

| Group | Names |
|---|---|
| Placement, enums, selectors | `Align`, `Axis`, `GeomType`, `Keep`, `Location`, `Locations`, `GridLocations`, `HexLocations`, `PolarLocations`, `Mode`, `Plane`, `Pos`, `Rot`, `Rotation`, `Select`, `SortBy`, `Until`, `Vector` |
| Builders and containers | `BuildLine`, `BuildPart`, `BuildSketch`, `Compound` |
| 3D primitives and features | `Box`, `Cone`, `CounterBoreHole`, `CounterSinkHole`, `Cylinder`, `Hole`, `Sphere`, `Torus`, `Wedge` |
| 2D sketch shapes | `Circle`, `Ellipse`, `Polygon`, `Rectangle`, `RectangleRounded`, `RegularPolygon`, `SlotCenterToCenter`, `SlotOverall`, `Trapezoid` |
| 1D lines | `Bezier`, `CenterArc`, `JernArc`, `Line`, `Polyline`, `RadiusArc`, `SagittaArc`, `Spline`, `TangentArc`, `ThreePointArc` |
| Operations | `add`, `chamfer`, `extrude`, `fillet`, `loft`, `make_face`, `mirror`, `offset`, `revolve`, `scale`, `split`, `sweep` |

## Allowed methods

Call these with `obj.method(...)`:

- Transforms and booleans: `chamfer`, `cut`, `fuse`, `intersect`, `located`, `mirror`, `move`, `moved`, `offset`, `rotate`, `scale`, `translate`.
- Read-only topology selectors: `edges`, `faces`, `filter_by`, `group_by`, `solids`, `sort_by`, `vertices`, `wires`. Example: `fillet(part.edges().filter_by(Axis.Z), radius=2)`; top face: `part.faces().sort_by(Axis.Z)[-1]`.
- Containers: `append`, `extend`, `items`, `keys`, `values`.

## Python and math

- Built-ins: `abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `float`, `int`, `len`, `list`, `max`, `min`, `range`, `reversed`, `round`, `set`, `sorted`, `str`, `sum`, `tuple`, `zip`.
- `import math` or `from math import ...` with: `acos`, `asin`, `atan`, `atan2`, `ceil`, `cos`, `degrees`, `e`, `floor`, `hypot`, `pi`, `radians`, `sin`, `sqrt`, `tan`, `tau`.
- Allowed syntax: functions, `for`, `if`, `with`, list/dict comprehensions and generator expressions, `*args` unpacking, tuple unpacking, and arithmetic including `//` and `%`.
- Not allowed: `lambda`, `while`, `class`, `try`, other imports, file/network access, decorators, function names starting with `_`, attribute names starting with `_`, dunder names (`__x__`), and calling anything not listed here. A plain `_` throwaway variable is fine: `for x, _, z in points:`.

## Plane cheat sheet

| Plane | Sketch X → | Sketch Y → | Normal (`offset` / positive `extrude` direction) |
|---|---|---|---|
| `Plane.XY` | +X | +Y | +Z |
| `Plane.XZ` | +X | +Z | **−Y** (`Plane.XZ.offset(d)` sits at y = −d) |
| `Plane.YZ` | +Y | +Z | +X |

## Placing and combining shapes

Verified behaviour of build123d 0.13 (pinned in `requirements-cad.lock`):

- **Inside a builder** (`with BuildPart()`, `with BuildSketch()`), objects are added where they are created. Place them with `with Locations((x, y[, z])):`, `with GridLocations(...)`, or `with PolarLocations(...)`. `Pos(...)` is **not** a context manager (`with Pos(...)` raises), and `Pos(10, 0) * Ellipse(2, 1)` inside a `BuildSketch` adds the ellipse at the origin, because the moved copy is a new object the builder never sees.
- **Outside a builder** (algebra style), `Pos(x, y, z) * shape` moves a shape and `Rot(rx, ry, rz) * shape` rotates it (degrees). Order matters: `Pos(p) * Rot(r) * shape` rotates the shape about its own origin and then moves it; `Rot(r) * Pos(p) * shape` swings it around the world origin.
- `Cone(bottom_radius, top_radius, height)` and `Cylinder(radius, height)` are centred on their Z axis by default (z from −h/2 to +h/2). Pass `align=(Align.CENTER, Align.CENTER, Align.MIN)` to start them at z = 0.
- **Ellipsoid**: `Sphere(1).scale((rx, ry, rz))`, then move it with `Pos(...)`.
- **Point-to-point limb, neck, tail, or strut**: orient a cone with a plane whose Z axis runs from start to end:

  ```python
  def segment(start, end, start_radius, end_radius):
      direction = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
      length = sqrt(sum(value * value for value in direction))
      return Plane(origin=start, z_dir=direction) * Cone(start_radius, end_radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
  ```

- **Ball joints between segments**: use a sphere a little larger than the limb, and turn its poles away from the limb axis, e.g. `Pos(p) * Rot(90, 0, 0) * Sphere(r)` for near-vertical legs. A default sphere (poles on Z) at the end of a vertical cone made `fuse` silently leave separate solids (`examples/standing-horse`).
- **Stacked parts must overlap, not just touch.** Extend each part a little into its neighbour (`examples/pagoda` uses `WALL_OVERLAP`).
- Fuse many parts with a loop: `part = part.fuse(piece)`. If the gate reports several solids, use `preview` and fuse step by step to find the piece that breaks it.
- **Revolve seams**: `revolve` leaves a seam line in the sketch plane (the +X side for `Plane.XZ`). Before fusing parts onto a revolved body, rotate the body so the seam faces away from them, e.g. `Rot(0, 0, 90) * revolved` puts it at the back.
- **Smooth rounded bodies from a measured outline** (heads, bottles, domes): run one `Spline` through the (radius, height) points, starting and ending on the axis with `tangents=((1, 0), (-1, 0))`, and `revolve` it. Avoid squashing the result with a non-uniform `scale` if you will fuse more parts onto it.
- **Trimming**: `shape.intersect(other)` returns a `ShapeList`; to keep only part of a shape, `cut` away the rest (e.g. a big `Box` below the floor).

## Views and camera direction

`comparison.png` shows the reference beside four CAD views. Each one is a true camera view:

| Panel | Camera at | Screen right | Screen up |
|---|---|---|---|
| Front · from −Y | −Y, looking toward +Y | +X | +Z |
| Right · from +X | +X, looking toward −X | +Y | +Z |
| Top · from +Z | +Z, looking down | +X | +Y |
| Isometric · from +X −Y +Z | (1, −1, 1) direction | — | — |

Model the object so the view that matches the image is easy to pick. For a side-view image, put the object's length on X with the visible side facing −Y, so the **Front** panel matches the image. `--reference-view x,y,z` replaces the isometric panel with a camera placed in direction (x, y, z) **from the model toward the camera** (Z up). Examples: `0,-1,0` is the Front panel; `-0.5,-1,0.4` is front-left, slightly above; `0.35,1,0.35` looks from the +Y side. Negative first values are fine (`--reference-view -0.5,-1,0.4`). The camera is orthographic, so photo perspective (near parts larger) cannot be matched exactly.

## Choosing a technique

| What the image shows | Approach | Example |
|---|---|---|
| Prismatic part, plates, brackets, hole patterns | `Box`/extruded sketch, `fillet`/`chamfer` edges, `GridLocations`/`PolarLocations` + `Hole` | `examples/mounting-plate` |
| Round part with an axis (shafts, bushings, knobs, bottles) | Half cross-section on `Plane.XZ` → `make_face` → `revolve(axis=Axis.Z)` | `examples/flanged-bushing`, `examples/vase` |
| Hollow container | Solid first, then `offset(amount=-wall, openings=<face>)` | `examples/vase` |
| Organic body (animals, handles, streamlined shapes) | `loft` through `Ellipse`/`Circle` sections on offset planes; add parts with `fuse` | `examples/fish` |
| Animal with legs, jointed or limbed shapes | lofted body + `segment` cones between measured joints + rotated ball joints + ellipsoid head | `examples/standing-horse` |
| Buildings, roofs, tiered structures | `Box` storeys + ruled `loft` through squares/rectangles for hipped roofs and battered bases | `examples/pagoda` |
| Bent tube, rail, or cable | Path in `BuildLine` + profile sketch → `sweep` | (none yet) |
| Thin flat parts (fins, ribs, blades) | `Polygon` on the matching plane → `extrude(amount=t/2, both=True)` | `examples/fish` |
| Quick blocky stand-in | Scaled `Sphere`/`Cylinder` primitives; fuse them (a `Compound` needs `allow_multiple_solids`) | `benchmark/cases/visual-pose-dog` |

## Reading sizes from an image

- **Dimensioned drawing**: use the labels exactly. Diameter labels (Ø) are diameters; `Hole`, `Cylinder`, and `Circle` take a **radius**. Derive the expected volume by hand and add it as a `volume` constraint.
- **Photo or illustration without scale**: pick a scale (for example, "1 px ≈ 0.4 mm" or a known real-world size such as a typical dog's shoulder height) and record it in the plan's `unknowns`. Write down the pixel-to-model mapping, e.g. `x = (px - 450) * 4, z = (560 - py) * 4`, and measure in pixels: overall length and height, joint positions, and for a round or tapered object the half-width at several evenly spaced heights. Do not guess proportions by eye; the vase example shows the difference.
- **Angled photo**: measurements along the depth axis are foreshortened. Measure what faces the camera, estimate depth, and compare using a `--reference-view` close to the photo's angle.
- Dimensions hidden in the image (thickness of a side-view object, the back side) are estimates; say so in observations (`inferred`) and in comments.

## Checks you can declare (dimension-constrained plans)

```json
{"name": "length", "value": 80, "tolerance": 0.01}
{"name": "hole", "diameter": 6, "count": 4, "tolerance": 0.01}
{"name": "boss", "diameter": 24, "count": 1}
{"name": "volume", "value": 22767.8, "tolerance": 1.0}
```

- `length`/`width`/`height` (or `x`/`y`/`z`) compare overall STEP bounds. The default tolerance is 0.02.
- `hole` and `boss` count full cylindrical features of that diameter (holes and bores vs. shafts and bosses), grouped by axis. Fillet rounds are partial cylinders and are ignored. **Position is not checked**; confirm it visually.
- `volume` needs an explicit absolute tolerance in mm³. It catches a missing feature or a wrong size that the bounds cannot.

## Iterating with `preview`

`agent_workflow.py preview <work> --model draft.py [--reference-view ...] [--reference-mask ...]` builds a draft into `<work>/previews/pNNN/` and prints the comparison path, solid count, and silhouette score. It does not touch any workflow stage, so use it as often as you like. Only run the reviewed source through `source-review` → `run` once a preview looks right.

## Silhouette score

`run` and `preview` report an advisory `silhouette` block and write `silhouette.png`. The reference outline is found by growing the background in from the image border (plus enclosed regions that match a common background colour, such as sky between legs). It is compared with each CAD view after normalizing position and scale, and mirrored views are tried too. Treat it as a hint about proportions, never a gate:

- **Check `reliable` first.** It is `false`, with `unreliable_reasons`, when the outline does not look like one clean object: several blobs, a speckled edge, or touching the border. That is what happens on real photos with grass, trees, or a background coloured like the subject, and on line drawings. When it is false, ignore the number.
- **For photos, supply a mask**: trace the subject's outline in image pixels and pass the mask with `--reference-mask mask.png`. A rough 12-point polygon was enough for a real cat photo (unreliable 0.48 became a reliable 0.79 at the matching view):

  ```python
  # run with .venv-cad/bin/python (it has Pillow); this is a helper script, not model source
  from PIL import Image, ImageDraw
  reference = Image.open("reference.png")
  mask = Image.new("L", reference.size, 0)
  ImageDraw.Draw(mask).polygon([(250, 560), (700, 480), ...], fill=255)  # outline points in image pixels
  mask.save("mask.png")
  ```

- Compare it between revisions of the same model, not against a fixed threshold. For reference: the blocky dog benchmark scores 0.66; an eyeballed vase profile scored 0.87 and the measured one 0.92; the horse 0.88; the pagoda 0.98. Shadows drawn on the ground count as part of the object and lower the score. The overlay shows where outlines differ (red: missing from the CAD; blue: extra).
- It cannot see features inside the outline (eyes, fins drawn over the body, windows).

# img2cad modeling reference

How to write `model.py` for `scripts/agent_workflow.py`. Read this, the closest example in [`examples/`](../../examples/README.md), and [`LESSONS.md`](LESSONS.md) before authoring a model.

## Source contract

- Define `build_model()` that returns one build123d shape containing at least one positive-volume solid. Prefer a single fused solid (builder mode or `.fuse`). A `Compound` of overlapping solids is allowed for quick visual approximations, but it is not a single manufacturable body.
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
- Not allowed: `lambda`, `while`, `class`, `try`, other imports, file/network access, names that start with `_`, decorators, and calling anything not listed here.

## Plane cheat sheet

| Plane | Sketch X → | Sketch Y → | Normal (`offset` / positive `extrude` direction) |
|---|---|---|---|
| `Plane.XY` | +X | +Y | +Z |
| `Plane.XZ` | +X | +Z | **−Y** (`Plane.XZ.offset(d)` sits at y = −d) |
| `Plane.YZ` | +Y | +Z | +X |

`Pos(x, y, z) * shape` moves a shape; `Rot(0, 0, 45) * shape` rotates it in degrees. Inside a builder, `with Locations(...)` or `with GridLocations(...)` places the following objects.

## Choosing a technique

| What the image shows | Approach | Example |
|---|---|---|
| Prismatic part, plates, brackets, hole patterns | `Box`/extruded sketch, `fillet`/`chamfer` edges, `GridLocations`/`PolarLocations` + `Hole` | `examples/mounting-plate` |
| Round part with an axis (shafts, bushings, knobs, bottles) | Half cross-section on `Plane.XZ` → `make_face` → `revolve(axis=Axis.Z)` | `examples/flanged-bushing`, `examples/vase` |
| Hollow container | Solid first, then `offset(amount=-wall, openings=<face>)` | `examples/vase` |
| Organic body (animals, handles, streamlined shapes) | `loft` through `Ellipse`/`Circle` sections on offset planes; add parts with `fuse` | `examples/fish` |
| Bent tube, rail, or cable | Path in `BuildLine` + profile sketch → `sweep` | (none yet) |
| Thin flat parts (fins, ribs, blades) | `Polygon` on the matching plane → `extrude(amount=t/2, both=True)` | `examples/fish` |
| Quick blocky stand-in | Scaled `Sphere`/`Cylinder` primitives; fuse or `Compound` | `benchmark/cases/visual-pose-dog` |

## Reading sizes from an image

- **Dimensioned drawing**: use the labels exactly. Diameter labels (Ø) are diameters; `Hole`, `Cylinder`, and `Circle` take a **radius**. Derive the expected volume by hand and add it as a `volume` constraint.
- **Photo or illustration without scale**: pick a scale (for example, "1 px ≈ 0.4 mm" or a known real-world size) and record it in the plan's `unknowns`. Then measure in pixels: overall length and height, and for a round or tapered object the half-width at several evenly spaced heights. Do not guess proportions by eye; the vase example shows the difference.
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

## Silhouette score

`run` also reports an advisory `silhouette` block and writes `silhouette.png`. The reference foreground is grown from the image border and compared with each CAD view mask after normalizing position and scale; mirrored views are tried too. Treat it as a hint about proportions, not a gate:

- Compare it between revisions of the same model rather than against a fixed threshold. For reference: the blocky dog benchmark scores 0.63; an eyeballed first vase profile scored 0.93 and the measured profile 0.98; the fish scores 0.95. The overlay shows where the outlines differ (red: missing from the CAD; blue: extra).
- It cannot see features inside the outline (eyes, holes in a face-on view, fins drawn over the body). It is low for line drawings, and `reliable: false` when the background could not be separated.

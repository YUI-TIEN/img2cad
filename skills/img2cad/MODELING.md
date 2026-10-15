# img2cad modeling reference

How to write `model.py` for `scripts/agent_workflow.py`. Read this, the closest example in [`examples/`](../../examples/README.md), and [`LESSONS.md`](LESSONS.md) before authoring a model.

## Source contract

- `model.py` is ordinary Python. Use any build123d API and any Python you need (helpers, classes, comprehensions, `lambda`, `math`, `itertools`, ...). Only two things are required: it must parse, and it must define `build_model()`.
- `build_model()` returns a build123d shape. Return either:
  - **one part**: a single valid solid, for example everything fused, or
  - **a coloured assembly**: `Compound(children=[part, part, ...])`, where each part is one valid solid with its own `.color` and `.label` (see "Colour and multi-part models").
- **The geometry gate** fails if any part splits into several solids, which is how a floating piece or a silently failed `fuse` shows up. It also fails if an assembly part touches no other part. Set `"allow_multiple_solids": true` in `plan.json` only for a model that is deliberately made of separate bodies.
- Units are millimetres. Z is up. Put named parameters at the top of the file, with a comment saying where each value came from: a drawing label, a measurement from the image, or an assumption.
- **Safety**: the source runs as unrestricted Python, in its own subprocess with a timeout and a minimal environment (`-I`). It is **not sandboxed**, so read the source before `source-review`. For model source you did not write or review yourself, use `--strict-source` on `source-review`/`preview`. That enforces a conservative allowlist of build123d names, `math`, and basic built-ins. It is a static check, not a security boundary; use a container or VM for truly untrusted code.

## Colour and multi-part models

STEP stores a name and an RGB colour per part (verified: exported colours survive re-import). Use this whenever the image has distinct colours or materials.

```python
from build123d import Color, Compound

body.color, body.label = Color(0.96, 0.96, 0.95), "body"          # sample colours from the image (RGB / 255)
eye.color, eye.label = Color(0.08, 0.08, 0.09), "left eye"
return Compound(children=[body, eye, ...], label="statue")
```

- **One part per colour region.** Fuse everything that shares a colour into one part. `fuse` keeps only one colour, so fusing a black eye into a white body makes it all white.
- **Painted details** (eyes, markings, blush, stripes, logos): trace them from the image and project them onto the surface as thin layers. See "Precision tools" below. Do not draw paint as hand-placed ellipsoids. On the statue, that approach overlapped the photo's black regions at only 0.45; traced decals reached 0.84.
- **Every part must be one solid that touches the rest.** Two fins that only meet through the body must be two parts, not one; the gate reports a part with 2 solids.
- The preview draws each part in its colour, with dark outlines on the silhouette and between parts. Compare the colours with the image in `comparison.png`.
- A colour is per part, not a texture: photos, gradients, and printed text are out of scope.

## Precision tools

Use these whenever the image has details that matter (paint, markings, feature outlines). They replace eyeballing with measurement. They live in `scripts/`, and the worker puts that directory on `sys.path`, so `model.py` can `from img2cad_lib import ...`.

1. **Register the image.** In `model.py`, define the pixel↔millimetre mapping of the front view:

   ```python
   from img2cad_lib import ImageFrame
   IMAGE_FRAME = ImageFrame(mm_per_px=4, origin_px=(398, 725))  # pixel (398, 725) = model x 0, z 0; camera on -Y
   ```

   Use `IMAGE_FRAME.to_model(px, py)` for every measured position. When `IMAGE_FRAME` exists, `run`/`preview` draw the CAD **in the photo's own pixel frame**: `registered.png` shows the CAD outline (red) and part edges (yellow) on the photo, next to a 50:50 blend. They also report `registered.silhouette_iou` (unnormalised, so scale and position errors count; needs `--reference-mask`) and `registered.color_regions`: the IoU of each part colour against the photo pixels nearest to that colour, measured with a shading-tolerant colour distance. Read these numbers after every preview; they say exactly which colour region is off.
2. **Trace colour regions** instead of guessing feature shapes:

   ```sh
   .venv-cad/bin/python scripts/trace_regions.py reference.png --mask mask.png \
     --color white=240,240,236 --color shade=200,200,196 --color black=30,28,30 --color pink=240,170,165 \
     --trace black --trace pink --out regions.json --overlay regions.png
   ```

   - Include every colour present on the subject in the palette, including a darker "shade" of the main colour, so shadows don't get assigned to paint.
   - Each traced region has an `outline`, `holes` (for example the highlight inside an eye), a centroid, and a bbox, all in image pixels.
   - Regions touching the mask edge are dropped (`--edge-band`).
   - Check `regions.png`, then copy the outlines you need into `model.py` as literals, so the model stays self-contained and hash-pinned.
3. **Project the outlines onto the surface:**

   ```python
   from img2cad_lib import projected_decal
   eye = projected_decal(head, outline_px, IMAGE_FRAME, thickness=3, holes_px=holes)  # exact layer following the surface
   highlight = projected_decal(head, holes[0], IMAGE_FRAME, thickness=3)             # fills the hole in another colour
   ```

   - The layer follows the surface curvature, touches it, and keeps the traced shape exactly (arcs, ω mouths, slanted stripes).
   - Pass the surface the paint sits on (the head, not the whole fused body); it is offset once and cached.
   - Each layer is one part, so give it its colour and label.
4. Other helpers:
   - `revolved_profile(points)`: smooth revolve, seam turned to the back.
   - `segment(start, end, r0, r1)`: a tapered limb between two points.
   - `ball_joint(point, r)`: a joint sphere, rotated so it fuses.

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
- **`offset` fails on a placed shape**: in the pinned build123d, `offset()` raises "offset Error" for any shape moved with `Pos`/`moved`, even a plain sphere. Offset it at the identity location and place the result back: `offset(s.located(Location()), amount=t).located(s.location)`. `projected_decal` already does this.

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

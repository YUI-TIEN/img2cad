# img2cad lessons

Short, verified pitfalls collected from real runs. Read before modeling; add to it after a run teaches something reusable. Each entry says what went wrong, how to avoid it, and where it was seen. Keep entries factual: only record something you actually observed, and delete or correct an entry that turns out to be wrong.

## Source check

- **A `_` throwaway variable is allowed** (`for x, _, z in points`); only `_`-prefixed function/attribute names and dunders are blocked. An earlier doc wording made one agent avoid it unnecessarily. *(blind test: castle)*
- **`*args` unpacking was rejected before it was allowlisted.** `Polygon(*points)` and `Spline(*points)` are normal build123d idioms; the source check now allows `Starred`. If the check rejects a construct, read the error and `MODELING.md` before rewriting the model. *(examples/flanged-bushing, vase, fish)*
- **`Hole`, `Cylinder`, `Circle`, `Sphere` take a radius.** Drawings label diameters (Ø). Name parameters `*_DIAMETER` and divide by 2 at the call. *(examples/mounting-plate)*

## Geometry

- **A model that splits into several solids is broken, and now fails the gate.** In blind tests on real photos, one agent's roof floated 5 units above the top storey (2 solids), and another's fuse of cones and joint spheres silently dropped most of a dog (4 solids, volume 32.5e6 → 0.24e6 mm³). Both had passed the old gate. Overlap parts instead of touching them, and read the per-solid volumes and centres in the error to find the stray piece. *(blind tests: castle, dog; examples/standing-horse)*
- **Ball joints: turn the sphere's poles off the limb axis.** A default `Sphere` at the end of a vertical `Cone` made `fuse` leave an extra solid; `Pos(p) * Rot(90, 0, 0) * Sphere(r)` fused cleanly. *(examples/standing-horse, reproduced in isolation)*
- **In a builder, place with `with Locations(...)`.** `with Pos(...)` raises `'Pos' object does not support the context manager protocol`, and `Pos(...) * Ellipse(...)` inside a `BuildSketch` silently adds the ellipse at the origin. *(examples/standing-horse; blind test: cat)*
- **`Pos(p) * Rot(r) * shape` ≠ `Rot(r) * Pos(p) * shape`.** The first rotates in place and then moves; the second swings the shape around the world origin. *(blind test: castle)*
- **Select edges before adding features that create similar edges.** On a box with four through-holes, `edges().filter_by(Axis.Z)` returns 8 edges (4 corners + 4 hole seams), not 4. Fillet the corners first, then drill. *(examples/mounting-plate)*
- **Revolve profiles: start at the bore radius for a hollow part, at the axis for a solid one.** A closed profile that touches the axis revolves into a solid with no bore. *(examples/flanged-bushing)*
- **`Plane.XZ` faces −Y.** `Plane.XZ.offset(d)` is at y = −d, and a positive `extrude` goes toward −Y. `Plane.YZ.offset(x)` moves along +X. Use the plane table in `MODELING.md`. *(examples/fish)*
- **Hollow with `offset(amount=-wall, openings=face)`.** The opening face must exist on the solid; closing a revolve profile to the axis at the top creates the disc that becomes the mouth. *(examples/vase)*

## Reading the image

- **On real photos the automatic silhouette is usually unusable**: grass, trees, and backgrounds coloured like the subject (an orange cat on beige and wood) break the segmentation. The run now reports `reliable: false` with reasons; trace a polygon mask and pass `--reference-mask`. *(blind tests: dog, cat, castle)*
- **Pick model axes so the matching panel is obvious.** For a side-view image, put length on X with the visible side toward −Y, and the Front panel matches the image. For an angled photo, set `--reference-view` to the camera direction; negative values such as `-0.5,-1,0.4` work. *(blind tests: castle, cat, dog)*
- **Measure the silhouette; don't eyeball proportions.** A vase profile guessed by eye left the neck short and narrow (silhouette 0.87). Measuring half-widths at 8 evenly spaced heights fixed it (0.92). *(examples/vase)*
- **Features inside the outline don't move the silhouette score.** Adding the fish's eye and pectoral fin changed the score from 0.9437 to 0.9438. Always look at `comparison.png` as well. *(examples/fish)*
- **Line drawings get no usable silhouette** (`reliable: false`): only lines and text are foreground. For drawings, rely on the dimension gate (bounds, hole/boss counts, volume). *(examples/flanged-bushing, mounting-plate)*
- **Hole/boss checks do not check position.** Confirm hole placement in the Top panel against the drawing. *(examples/mounting-plate)*

## Process

- **Iterate with `preview`, not revisions.** Each `run` spends a revision; `preview` builds and renders a draft without touching the workflow. Two of three blind-test agents worked around the missing command by calling the runner directly. *(blind tests: cat, dog)*
- **A typo in a command no longer burns a revision.** Bad `--reference-view` values, a missing CAD interpreter, or a missing mask are rejected before the CAD run is recorded. *(blind test: cat lost r001 this way before the fix)*

## Review

- **A review that lists concrete mismatches makes the next revision easy.** "Eye missing; pectoral fin missing" with a specific `next_changes` led directly to r002. Vague notes ("looks a bit off") do not. *(examples/fish)*

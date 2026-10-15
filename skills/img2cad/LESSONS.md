# img2cad lessons

Short, verified pitfalls collected from real runs. Read before modeling; add to it after a run teaches something reusable. Each entry says what went wrong, how to avoid it, and where it was seen. Keep entries factual: only record something you actually observed, and delete or correct an entry that turns out to be wrong.

## Source check

- **A `_` throwaway variable is allowed** (`for x, _, z in points`); only `_`-prefixed function/attribute names and dunders are blocked. An earlier doc wording made one agent avoid it unnecessarily. *(blind test: castle)*
- **The source allowlist was removed from the default path.** It blocked normal modelling (`*args`, `lambda`, `Box`/`Hole` at first, and `Color`) without adding real safety, since the agent writing the model can already run shell commands. Model source is now ordinary Python; `--strict-source` brings the allowlist back for untrusted source. *(examples; blind tests; photo test: character statue)*
- **`Hole`, `Cylinder`, `Circle`, `Sphere` take a radius.** Drawings label diameters (Ø). Name parameters `*_DIAMETER` and divide by 2 at the call. *(examples/mounting-plate)*

## Geometry

- **A model that splits into several solids is broken, and now fails the gate.** In blind tests on real photos, one agent's roof floated 5 units above the top storey (2 solids), and another's fuse of cones and joint spheres silently dropped most of a dog (4 solids, volume 32.5e6 → 0.24e6 mm³). Both had passed the old gate. Overlap parts instead of touching them, and read the per-solid volumes and centres in the error to find the stray piece. *(blind tests: castle, dog; examples/standing-horse)*
- **Ball joints: turn the sphere's poles off the limb axis.** A default `Sphere` at the end of a vertical `Cone` made `fuse` leave an extra solid; `Pos(p) * Rot(90, 0, 0) * Sphere(r)` fused cleanly. *(examples/standing-horse, reproduced in isolation)*
- **In a builder, place with `with Locations(...)`.** `with Pos(...)` raises `'Pos' object does not support the context manager protocol`, and `Pos(...) * Ellipse(...)` inside a `BuildSketch` silently adds the ellipse at the origin. *(examples/standing-horse; blind test: cat)*
- **`Pos(p) * Rot(r) * shape` ≠ `Rot(r) * Pos(p) * shape`.** The first rotates in place and then moves; the second swings the shape around the world origin. *(blind test: castle)*
- **Keep a revolve's seam away from parts you fuse onto it.** `revolve` leaves a seam in the sketch plane; for a profile on `Plane.XZ` it runs down the +X side. A head revolved this way fused cleanly with its left ear but not its right one, which sat on the seam: that fuse made the shape invalid, and by the end the model had split into 10 solids. `Rot(0, 0, 90) * revolved` moves the seam to the back (+Y), where nothing attached, and the model fused into one valid solid. *(photo test: character statue)*
- **Avoid non-uniform `scale` on revolved or lofted solids you will fuse onto.** Squashing a revolved head with `.scale((1, 0.85, 1))` turned its surface into a general spline. Whether an ear then fused cleanly depended on how the ear sphere was rotated: only 1 of 3 orientations tried gave a valid shape. Keeping the round cross-section, with the seam turned away as above, fused every part cleanly. `Sphere(1).scale(...)` ellipsoids were fine. *(photo test: character statue)*
- **Close a rounded top with a revolved spline, not a loft.** A loft through measured sections ending in a small top ellipse left a flat cap with a raised rim. Adding a half-ellipsoid dome on top left a visible crease where they met. One `Spline` through all the (radius, height) points, starting and ending on the axis with `tangents=((1, 0), (-1, 0))`, then `revolve`, gave a smooth head. *(photo test: character statue)*
- **`shape.intersect(...)` returns a `ShapeList`, not a shape**, so returning it from `build_model()` fails with `build_model() must return a build123d Shape`. To trim to a region, `cut` away the outside instead, e.g. `part.cut(Pos(0, 0, -1500) * Box(6000, 6000, 3000))` to flatten at the floor. *(photo test: character statue)*
- **Select edges before adding features that create similar edges.** On a box with four through-holes, `edges().filter_by(Axis.Z)` returns 8 edges (4 corners + 4 hole seams), not 4. Fillet the corners first, then drill. *(examples/mounting-plate)*
- **Revolve profiles: start at the bore radius for a hollow part, at the axis for a solid one.** A closed profile that touches the axis revolves into a solid with no bore. *(examples/flanged-bushing)*
- **`Plane.XZ` faces −Y.** `Plane.XZ.offset(d)` is at y = −d, and a positive `extrude` goes toward −Y. `Plane.YZ.offset(x)` moves along +X. Use the plane table in `MODELING.md`. *(examples/fish)*
- **Hollow with `offset(amount=-wall, openings=face)`.** The opening face must exist on the solid; closing a revolve profile to the axis at the top creates the disc that becomes the mouth. *(examples/vase)*

## Colour

- **One part per colour.** `fuse` keeps a single colour: a black eye fused into a white body came out all white. Keep each colour region as its own part in `Compound(children=[...])`; STEP keeps every part's colour and name. *(photo test: character statue; verified by STEP re-import)*
- **A part that only connects through another part is two solids.** The fish's tail and dorsal fin as one part reported "part 'tail_and_dorsal_fin' has 2 solids"; they meet only through the body. Make them separate parts. *(examples/fish)*
- **Stack paint by lifting it.** Eye highlights on eyes and stripes on blush were lifted a little further off the surface than the layer under them, so they show on top. *(photo test: character statue)*

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

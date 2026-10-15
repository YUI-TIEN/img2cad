# img2cad lessons

Short, verified pitfalls collected from real runs. Read before modeling; add to it after a run teaches something reusable. Each entry says what went wrong, how to avoid it, and where it was seen. Keep entries factual: only record something you actually observed, and delete or correct an entry that turns out to be wrong.

## Source check

- **`*args` unpacking was rejected before it was allowlisted.** `Polygon(*points)` and `Spline(*points)` are normal build123d idioms; the source check now allows `Starred`. If the check rejects a construct, read the error and `MODELING.md` before rewriting the model. *(examples/flanged-bushing, vase, fish)*
- **`Hole`, `Cylinder`, `Circle`, `Sphere` take a radius.** Drawings label diameters (Ø). Name parameters `*_DIAMETER` and divide by 2 at the call. *(examples/mounting-plate)*

## Geometry

- **Select edges before adding features that create similar edges.** On a box with four through-holes, `edges().filter_by(Axis.Z)` returns 8 edges (4 corners + 4 hole seams), not 4. Fillet the corners first, then drill. *(examples/mounting-plate)*
- **Revolve profiles: start at the bore radius for a hollow part, at the axis for a solid one.** A closed profile that touches the axis revolves into a solid with no bore. *(examples/flanged-bushing)*
- **`Plane.XZ` faces −Y.** `Plane.XZ.offset(d)` is at y = −d, and a positive `extrude` goes toward −Y. `Plane.YZ.offset(x)` moves along +X. Use the plane table in `MODELING.md`. *(examples/fish)*
- **Hollow with `offset(amount=-wall, openings=face)`.** The opening face must exist on the solid; closing a revolve profile to the axis at the top creates the disc that becomes the mouth. *(examples/vase)*

## Reading the image

- **Measure the silhouette; don't eyeball proportions.** A vase profile guessed by eye left the neck short and narrow (silhouette 0.93). Measuring half-widths at 8 evenly spaced heights fixed it (0.98). *(examples/vase)*
- **Features inside the outline don't move the silhouette score.** Adding the fish's eye and pectoral fin changed the score from 0.951 to 0.951. Always look at `comparison.png` as well. *(examples/fish)*
- **Line drawings score low on silhouette.** Dimension text and lines count as foreground. For drawings, rely on the dimension gate (bounds, hole/boss counts, volume). *(examples/flanged-bushing, mounting-plate)*
- **Hole/boss checks do not check position.** Confirm hole placement in the Top panel against the drawing. *(examples/mounting-plate)*

## Review

- **A review that lists concrete mismatches makes the next revision easy.** "Eye missing; pectoral fin missing" with a specific `next_changes` led directly to r002. Vague notes ("looks a bit off") do not. *(examples/fish)*

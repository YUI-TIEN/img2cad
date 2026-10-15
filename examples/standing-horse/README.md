# Standing horse (visual approximation, jointed legs)

**Input:** a side-view illustration of a standing horse with its head to the left.

**How it was read:**
- Scale was assumed at 1 px = 4 mm, mapping image `(px, py)` to `x = (px - 450) * 4`, `z = (560 - py) * 4`, with the ground at z = 0.
- The camera is on the −Y side (the Front panel), so the lighter near-side legs sit at y = −150 and the darker far-side legs at y = +150.
- The hind legs bend backward at the hock, so each leg is a chain of joints read from the image: shoulder or hip, knee or hock, hoof.

**Technique:**

```python
def segment(start, end, start_radius, end_radius):
    direction = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    length = sqrt(sum(value * value for value in direction))
    return Plane(origin=start, z_dir=direction) * Cone(start_radius, end_radius, length, align=(Align.CENTER, Align.CENTER, Align.MIN))
```

- **Barrel:** a `loft` through ellipses on `Plane.YZ.offset(x)`, placed with `with Locations((0, z))`.
- **Neck, tail, ears, leg pieces:** `segment(...)` between measured points.
- **Joints:** spheres 10% larger than the limb.
- **Head and muzzle:** `Pos(...) * Sphere(1).scale((rx, ry, rz))`.
- **Hooves:** short cylinders.
- Everything is fused into one solid.

**How it was built:** `preview` was used three times before the workflow `run`, so none of these cost a revision:

1. `with Pos(0, z):` failed (`'Pos' object does not support the context manager protocol`).
2. The model came out as **9 solids with an invalid B-rep**, which the geometry gate rejects (see below).
3. The tail was too thin and the head a little small, as the silhouette overlay showed.

**Pitfalls:**

- **Ball joint fuse failure:** a default `Sphere` has its poles on Z. At the end of a near-vertical leg cone, its poles sit on the cone's axis, and `fuse` silently leaves separate solids and an invalid shape. Tracing the fuses one by one showed the barrel, neck, head and legs fused cleanly, and the first joint sphere broke it. `Rot(90, 0, 0) * Sphere(r)` turns the poles to Y, across the leg, and gives one valid solid.
- In a builder, place sketches with `with Locations((x, y)):`, not `with Pos(...)`. Outside a context, `Pos(...) * Shape` is the way to move a shape.
- The sky between the legs is enclosed by the legs and the ground. The silhouette code treats enclosed regions that match a common background colour as background, so they don't count as horse.

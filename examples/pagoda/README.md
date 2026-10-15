# Pagoda (visual approximation, stepped hipped roofs)

**Input:** a front-elevation illustration of a three-tier pagoda.

**How it was read:**
- Scale was assumed at 1 px = 25 mm (about 13 m tall), mapping image `(px, py)` to `x = (px - 320) * 25`, `z = (740 - py) * 25`.
- Only the front is shown, so the plan is assumed square.
- Each tier was measured: wall half-width, wall bottom and top, eave half-width, roof-top half-width, and roof-top height.

**Technique:** every non-box part is a ruled loft through centred squares:

```python
def square_frustum(sections):  # [(half_width, height), ...]
    with BuildPart() as solid:
        for half, height in sections:
            with BuildSketch(Plane.XY.offset(height)):
                Rectangle(2 * half, 2 * half)
        loft(ruled=True)
    return solid.part
```

- **Base:** two squares, giving the battered (sloping) stone sides.
- **Roof:** three squares (eave underside, flared eave edge, small top), giving a hipped roof with a flared eave.
- **Walls:** a `Box` per storey.
- **Finial:** a `Cylinder` plus a `Cone`.

**Pitfalls:**

- **Tiers must overlap, not just touch.** Each wall starts `WALL_OVERLAP` below the roof top under it, so every `fuse` has real overlap and the result stays one solid.
- **Windows are surface detail.** They are not modelled; cutting them would add many small booleans with no effect on the silhouette.
- **Straight hips only.** Curved Japanese roofs would need a curved profile, for example a `sweep` or a loft through more sections; this example keeps straight hips.

# Mounting plate (dimension-constrained)

**Input:** a dimensioned drawing with a top view and a side view. Every number in `model.py` comes straight from a label in the drawing, so the plan uses tight 0.01 mm checks.

**How it was read:** the outline (80 × 50), thickness (6), corner radius (R4), hole callouts (4× Ø6 THRU on a 64 × 34 pitch, Ø10 THRU at the center). The volume constraint was derived by hand in `plan.json` (`derivations`) so the gate catches a missing or wrong-size hole.

**Technique:**

```python
with BuildPart() as plate:
    Box(LENGTH, WIDTH, THICKNESS)
    fillet(plate.edges().filter_by(Axis.Z), radius=CORNER_RADIUS)
    with GridLocations(HOLE_PITCH_X, HOLE_PITCH_Y, 2, 2):
        Hole(radius=MOUNT_HOLE_DIAMETER / 2)
    Hole(radius=CENTER_HOLE_DIAMETER / 2)
```

**Pitfalls:**

- Fillet the vertical edges *before* drilling. After the holes exist, `edges().filter_by(Axis.Z)` returns 8 edges instead of 4, because each hole's vertical seam line is also a Z-parallel edge, so the fillet targets edges you did not mean to round.
- `Hole` takes a **radius**; drawings give a **diameter**.
- The dimension gate checks hole diameter and count, not hole position. Check positions in the Top panel.
- The fillet rounds show up in `cylindrical_features` as partial bosses (`full: false`). Hole/boss constraints ignore them.

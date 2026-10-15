# Flanged bushing (dimension-constrained)

**Input:** a side-view drawing of a turned part with hidden (dashed) bore lines.

**How it was read:** a dash-dot center line plus diameter (Ø) labels means the part is rotationally symmetric, so one half cross-section describes it completely. The flange is Ø40 × 5, the body is Ø24, the overall length is 25, and the bore is Ø12 THRU.

**Technique:** draw the closed half-profile on `Plane.XZ` (sketch X = radius, sketch Y = axial position, which becomes global Z) and `revolve` it about `Axis.Z`:

```python
profile = [(BORE/2, 0), (FLANGE/2, 0), (FLANGE/2, FLANGE_T), (BODY/2, FLANGE_T), (BODY/2, LENGTH), (BORE/2, LENGTH)]
with BuildPart() as bushing:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Polyline(*profile, close=True)
        make_face()
    revolve(axis=Axis.Z)
```

**Pitfalls:**

- Start the profile at the bore radius, not at the axis. A profile that touches the axis revolves into a solid with no bore.
- `Plane.XZ` maps sketch Y to global **Z** and faces −Y. Draw radius on sketch X and height on sketch Y.
- The drawing's axis is horizontal but the model's axis is Z. Say so in the review; it is an orientation choice, not an error.
- For line drawings the silhouette score is low (dimension text and lines count as foreground). Trust the dimension gate instead.

# Vase (visual approximation)

**Input:** a front-view illustration of a vase on a plain background.

**How it was read:** a round object seen from the side gives its radius at every height directly from the silhouette. The image has no scale, so 1 px ≈ 0.4 mm was assumed (200 mm tall). Half the silhouette width was measured at 8 heights: foot, lower belly, widest point, upper belly, shoulder, neck, narrowest neck, and lip. The dark ellipse at the top shows the mouth is open, so the model is hollow.

**Technique:**

```python
with BuildPart() as vase:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Line((0, 0), PROFILE[0])
            Spline(*PROFILE)
            Line(PROFILE[-1], (0, HEIGHT))
            Line((0, HEIGHT), (0, 0))
        make_face()
    revolve(axis=Axis.Z)
    offset(amount=-WALL, openings=vase.faces().sort_by(Axis.Z)[-1])
```

**Pitfalls:**

- The first attempt guessed 6 radii by eye, and the neck came out too short and narrow (silhouette 0.87). Measuring the silhouette at evenly spaced heights fixed it (0.92). Measure; don't eyeball.
- Close the profile to the axis (`Line` segments to x = 0) so `make_face` gets a closed wire. The top disc this creates is then the face passed to `offset(..., openings=...)` to open the mouth.
- `offset` with a negative amount hollows inward. A wall thinner than the tightest curvature radius can fail; 2.5 mm is safe at this size.
- The Front and Right panels are orthographic, so for a symmetric object they line up with the illustration closely. The score stays below 1 mainly because the drawn ground shadow under the foot counts as part of the object.

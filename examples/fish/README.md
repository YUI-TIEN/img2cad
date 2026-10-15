# Fish (visual approximation, coloured, registered, with a revise round)

**Input:** a side-view illustration of a fish.

**How it was read:**
- The silhouette gives length and height. Thickness is invisible, so the half-width was estimated at about 45% of the half-height.
- The tail and dorsal fin are flat shapes.
- The darker triangle on the body is the pectoral fin, and the white/black circle is the eye.
- Scale was assumed at 1 px = 0.4 mm, with image pixel (375, 260), the body centre, at the model origin.

**Technique:**

- **Body and fins**: an organic body is a `loft` through cross-sections placed along its length; flat fins are sketched polygons extruded thinly.

  ```python
  for x, half_height, half_width in BODY_SECTIONS:
      with BuildSketch(Plane.YZ.offset(x)):
          Ellipse(half_width, half_height)
  loft()
  ```

- **Registration and traced paint**: `IMAGE_FRAME = ImageFrame(mm_per_px=0.4, origin_px=(375, 260))` registers the image. The eye white, pupil, and pectoral fin were traced from the image (`scripts/trace_regions.py`, palette background/body/fin/pectoral/white/black). The outlines are embedded in `model.py` and projected onto the body with `img2cad_lib.projected_decal`. The eye white has the pupil as a hole, and the pupil fills it. Each layer is mirrored to the hidden side with `mirror(decal, about=Plane.XZ)`.
- **Colour**: each region is its own part, coloured with the colour sampled from the image. Returning `Compound(children=parts)` keeps every part's colour and name in the STEP file.

**Checking it:** `registered.png` draws the CAD in the image's own pixel frame. Registered colour IoU:

| Region | IoU |
|---|---|
| Body | 0.94 |
| Tail and dorsal fin | 0.91 |
| Pectoral fin | 0.96 |
| Eye white | 0.92 |
| Pupil | 0.84 |

The registered silhouette scores 0.95. The overlay also shows the remaining error: the lofted nose sits slightly low and wide compared with the drawn ellipse.

**Revision history:** `history/r001` is the first model. Its review found the eye and the pectoral fin missing (`verdict: revise`), so `new-revision` started r002, which added them. This is the normal loop: review against the image, list concrete mismatches, change the model, and run the checks again.

**Pitfalls:**

- The tail and dorsal fin must be two parts. They only connect through the body, so one part holding both is two solids and fails the gate.
- `Plane.YZ.offset(x)` moves along +X, so sections can be listed by x position. In `Ellipse(a, b)` on `Plane.YZ`, `a` is the Y (thickness) radius and `b` is the Z (height) radius.
- The nose and tail ends are small ellipses (a few mm), so the loft closes into a rounded tip.
- `Plane.XZ` faces −Y: `Plane.XZ.offset(d)` sits at y = −d, and a positive `extrude` goes toward −Y.
- Features inside the outline (eye, pectoral fin) barely change the normalised silhouette score (0.9437 before, 0.9438 after). The registered colour scores do see them.
- The faceted shading is preview tessellation, not the B-rep.

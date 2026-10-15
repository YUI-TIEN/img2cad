# Fish (visual approximation, coloured, with a revise round)

**Input:** a side-view illustration of a fish.

**How it was read:** the silhouette gives length and height. Thickness is invisible, so the half-width was estimated at about 45% of the half-height. The tail and dorsal fin are flat shapes. The darker triangle inside the body is the pectoral fin, and the white/black circle is the eye.

**Technique:** an organic body is a `loft` through cross-sections placed along its length; flat fins are sketched polygons extruded thinly.

```python
for x, half_height, half_width in BODY_SECTIONS:
    with BuildSketch(Plane.YZ.offset(x)):
        Ellipse(half_width, half_height)
loft()
with BuildSketch(Plane.XZ):
    Polygon(*TAIL)
    Polygon(*DORSAL_FIN)
extrude(amount=FIN_THICKNESS / 2, both=True)
```

**Colour:** each region is its own part with the colour sampled from the image (RGB / 255): orange body, darker tail and dorsal fin, darkest pectoral fins, white eyes with black pupils. Returning `Compound(children=parts)` keeps every part's colour and name in the STEP file:

```python
body.color, body.label = Color(240 / 255, 140 / 255, 60 / 255), "body"
return Compound(children=parts, label="fish")
```

**Revision history:** `history/r001` is the first model. Its review found the eye and the pectoral fin missing (`verdict: revise`), so `new-revision` started r002, which added both. This is the normal loop: review against the image, list concrete mismatches, change the model, and run the checks again.

**Pitfalls:**

- The tail and dorsal fin must be two parts: they only connect through the body, so one part holding both is two solids and fails the gate.
- `Plane.YZ.offset(x)` moves along +X, so sections can be listed by x position. In `Ellipse(a, b)` on `Plane.YZ`, `a` is the Y (thickness) radius and `b` is the Z (height) radius.
- The nose and tail ends are small ellipses (a few mm), so the loft closes into a rounded tip.
- `Plane.XZ` faces −Y: `Plane.XZ.offset(d)` sits at y = −d, and a positive `extrude` goes toward −Y. The pectoral fins use the side sign to extrude outward on each side.
- Features inside the silhouette (eye, pectoral fin) barely change the silhouette score (0.9437 before, 0.9438 after). Compare the comparison image by eye, too.
- The faceted shading is preview tessellation, not the B-rep.

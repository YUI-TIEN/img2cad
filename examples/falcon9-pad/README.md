# Falcon 9 on the pad (real photo, known dimensions, lattice towers)

**Input:** a real photo of SpaceX's Falcon 9 on its launch pad at dusk, before the 2015 DSCOVR launch. Source: scikit-image's `rocket` image, captured by SpaceX and released into the public domain.

**How the image was read:**

- **Decompose first.** The scene splits into a rocket, the transporter-erector strongback behind it, the launch mount, a pad slab, two lightning towers and their masts. The large towers cut off at the image edges are left out.
- **Use known sizes where they exist.** Falcon 9 v1.1's published dimensions (68.4 m tall, 3.66 m core, 5.2 m fairing) give the scale. The rocket spans image rows 127 to 405, so 1 px = 246 mm. The camera is far away and level, so verticals stay vertical and a front orthographic `ImageFrame` fits.
- **Measure what isn't known.** With that scale, the towers measured on 4× zooms come out as follows:
  - base 8.6 m wide;
  - platform 3.7 m wide at 54 m;
  - masts to 70 m, standing on the platforms' inner edges;
  - tower axes 32 m either side of the rocket.

**Technique:**

- **A lattice tower is one solid.** Loft a square frustum, subtract a smaller inner loft to get a shell, then cut triangular windows (the four triangles of each X-braced bay) through the faces. Each window is cut by a prism along Y and another along X. That gives nine braced bays from one `loft` and one boolean cut, instead of fusing about a hundred struts.

  ```python
  shell = loft([square(0, base_half), square(h, top_half)]) - loft([...inner...])
  cutters = [extrude(Plane.XZ * Polygon(*tri, align=None), amount=big, both=True) for tri in windows]
  lattice = shell - Compound(children=cutters)
  ```

- The rocket is one spline-tipped revolve. The strongback, mount and slab are boxes, and every part sits on the slab, so the assembly touches.

**Checking it:** in `registered.png`, the rocket outline, both towers' leg lines, the nine bays, the platforms, the masts and the launch mount all land on the photo. The per-colour IoU is not meaningful for this photo. At dusk the white rocket photographs tan, and the towers are thin lines against the sky. That is why this example is reviewed by eye on the overlay, not by score.

**Pitfalls:**

- **The towers are not in the rocket's plane.** One front view can't tell their depth, so they are placed in that plane. Their image sizes are right, but their true sizes are not.
- **Masts are off-axis.** In the photo, each mast stands on the inner edge of its platform. The first preview put them on the tower axes, about 9 px off.
- **Check the overlay, not just the scores**, when the lighting makes colours unreliable.

# Espresso cup (real photo, perspective registration, coloured)

**Input:** a real photo of an espresso cup on a saucer with a teaspoon, shot from the front and well above. Source: scikit-image's `coffee` image, CC0 by Rachel Michetti ("No copyright restrictions"; courtesy of Pikolo Espresso Bar).

**How the image was read:**

- **Decompose first.** The parts are a saucer, a cup body (red outside), a white glaze (inside and on the rim), the espresso, a handle and a teaspoon. Everything except the handle and spoon is a solid of revolution.
- **Measure the main bodies.** The cup rim, saucer rim and cup foot are circles, so they image as ellipses. `fit_camera.py` fits a perspective `ImageFrame` to hand-picked edge points on all three by least squares. Result: camera 57° above the table and 0.63 m away, 0.301 mm/px, 2.3 px RMS. An orthographic frame fits the points almost as well (2.5 px) but puts the cup 16 mm behind the saucer centre. That is not physical, so use perspective for close-up photos.
- **Solve the profile through the camera.** `fit_profile.py` turns the cup's left and right silhouette edges at four image rows into (radius, height) pairs. The two sides agree within 2 mm.
- **Use typical sizes for small parts.** The spoon is small, shiny and partly hidden, so its depth cannot be read off the photo. It is a typical 105 mm teaspoon lying in the saucer with its handle on the rim, anchored on two pixels.
- **Scale** is an assumed 120 mm saucer, which gives a 68 mm rim.

**Technique:**

```python
IMAGE_FRAME = ImageFrame(mm_per_px=0.301, origin_px=(276.0, 235.4),
                         view=(0, -cos(57°), sin(57°)), distance=629.5)   # perspective camera
IMAGE_FRAME.project(x, y, z)        # model point -> pixel
IMAGE_FRAME.on_plane_z(px, py, z)   # pixel -> model point at height z
```

- The cup body, glaze and espresso are spline revolves (`revolve_path`). The handle ring fuses into the body.
- The handle's azimuth and height are solved so that the ring centre projects onto the handle in the photo.

**Checking it:** `registered.png` draws the CAD from the fitted camera over the photo.

| Check | Score |
|---|---|
| Registered silhouette (cup + saucer + spoon mask, `reference_mask.png`) | 0.98 |
| Red glaze | 0.74 |
| White glaze | 0.50 |
| Crema | 0.36 |
| Spoon | 0.13 |

The white and crema scores are limited by lighting: the cup's inner wall reflects the coffee, so the photo labels it "crema". The spoon bowl sits about 25 px right of the photo, because where its pixel ray meets the saucer, the cup's overhang leaves no room.

**Pitfalls (all hit while building this):**

- **Don't solve small parts from pixels.** Solving the spoon's depth from pixel rays and contact took about six previews and stood the spoon upright against the cup. Reading the scene ("it lies in the saucer") and using a typical size took one preview.
- **Fusing a `Sphere(1).scale(...)` bowl to a cylinder wrote a STEP that lost the bowl** (3174 → 696 mm³ after re-import). The runner now fails on any STEP volume loss. Keep such pieces as separate parts.
- **Revolve splines, not dense polygons.** A 64-segment polygon revolve made the handle fuse fail (2 solids, invalid B-rep). A spline profile fused cleanly.
- **A sketch revolved about an axis normal to its own plane has zero volume.** The handle's tube section must lie in a plane that contains the ring's axis.
- **One pixel is a ray, not a point.** Without the foot-arc constraint, cup height and depth trade off along the rays, and the first fit made the cup 10 mm too tall.

# Changelog

All notable changes. Versions follow `VERSION`; plugin manifests carry the same number.

## 0.12.0

- **`img2cad hull`.** A visual-hull blockout from two or three silhouettes (front, right, top), plus `img2cad_lib.visual_hull`. It writes `hull.step`, the traced outlines, and a `model_hull.py` to carve from.
- **PDF engineering drawings.** `img2cad drawing` writes a vector `drawing.pdf` (no extra dependencies) next to SVG and DXF.
- **Category checklists** in MODELING.md for filling the detail inventory (mechanical, tableware, vehicles, animals, characters, buildings, products).
- **Example parameters** carry `[min, max] label` ranges for the parameter panel. Comments only; geometry unchanged.
- **Release workflow.** Pushing a `vX.Y.Z` tag builds and smoke-tests the wheel, publishes to PyPI via trusted publishing, and creates a GitHub release from this file.
- **Verified the plugin path.** `claude plugin validate` passes for the plugin, marketplace and skills. The plugin installs in Claude Code (2 skills, 1 MCP server). The MCP server and `img2cad doctor` run from `uvx --from git+https://github.com/YUI-TIEN/img2cad`. Added a marketplace description.

## 0.11.0

- **Parameter panel.** `img2cad view model.py` builds the model and lists its parameters (module-level UPPERCASE numbers, with `# [min, max] label` ranges). You can drag labels Figma-style or type values, and the model rebuilds locally without an AI round trip. Save writes the values back (with `model.py.bak`). `img2cad params` does the same from the shell.
- **Viewer redesign.** Liquid-glass panels (blur, specular sheen, refracting rim, SVG refraction on Chromium) in light and dark. Layers panel with show/hide. Properties panel with Parameters and Inspect tabs. Floating toolbar with shortcuts, section popover, toasts, animated camera moves, soft shadows, and a mobile bottom sheet.

## 0.10.0

- **Decomposition gate.** Visual-approximation plans must list `parts` (each with a technique and a size source: measured, known or estimated), a `detail_inventory` (every identity-defining detail with its part and handling: modelled, painted, or omitted with a reason), and ordered build `passes`.
- **Staged passes.** `workflow preview --stage blockout|form|detail|colour` and `workflow pass-review`. Passes cannot be skipped, the detail pass must check every non-omitted detail, and `source-review` is refused until all passes pass.
- **`img2cad camera`.** Fits an `IMAGE_FRAME` (orthographic or perspective) to picked points on known circles and points, and solves silhouette pixels into a revolve profile. It refuses when the fit is poor or any value is not pinned down, reports priors as assumptions, and always writes a check overlay.
- **`img2cad mask`.** Subject masks from polygons, ellipses and colour seeds.

## 0.9.x

- Real-photo examples: `espresso-cup` (perspective registration fitted to three circles) and `falcon9-pad` (known dimensions, lattice towers).
- `ImageFrame` gains `view`, `roll` and `distance`, plus `project()` and `on_plane_z()`. Decals and the registered overlay use the photo's camera.
- The worker re-imports the STEP and fails when the export lost geometry.
- SKILL.md rule: measure the main bodies, use typical sizes for small parts, time-box a part to two previews.
- `img2cad` CLI (pip/uvx), `doctor`, GLB/3MF/STL exports, local 3D viewer, MCP server, engineering drawings, printability check, plugin manifests, GitHub Pages site, CI.

## 0.8 and earlier

- Staged, hash-bound workflow; geometry gate (one solid per part, touching assemblies); coloured assemblies; traced decals; registered per-colour overlay; worked examples; LESSONS.md.

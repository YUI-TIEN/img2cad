---
name: cad-output
description: Turn a finished STEP model into deliverables - interactive 3D view, GLB/STL/3MF meshes, a dimensioned engineering drawing (SVG/DXF), and a 3D-printability report. Use after img2cad produced a model, or for any STEP the user supplies.
---

# cad-output — view, export, draw, and print-check a CAD model

Use the `img2cad` command described in [`../img2cad/SKILL.md`](../img2cad/SKILL.md) ("The `img2cad` command"). All commands read the saved STEP, so every deliverable matches the checked B-rep.

## View

```sh
img2cad view model.step [more files...]          # opens the browser
img2cad view model.step --no-open --json         # prints {"url": ...}; keeps serving
```

The viewer shows STEP, GLB, STL and 3MF with part colours. Use the standard views (Front from −Y, Right from +X, Top from +Z, Iso), the part list (click to select, toggle visibility), **Measure** (pick two points; reports distance and ΔX/ΔY/ΔZ in model mm), **Section** along X/Y/Z, wireframe, and screenshot. Through MCP, `img2cad_show` returns the same URL.

## Export meshes

`img2cad workflow run` and `preview` already write `model.glb`, `model.stl` and `model.3mf` next to `model.step` (turn off with `--mesh-formats none`). For any other STEP:

```sh
img2cad export model.step out/ --formats glb,stl,3mf [--tolerance 0.05]
```

| Format | Keeps | Use for |
|---|---|---|
| GLB | part names and colours (glTF, metres, Y-up) | web, viewers, AR |
| 3MF | one object per part with its colour, mm | slicers, multi-colour printing |
| STL | one uncoloured mesh, mm | tools that only read STL |

The tessellation tolerance defaults to 1/2000 of the model diagonal (at least 0.01 mm).

## Engineering drawing

```sh
img2cad drawing model.step out/ --name "Mounting plate"      # out/drawing.svg + out/drawing.dxf
```

Third-angle sheet: front view (looking along +Y), top view above it, right view beside it; visible edges solid, hidden edges dashed; overall width, height and depth dimensioned; and a note block listing every full cylindrical hole/boss with diameter, axis and position. Check the hole table against the source drawing: it is the fastest way to catch a hole in the wrong place, which the dimension gate does not check. The DXF opens in any 2D CAD tool for further dimensioning.

## 3D-printability check

```sh
img2cad printcheck model.step [--build-volume 220,220,250] [--min-wall 0.8] [--overhang 45]
```

Orient the model as it will print (Z up, bed at the lowest point). The report gives `pass`/`warn`/`fail` per check and an overall status (exit code 1 on fail):

- `watertight` — every part closed and manifold; `solids` — no loose pieces inside a part;
- `build_volume` — fits the printer; `bed_contact` — enough area on the bed to stay put;
- `overhangs` — downward area steeper than the limit (needs supports);
- `thin_walls` — sampled wall thickness under `--min-wall`.

Visual-approximation models usually warn: organic undersides overhang, and projected paint decals (`projected_decal`) are deliberately about 0.5 mm thick. For a print, either thicken the paint (`depth=`), print it as a separate colour (3MF keeps parts), or drop it; add a flat base by cutting the bottom (`part.cut(Pos(0, 0, z0 - big / 2) * Box(big, big, big))`). Report warnings to the user rather than claiming a model is print-ready.

# Worked examples

Each directory is a complete, accepted `scripts/agent_workflow.py` run copied here with `promote`, so an agent can see the whole chain: **image → observations → plan → build123d source → checks → comparison → review**. Read the example closest to your task before modeling. `espresso-cup` and `falcon9-pad` start from real public-domain photos (credits in each README). The others use references drawn for this repo.

| Example | Target | Main technique | Read it for |
|---|---|---|---|
| [`espresso-cup`](espresso-cup/) | visual approximation, coloured, **real photo** | perspective `IMAGE_FRAME` fitted to three circles; profile solved from silhouette edges; spline revolves; typical-size teaspoon | angled close-up photos; measuring through a fitted camera; deciding what to measure and what to take from typical sizes |
| [`falcon9-pad`](falcon9-pad/) | visual approximation, coloured, **real photo** | published rocket dimensions as scale; lattice towers as one cut shell | scenes with a known object; trusses, towers, lattices; judging by overlay when colours mislead |
| [`mounting-plate`](mounting-plate/) | dimension-constrained | `Box` + `fillet` + `GridLocations`/`Hole` | prismatic parts with hole patterns, reading a dimensioned drawing, hole/volume constraints |
| [`flanged-bushing`](flanged-bushing/) | dimension-constrained | half-profile + `revolve` | turned/round parts, bores, boss/hole constraints |
| [`vase`](vase/) | visual approximation | silhouette-measured `Spline` + `revolve` + `offset` shell | round organic objects from one front view, hollow parts |
| [`fish`](fish/) | visual approximation, coloured | `loft` through `Ellipse` sections + thin fins; paint traced and projected with `projected_decal`; `IMAGE_FRAME` registration | organic bodies; precise painted details; per-colour scoring in `registered.png`; a real `revise` → `r002` round in `history/` |
| [`standing-horse`](standing-horse/) | visual approximation | point-to-point `Cone` limbs + rotated ball joints, ellipsoids, lofted barrel | animals with legs or any jointed/limbed shape; fusing many parts into one solid; using `preview` |
| [`pagoda`](pagoda/) | visual approximation | ruled `loft` through squares for battered base and hipped roofs | buildings, roofs, stepped/tiered structures |
| [`../benchmark/cases/visual-pose-dog`](../benchmark/cases/visual-pose-dog/) | visual approximation | scaled `Sphere`/`Cylinder` primitives in a `Compound` | quickest blocky approximation (frozen benchmark fixture; multi-solid, so it needs `allow_multiple_solids`) |

Files in each example:

- `reference.png` — input image.
- `observations.json`, `plan.json` — what was seen, inferred, and planned (the workflow's recorded inputs).
- `model.py` — final reviewed build123d source.
- `comparison.png` — reference beside the four CAD views (Front from −Y, Right from +X, Top, Isometric); `silhouette.png` — advisory overlap overlay (gray both, red reference only, blue CAD only); `registered.png` (when the model defines `IMAGE_FRAME`) — the CAD drawn on the image in its own pixel frame.
- `visual_review.json` — hash-bound agent review. `history/rNNN/` holds earlier revisions when there were any.
- `example.json` — techniques, measured geometry, dimension checks, silhouette score, revision history, and file hashes.
- `README.md` — how the image was read and the pitfalls hit while building it.

All reviews are agent reviews (`human_acceptance: not_verified`).

## Adding an example

After a run whose visual review is `acceptable`:

```sh
img2cad workflow promote /path/to/work --name short-slug \
  --technique "main build123d technique" --technique "anything else worth copying"
```

Then add a short `README.md` in the new directory and a row to the table above. Add any general pitfall to [`skills/img2cad/LESSONS.md`](../skills/img2cad/LESSONS.md).

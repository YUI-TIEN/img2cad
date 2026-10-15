# Worked examples

Each directory is a complete, accepted `scripts/agent_workflow.py` run copied here with `promote`, so an agent can see the whole chain: **image → observations → plan → build123d source → checks → comparison → review**. Read the example closest to your task before modeling. The references are synthetic (drawn for this repo), not real photos.

| Example | Target | Main technique | Read it for |
|---|---|---|---|
| [`mounting-plate`](mounting-plate/) | dimension-constrained | `Box` + `fillet` + `GridLocations`/`Hole` | prismatic parts with hole patterns, reading a dimensioned drawing, hole/volume constraints |
| [`flanged-bushing`](flanged-bushing/) | dimension-constrained | half-profile + `revolve` | turned/round parts, bores, boss/hole constraints |
| [`vase`](vase/) | visual approximation | silhouette-measured `Spline` + `revolve` + `offset` shell | round organic objects from one front view, hollow parts |
| [`fish`](fish/) | visual approximation | `loft` through `Ellipse` sections + thin extruded fins | free-form organic bodies; includes a real `revise` → `r002` round in `history/` |
| [`../benchmark/cases/visual-pose-dog`](../benchmark/cases/visual-pose-dog/) | visual approximation | scaled `Sphere`/`Cylinder` primitives in a `Compound` | quickest blocky approximation (frozen benchmark fixture) |

Files in each example:

- `reference.png` — input image.
- `observations.json`, `plan.json` — what was seen, inferred, and planned (the workflow's recorded inputs).
- `model.py` — final reviewed build123d source.
- `comparison.png` — reference beside the four CAD views; `silhouette.png` — advisory overlap overlay (gray both, red reference only, blue CAD only).
- `visual_review.json` — hash-bound agent review. `history/rNNN/` holds earlier revisions when there were any.
- `example.json` — techniques, measured geometry, dimension checks, silhouette score, revision history, and file hashes.
- `README.md` — how the image was read and the pitfalls hit while building it.

All reviews are agent reviews (`human_acceptance: not_verified`).

## Adding an example

After a run whose visual review is `acceptable`:

```sh
python3 -B scripts/agent_workflow.py promote /path/to/work --name short-slug \
  --technique "main build123d technique" --technique "anything else worth copying"
```

Then add a short `README.md` in the new directory and a row to the table above. Add any general pitfall to [`skills/img2cad/LESSONS.md`](../skills/img2cad/LESSONS.md).

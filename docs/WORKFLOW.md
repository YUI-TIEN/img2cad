# Workflow reference

The staged, hash-bound workflow behind `img2cad workflow`. Agents follow [skills/img2cad/SKILL.md](../skills/img2cad/SKILL.md); this page is the human-oriented reference.

## Overview

The repository-owned agent procedure is [`skills/img2cad/SKILL.md`](../skills/img2cad/SKILL.md), routed through [`AGENTS.md`](../AGENTS.md). For the general path, use the resumable `scripts/agent_workflow.py` coordinator around `scripts/run_agent_cad.py` and `scripts/record_visual_review.py`. It records image evidence and plan, pins inspected model source, executes the local CAD/STEP gate, and binds review to that run's hashes. An optional manual camera direction can replace the generic isometric preview; it is not automatic photo alignment. `run_report.json` records **geometry/STEP success only**, never visual fidelity. The review record preserves the declared reviewer and notes but cannot independently prove a human inspected or accepted the image. The separate `scripts/run_pipeline.py` remains a constrained benchmark path requiring a pre-authored spec; its generator only creates a rectangular prism with optional through-holes. The optional vision adapter is not required for an agent that already has image input capability.

## Resumable general workflow CLI

Use `img2cad workflow` (`scripts/agent_workflow.py`) for the ordinary image-led path. It stores a local `workflow.json`, pins the reference image, records stage input/output hashes and a `next_step` for each stage, and reports the next action on `status`. Each workflow directory is new; revisions are append-only, with the earlier CAD run retained. This state machine coordinates the agent's judgments—it does not infer observations, inspect visual quality, or turn an agent review into human acceptance.

```sh
img2cad workflow init /path/to/work --reference /path/to/image.png --target-type visual_approximation
img2cad workflow status /path/to/work
img2cad workflow observations /path/to/work --file /path/to/observations.json
img2cad workflow plan /path/to/work --file /path/to/plan.json
img2cad workflow preview /path/to/work --model /path/to/draft.py   # iterate freely; no stage changes
img2cad workflow source-review /path/to/work --model /path/to/model.py \
  --inspection-note "Checked the source against the plan; only intended build123d geometry is created."
img2cad workflow run /path/to/work
img2cad workflow review /path/to/work --notes /path/to/review.json
img2cad workflow promote /path/to/work --name short-slug --technique "what it demonstrates"
```

`run` uses `--cad-python`, else `$IMG2CAD_CAD_PYTHON`, else the clone's `.venv-cad/bin/python`, else the interpreter running `img2cad`.

## Learning material for agents

- [`skills/img2cad/MODELING.md`](../skills/img2cad/MODELING.md): the allowed build123d API, plane orientation, technique-by-object-type table, how to read sizes from images, and the declarable checks.
- [`examples/`](../examples/README.md): accepted end-to-end runs (dimensioned plate, revolved bushing, revolved and shelled vase, lofted fish with a revise round, jointed standing horse, tiered pagoda), each with reference, observations, plan, model, comparison, silhouette overlay, review, and a short write-up.
- [`skills/img2cad/LESSONS.md`](../skills/img2cad/LESSONS.md): verified pitfalls from real runs.
- [`skills/cad-output/SKILL.md`](../skills/cad-output/SKILL.md): viewing, mesh export, engineering drawings, and printability checks for a finished model.
- Precision tools:
  - `scripts/trace_regions.py` traces colour regions of the photo into pixel outlines.
  - `scripts/img2cad_lib.py`, importable from `model.py`, provides `ImageFrame` registration, `projected_decal` for exact painted details on curved surfaces, and helpers for revolves, limbs, and joints.
  - With `IMAGE_FRAME` set, runs draw the CAD on the photo (`registered.png`) and score each colour region against it.

`promote` copies an accepted workflow into `examples/` so later agents can reuse it; new pitfalls go into `LESSONS.md`. This is how the repository accumulates experience across runs; agents do not otherwise remember earlier sessions.

Observation JSON uses `observed`, `inferred`, `unknowns` string arrays and `evidence` objects with `claim` and `source`. Plan JSON includes `target_type` (`visual_approximation` or `dimension_constrained`), `goal`, nonempty `geometry_plan`, `constraints`, and `unknowns`. For dimension-constrained plans, `constraints` can declare overall bounds (`length`/`width`/`height` or `x`/`y`/`z`, optional `tolerance`, default 0.02 model units), `volume` (explicit absolute tolerance), and `hole`/`boss` diameter and count; the workflow compares them with the STEP inspection. Feature positions are not checked and remain review criteria. The geometry gate requires each part to be one solid (a single fused body, or each part of a coloured `Compound(children=[...])` assembly, whose part colours and names are kept in the STEP) unless the plan sets `"allow_multiple_solids": true`. `run` and `preview` also write an advisory silhouette comparison (`silhouette.png` and a best-view IoU, with a `reliable` flag that is false when the image's background could not be separated); for real photos pass a traced `--reference-mask`. It helps spot proportion errors but is never a gate. Review JSON follows `scripts/record_visual_review.py`: reviewer, verdict (`acceptable`, `revise`, or `blocked`), compared views, matches, mismatches, next_changes, and assumptions. `revise` must name mismatches and geometry/parameter changes; `blocked` must identify missing evidence in `next_changes`.

The CLI refuses to run CAD before source review, refuses visual review unless geometry/STEP and (for dimension-constrained work) declared bounding-dimension gates pass, checks source/reference/artifact hashes, and stores the exact reviewer/verdict separately from geometry status. After `revise` or `blocked` (or a failed geometry/dimension run), start a fresh revision with `new-revision --reason ...`; it preserves the prior run and inherits observations/plan. If new evidence or a changed plan is needed, record it into the new revision; source, geometry, dimensions, and visual-review gates reset. Do not reuse a previous preview's review for the new source. `human_acceptance` remains `not_verified` even when the agent review is acceptable.

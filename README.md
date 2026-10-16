# img2cad

An image-to-parametric-CAD workflow: turn a product image, sketch, or engineering drawing into a reviewable CAD specification, an editable solid model, and validated exchange files such as STEP.

> **Status:** early workflow prototype. The repository has an agent skill, a local runner for reviewed agent-authored build123d source, generic STEP inspection and preview generation, plus a constrained spec-to-CAD benchmark runner. The agent still performs image interpretation, model authoring, preview review, and refinement; the local runner handles CAD execution and artifact checks.

**Website:** <https://yui-tien.github.io/img2cad/> — how the pipeline works, with interactive 3D examples.

## Quick start

img2cad is a set of agent skills plus one command-line tool, `img2cad`. Install it in your agent, then give the agent an image and ask for CAD.

| Host | Install |
|---|---|
| Claude Code | `/plugin marketplace add YUI-TIEN/img2cad` then `/plugin install img2cad@img2cad` |
| Codex, Cursor | add this repository as a plugin (`.codex-plugin/`, `.cursor-plugin/`) |
| Gemini CLI | `gemini extensions install https://github.com/YUI-TIEN/img2cad` |
| Any agent with skills | `npx skills add YUI-TIEN/img2cad` |
| Any MCP host | server command `uvx --python 3.13 --from git+https://github.com/YUI-TIEN/img2cad img2cad mcp` |

The command line works without a clone (needs [uv](https://docs.astral.sh/uv/)):

```sh
uvx --python 3.13 --from git+https://github.com/YUI-TIEN/img2cad img2cad doctor     # check the CAD stack
uv tool install --python 3.13 git+https://github.com/YUI-TIEN/img2cad               # or put `img2cad` on PATH
```

From a clone, use `.venv-cad/bin/python scripts/img2cad_cli.py` in place of `img2cad`:

```sh
python3 -m venv .venv-cad && .venv-cad/bin/pip install -r requirements-cad.lock
.venv-cad/bin/python scripts/img2cad_cli.py doctor
```

| Command | What it does |
|---|---|
| `img2cad workflow ...` | staged, resumable image → CAD workflow (init, observations, plan, preview, source-review, run, review, new-revision, promote, status) |
| `img2cad build model.py out/` | build one `model.py`: STEP + GLB/STL/3MF, checks, previews, comparison, registered overlay |
| `img2cad trace image.png ...` | trace colour regions of a reference image into pixel outlines |
| `img2cad inspect model.step` | measure a STEP: validity, solids, parts and colours, bounds, volume, holes/bosses |
| `img2cad view model.py` | 3D viewer with a live parameter panel (drag, type, rebuild locally, save back); also opens STEP/GLB/STL/3MF |
| `img2cad params model.py` | list or set a model's parameters (module-level UPPERCASE numbers) |
| `img2cad camera camera.json` | fit the photo's camera to known circles/points; refuses poor or under-constrained fits |
| `img2cad mask photo.png mask.png` | subject mask from polygons, ellipses, colour seeds |
| `img2cad export model.step out/` | GLB (coloured), 3MF (coloured parts), STL |
| `img2cad drawing model.step out/` | three-view SVG/DXF drawing with overall dimensions and a hole table |
| `img2cad printcheck model.step` | watertight, overhangs, bed contact, thin walls, build volume |
| `img2cad mcp` | the same tools over MCP (stdio) |
| `img2cad doctor` / `version` | environment check / version |

**Outputs of every run:** `model.py` (the editable source of truth), `model.step` (B-rep with part names and colours), `model.glb`, `model.3mf`, `model.stl`, `preview.png`, `comparison.png`, `silhouette.png`, `registered.png` (when the model registers the image), `inspection.json` and `run_report.json`.

## Problem

Image-to-3D tools can create visually convincing 3D models, while CAD tools can create editable solids from code. img2cad's intended workflow is for an agent to inspect the image, plan the geometry, author a parametric CAD model, and compare a render with the reference. The difficult gap is making that model both visually faithful and a valid, editable CAD artifact—not choosing a particular vision API.

A single image cannot reveal hidden geometry or true scale. The workflow must expose uncertainty and distinguish an approximate visual model from dimensionally constrained engineering CAD.

## Product goal

Given one or more images and optional dimensions, the agent should help a user produce:

1. A structured, inspectable description of the part or assembly.
2. A native parametric model that can be edited and regenerated.
3. A valid STEP export, plus preview formats when useful.
4. Evidence of geometric checks and a visual comparison against the reference.

The primary success criterion is a useful CAD artifact whose fidelity and editability are reported honestly. A visually similar organic model and a dimensionally constrained engineering part are both valid targets, but they have different acceptance criteria.

## Proposed workflow

```text
Image(s) + optional measurements
  → agent inspects image using its already-available visual capability
  → observations, geometry plan, confidence / unknowns
  → agent authors an editable build123d CAD model
  → local CAD kernel builds, measures, and exports STEP / preview
  → compare preview with reference and revise the model
  → report estimates, checks, and remaining limitations
```

No separate third-party vision service or API key is required by this workflow. The optional vision adapter is a separate integration for users who explicitly choose provider-backed inference; it is not the default agent path.

### 1. Assess the input

Classify the input as a product photo, sketch, or dimensioned drawing. Identify view count, occlusion, perspective, visible scale cues, and whether the target is primarily prismatic/mechanical or organic. If the image is unsuitable or confidence is low, request another view or route the task to manual input.

### 2. Plan the geometry and record an `Object2CADSpec`

Create a versioned JSON specification before generating geometry. It should record:

- Components and assembly relationships.
- Candidate features (for example, base extrusion, hole pattern, revolve, pocket, rib).
- Coordinate frame, units, datums, and dimensional constraints.
- Observed evidence and source view for each feature.
- Confidence, assumptions, and unresolved questions per feature/dimension.
- Manufacturing intent when known (3D print, CNC, sheet metal, or visual prototype).

Keep observed facts separate from inferred geometry. For a visual prototype, proceed with clearly labeled estimates rather than blocking on engineering dimensions. Ask only when a missing fact materially changes the requested result. The current v1 schema is limited to one rectangular prism and holes; it is a benchmark fixture, not yet a general geometry plan for organic shapes or assemblies.

### 3. Generate native CAD

The intended agent path is to author ordinary, parameterized build123d code using Open CASCADE from the image observations and geometry plan. Preserve meaningful parameters and feature-level structure so the model can be edited and regenerated. Organic forms may need lofts, sweeps, or carefully joined solids; a mesh-only result is not equivalent to an editable CAD model. STEP is the primary interchange output; STL/GLB are derived previews, not the source of truth.

### 4. Validate geometry

Before claiming success, check that the model builds, contains valid positive-volume solids where expected, satisfies any explicit dimensions and constraints, and can be exported and re-imported from STEP. For an approximate visual model, report estimated scale and visual fidelity separately from dimensional validation. Add manufacturability checks only for the chosen process; a successful export alone does not establish engineering correctness.

### 5. Review and refine

Render the generated CAD from the input camera/view where possible and from a small set of diagnostic views. Compare silhouette, proportions, component placement, and specified feature locations using the agent's already-available image capability; this does not imply adding a vision service. Use deterministic checks for measurable geometry. Every correction should identify whether it changes the spec, the code, or an assumption.

## Design principles

- **CAD-first:** the editable parametric solid is canonical; meshes and renders are derived.
- **Evidence-aware:** every inferred feature has a confidence and an evidence source.
- **Human-confirmed constraints:** do not invent scale or hidden dimensions and label them as facts.
- **Progressive automation:** support visual organic models and constrained mechanical parts with the right fidelity/measurement criteria for each; route genuinely ambiguous requirements to a question or documented best-effort result.
- **Reviewable loop:** retain input, spec, generated source, validation results, and revision history together.
- **Controlled execution:** review model source before running it. Agent-authored model source is ordinary Python with the full build123d API, run in an isolated subprocess with a timeout; it is **not sandboxed**, so only execute source you have inspected. An optional `--strict-source` allowlist check exists for source you did not write.

## MVP scope

Start with the agent-led loop: inspect a user image, plan geometry, author a build123d model, run local checks, inspect a preview, and make a bounded correction. Include both a visual-model case (the frozen synthetic dog illustration) and a dimensioned mechanical case, with different acceptance criteria. Defer guaranteed hidden-surface reconstruction and claims of production readiness without process-specific engineering checks.

## Relationship to existing projects

The original concept combines **img2threejs**' staged image inspection and render/revise loop with **txt2cad**'s CAD modeling/output direction. The exact upstream repository identity of `txt2cad` has not been verified; do not equate it with a similarly named GitHub repository. These are conceptual inputs, not claims that this repository imports their code or reproduces their implementation.

The proposed contribution is the agent workflow that bridges image evidence → geometry plan / uncertainty-bearing spec → agent-authored native parametric model → geometry and visual review. Requiring a pre-filled spec and a fixed shape generator is useful for a deterministic fixture, but is not the intended general image-to-CAD interaction.

## Initial acceptance criteria

For a supported test part with a reference image and known key dimensions:

- The workflow produces a spec that distinguishes observed, inferred, and user-confirmed values.
- The generated build123d model executes and exports a STEP file that can be re-imported.
- Explicit dimensions and feature counts pass geometric checks.
- A reviewer can inspect and edit model parameters without editing a triangle mesh.
- The review screen shows the reference, generated preview, validation results, and remaining assumptions.
- Unsupported or ambiguous input is reported as such rather than marked as a successful engineering reconstruction.

## Suggested first prototype

Use the frozen synthetic dog illustration in `benchmark/cases/visual-pose-dog` as an initial visual-model acceptance case: inspect the image, document observed/inferred/unknown geometry, author an editable approximation, export and check it locally, inspect the preview, and record a separate finding for each visual criterion. It is an illustration fixture, not evidence of performance on real photographs. Keep `benchmark/cases/repro-block` as the separate dimensioned mechanical case for exact constraints and STEP round-trip behavior. Neither case requires adding a third-party vision API solely to follow the workflow.

## Repeatable validation

The benchmark format and local validation commands are defined in [`benchmark/README.md`](benchmark/README.md). Two frozen fixtures separate visual approximation (`benchmark/cases/visual-pose-dog`) from dimension-constrained CAD (`benchmark/cases/repro-block`). The validator checks case/run metadata, input and artifact hashes, per-case gates, criterion-level visual review, and dimension tolerances across repeat runs. It is a reproducibility scaffold—not a CAD kernel or an independent visual judge; geometry and STEP round-trip checks must be performed by the CAD runner, and visual criteria must be reviewed against the comparison image.

## Agent workflow

The repository-owned agent procedure is [`skills/img2cad/SKILL.md`](skills/img2cad/SKILL.md), routed through [`AGENTS.md`](AGENTS.md). For the general path, use the resumable `scripts/agent_workflow.py` coordinator around `scripts/run_agent_cad.py` and `scripts/record_visual_review.py`. It records image evidence and plan, pins inspected model source, executes the local CAD/STEP gate, and binds review to that run's hashes. An optional manual camera direction can replace the generic isometric preview; it is not automatic photo alignment. `run_report.json` records **geometry/STEP success only**, never visual fidelity. The review record preserves the declared reviewer and notes but cannot independently prove a human inspected or accepted the image. The separate `scripts/run_pipeline.py` remains a constrained benchmark path requiring a pre-authored spec; its generator only creates a rectangular prism with optional through-holes. The optional vision adapter is not required for an agent that already has image input capability.

### Resumable general workflow CLI

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

### Learning material for agents

- [`skills/img2cad/MODELING.md`](skills/img2cad/MODELING.md): the allowed build123d API, plane orientation, technique-by-object-type table, how to read sizes from images, and the declarable checks.
- [`examples/`](examples/README.md): accepted end-to-end runs (dimensioned plate, revolved bushing, revolved and shelled vase, lofted fish with a revise round, jointed standing horse, tiered pagoda), each with reference, observations, plan, model, comparison, silhouette overlay, review, and a short write-up.
- [`skills/img2cad/LESSONS.md`](skills/img2cad/LESSONS.md): verified pitfalls from real runs.
- [`skills/cad-output/SKILL.md`](skills/cad-output/SKILL.md): viewing, mesh export, engineering drawings, and printability checks for a finished model.
- Precision tools:
  - `scripts/trace_regions.py` traces colour regions of the photo into pixel outlines.
  - `scripts/img2cad_lib.py`, importable from `model.py`, provides `ImageFrame` registration, `projected_decal` for exact painted details on curved surfaces, and helpers for revolves, limbs, and joints.
  - With `IMAGE_FRAME` set, runs draw the CAD on the photo (`registered.png`) and score each colour region against it.

`promote` copies an accepted workflow into `examples/` so later agents can reuse it; new pitfalls go into `LESSONS.md`. This is how the repository accumulates experience across runs; agents do not otherwise remember earlier sessions.

Observation JSON uses `observed`, `inferred`, `unknowns` string arrays and `evidence` objects with `claim` and `source`. Plan JSON includes `target_type` (`visual_approximation` or `dimension_constrained`), `goal`, nonempty `geometry_plan`, `constraints`, and `unknowns`. For dimension-constrained plans, `constraints` can declare overall bounds (`length`/`width`/`height` or `x`/`y`/`z`, optional `tolerance`, default 0.02 model units), `volume` (explicit absolute tolerance), and `hole`/`boss` diameter and count; the workflow compares them with the STEP inspection. Feature positions are not checked and remain review criteria. The geometry gate requires each part to be one solid (a single fused body, or each part of a coloured `Compound(children=[...])` assembly, whose part colours and names are kept in the STEP) unless the plan sets `"allow_multiple_solids": true`. `run` and `preview` also write an advisory silhouette comparison (`silhouette.png` and a best-view IoU, with a `reliable` flag that is false when the image's background could not be separated); for real photos pass a traced `--reference-mask`. It helps spot proportion errors but is never a gate. Review JSON follows `scripts/record_visual_review.py`: reviewer, verdict (`acceptable`, `revise`, or `blocked`), compared views, matches, mismatches, next_changes, and assumptions. `revise` must name mismatches and geometry/parameter changes; `blocked` must identify missing evidence in `next_changes`.

The CLI refuses to run CAD before source review, refuses visual review unless geometry/STEP and (for dimension-constrained work) declared bounding-dimension gates pass, checks source/reference/artifact hashes, and stores the exact reviewer/verdict separately from geometry status. After `revise` or `blocked` (or a failed geometry/dimension run), start a fresh revision with `new-revision --reason ...`; it preserves the prior run and inherits observations/plan. If new evidence or a changed plan is needed, record it into the new revision; source, geometry, dimensions, and visual-review gates reset. Do not reuse a previous preview's review for the new source. `human_acceptance` remains `not_verified` even when the agent review is acceptable.

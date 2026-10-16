# Design notes

Why img2cad works the way it does: the problem, the goals, and the principles behind the workflow. For how to use it, see the [README](../README.md) and [skills/img2cad/SKILL.md](../skills/img2cad/SKILL.md).

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

The benchmark format and local validation commands are defined in [`benchmark/README.md`](../benchmark/README.md). Two frozen fixtures separate visual approximation (`benchmark/cases/visual-pose-dog`) from dimension-constrained CAD (`benchmark/cases/repro-block`). The validator checks case/run metadata, input and artifact hashes, per-case gates, criterion-level visual review, and dimension tolerances across repeat runs. It is a reproducibility scaffold—not a CAD kernel or an independent visual judge; geometry and STEP round-trip checks must be performed by the CAD runner, and visual criteria must be reviewed against the comparison image.


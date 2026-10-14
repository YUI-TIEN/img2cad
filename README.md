# img2cad

An image-to-parametric-CAD workflow: turn a product image, sketch, or engineering drawing into a reviewable CAD specification, an editable solid model, and validated exchange files such as STEP.

> **Status:** concept / MVP proposal. This repository currently documents the product direction and first workflow; it is not yet an implemented converter.

## Problem

Image-to-3D tools can create visually convincing meshes, while CAD-generation tools can create editable solids from text or code. The difficult gap is translating visual evidence into explicit, constrained CAD intent: what parts exist, how they relate, which dimensions are known, and which details are guesses.

A single image cannot reveal hidden geometry or true scale. The workflow must expose uncertainty and let a person supply missing dimensions instead of silently presenting a visual guess as manufacturing-ready engineering.

## Product goal

Given one or more images and any available dimensions, help a user produce:

1. A structured, inspectable description of the part or assembly.
2. A native parametric model that can be edited and regenerated.
3. A valid STEP export, plus preview formats when useful.
4. Evidence of geometric checks and a visual comparison against the reference.

The primary success criterion is useful, editable CAD—not merely a similar-looking render or a watertight triangle mesh.

## Proposed workflow

```text
Image(s) + optional measurements
  → suitability and view assessment
  → visual observations with confidence / unknowns
  → editable CAD specification
  → user confirms critical assumptions and dimensions
  → generate parametric build123d model
  → kernel, geometry, and export validation
  → render from comparable views and review against reference
  → revise specification or model, then export STEP
```

### 1. Assess the input

Classify the input as a product photo, sketch, or dimensioned drawing. Identify view count, occlusion, perspective, visible scale cues, and whether the target is primarily prismatic/mechanical or organic. If the image is unsuitable or confidence is low, request another view or route the task to manual input.

### 2. Build an `Object2CADSpec`

Create a versioned JSON specification before generating geometry. It should record:

- Components and assembly relationships.
- Candidate features (for example, base extrusion, hole pattern, revolve, pocket, rib).
- Coordinate frame, units, datums, and dimensional constraints.
- Observed evidence and source view for each feature.
- Confidence, assumptions, and unresolved questions per feature/dimension.
- Manufacturing intent when known (3D print, CNC, sheet metal, or visual prototype).

Keep observed facts separate from inferred geometry. Ask the user only for unknowns that materially change fit, function, or manufacturing.

### 3. Generate native CAD

Translate the confirmed specification into ordinary, parameterized build123d code using Open CASCADE. Preserve meaningful parameters and feature-level structure so the model can be edited and regenerated. STEP is the primary interchange output; STL/GLB are derived previews, not the source of truth.

### 4. Validate geometry

Before claiming success, check that the model builds, contains valid positive-volume solids where expected, satisfies explicit dimensions and constraints, and can be exported and re-imported from STEP. Add manufacturability checks only for the chosen process; a successful export alone does not establish engineering correctness.

### 5. Review and refine

Render the generated CAD from the input camera/view where possible and from a small set of diagnostic views. Compare silhouette, proportions, component placement, and specified feature locations. Use deterministic checks for measurable geometry and a vision model only for visual judgments. Every correction should identify whether it changes the spec, the code, or an assumption.

## Design principles

- **CAD-first:** the editable parametric solid is canonical; meshes and renders are derived.
- **Evidence-aware:** every inferred feature has a confidence and an evidence source.
- **Human-confirmed constraints:** do not invent scale or hidden dimensions and label them as facts.
- **Progressive automation:** automate clear, constrained mechanical parts first; route ambiguous cases to questions or a documented best-effort result.
- **Reviewable loop:** retain input, spec, generated source, validation results, and revision history together.
- **Safe execution:** generated model code must run in a constrained worker with resource limits and explicit file boundaries.

## MVP scope

Start with single-part, mostly prismatic objects and dimensioned sketches/drawings where dimensions can be read or supplied. Support image upload, spec preview/edit, user confirmation of critical dimensions, build123d generation, STEP validation, and side-by-side visual review.

Defer arbitrary organic objects, automatic recovery of a complete feature tree from any photo, guaranteed hidden-surface reconstruction, and claims of production readiness without process-specific engineering checks.

## Relationship to existing projects

- [`earthtojake/text-to-cad`](https://github.com/earthtojake/text-to-cad) is a CAD-generation and local-review workflow built around build123d/Open CASCADE and exports such as STEP. It is a useful candidate for the CAD backend and project conventions.
- [`img2threejs/img2threejs`](https://github.com/img2threejs/img2threejs) demonstrates staged image analysis, structured specs, render-and-review passes, and bounded correction. Its generated Three.js model is a visual/interactive output, not a parametric CAD solid; treat it as a workflow reference rather than a geometry converter.
- [`sagarshedage7/text-to-cad`](https://github.com/sagarshedage7/text-to-cad) is a small prototype that accepts images and generates build123d/STEP with local vision and language models. It is a useful prior-art and implementation study, not a proven general solution.
- Raster-to-DXF projects such as [`adityaintwala/Image2CAD`](https://github.com/adityaintwala/Image2CAD) recover 2D entities from CAD drawing images; this is a different task from reconstructing a 3D solid from a product photo.

The proposed contribution is the explicit bridge: image evidence → uncertainty-bearing CAD spec → native parametric model → geometry and visual review.

## Initial acceptance criteria

For a supported test part with a reference image and known key dimensions:

- The workflow produces a spec that distinguishes observed, inferred, and user-confirmed values.
- The generated build123d model executes and exports a STEP file that can be re-imported.
- Explicit dimensions and feature counts pass geometric checks.
- A reviewer can inspect and edit model parameters without editing a triangle mesh.
- The review screen shows the reference, generated preview, validation results, and remaining assumptions.
- Unsupported or ambiguous input is reported as such rather than marked as a successful engineering reconstruction.

## Suggested first prototype

Pick one simple part with a front and side image plus a small set of known dimensions. Use an image-capable model to draft `Object2CADSpec`, let the user confirm unknowns, generate build123d, validate/export STEP, then render and compare. Measure success by dimensional agreement and editability, not only image similarity.

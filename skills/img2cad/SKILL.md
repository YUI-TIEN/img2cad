---
name: img2cad
description: Turn a supported reference image, sketch, or engineering drawing into a reviewable Object2CADSpec, editable parametric CAD, and validated STEP using this repository's local pipeline. Use for image-to-CAD reconstruction; external vision services are optional and never implicit.
---

# img2cad — evidence-led image to editable CAD

This is the agent workflow for this repository. The goal is an editable, reviewable parametric solid with evidence—not merely a plausible-looking render. Read the project `README.md` for product boundaries and `benchmark/README.md` for the exact command/manifest contract.

## Workflow

1. **Assess the input before modeling.** Identify the target part, image/drawing type, view labels, units, visible dimensions, scale cues, occlusion, perspective, and supported geometry. Separate direct observations from inferences and unknowns. A single view cannot establish hidden geometry or scale without evidence.
2. **Write and validate `Object2CADSpec`.** Bind it to the frozen case's source hashes. Record units, coordinate frame/datums, features, dimension provenance/status, confidence, and unresolved assumptions. Do not promote inferred or unknown critical dimensions to facts. If an unknown changes fit, function, or manufacturability, stop at the assumption gate and ask for the smallest useful dimension/view/confirmation.
3. **Use the deterministic generator and CAD worker.** Generate named, editable parameters from a validated, ready spec. In the current MVP, the generator supports one rectangular prism with optional circular through-holes; inspect the live schema/generator before accepting other shapes. Never execute arbitrary Python supplied by an image model or user. The worker executes canonical generated source in an isolated Python interpreter with a timeout; it is not an OS sandbox.
4. **Run the local pipeline.** Follow the `Drive a reusable workflow` instructions in `benchmark/README.md` for environment setup and `scripts/run_pipeline.py`. The runner should record the frozen input, Spec readiness, build, geometry and STEP round-trip evidence, then pause at visual review. Run from a clean checkout so the manifest pins an exact pipeline commit; if the active source tree is dirty, use a disposable local validation worktree with the exact snapshot committed locally—do not bypass the provenance gate.
5. **Check geometry, then review the preview.** Require a valid positive-volume solid, expected solid count, explicit dimensions/features within case tolerances, STEP export and re-import, and checks on the re-imported solid. Inspect `preview.svg` against the frozen reference from comparable views. A real acceptance review must be performed by a human and tied to the exact preview/input hashes. Synthetic review fixtures are for automated tests only; label them synthetic and never report them as human acceptance.
6. **Revise with bounded invalidation.** If a gate or visual review fails, decide whether to revise the input, Spec, or generated model and record why. Use `scripts/pipeline_state.py revise ...`; upstream revisions must invalidate downstream evidence while preserving prior artifacts/history. Respect the per-stage attempt limit and stop with the concrete blocker when evidence cannot resolve it.
7. **Compare repeat runs and report honestly.** Use `scripts/validate_benchmark.py compare-runs` on separate run directories for the same frozen case/config. Compare measured geometry against declared tolerances; differing STEP/report byte hashes alone do not establish geometry drift. Report supported scope, dimensions/tolerances, review type, assumptions, and untested requirements. Do not call an output manufacturing-ready without process-specific checks.

## Vision adapter boundary

`scripts/vision_adapter.py` is an optional OpenAI-compatible provider adapter. Its invocation sends the frozen input images to the explicitly configured endpoint. Do not call it, select a provider, or upload images merely because the adapter exists or the request says “image to CAD.” Prefer a user-provided/dimensioned Spec or inference already authorized to run locally. Do not assume a vision-capable agent/tool is local; ask before sending inputs to an external service. Use the adapter only when the user explicitly asks for provider-backed image inference and has selected/approved the endpoint. Keep the API key in `IMG2CAD_VISION_API_KEY`; never print it or place it in a command argument.

## Current MVP boundary

The included `repro-block` case demonstrates a small dimensioned part and repeatable local execution. It does not prove general image reconstruction, arbitrary/freeform support, real provider inference, or human approval. Report those boundaries rather than extrapolating from the fixture.

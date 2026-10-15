# Repeatable img2cad benchmark

The goal is to make a result reproducible and auditable, not to claim that one successful render proves a CAD workflow works. Freeze each case, record every run's inputs/configuration/artifacts, and compare geometry using declared tolerances.

## Commands

This validator uses only Python's standard library:

```sh
python3 scripts/validate_benchmark.py validate-case benchmark/cases/<case-id>
python3 scripts/validate_benchmark.py validate-run benchmark/runs/<run-id>
python3 scripts/validate_benchmark.py compare-runs benchmark/runs/<run-a> benchmark/runs/<run-b>
```

`validate-case` verifies the case manifest and every source file hash. `validate-run` checks its provenance/artifact hashes, requires each declared gate to be recorded as passed, and checks measured explicit dimensions against the case. `compare-runs` requires the same case, source hashes, artifact roles, and pipeline configuration, then checks recorded dimensions against the case tolerances. It reports output-file hash drift separately: stochastic model output may differ byte-for-byte while remaining geometrically within tolerance.

## Freeze a case

1. Put source images/drawings and (when available) reference CAD under one case directory. Do not overwrite them after adding the case; create a new case revision instead.
2. Fill `case.json` from [`schemas/case.schema.json`](schemas/case.schema.json). Record units and known dimensions with tolerances. Mark unsupported or unknown properties explicitly; never convert inferred dimensions into ground truth.
3. Compute each source file's SHA-256 (`shasum -a 256 <file>`) and store it in the manifest. The validator rejects missing files and hash mismatch.
4. Keep the case manifest and source assets together under version control or another immutable, access-controlled dataset store. A hash proves byte identity, not permission to redistribute an image.

## Record a run

Each execution gets a new directory and `run.json` based on [`schemas/run.schema.json`](schemas/run.schema.json). Keep the input case unchanged. Record:

- case ID and all source hashes;
- pipeline commit, prompt hash, model/provider/version, sampling settings/seed, and timestamp;
- generated spec, build123d source, STEP, and preview/render artifacts with SHA-256;
- explicit geometry measurements (including units), solid count, and gates for spec validation, build, STEP export/re-import, and review.

## Drive the constrained benchmark workflow

`scripts/run_pipeline.py` drives a frozen, already-specified supported case through assumption gating, parametric build, B-rep checks, STEP round-trip, preview generation, human review, and final manifest validation. CAD execution requires Python 3.10–3.13 with the pinned dependencies in [`requirements-cad.lock`](../requirements-cad.lock). Use a separate virtual environment. This is a deterministic benchmark path, not the general agent-led image → CAD workflow: it requires a spec draft and the current generator only builds one rectangular prism with optional through-holes. It does not analyze an image or accept arbitrary agent-authored geometry.

The standard benchmark command does not require an external model service or API key. An agent that already has access to the image can author a draft spec itself; the optional adapter below is only for explicitly selected provider-backed inference.

```sh
python3 -m venv .venv-cad
.venv-cad/bin/pip install -r requirements-cad.lock
python3 -B scripts/run_pipeline.py \
  benchmark/cases/repro-block benchmark/cases/repro-block/spec.json \
  benchmark/runs/repro-block-run-001 \
  --cad-python .venv-cad/bin/python
```

An optional vision adapter is explicit (no images leave the machine unless this command is run against a configured provider):

```sh
python3 -B scripts/vision_adapter.py \
  benchmark/cases/<case-id> /tmp/<case-id>-spec.json \
  --endpoint https://<approved-provider>/v1 --model <vision-model>
```

The vision adapter calls an explicitly supplied OpenAI-compatible endpoint, binds the returned spec to frozen image hashes, and stores output locally. It requires `IMG2CAD_VISION_API_KEY`; the key is never printed. Drafts with inferred/observed critical dimensions or unresolved unknowns stop before modeling until a user confirms them or a dimensioned drawing provides evidence. The spec contract is [`object2cad.schema.json`](schemas/object2cad.schema.json); v1 builds one rectangular prism and optional through-holes.

At the visual-review stage, the command intentionally pauses with `preview.svg`. Compare it with the frozen drawing and provide a local JSON review tied to exact hashes:

```json
{"reviewer":"Wayne","outcome":"pass","findings":"Dimensions and hole placement match the drawing.","preview_sha256":"<sha256>","input_image_hashes":{"drawing.png":"<sha256>"}}
```

Resume with the same `run_pipeline.py` command plus `--review-json /path/to/review.json`. A failed review remains blocked. To revise an upstream decision, use `scripts/pipeline_state.py revise spec_authoring|model_generation|visual_review --run-dir ... --reason ...`; downstream evidence is invalidated and previous generated artifacts are archived under `history/` rather than deleted. Each stage has at most three attempts. `scripts/validate_benchmark.py compare-runs <run-a> <run-b> --case-dir <case>` checks repeat-run dimensional drift under the same frozen pipeline config.

The validator independently checks the recorded hashes and explicit-dimension tolerances. The CAD worker executes the restricted canonical generator and records Open CASCADE/STEP geometry checks; the benchmark validator itself does not execute Open CASCADE, inspect STEP topology, or decide whether a visual review is correct. A reviewer must still inspect visual alignment and assumptions; automated hashes cannot establish visual correctness.

## Two different repeatability questions

- **Same-output determinism:** rerunning a pinned pipeline with identical input/configuration produces identical bytes. Compare artifact hashes. This is a strong property but not required of stochastic model stages.
- **Workflow reproducibility:** reruns preserve provenance and meet the same declared geometric tolerances and mandatory gates, even if model text or STEP bytes differ. This is the primary img2cad acceptance target.

Do not compare runs when the case inputs or pipeline configuration differ. To evaluate model variability, make a separate multi-seed study: pin the model/version/prompt, vary only the seed, and report pass rate plus metric spread. Do not blend that study with exact deterministic reruns.

## Acceptance profiles

The frozen cases define two distinct success criteria. The dimensioned `repro-block` requires `explicit_dimensions`; the visual `visual-pose-dog` requires three criterion-level review findings and deliberately has no dimension gate. Every case requires model build, STEP round-trip, and visual review. The validator rejects a visual-only case that claims explicit dimensions, a dimensioned case that omits that gate, or a visual review that skips or fails one of the case's criteria.

The visual criteria are qualitative evidence entered by a reviewer; the validator checks that they are present and hash-bound, not that an agent or human judged them correctly. A passing `run_report.json` from `run_agent_cad.py` remains geometry/STEP evidence only. Keep a human review distinct from an agent review in the `reviewer` field, and do not infer human acceptance from an agent pass.

## Initial acceptance ladder

Use `repro-block` to validate the dimensioned path and `visual-pose-dog` to validate a visual approximation without inventing a scale. For each case:

1. Spec gate: known / inferred / unknown and user-confirmed values remain distinguishable.
2. Geometry gate: build succeeds; expected solids are valid and positive-volume; explicit dimensions pass.
3. Exchange gate: STEP exports and re-imports, preserving solid count and checked dimensions.
4. Repeatability gate: rerun the same pinned configuration; all required gates pass and metrics stay within case tolerances. Record model variability separately if the pipeline is stochastic.
5. Visual gate: compare input and CAD from matched views; record reviewer, outcome, and concise findings. For `visual-pose-dog`, record an outcome and finding for every criterion in `case.json`.

`visual-pose-dog/model.py` is deliberately a `Compound` of overlapping primitives (9 solids). `scripts/run_agent_cad.py` rejects multi-solid models by default, so run this fixture with `--allow-multiple-solids`.

Report per-case and aggregate pass rates, failures, and unsupported inputs. A failed or unsupported case is data, not something to remove from the denominator after seeing the result. These two fixtures establish separate acceptance profiles, not general-purpose CAD accuracy or manufacturing readiness. The included manifest tests use synthetic file contents and do not substitute for running Open CASCADE, inspecting the STEP output, or independently judging the reference comparison.

## Current boundary

This repository has the case/run manifest contract, metadata/hash/tolerance validator, resumable stage/evidence state runner, a narrow build123d/Open CASCADE worker for the supported box-and-hole fixture, generic `scripts/inspect_step.py` metrics, and `scripts/run_agent_cad.py` for reviewed agent-authored model execution, STEP inspection, and preview/comparison artifacts. The agent—not the runner—performs image understanding, model planning, visual review, and refinement. The synthetic dog illustration fixture checks that visual criteria are independently recorded; it is not evidence of performance on real photographs or general photo-understanding quality. The optional provider adapter is not a substitute for CAD capability and is not required when the agent already sees the input image.

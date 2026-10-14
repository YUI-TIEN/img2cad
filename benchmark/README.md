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

## Drive a reusable workflow

`scripts/run_pipeline.py` drives a frozen case through spec intake, assumption gating, parametric build, B-rep checks, STEP round-trip, preview generation, human review, and final manifest validation. CAD execution requires Python 3.10–3.13 with the pinned dependencies in [`requirements-cad.lock`](../requirements-cad.lock). Use a separate virtual environment; the example command never executes model-supplied Python.

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

The validator independently checks the recorded hashes and explicit-dimension tolerances. Gate status is an attestation from the CAD runner/reviewer: the validator does not itself execute Open CASCADE, inspect STEP topology, or decide whether a visual review is correct. A reviewer must still inspect visual alignment and assumptions; automated hashes cannot establish geometric correctness.

## Two different repeatability questions

- **Same-output determinism:** rerunning a pinned pipeline with identical input/configuration produces identical bytes. Compare artifact hashes. This is a strong property but not required of stochastic model stages.
- **Workflow reproducibility:** reruns preserve provenance and meet the same declared geometric tolerances and mandatory gates, even if model text or STEP bytes differ. This is the primary img2cad acceptance target.

Do not compare runs when the case inputs or pipeline configuration differ. To evaluate model variability, make a separate multi-seed study: pin the model/version/prompt, vary only the seed, and report pass rate plus metric spread. Do not blend that study with exact deterministic reruns.

## Initial acceptance ladder

Start with 10 simple, supported parts (mostly prismatic), each with a reference view and at least two known key dimensions. For each case:

1. Spec gate: known / inferred / unknown and user-confirmed values remain distinguishable.
2. Geometry gate: build succeeds; expected solids are valid and positive-volume; explicit dimensions pass.
3. Exchange gate: STEP exports and re-imports, preserving solid count and checked dimensions.
4. Repeatability gate: rerun the same pinned configuration; all required gates pass and metrics stay within case tolerances. Record model variability separately if the pipeline is stochastic.
5. Visual gate: compare input and CAD from matched views; record reviewer, outcome, and concise findings.

Report per-case and aggregate pass rates, failures, and unsupported inputs. A failed or unsupported case is data, not something to remove from the denominator after seeing the result. Ten cases establish an initial repeatable benchmark, not general-purpose CAD accuracy or manufacturing readiness.

## Current boundary

This repository now has the case/run manifest contract, metadata/hash/tolerance validator, and resumable stage/evidence state runner. It does **not** yet include a vision model, build123d generation, Open CASCADE inspection, STEP round-trip executor, rendering service, reference dataset, or results. Those components must write the run records described here before the benchmark can measure real img2cad quality.

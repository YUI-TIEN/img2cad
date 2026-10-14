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

This repository now has the manifest contract and metadata/hash/tolerance validator. It does **not** yet include a vision model, build123d generation, Open CASCADE inspection, STEP round-trip runner, rendering service, reference dataset, or results. Those components must write the run records described here before the benchmark can measure real img2cad quality.

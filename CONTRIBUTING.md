# Contributing

Thanks for helping improve img2cad. Branch from `main` and open pull requests against `main`.

## Set up

```sh
python3 -m venv .venv-cad
.venv-cad/bin/pip install -r requirements-cad.lock pytest
```

`requirements-cad.lock` pins build123d / Open CASCADE and the image tools (numpy, scipy, Pillow). Python 3.10–3.13.

## Test

```sh
python3 -m pytest -q                                                    # fast unit tests, no CAD kernel
IMG2CAD_CAD_PYTHON=$PWD/.venv-cad/bin/python .venv-cad/bin/python -m pytest -q   # everything, incl. example rebuilds
```

CI (`.github/workflows/test.yml`) runs both on every pull request.

## What a good change looks like

- **Workflow or tool changes** (`scripts/`): add or update a test in `tests/`. A gate that can fail should have a test that makes it fail.
- **Agent guidance** (`skills/img2cad/`): keep `SKILL.md` a short procedure; put API details in `MODELING.md` and verified pitfalls in `LESSONS.md`. Only record behaviour you observed, and say where (`*(examples/fish)*`, `*(photo test: ...)*`).
- **Examples** (`examples/`): produce them with the real workflow and `agent_workflow.py promote`, never by hand-editing outputs. Only add reference images you have the right to publish.
- Do not commit generated runs (`benchmark/runs/`, workflow directories) or the CAD environment.

## Reporting problems

Open an issue with the command you ran, the full error, and (when you can share it) the image and `model.py`.

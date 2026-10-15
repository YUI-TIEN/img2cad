# Frozen benchmark cases

The repository now has two deliberately different acceptance profiles:

| Case | What it checks | What it must not claim |
| --- | --- | --- |
| `repro-block/` | Dimensioned drawing → one editable prism with a centered through-hole; explicit bounds, solid count, STEP round-trip, and visual review. Dimensions are 20 × 10 × 5 mm. | General image understanding or production suitability. |
| `visual-pose-dog/` | A frozen synthetic side-view illustration → an editable multi-solid CAD approximation; review separately scores body silhouette, head/muzzle placement, and legs/tail. | Physical scale, dimension accuracy, a real-photo result, or human acceptance from a recorded agent review. |

The visual case intentionally has no required dimensions. A passing geometry/STEP gate does not make it visually faithful; every listed visual criterion must have its own recorded reviewer finding. The dog image is a generated illustration, not a customer or personal photo.

`case.json` freezes each source hash and its required gates. For the visual case, `model.py` is an editable starter model and `model_plan.json` records observations, inferences, and unknowns. Run it through the reviewed agent-authored path, inspect the resulting `comparison.png`, and record the required criteria evaluations in `run.json`. For the dimensioned fixture, use the resumable constrained workflow described in [`../README.md`](../README.md).

The manifest tests use synthetic artifact bytes to exercise hash, gate, criteria, and tolerance validation; they do **not** build or inspect a real STEP file. CAD execution and visual judgment remain separate acceptance evidence. These two cases establish an initial split between visual and dimensional acceptance, not a benchmark pass rate or production suitability.

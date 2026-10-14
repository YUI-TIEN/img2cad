# Frozen benchmark cases

`repro-block/` is a deterministic dimensioned-drawing fixture for the v1 CAD adapter. It covers a 20 × 10 × 5 mm rectangular prism with one centered Ø2 mm through-hole. The dimensions and input hash are frozen in `case.json`; `spec.json` is an evidence-bearing reference spec. This one case validates the workflow and CAD kernel integration, not general image understanding or production suitability. Add independently reviewed cases before claiming a benchmark pass rate.

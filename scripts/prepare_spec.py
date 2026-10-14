#!/usr/bin/env python3
"""Validate a vision/model adapter's draft and bind it to frozen case images.

Provider calls are deliberately outside this command: the draft can come from a
local model or an explicitly approved adapter. This tool never uploads images.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spec_contract import SpecError, digest, validate_spec
from validate_benchmark import validate_case


def bind_case(case_dir: Path, draft_path: Path) -> dict:
    case = validate_case(case_dir)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        raise SpecError("spec draft must be a JSON object")
    if draft.get("case_id") != case["case_id"]:
        raise SpecError("spec case_id does not match the frozen case")
    declared = {item["path"]: item["sha256"] for item in case["source_files"] if item["role"] in {"input_image", "drawing"}}
    supplied: dict[str, str] = {}
    draft_images = draft.get("input_images")
    if not isinstance(draft_images, list):
        raise SpecError("spec input_images must be an array")
    for image in draft_images:
        if not isinstance(image, dict):
            raise SpecError("each spec input_images entry must be an object")
        if image.get("path") not in declared or image.get("sha256") != declared[image["path"]]:
            raise SpecError(f"spec input image is not a pinned case image: {image.get('path')}")
        supplied[image["path"]] = image["sha256"]
    if supplied != declared:
        raise SpecError("spec must bind every frozen case image exactly once")
    return validate_spec(case_dir, draft_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("draft", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        spec = bind_case(args.case_dir, args.draft)
        if args.require_ready and not spec["_model_ready"]:
            raise SpecError("spec is not ready; confirm critical assumptions or record unresolved unknowns")
        spec.pop("_model_ready", None)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"PASS: bound spec to {len(spec['input_images'])} pinned case image(s); model_ready={str(validate_spec(args.case_dir, args.output)['_model_ready']).lower()}")
        return 0
    except (SpecError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Optional OpenAI-compatible image-to-spec adapter; never called implicitly."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from prepare_spec import bind_case
from validate_benchmark import validate_case


ROOT = Path(__file__).resolve().parent.parent
PROMPT = (ROOT / "prompts/image_to_spec.txt").read_text(encoding="utf-8")
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 24 * 1024 * 1024


def checked_endpoint(raw: str, allow_local_http: bool) -> str:
    parsed = urllib.parse.urlsplit(raw)
    host = (parsed.hostname or "").lower()
    local = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (allow_local_http and local and parsed.scheme == "http"):
        raise ValueError("vision endpoint must use HTTPS; plain HTTP is allowed only for explicitly enabled loopback testing")
    if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("endpoint must be an origin/path without embedded credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def build_request(case_dir: Path, model: str) -> tuple[dict, str]:
    case = validate_case(case_dir)
    parts = []
    expected_images = []
    total_image_bytes = 0
    for item in case["source_files"]:
        if item["role"] not in {"input_image", "drawing"}:
            continue
        path = (case_dir / item["path"]).resolve()
        if case_dir.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"unsafe or missing image path: {item['path']}")
        raw = path.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"image exceeds {MAX_IMAGE_BYTES} bytes: {item['path']}")
        total_image_bytes += len(raw)
        if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError(f"combined images exceed {MAX_TOTAL_IMAGE_BYTES} bytes")
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"case input hash changed: {item['path']}")
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError(f"vision API accepts PNG/JPEG/WebP only; convert {item['path']} to a supported image before upload")
        view = "unknown"
        # View labels can be added to a frozen case without editing this adapter.
        view_map = case.get("input_views", {})
        view = view_map.get(item["path"], "unknown") if isinstance(view_map, dict) else "unknown"
        expected_images.append({"path": item["path"], "sha256": item["sha256"], "view": view})
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"}})
    if not parts:
        raise ValueError("case has no image/drawing source")
    prompt = PROMPT + f"\ncase_id={case['case_id']} revision={case['revision']}\ninput_images={json.dumps(expected_images, separators=(',', ':'))}\n"
    payload = {"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, *parts]}]}
    return payload, prompt


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect rejected", headers, fp)


def infer(case_dir: Path, model: str, endpoint: str, api_key: str, timeout: int = 90) -> tuple[dict, str]:
    payload, prompt = build_request(case_dir, model)
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as response:
            raw_response = response.read(4 * 1024 * 1024 + 1)
            if len(raw_response) > 4 * 1024 * 1024:
                raise RuntimeError("vision response exceeds size limit")
            result = json.loads(raw_response.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        # Do not include request/response bodies or auth headers in an error.
        raise RuntimeError(f"vision provider request failed ({type(exc).__name__})") from None
    try:
        content = result["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        draft = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise RuntimeError("vision response did not contain valid JSON Object2CADSpec") from None
    return draft, prompt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("output", type=Path, help="spec draft destination; local only")
    parser.add_argument("--endpoint", required=True, help="explicit OpenAI-compatible HTTPS endpoint")
    parser.add_argument("--model", required=True)
    parser.add_argument("--allow-local-http", action="store_true", help="allow HTTP only for localhost test servers")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        endpoint = checked_endpoint(args.endpoint, args.allow_local_http)
        api_key = os.environ.get("IMG2CAD_VISION_API_KEY", "")
        if not api_key:
            raise ValueError("set IMG2CAD_VISION_API_KEY in the environment; the key is never printed")
        draft, prompt = infer(args.case_dir, args.model, endpoint, api_key)
        temp = args.output.with_suffix(args.output.suffix + ".draft")
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
        spec = bind_case(args.case_dir, temp)
        ready = spec["_model_ready"]
        spec.pop("_model_ready", None)
        if args.require_ready and not ready:
            raise ValueError("vision draft contains unresolved or low-confidence dimensions; confirm assumptions before modeling")
        spec["adapter"] = {"provider_model": args.model, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        args.output.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.unlink(missing_ok=True)
        print(f"PASS: saved local spec draft; model_ready={str(ready).lower()}; prompt_sha256={spec['adapter']['prompt_sha256']}")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

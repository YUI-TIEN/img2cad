#!/usr/bin/env python3
"""Local 3D viewer for img2cad models and outputs (model.py, STEP, GLB, STL, 3MF).

    img2cad view model.py                        # live parameter panel: edit, rebuild, save
    img2cad view model.step other.glb            # serve and open in the browser
    img2cad view model.step --no-open --json     # print {"url": ...} and keep serving

Opening a model.py builds it and shows its parameters (module-level UPPERCASE
numbers, see model_params.py) in a panel: drag a label or type a value and the
model rebuilds locally, without an AI round trip; Save writes the values back
into model.py (the previous version is kept as model.py.bak).

Orbit/zoom, standard views, part list with colours and visibility, click a part
to see its name and size, measure the distance between two picked points,
section planes along X/Y/Z, wireframe, and PNG screenshots. STEP files are
converted to GLB (keeping part names and colours) on first view. Only the files
named on the command line (or registered by the MCP server) are served.

three.js is bundled (scripts/vendor/three), so the viewer works offline.
"""

from __future__ import annotations

import argparse
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import subprocess
import time
import tempfile
import threading
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
import webbrowser

SUPPORTED = {".py", ".step", ".stp", ".glb", ".gltf", ".stl", ".3mf"}
BUILD_TIMEOUT = 300
CACHE_DIR = Path(tempfile.gettempdir()) / "img2cad-viewer"
SCRIPTS = Path(__file__).resolve().parent
VENDOR_DIR = (SCRIPTS / "vendor").resolve()


class Registry:
    """Files the viewer may serve, by id; STEP files get a cached GLB, model.py files are built."""

    def __init__(self) -> None:
        self.files: dict[str, Path] = {}
        self.edits: dict[str, dict[str, float]] = {}  # unsaved parameter values per model.py
        self.lock = threading.Lock()
        self.build_lock = threading.Lock()

    def add(self, path: Path) -> str:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix.lower() not in SUPPORTED:
            raise ValueError(f"unsupported file type {path.suffix}; use one of {sorted(SUPPORTED)}")
        file_id = hashlib.sha256(str(path).encode()).hexdigest()[:12]
        with self.lock:
            self.files[file_id] = path
        return file_id

    def listing(self) -> list[dict[str, Any]]:
        with self.lock:
            return [{"id": file_id, "name": path.name, "path": str(path), "format": viewable_format(path),
                     "editable": path.suffix.lower() == ".py"} for file_id, path in self.files.items()]

    def path(self, file_id: str) -> Path:
        with self.lock:
            return self.files[file_id]

    def source(self, file_id: str) -> str:
        from model_params import apply_params

        text = self.path(file_id).read_text(encoding="utf-8")
        edits = self.edits.get(file_id)
        return apply_params(text, edits) if edits else text

    def viewable(self, file_id: str) -> Path:
        path = self.path(file_id)
        if path.suffix.lower() == ".py":
            return self.build(file_id)
        if path.suffix.lower() in (".step", ".stp"):
            return step_to_glb(path)
        return path

    def build(self, file_id: str) -> Path:
        """Build the model.py (with any unsaved edits) to a GLB, cached by source hash."""
        source = self.source(file_id)
        key = hashlib.sha256(source.encode()).hexdigest()[:16]
        work = CACHE_DIR / "models" / key
        glb = work / "model.glb"
        if glb.is_file():
            return glb
        with self.build_lock:
            if glb.is_file():
                return glb
            work.mkdir(parents=True, exist_ok=True)
            # Build next to the original so relative imports and data files still resolve.
            original = self.path(file_id)
            model = original.with_name(f".img2cad-view-{key}.py")
            model.write_text(source, encoding="utf-8")
            try:
                python = str(cad_python())
                steps = ([python, "-B", str(SCRIPTS / "agent_cad_worker.py"), str(model), str(work)],
                         [python, "-B", str(SCRIPTS / "mesh_export.py"), str(work / "model.step"), str(work), "--formats", "glb", "--stem", "model"])
                for command in steps:
                    done = subprocess.run(command, capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=str(original.parent))
                    if done.returncode:
                        message = (done.stderr or done.stdout).strip().splitlines()
                        raise RuntimeError(message[-1] if message else "build failed")
            finally:
                model.unlink(missing_ok=True)
        return glb


def cad_python() -> Path:
    """The interpreter with build123d: $IMG2CAD_CAD_PYTHON, a clone's .venv-cad, or this one."""
    import os
    import sys

    for candidate in (os.environ.get("IMG2CAD_CAD_PYTHON"), str(SCRIPTS.parent / ".venv-cad/bin/python")):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return Path(sys.executable)


def viewable_format(path: Path) -> str:
    suffix = path.suffix.lower()
    return "glb" if suffix in (".py", ".step", ".stp", ".glb", ".gltf") else suffix.lstrip(".")


def step_to_glb(path: Path) -> Path:
    from mesh_export import export_meshes

    stat = path.stat()
    key = hashlib.sha256(f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16]
    target = CACHE_DIR / key / f"{path.stem}.glb"
    if not target.is_file():
        export_meshes(path, target.parent, ("glb",), stem=path.stem)
    return target


class Handler(BaseHTTPRequestHandler):
    registry: Registry

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet server
        return

    def send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            self.send_bytes(VIEWER_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path.startswith("/vendor/"):
            # Bundled three.js (no CDN needed); only files under scripts/vendor.
            target = (VENDOR_DIR / url.path[len("/vendor/"):]).resolve()
            if VENDOR_DIR in target.parents and target.is_file():
                self.send_bytes(target.read_bytes(), "text/javascript; charset=utf-8")
            else:
                self.send_bytes(b"not found", "text/plain", HTTPStatus.NOT_FOUND)
        elif url.path == "/api/params":
            file_id = (query.get("id") or [""])[0]
            try:
                self.send_json(self.params(file_id))
            except KeyError:
                self.send_bytes(b"unknown file id", "text/plain", HTTPStatus.NOT_FOUND)
            except Exception as error:  # noqa: BLE001 - a syntax error in model.py is reported, not fatal
                self.send_json({"params": [], "error": str(error)})
        elif url.path == "/api/files":
            self.send_bytes(json.dumps(self.registry.listing()).encode(), "application/json")
        elif url.path == "/api/file":
            file_id = (query.get("id") or [""])[0]
            try:
                path = self.registry.viewable(file_id)
            except KeyError:
                self.send_bytes(b"unknown file id", "text/plain", HTTPStatus.NOT_FOUND)
                return
            except Exception as error:  # noqa: BLE001 - report conversion failures to the page
                self.send_bytes(f"could not load: {error}".encode(), "text/plain", HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix.lower() == ".glb":
                content_type = "model/gltf-binary"
            self.send_bytes(path.read_bytes(), content_type)
        else:
            self.send_bytes(b"not found", "text/plain", HTTPStatus.NOT_FOUND)


    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(json.dumps(data).encode(), "application/json", status)

    def params(self, file_id: str) -> dict[str, Any]:
        from model_params import find_params

        path = self.registry.path(file_id)
        if path.suffix.lower() != ".py":
            return {"params": [], "editable": False}
        saved = {p["name"]: p["value"] for p in find_params(path.read_text(encoding="utf-8"))}
        current = find_params(self.registry.source(file_id))
        for param in current:
            param["saved"] = saved.get(param["name"])
        return {"params": current, "editable": True, "dirty": bool(self.registry.edits.get(file_id))}

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            self.send_json({"ok": False, "error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            file_id = body.get("id", "")
            path = self.registry.path(file_id)
        except (ValueError, KeyError):
            self.send_json({"ok": False, "error": "unknown file id or bad request"}, HTTPStatus.BAD_REQUEST)
            return
        if path.suffix.lower() != ".py":
            self.send_json({"ok": False, "error": "only model.py files have parameters"}, HTTPStatus.BAD_REQUEST)
            return
        from model_params import apply_params

        try:
            values = {str(k): float(v) for k, v in (body.get("values") or {}).items()}
            if url.path == "/api/rebuild":
                apply_params(path.read_text(encoding="utf-8"), values)  # validate before keeping
                self.registry.edits[file_id] = values
                started = time.time()
                glb = self.registry.build(file_id)
                self.send_json({"ok": True, "version": glb.parent.name, "seconds": round(time.time() - started, 2)})
            elif url.path == "/api/save":
                text = path.read_text(encoding="utf-8")
                edited = apply_params(text, values or self.registry.edits.get(file_id, {}))
                path.with_suffix(path.suffix + ".bak").write_text(text, encoding="utf-8")
                path.write_text(edited, encoding="utf-8")
                self.registry.edits.pop(file_id, None)
                self.send_json({"ok": True, "saved": str(path), "backup": str(path.with_suffix(path.suffix + ".bak"))})
            elif url.path == "/api/reset":
                self.registry.edits.pop(file_id, None)
                glb = self.registry.build(file_id)
                self.send_json({"ok": True, "version": glb.parent.name})
            else:
                self.send_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as error:  # noqa: BLE001 - build errors go back to the panel
            self.send_json({"ok": False, "error": str(error)[-600:]})


def start_server(registry: Registry, host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server_class = type("Img2cadViewerHandler", (Handler,), {"registry": registry})
    server = ThreadingHTTPServer((host, port), server_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_address[1]}/"


def file_url(base: str, file_id: str) -> str:
    return f"{base}?file={quote(file_id)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="port to serve on (default: any free port)")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument("--json", action="store_true", help="print the URLs as one JSON line")
    args = parser.parse_args()
    registry = Registry()
    ids = [registry.add(path) for path in args.files]
    server, base = start_server(registry, args.host, args.port)
    urls = {str(path.resolve()): file_url(base, file_id) for path, file_id in zip(args.files, ids)}
    print(json.dumps({"url": base, "files": urls}) if args.json else f"img2cad viewer: {base}  (Ctrl+C to stop)\n" + "\n".join(urls.values()), flush=True)
    if not args.no_open:
        webbrowser.open(file_url(base, ids[0]))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


VIEWER_HTML = (SCRIPTS / "viewer.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""img2cad MCP server (stdio, JSON-RPC 2.0, newline-delimited).

    img2cad mcp            # started by an agent host from claude.mcp.json / mcp.json

Tools:

* `img2cad_run`     run any img2cad subcommand (workflow, build, trace, inspect, export,
                    review, drawing, printcheck, doctor) with arguments; returns exit code and output.
* `img2cad_inspect` measure a STEP file (parts, colours, bounds, volume, holes/bosses).
* `img2cad_show`    open STEP/GLB/STL/3MF files in the local 3D viewer; returns the URL.
* `img2cad_image`   return a PNG/JPEG (preview, comparison, registered overlay) as image content.

The server holds no state besides the viewer. Every tool runs the same CLI an
agent would run in a shell, so the MCP route and the shell route never differ.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

PROTOCOL_VERSION = "2025-06-18"
RUNNABLE = ("workflow", "build", "camera", "hull", "mask", "params", "trace", "inspect", "export", "review", "drawing", "printcheck", "dfm", "slice", "parts", "urdf", "doctor", "version")
MAX_OUTPUT = 60_000

TOOLS = [
    {
        "name": "img2cad_run",
        "description": "Run an img2cad CLI subcommand, exactly as `img2cad <command> <args...>` in a shell. "
                       "Use `workflow` for the staged image->CAD workflow (init, observations, plan, preview, "
                       "source-review, run, review, new-revision, promote, status). Pass `--help` to see options. "
                       "Read skills/img2cad/SKILL.md for the order of stages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "enum": list(RUNNABLE)},
                "args": {"type": "array", "items": {"type": "string"}, "default": []},
                "cwd": {"type": "string", "description": "working directory (default: the server's)"},
                "timeout_s": {"type": "number", "default": 900},
            },
            "required": ["command"],
        },
    },
    {
        "name": "img2cad_inspect",
        "description": "Measure a STEP file: validity, solid count, parts with names and colours, bounds, volume, cylindrical holes/bosses.",
        "inputSchema": {"type": "object", "properties": {"step": {"type": "string"}}, "required": ["step"]},
    },
    {
        "name": "img2cad_show",
        "description": "Open STEP/GLB/STL/3MF files in the local img2cad 3D viewer (orbit, parts, measure, section, screenshot). Returns the URL; open it in a browser.",
        "inputSchema": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
            "required": ["paths"],
        },
    },
    {
        "name": "img2cad_image",
        "description": "Return a PNG or JPEG file (preview.png, comparison.png, registered.png, a reference image) as image content so it can be looked at.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
]


class ToolError(Exception):
    pass


class Server:
    def __init__(self) -> None:
        self.registry = None
        self.base_url = ""

    # tools ---------------------------------------------------------------
    def run(self, command: str, args: list[str] | None = None, cwd: str | None = None, timeout_s: float = 900) -> list[dict[str, Any]]:
        if command not in RUNNABLE:
            raise ToolError(f"unknown command {command!r}; choose from {', '.join(RUNNABLE)}")
        argv = [sys.executable, str(SCRIPTS / "img2cad_cli.py"), command, *[str(arg) for arg in (args or [])]]
        try:
            done = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise ToolError(f"img2cad {command} timed out after {timeout_s} s") from None
        output = {"exit_code": done.returncode, "stdout": clip(done.stdout), "stderr": clip(done.stderr)}
        return [text(json.dumps(output, indent=2))]

    def inspect(self, step: str) -> list[dict[str, Any]]:
        from inspect_step import inspect_step

        path = Path(step).expanduser()
        if not path.is_file():
            raise ToolError(f"no such STEP file: {path}")
        return [text(json.dumps(inspect_step(path), indent=2))]

    def show(self, paths: list[str]) -> list[dict[str, Any]]:
        from viewer import Registry, file_url, start_server

        if self.registry is None:
            self.registry = Registry()
            _, self.base_url = start_server(self.registry)
        ids = []
        for raw in paths:
            try:
                ids.append(self.registry.add(Path(raw)))
            except (FileNotFoundError, ValueError) as error:
                raise ToolError(str(error)) from None
        return [text(json.dumps({"url": file_url(self.base_url, ids[0]), "files": self.registry.listing()}, indent=2))]

    def image(self, path: str) -> list[dict[str, Any]]:
        file = Path(path).expanduser()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(file.suffix.lower())
        if mime is None or not file.is_file():
            raise ToolError(f"not a PNG/JPEG file: {file}")
        return [{"type": "image", "data": base64.b64encode(file.read_bytes()).decode("ascii"), "mimeType": mime}]

    # protocol ------------------------------------------------------------
    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if request_id is None:  # notification (initialized, cancelled, ...)
            return None
        if method == "initialize":
            from img2cad_cli import version

            result = {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "img2cad", "version": version()},
                "instructions": "Image -> editable coloured CAD. Read skills/img2cad/SKILL.md first; "
                                "drive the staged workflow with img2cad_run command=workflow.",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            handlers = {"img2cad_run": self.run, "img2cad_inspect": self.inspect, "img2cad_show": self.show, "img2cad_image": self.image}
            name = params.get("name")
            if name not in handlers:
                return error(request_id, -32602, f"unknown tool {name!r}")
            try:
                result = {"content": handlers[name](**(params.get("arguments") or {}))}
            except (ToolError, TypeError) as failure:
                result = {"content": [text(str(failure))], "isError": True}
            except Exception as failure:  # noqa: BLE001 - report CAD failures to the agent, keep serving
                result = {"content": [text(f"{type(failure).__name__}: {failure}")], "isError": True}
        else:
            return error(request_id, -32601, f"method not found: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def text(value: str) -> dict[str, str]:
    return {"type": "text", "text": value}


def clip(value: str) -> str:
    return value if len(value) <= MAX_OUTPUT else value[:MAX_OUTPUT // 2] + "\n...[clipped]...\n" + value[-MAX_OUTPUT // 2:]


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main() -> int:
    server = Server()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = error(None, -32700, "parse error")
        else:
            reply = server.handle(message) if isinstance(message, dict) else error(None, -32600, "invalid request")
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

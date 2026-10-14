#!/usr/bin/env python3
"""Execute a reviewed agent-authored build123d function and export STEP."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
from pathlib import Path
import sys
from typing import Any


ALLOWED_IMPORTS = {
    "Align", "Axis", "BuildLine", "BuildPart", "BuildSketch", "Circle", "Compound",
    "Cone", "Cylinder", "Ellipse", "Line", "Locations", "Mode", "Plane", "Polyline",
    "Rectangle", "SlotOverall", "Sphere", "Spline", "ThreePointArc", "ThreePointSpline",
    "Vector", "add", "chamfer", "extrude", "fillet", "loft", "make_face", "revolve",
    "sweep",
}
SAFE_BUILTINS = {
    "abs": abs,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}
SAFE_METHODS = {"append", "chamfer", "cut", "fuse", "mirror", "move", "rotate", "scale", "translate"}
SAFE_NODES = {
    ast.Module, ast.ImportFrom, ast.alias, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
    ast.Assign, ast.AnnAssign, ast.Expr, ast.For, ast.If, ast.IfExp, ast.With, ast.withitem,
    ast.Pass, ast.Break, ast.Continue, ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Set,
    ast.Dict, ast.Attribute, ast.Call, ast.keyword, ast.BinOp, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.Pow, ast.Mod, ast.UnaryOp, ast.USub, ast.UAdd, ast.BoolOp, ast.And, ast.Or,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Subscript, ast.Slice,
    ast.AugAssign,
}
BLOCKED_NAMES = {"__builtins__", "__import__", "eval", "exec", "compile", "open", "input", "globals", "locals", "vars", "getattr", "setattr", "delattr"}


def parse_model_source(source: str, label: str) -> tuple[ast.Module, set[str]]:
    if len(source.encode("utf-8")) > 256_000:
        raise ValueError("model source exceeds 256 KB")
    tree = ast.parse(source, filename=label)
    nodes = list(ast.walk(tree))
    if len(nodes) > 12_000:
        raise ValueError("model source exceeds the syntax-node limit")
    functions: set[str] = set()
    functions = {node.name for node in nodes if isinstance(node, ast.FunctionDef)}
    for node in nodes:
        if type(node) not in SAFE_NODES:
            raise ValueError(f"unsupported source construct: {type(node).__name__}")
        if isinstance(node, ast.FunctionDef):
            if node.decorator_list or node.name.startswith("_"):
                raise ValueError("decorators and private helper names are not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module != "build123d":
                raise ValueError("model source may only import approved names from build123d")
            for alias in node.names:
                if alias.name == "*" or alias.name not in ALLOWED_IMPORTS:
                    raise ValueError(f"build123d import is not allowed: {alias.name}")
        elif isinstance(node, ast.Name) and (node.id in BLOCKED_NAMES or node.id.startswith("__")):
            raise ValueError(f"restricted name in model source: {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ValueError(f"private attribute access is not allowed: {node.attr}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                allowed_names = ALLOWED_IMPORTS | set(SAFE_BUILTINS) | functions | {"build_model"}
                if node.func.id not in allowed_names:
                    raise ValueError(f"call is not allowed: {node.func.id}")
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr not in SAFE_METHODS:
                    raise ValueError(f"method call is not allowed: {node.func.attr}")
            else:
                raise ValueError("indirect/dynamic calls are not allowed")
    if "build_model" not in functions:
        raise ValueError("model source must define build_model()")
    return tree, functions


def run_model(source_path: Path, output_dir: Path) -> dict[str, Any]:
    from build123d import Shape, export_step

    source = source_path.read_text(encoding="utf-8")
    tree, _functions = parse_model_source(source, str(source_path))
    build123d = importlib.import_module("build123d")

    def restricted_import(name: str, globals: Any = None, locals: Any = None, fromlist: tuple[str, ...] = (), level: int = 0) -> Any:
        if name != "build123d" or level:
            raise ImportError(f"import blocked in CAD model: {name}")
        if any(item == "*" or item not in ALLOWED_IMPORTS for item in fromlist):
            raise ImportError("model requested a non-allowlisted build123d symbol")
        return build123d

    namespace: dict[str, Any] = {"__builtins__": {**SAFE_BUILTINS, "__import__": restricted_import}}
    exec(compile(tree, str(source_path), "exec"), namespace, namespace)
    result = namespace["build_model"]()
    if not isinstance(result, Shape):
        raise TypeError("build_model() must return a build123d Shape")
    if not result.solids():
        raise ValueError("build_model() returned no solids")
    step_path = output_dir / "model.step"
    export_step(result, str(step_path))
    return {"step": str(step_path), "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    source_path = args.model_source.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_model(source_path, output_dir)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(f"CAD model failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

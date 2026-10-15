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


# Keep this list in sync with skills/img2cad/MODELING.md (enforced by tests).
ALLOWED_IMPORTS = {
    # Placement, enums, and selectors.
    "Align", "Axis", "GeomType", "Keep", "Location", "Locations", "GridLocations",
    "HexLocations", "PolarLocations", "Mode", "Plane", "Pos", "Rot", "Rotation", "Select",
    "SortBy", "Until", "Vector",
    # Builders and shape containers.
    "BuildLine", "BuildPart", "BuildSketch", "Compound",
    # 3D primitives and features.
    "Box", "Cone", "CounterBoreHole", "CounterSinkHole", "Cylinder", "Hole", "Sphere",
    "Torus", "Wedge",
    # 2D sketch primitives.
    "Circle", "Ellipse", "Polygon", "Rectangle", "RectangleRounded", "RegularPolygon",
    "SlotCenterToCenter", "SlotOverall", "Trapezoid",
    # 1D line primitives.
    "Bezier", "CenterArc", "JernArc", "Line", "Polyline", "RadiusArc", "SagittaArc",
    "Spline", "TangentArc", "ThreePointArc",
    # Operations.
    "add", "chamfer", "extrude", "fillet", "loft", "make_face", "mirror", "offset",
    "revolve", "scale", "split", "sweep",
}
MATH_NAMES = {
    "acos", "asin", "atan", "atan2", "ceil", "cos", "degrees", "e", "floor", "hypot",
    "pi", "radians", "sin", "sqrt", "tan", "tau",
}
SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
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
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}
SAFE_METHODS = {
    # Shape transforms and booleans.
    "chamfer", "cut", "fuse", "intersect", "located", "mirror", "move", "moved", "offset",
    "rotate", "scale", "translate",
    # Read-only topology selectors, e.g. fillet(part.edges().filter_by(Axis.Z), 2).
    "edges", "faces", "filter_by", "group_by", "solids", "sort_by", "vertices", "wires",
    # Plain container helpers.
    "append", "extend", "items", "keys", "values",
}
SAFE_NODES = {
    ast.Module, ast.ImportFrom, ast.alias, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
    ast.Assign, ast.AnnAssign, ast.Expr, ast.For, ast.If, ast.IfExp, ast.With, ast.withitem,
    ast.Pass, ast.Break, ast.Continue, ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Set,
    ast.Dict, ast.Attribute, ast.Call, ast.keyword, ast.BinOp, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.Pow, ast.Mod, ast.UnaryOp, ast.USub, ast.UAdd, ast.BoolOp, ast.And, ast.Or,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Subscript, ast.Slice,
    ast.AugAssign, ast.Import, ast.ListComp, ast.GeneratorExp, ast.DictComp, ast.comprehension,
    ast.FloorDiv, ast.Not, ast.In, ast.NotIn, ast.Starred,
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
        elif isinstance(node, ast.Import):
            if [(alias.name, alias.asname) for alias in node.names] != [("math", None)]:
                raise ValueError("model source may only use `import math` or approved build123d names")
        elif isinstance(node, ast.ImportFrom):
            allowed = {"build123d": ALLOWED_IMPORTS, "math": MATH_NAMES}.get(node.module or "")
            if node.level or allowed is None:
                raise ValueError("model source may only import approved names from build123d or math")
            for alias in node.names:
                if alias.name == "*" or alias.name not in allowed or alias.asname:
                    raise ValueError(f"{node.module} import is not allowed: {alias.name}")
        elif isinstance(node, ast.Name) and (node.id in BLOCKED_NAMES or node.id.startswith("__")):
            raise ValueError(f"restricted name in model source: {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ValueError(f"private attribute access is not allowed: {node.attr}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                allowed_names = ALLOWED_IMPORTS | MATH_NAMES | set(SAFE_BUILTINS) | functions | {"build_model"}
                if node.func.id not in allowed_names:
                    raise ValueError(f"call is not allowed: {node.func.id}")
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "math":
                    if node.func.attr not in MATH_NAMES:
                        raise ValueError(f"math call is not allowed: {node.func.attr}")
                elif node.func.attr not in SAFE_METHODS:
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
    modules = {"build123d": (importlib.import_module("build123d"), ALLOWED_IMPORTS), "math": (importlib.import_module("math"), MATH_NAMES)}

    def restricted_import(name: str, globals: Any = None, locals: Any = None, fromlist: tuple[str, ...] | None = (), level: int = 0) -> Any:
        if name not in modules or level:
            raise ImportError(f"import blocked in CAD model: {name}")
        module, allowed = modules[name]
        if any(item == "*" or item not in allowed for item in fromlist or ()):
            raise ImportError(f"model requested a non-allowlisted {name} symbol")
        return module

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

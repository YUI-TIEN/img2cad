#!/usr/bin/env python3
"""Find and edit the numeric parameters of a model.py.

A parameter is a module-level UPPERCASE name assigned a plain number (or a
bool, shown as a switch, or a tuple/list of numbers, one entry per element
named NAME[i]); or any assignment anywhere, in any case, whose comment starts
with `[min, max]` or `@param` (inside a function it is named function.name):

    HEIGHT = 68.4            # [40, 90] overall height, mm
    WALL = 1.5               # wall thickness
    SPOKES = 6               # [3, 12]

An optional `[min, max]` at the start of the trailing comment sets the slider
range; the rest of the comment is the label. Without a range the panel offers
half to double the value. Integers stay integers. Computed values are not
parameters (they are derived; expose the inputs instead):

    def build_model():
        wall = 1.2               # [0.8, 3] wall inside the function
        holes = 4                # @param number of holes

    img2cad params model.py                      # list as JSON
    img2cad params model.py --set HEIGHT=72 --set WALL=2 --out edited.py
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import math
from pathlib import Path
import re
import tokenize
from typing import Any

RANGE = re.compile(r"^\s*\[\s*(-?[\d.eE+]+)\s*,\s*(-?[\d.eE+]+)\s*\]\s*(.*)$")


def _number(node: ast.AST) -> float | int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _number(node.operand)
        if inner is not None:
            return -inner if isinstance(node.op, ast.USub) else inner
    return None


def _comments(source: str) -> dict[int, str]:
    comments = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments[token.start[0]] = token.string.lstrip("#").strip()
    except (tokenize.TokenError, IndentationError):
        pass
    return comments


def _entry(name: str, value_node: ast.AST, comment: str, source_lines: list[str]) -> dict[str, Any] | None:
    if isinstance(value_node, ast.Constant) and isinstance(value_node.value, bool):
        value, kind = int(value_node.value), "bool"
    else:
        value, kind = _number(value_node), "number"
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return None
    integer = kind == "bool" or isinstance(value, int)
    match = RANGE.match(comment)
    if kind == "bool":
        low, high, label = 0, 1, (match.group(3).strip() if match else comment)
    elif match:
        low, high, label = float(match.group(1)), float(match.group(2)), match.group(3).strip()
    else:
        label = comment
        span = abs(value) if value else 10
        low, high = (value - span * 0.5, value + span) if value >= 0 else (value - span, value + span * 0.5)
    if low > high:
        low, high = high, low
    decimals = 0 if integer else max(1, min(4, len(repr(float(value)).split(".")[1].rstrip("0")) or 1))
    return {
        "name": name, "value": value, "integer": integer, "kind": kind, "label": label,
        "min": int(math.floor(low)) if integer else low, "max": int(math.ceil(high)) if integer else high,
        "step": 1 if integer else 10 ** -decimals,
        "line": value_node.lineno, "col": value_node.col_offset, "end_col": value_node.end_col_offset,
        "end_line": value_node.end_lineno, "source_line": source_lines[value_node.lineno - 1].strip(),
    }


def _targets(node: ast.AST) -> tuple[str, ast.AST] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    return None


def find_params(source: str) -> list[dict[str, Any]]:
    """Parameters, in source order:

    * module-level UPPERCASE names assigned a number or a bool (bools become 0/1 switches);
    * each number in a module-level UPPERCASE tuple or list, named NAME[i];
    * any assignment, at any level and in any case, whose trailing comment starts
      with `[min, max]` or `@param`; inside a function it is named function.name.
    """
    tree = ast.parse(source)
    comments = _comments(source)
    lines = source.splitlines()
    params: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(entry: dict[str, Any] | None) -> None:
        if entry and entry["name"] not in seen:
            seen.add(entry["name"])
            params.append(entry)

    def visit(body: list[ast.stmt], scope: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(node.body, f"{scope}{node.name}.")
                continue
            if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(node, field, None) or [], scope)
            found = _targets(node)
            if not found:
                continue
            name, value_node = found
            comment = comments.get(node.lineno, "")
            marked = bool(RANGE.match(comment)) or comment.startswith("@param")
            if comment.startswith("@param"):
                comment = comment[len("@param"):].strip()
            top_level = scope == "" and name.isupper() and not name.startswith("_")
            if not (top_level or marked):
                continue
            qualified = scope + name
            if isinstance(value_node, (ast.Tuple, ast.List)):
                if not top_level and not marked:
                    continue
                for index, item in enumerate(value_node.elts):
                    add(_entry(f"{qualified}[{index}]", item, comment, lines))
                continue
            add(_entry(qualified, value_node, comment, lines))

    visit(tree.body, "")
    params.sort(key=lambda p: (p["line"], p["col"]))
    return params


def _format(value: float, integer: bool, kind: str = "number") -> str:
    if kind == "bool":
        return "True" if value else "False"
    if integer:
        return str(int(round(value)))
    text = repr(round(float(value), 6))
    return text if "." in text or "e" in text else text + ".0"


def apply_params(source: str, values: dict[str, float]) -> str:
    """Return the source with the given parameters' numbers replaced (nothing else changes)."""
    params = {p["name"]: p for p in find_params(source)}
    unknown = sorted(set(values) - set(params))
    if unknown:
        raise ValueError(f"not parameters of this model: {', '.join(unknown)}")
    lines = source.splitlines(keepends=True)
    # Replace from the end of each line backwards so earlier columns stay valid.
    for name in sorted(values, key=lambda n: (params[n]["line"], params[n]["col"]), reverse=True):
        param, value = params[name], values[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"{name}: value must be a finite number")
        if param["line"] != param.get("end_line", param["line"]):
            raise ValueError(f"{name}: multi-line values are not editable")
        row = param["line"] - 1
        line = lines[row]
        lines[row] = line[:param["col"]] + _format(value, param["integer"], param.get("kind", "number")) + line[param["end_col"]:]
    result = "".join(lines)
    ast.parse(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", type=Path)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--out", type=Path, help="write the edited source here (default: print it)")
    args = parser.parse_args()
    source = args.model.read_text(encoding="utf-8")
    if not args.set:
        print(json.dumps(find_params(source), indent=2))
        return 0
    values = {}
    for item in args.set:
        name, _, raw = item.partition("=")
        raw = raw.strip()
        values[name.strip()] = {"true": 1, "false": 0}.get(raw.lower(), None) if raw.lower() in ("true", "false") else float(raw)
    edited = apply_params(source, values)
    if args.out:
        args.out.write_text(edited, encoding="utf-8")
    else:
        print(edited, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

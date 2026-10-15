"""Command-line helpers shared by the workflow and the CAD runner (no CAD imports)."""

from __future__ import annotations

import argparse
import math


def parse_view(raw: str) -> tuple[float, float, float]:
    """Parse a model-to-camera direction such as ``1,-1,0.7``."""
    try:
        values = tuple(float(value) for value in raw.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected three comma-separated numbers such as 1,-1,0.7") from exc
    if len(values) != 3 or not all(math.isfinite(value) for value in values) or sum(value * value for value in values) <= 0:
        raise argparse.ArgumentTypeError("expected three finite, not-all-zero numbers such as 1,-1,0.7")
    return values  # type: ignore[return-value]


def join_negative_option_values(argv: list[str], options: tuple[str, ...]) -> list[str]:
    """Rewrite ``--opt -1,0,0.3`` as ``--opt=-1,0,0.3``.

    argparse otherwise reads a value that starts with ``-`` and contains commas
    as an unknown option and fails before the command runs.
    """
    joined: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index + 1] if index + 1 < len(argv) else ""
        if argv[index] in options and value[:1] == "-" and value[1:2] in set("0123456789."):
            joined.append(f"{argv[index]}={value}")
            index += 2
            continue
        joined.append(argv[index])
        index += 1
    return joined

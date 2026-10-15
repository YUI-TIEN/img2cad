from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_cad_worker import ALLOWED_IMPORTS, parse_model_source  # noqa: E402


MECHANICAL = '''import math
from build123d import Axis, Box, BuildPart, GridLocations, Hole, Pos, Cylinder, fillet
from math import radians


def build_model():
    with BuildPart() as plate:
        Box(80, 50, 6)
        fillet(plate.edges().filter_by(Axis.Z), radius=4)
        with GridLocations(64, 34, 2, 2):
            Hole(radius=3)
    pegs = [Pos(20 * math.cos(radians(a)), 0, 5) * Cylinder(1, 4) for a in range(0, 360, 90)]
    part = plate.part
    for peg in pegs:
        part = part.fuse(peg)
    return part
'''

ORDINARY_PYTHON = '''import itertools
from dataclasses import dataclass
from build123d import *


@dataclass
class Ear:
    x: float
    radius: float


def build_model():
    ears = sorted([Ear(-60, 20), Ear(60, 22)], key=lambda ear: ear.x)
    head = Sphere(100)
    head.color = Color(1, 1, 1)
    parts = [head] + [Pos(ear.x, 0, 90) * Sphere(ear.radius) for ear in ears]
    return Compound(children=parts)
'''


class ModelSourcePolicyTests(unittest.TestCase):
    def assert_rejected(self, source: str, message: str, strict: bool = True) -> None:
        with self.assertRaisesRegex(ValueError, message):
            parse_model_source(source, "model.py", strict=strict)

    def test_open_mode_accepts_ordinary_python_and_full_build123d(self) -> None:
        parse_model_source(ORDINARY_PYTHON, "model.py")
        parse_model_source("import os\ndef build_model():\n    return (lambda: 1)()\n", "model.py")

    def test_open_mode_still_requires_build_model_and_valid_syntax(self) -> None:
        self.assert_rejected("def make():\n    pass\n", "must define build_model", strict=False)
        with self.assertRaises(SyntaxError):
            parse_model_source("def build_model(:\n", "model.py")

    def test_strict_mode_accepts_common_idioms(self) -> None:
        parse_model_source(MECHANICAL, "model.py", strict=True)

    def test_strict_mode_limits_imports(self) -> None:
        self.assert_rejected("import os\ndef build_model():\n    pass\n", "import math")
        self.assert_rejected("import math as m\ndef build_model():\n    pass\n", "import math")
        self.assert_rejected("from math import exp\ndef build_model():\n    pass\n", "math import is not allowed")
        self.assert_rejected("from build123d import export_step\ndef build_model():\n    pass\n", "build123d import is not allowed")
        self.assert_rejected("from build123d import Box as B\ndef build_model():\n    pass\n", "build123d import is not allowed")

    def test_strict_mode_rejects_unsafe_calls_and_attributes(self) -> None:
        self.assert_rejected("import math\ndef build_model():\n    return math.exp(1)\n", "math call is not allowed")
        self.assert_rejected("from build123d import Box\ndef build_model():\n    Box(1, 1, 1).export_step('x')\n", "method call is not allowed")
        self.assert_rejected("def build_model():\n    return [c for c in ().__class__.__bases__]\n", "private attribute")
        self.assert_rejected("def build_model():\n    return open('x')\n", "call is not allowed: open")
        self.assert_rejected("def build_model():\n    shape = lambda: 1\n    return shape\n", "unsupported source construct: Lambda")

    def test_strict_allowlist_names_exist_in_build123d(self) -> None:
        try:
            import build123d
        except ImportError:
            self.skipTest("build123d is only installed in the CAD environment")
        self.assertEqual(sorted(name for name in ALLOWED_IMPORTS if not hasattr(build123d, name)), [])


if __name__ == "__main__":
    unittest.main()

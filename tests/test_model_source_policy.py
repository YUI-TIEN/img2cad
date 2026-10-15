from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_cad_worker import ALLOWED_IMPORTS, MATH_NAMES, SAFE_BUILTINS, SAFE_METHODS, parse_model_source  # noqa: E402


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


class ModelSourcePolicyTests(unittest.TestCase):
    def assert_rejected(self, source: str, message: str) -> None:
        with self.assertRaisesRegex(ValueError, message):
            parse_model_source(source, "model.py")

    def test_common_mechanical_and_math_idioms_are_allowed(self) -> None:
        parse_model_source(MECHANICAL, "model.py")

    def test_imports_are_limited_to_build123d_allowlist_and_math(self) -> None:
        self.assert_rejected("import os\ndef build_model():\n    pass\n", "import math")
        self.assert_rejected("import math as m\ndef build_model():\n    pass\n", "import math")
        self.assert_rejected("from math import exp\ndef build_model():\n    pass\n", "math import is not allowed")
        self.assert_rejected("from build123d import export_step\ndef build_model():\n    pass\n", "build123d import is not allowed")
        self.assert_rejected("from build123d import Box as B\ndef build_model():\n    pass\n", "build123d import is not allowed")

    def test_unsafe_calls_and_attributes_are_rejected(self) -> None:
        self.assert_rejected("import math\ndef build_model():\n    return math.exp(1)\n", "math call is not allowed")
        self.assert_rejected("from build123d import Box\ndef build_model():\n    Box(1, 1, 1).export_step('x')\n", "method call is not allowed")
        self.assert_rejected("def build_model():\n    return [c for c in ().__class__.__bases__]\n", "private attribute")
        self.assert_rejected("def build_model():\n    return open('x')\n", "call is not allowed: open")
        self.assert_rejected("def build_model():\n    shape = lambda: 1\n    return shape\n", "unsupported source construct: Lambda")

    def test_modeling_reference_documents_every_allowed_name(self) -> None:
        text = (ROOT / "skills/img2cad/MODELING.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", text))
        for group in (ALLOWED_IMPORTS, MATH_NAMES, set(SAFE_BUILTINS), SAFE_METHODS):
            self.assertEqual(sorted(group - documented), [], "MODELING.md is missing allowlisted names")

    def test_allowed_names_exist_in_build123d(self) -> None:
        try:
            import build123d
        except ImportError:
            self.skipTest("build123d is only installed in the CAD environment")
        self.assertEqual(sorted(name for name in ALLOWED_IMPORTS if not hasattr(build123d, name)), [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cli_args import join_negative_option_values, parse_view  # noqa: E402


class CliArgsTests(unittest.TestCase):
    def test_negative_view_values_are_joined_to_their_option(self) -> None:
        self.assertEqual(join_negative_option_values(["run", "w", "--reference-view", "-0.35,-1,0.35"], ("--reference-view",)),
                         ["run", "w", "--reference-view=-0.35,-1,0.35"])
        self.assertEqual(join_negative_option_values(["--reference-view", "-.5,1,0"], ("--reference-view",)), ["--reference-view=-.5,1,0"])
        self.assertEqual(join_negative_option_values(["--reference-view", "1,-1,0.7", "--other", "-1"], ("--reference-view",)),
                         ["--reference-view", "1,-1,0.7", "--other", "-1"])
        self.assertEqual(join_negative_option_values(["--reference-view", "--reference-mask", "m.png"], ("--reference-view",)),
                         ["--reference-view", "--reference-mask", "m.png"])

    def test_view_parsing(self) -> None:
        self.assertEqual(parse_view("-0.35,-1,0.35"), (-0.35, -1.0, 0.35))
        for bad in ("1,2", "0,0,0", "a,b,c", "1,nan,0"):
            with self.assertRaises(argparse.ArgumentTypeError):
                parse_view(bad)


if __name__ == "__main__":
    unittest.main()

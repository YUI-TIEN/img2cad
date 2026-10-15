from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import img2cad_cli  # noqa: E402


class CliTests(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        saved_argv, saved_path = list(sys.argv), list(sys.path)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = img2cad_cli.main(list(argv))
        finally:
            sys.argv, sys.path[:] = saved_argv, saved_path
        return code, out.getvalue(), err.getvalue()

    def test_help_lists_every_command(self) -> None:
        code, out, _ = self.run_cli("--help")
        self.assertEqual(code, 0)
        for command in [*img2cad_cli.COMMANDS, "doctor", "version"]:
            self.assertIn(command, out)

    def test_every_command_script_exists(self) -> None:
        for command, (script, _) in img2cad_cli.COMMANDS.items():
            self.assertTrue((ROOT / "scripts" / script).is_file(), f"{command} -> {script}")

    def test_unknown_command_fails_with_usage(self) -> None:
        code, _, err = self.run_cli("frobnicate")
        self.assertEqual(code, 2)
        self.assertIn("unknown command", err)

    def test_version_matches_version_file(self) -> None:
        code, out, _ = self.run_cli("version")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_subcommand_passes_arguments_through(self) -> None:
        code, out, _ = self.run_cli("workflow", "--help")
        self.assertEqual(code, 0)
        self.assertIn("promote", out)


if __name__ == "__main__":
    unittest.main()

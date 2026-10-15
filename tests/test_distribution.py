"""Plugin manifests, skills and the MCP server stay consistent with the package."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mcp_server  # noqa: E402

VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
MANIFESTS = [".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json", "gemini-extension.json"]
UVX_ARGS = ["--python", "3.13", "--from", "git+https://github.com/YUI-TIEN/img2cad", "img2cad", "mcp"]


class ManifestTests(unittest.TestCase):
    def load(self, name: str) -> dict:
        return json.loads((ROOT / name).read_text(encoding="utf-8"))

    def test_versions_match_version_file(self) -> None:
        for name in MANIFESTS:
            self.assertEqual(self.load(name)["version"], VERSION, name)
        self.assertEqual(self.load(".claude-plugin/marketplace.json")["plugins"][0]["version"], VERSION)

    def test_mcp_configs_start_the_packaged_server(self) -> None:
        servers = [self.load(name)["mcpServers"]["img2cad"] for name in ("claude.mcp.json", "mcp.json")]
        servers.append(self.load("gemini-extension.json")["mcpServers"]["img2cad"])
        for server in servers:
            self.assertEqual(server, {"command": "uvx", "args": UVX_ARGS})
        for name in MANIFESTS[:3]:
            self.assertTrue((ROOT / self.load(name)["mcpServers"]).is_file(), name)

    def test_every_skill_has_matching_front_matter(self) -> None:
        listed = self.load("skills.sh.json")["skills"]
        found = sorted(str(path.parent.relative_to(ROOT)) for path in (ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual(sorted(listed), found)
        for skill in found:
            text = (ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
            match = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(match, skill)
            self.assertEqual(match.group(1), Path(skill).name)

    def test_skill_links_resolve(self) -> None:
        for skill in (ROOT / "skills").glob("*/*.md"):
            for target in re.findall(r"\]\(([^)#:]+)\)", skill.read_text(encoding="utf-8")):
                self.assertTrue((skill.parent / target).exists(), f"{skill}: {target}")


class SiteTests(unittest.TestCase):
    def test_site_sources_and_links(self) -> None:
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        for asset in ("style.css", "app.js", "./vendor/three/build/three.module.min.js", "llms.txt"):
            self.assertIn(asset, html)
        self.assertTrue((ROOT / "scripts/vendor/three/build/three.module.min.js").is_file())
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/build_site.py --out _site", workflow)

    def test_every_example_has_what_the_site_needs(self) -> None:
        import build_site

        for example in (ROOT / "examples").glob("*/example.json"):
            summary = build_site.example_summary(example.parent)
            self.assertTrue(summary["title"] and summary["techniques"], example)
            self.assertTrue((example.parent / "reference.png").is_file(), example)


class McpServerTests(unittest.TestCase):
    def test_initialize_and_list_tools(self) -> None:
        server = mcp_server.Server()
        reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(reply["result"]["serverInfo"], {"name": "img2cad", "version": VERSION})
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({tool["name"] for tool in tools}, {"img2cad_run", "img2cad_inspect", "img2cad_show", "img2cad_image"})
        self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)

    def test_tool_errors_are_reported_not_raised(self) -> None:
        server = mcp_server.Server()
        for name, arguments in (("img2cad_run", {"command": "rm"}), ("img2cad_image", {"path": "missing.png"}), ("img2cad_run", {"bad": 1})):
            result = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": name, "arguments": arguments}})["result"]
            self.assertTrue(result["isError"], name)

    def test_stdio_round_trip_runs_the_cli(self) -> None:
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "img2cad_run", "arguments": {"command": "version"}}}]
        done = subprocess.run([sys.executable, str(ROOT / "scripts/mcp_server.py")], input="\n".join(map(json.dumps, requests)) + "\n",
                              capture_output=True, text=True, timeout=60, check=True)
        payload = json.loads(json.loads(done.stdout.splitlines()[0])["result"]["content"][0]["text"])
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(payload["stdout"].strip(), VERSION)


@unittest.skipUnless(os.environ.get("IMG2CAD_CAD_PYTHON"), "set IMG2CAD_CAD_PYTHON to run drawing and printcheck")
class DeliverableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import tempfile

        cls.temp = tempfile.TemporaryDirectory(prefix="img2cad-deliver-")
        cls.root = Path(cls.temp.name)
        cad = os.environ["IMG2CAD_CAD_PYTHON"]
        subprocess.run([cad, "-B", str(ROOT / "scripts/run_agent_cad.py"), str(ROOT / "examples/mounting-plate/model.py"), str(cls.root / "plate"),
                        "--cad-python", cad, "--mesh-formats", "stl"], capture_output=True, text=True, check=True)
        cls.step = cls.root / "plate/model.step"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def cli(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([os.environ["IMG2CAD_CAD_PYTHON"], "-B", str(ROOT / "scripts/img2cad_cli.py"), *argv], capture_output=True, text=True, check=False)

    def test_drawing_has_three_views_dimensions_and_hole_table(self) -> None:
        result = self.cli("drawing", str(self.step), str(self.root / "drawing"))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["overall_mm"], {"x": 80.0, "y": 50.0, "z": 6.0})
        self.assertIn("4x hole D6 along Z at (-32, -17, 0), (-32, 17, 0), (32, -17, 0), (32, 17, 0)", report["notes"])
        self.assertIn("1x hole D10 along Z at (0, 0, 0)", report["notes"])
        svg = (self.root / "drawing/drawing.svg").read_text(encoding="utf-8")
        self.assertIn("<svg", svg)
        self.assertGreater(svg.count("<path"), 20)
        self.assertTrue((self.root / "drawing/drawing.dxf").read_text(encoding="utf-8", errors="replace").startswith("  0\nSECTION"))

    def test_printcheck_passes_a_plate_and_fails_an_open_mesh(self) -> None:
        for target in (self.step, self.root / "plate/model.stl"):
            result = self.cli("printcheck", str(target))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "pass", report)
            thin = next(check for check in report["checks"] if check["check"] == "thin_walls")
            self.assertGreater(thin["min_mm"], 4.0)
        # An open box (five faces) is not watertight.
        sys.path.insert(0, str(ROOT / "scripts"))
        import numpy as np

        import printcheck

        vertices = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=float) * 10
        faces = [[0, 2, 1], [0, 3, 2], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
        report = printcheck.printcheck([("open box", vertices, np.array(faces))])
        watertight = report["checks"][0]
        self.assertEqual((watertight["status"], watertight["open_edges"]), ("fail", 4))


if __name__ == "__main__":
    unittest.main()

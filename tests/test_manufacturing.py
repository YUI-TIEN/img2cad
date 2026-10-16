"""img2cad parts / urdf / dfm / slice."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class SliceTests(unittest.TestCase):
    def test_slice_runs_the_slicer_and_reads_its_estimates(self) -> None:
        import slice as slicer

        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "prusa-slicer"
            fake.write_text("#!/bin/sh\nwhile [ $# -gt 1 ]; do [ \"$1\" = --output ] && out=$2; shift; done\n"
                            "printf '; filament used [g] = 3.2\\n; estimated printing time (normal mode) = 12m 5s\\n' > \"$out\"\n")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            report = slicer.slice_model(Path(temp) / "m.stl", Path(temp) / "out" / "m.gcode", slicer_path=str(fake))
            self.assertEqual(report["slicer"], "prusa")
            self.assertEqual(report["filament_g"], "3.2")
            self.assertEqual(report["estimated_time"], "12m 5s")

    def test_missing_slicer_is_a_clear_error(self) -> None:
        import slice as slicer

        old = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            with self.assertRaisesRegex(FileNotFoundError, "no slicer found"):
                slicer.find_slicer()
        finally:
            os.environ["PATH"] = old

    def test_orca_command_line(self) -> None:
        import slice as slicer

        args = slicer.command("orca", "orca-slicer", Path("m.3mf"), Path("o/p.3mf"), None, "m.json,p.json,f.json")
        self.assertIn("--export-3mf", args)
        self.assertEqual(args[args.index("--load-settings") + 1], "m.json;p.json")
        self.assertEqual(args[args.index("--load-filaments") + 1], "f.json")


@unittest.skipUnless(os.environ.get("IMG2CAD_CAD_PYTHON"), "set IMG2CAD_CAD_PYTHON to build CAD")
class CadManufacturingTests(unittest.TestCase):
    def test_standard_parts_are_valid_solids(self) -> None:
        import std_parts

        for kind, size, length in (("screw", "M3", 12), ("nut", "M5", None), ("washer", "M8", None),
                                   ("bearing", "608", None), ("nema17", None, None), ("extrusion2020", None, 100)):
            part = std_parts.make(kind, size, length)
            self.assertTrue(part.is_valid, kind)
            self.assertGreater(part.volume, 0, kind)
        box = std_parts.ball_bearing("608").bounding_box()
        self.assertAlmostEqual(box.size.X, 22, places=3)
        self.assertAlmostEqual(box.size.Z, 7, places=3)

    def test_urdf_has_links_joints_and_exact_inertia(self) -> None:
        from build123d import Box, Color, Compound, Pos, export_step
        import urdf_export

        base, arm = Box(40, 40, 10), Pos(0, 0, 30) * Box(10, 10, 40)
        base.label, base.color, arm.label, arm.color = "base", Color(1, 0, 0), "arm", Color(0, 0, 1)
        with tempfile.TemporaryDirectory() as temp:
            export_step(Compound(children=[base, arm]), str(Path(temp) / "m.step"))
            spec = {"joints": [{"name": "spin", "type": "revolute", "parent": "base", "child": "arm", "origin": [0, 0, 10]}]}
            report = urdf_export.export_urdf(Path(temp) / "m.step", Path(temp) / "out", spec)
            robot = ET.parse(report["urdf"]).getroot()
            self.assertEqual(report["root"], "base")
            self.assertTrue((Path(temp) / "out" / "meshes" / "arm.stl").exists())
            joint = robot.find("joint")
            self.assertEqual(joint.get("type"), "revolute")
            self.assertEqual(joint.find("origin").get("xyz"), "0 0 0.01")
            link = next(l for l in robot.findall("link") if l.get("name") == "base")
            mass = float(link.find("inertial/mass").get("value"))
            self.assertAlmostEqual(mass, 16000 * 1.24e-6, places=6)
            ixx = float(link.find("inertial/inertia").get("ixx"))
            self.assertAlmostEqual(ixx, mass * (0.04 ** 2 + 0.01 ** 2) / 12, delta=1e-9)

    def test_dfm_finds_cnc_and_sheet_problems(self) -> None:
        from build123d import Axis, Box, Cylinder, Pos, export_step
        import dfm

        with tempfile.TemporaryDirectory() as temp:
            sharp = Box(60, 40, 20) - Pos(0, 0, 5) * Box(30, 20, 10) - Pos(20, 0, 0) * Cylinder(0.3, 20)
            export_step(sharp, str(Path(temp) / "c.step"))
            checks = {c["name"]: c for c in dfm.dfm(Path(temp) / "c.step", "cnc")["parts"][0]["checks"]}
            self.assertEqual(len(checks["sharp_internal_corners"]["evidence"]), 4)
            self.assertEqual(checks["deep_holes"]["status"], "fail")
            self.assertEqual(checks["tiny_holes"]["status"], "warn")
            pocket = Box(30, 20, 10)
            pocket = pocket.fillet(3, pocket.edges().filter_by(Axis.Z))
            export_step(Box(60, 40, 20) - Pos(0, 0, 5) * pocket, str(Path(temp) / "f.step"))
            report = dfm.dfm(Path(temp) / "f.step", "cnc", tool_radius=2)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(dfm.dfm(Path(temp) / "f.step", "cnc", tool_radius=4)["status"], "fail")
            export_step(Box(50, 30, 2) - Cylinder(0.8, 2), str(Path(temp) / "s.step"))
            sheet = {c["name"]: c for c in dfm.dfm(Path(temp) / "s.step", "sheet")["parts"][0]["checks"]}
            self.assertAlmostEqual(sheet["uniform_thickness"]["thickness_mm"], 2.0, delta=0.01)
            self.assertEqual(sheet["small_holes"]["status"], "warn")


if __name__ == "__main__":
    unittest.main()

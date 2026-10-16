"""img2cad parts / urdf / dfm / slice."""

from __future__ import annotations

import math
import os
import stat
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
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


class SendTests(unittest.TestCase):
    def serve(self):
        import http.server
        import threading

        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def handle_one(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                seen.append((self.command, self.path, dict(self.headers), body))
                self.send_response(201)
                self.end_headers()
                self.wfile.write(b'{"done": true}')

            do_POST = do_PUT = handle_one

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f"127.0.0.1:{server.server_port}", seen

    def test_octoprint_prusalink_and_moonraker_uploads(self) -> None:
        import send_print

        host, seen = self.serve()
        with tempfile.TemporaryDirectory() as temp:
            gcode = Path(temp) / "part.gcode"
            gcode.write_text("G28\n")
            send_print.send(gcode, "octoprint", host, start=True, key="k1")
            send_print.send(gcode, "prusalink", host, start=False, key="k2")
            send_print.send(gcode, "moonraker", host, start=True, key="")
        (m1, p1, h1, b1), (m2, p2, h2, b2), (m3, p3, h3, b3) = seen
        self.assertEqual((m1, p1, h1["X-Api-Key"]), ("POST", "/api/files/local", "k1"))
        self.assertIn(b'name="print"\r\n\r\ntrue', b1)
        self.assertIn(b"G28", b1)
        self.assertEqual((m2, p2, h2["Print-After-Upload"], b2), ("PUT", "/api/v1/files/usb/part.gcode", "?0", b"G28\n"))
        self.assertEqual((m3, p3), ("POST", "/server/files/upload"))
        self.assertNotIn("X-Api-Key", h3)

    def test_bambu_needs_an_access_code_and_a_sliced_3mf(self) -> None:
        import send_print

        with tempfile.TemporaryDirectory() as temp:
            gcode = Path(temp) / "part.gcode"
            gcode.write_text("G28\n")
            with self.assertRaisesRegex(RuntimeError, "access code"):
                send_print.send(gcode, "bambu", "127.0.0.1", key="")
            with self.assertRaisesRegex(RuntimeError, "gcode.3mf"):
                send_print.send(gcode, "bambu", "127.0.0.1", key="12345678")


@unittest.skipUnless(os.environ.get("IMG2CAD_CAD_PYTHON"), "set IMG2CAD_CAD_PYTHON to build CAD")
class CadManufacturingTests(unittest.TestCase):
    def test_standard_parts_are_valid_solids(self) -> None:
        import std_parts

        for kind, size, length in (("screw", "M3", 12), ("nut", "M5", None), ("washer", "M8", None),
                                   ("bearing", "608", None), ("nema17", None, None), ("extrusion2020", None, 100)):
            part = std_parts.make(kind, size, length)
            self.assertTrue(part.is_valid, kind)
            self.assertGreater(part.volume, 0, kind)
        for kind, size, length, extra in (("gear", None, None, {"module": 2, "teeth": 17, "width": 8, "bore": 5}), ("pulley", None, None, {}),
                                          ("rail", "MGN12", 100, {}), ("servo", "MG996R", None, {}), ("screw", "M3", 10, {"threads": True})):
            part = std_parts.make(kind, size, length, **extra)
            self.assertTrue(part.is_valid, kind)
        gear = std_parts.spur_gear(2, 17, 8)
        self.assertAlmostEqual(gear.bounding_box().size.X, 2 * (17 + 2) / 2 * 2, delta=0.3)  # tip diameter m(z + 2)
        threaded, plain = std_parts.socket_head_screw("M3", 10, threads=True), std_parts.socket_head_screw("M3", 10)
        self.assertLess(threaded.volume, plain.volume)
        self.assertAlmostEqual(threaded.bounding_box().size.X, 5.5, places=3)
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
            sdf = ET.parse(urdf_export.export_urdf(Path(temp) / "m.step", Path(temp) / "out", spec, fmt="sdf")["sdf"]).getroot()
            arm_link = next(l for l in sdf.iter("link") if l.get("name") == "arm")
            self.assertEqual(arm_link.find("pose").text, "0 0 0.01 0 0 0")
            self.assertEqual(sdf.find("model/joint").get("type"), "revolute")
            mjcf = urdf_export.export_urdf(Path(temp) / "m.step", Path(temp) / "out", spec, fmt="mjcf")["mjcf"]
            body = ET.parse(mjcf).getroot().find("worldbody/body/body")
            self.assertEqual((body.get("name"), body.get("pos"), body.find("joint").get("type")), ("arm", "0 0 0.01", "hinge"))
            try:
                import mujoco
            except ImportError:
                return
            model = mujoco.MjModel.from_xml_path(mjcf)
            data = mujoco.MjData(model)
            mujoco.mj_forward(model, data)
            self.assertAlmostEqual(float(data.geom_xpos[1][2]), 0.03, places=6)  # the arm sits where it was modelled

    def test_orient_turns_a_mushroom_cap_down(self) -> None:
        from build123d import Align, Axis, Cylinder, Pos, export_step, import_step
        import printcheck

        mushroom = Cylinder(5, 30, align=(Align.CENTER, Align.CENTER, Align.MIN)) + Pos(0, 0, 30) * Cylinder(20, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))
        mushroom = mushroom.rotate(Axis.X, 90)  # lying on its side, cap toward -Y
        with tempfile.TemporaryDirectory() as temp:
            export_step(mushroom, str(Path(temp) / "m.step"))
            parts = printcheck.load_parts(Path(temp) / "m.step")
            orientation = printcheck.best_orientation(parts)
            self.assertEqual(orientation["down"], [0.0, -1.0, 0.0])
            self.assertEqual(orientation["best"]["support_area_mm2"], 0.0)
            self.assertGreater(orientation["as_given"]["support_area_mm2"], 100)
            oriented = printcheck.apply_rotation(parts, np.array(orientation["rotation_matrix"]))
            self.assertEqual(printcheck.printcheck(oriented)["checks"][3]["status"], "pass")  # overhangs
            printcheck.write_oriented(Path(temp) / "m.step", Path(temp) / "o.step", oriented, orientation)
            box = import_step(str(Path(temp) / "o.step")).bounding_box()
            self.assertAlmostEqual(box.min.Z, 0, places=4)
            self.assertAlmostEqual(box.size.Z, 34, places=3)
            printcheck.write_oriented(Path(temp) / "m.step", Path(temp) / "o.stl", oriented, orientation)
            vertices, _ = printcheck.read_stl(Path(temp) / "o.stl")
            self.assertAlmostEqual(float(vertices[:, 2].max()), 34, places=2)

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
            self.assertEqual(checks["setups"]["plan"][0]["direction"], "+Z")
            self.assertEqual(len(checks["setups"]["plan"]), 2)

    def test_sheet_flat_blank_and_hole_to_bend(self) -> None:
        from build123d import Cylinder, Plane, Pos, Rectangle, Sketch, export_step, extrude, fillet
        import dfm

        t, r = 2.0, 2.0  # L bracket: 40 x 30 legs, 2 mm sheet, 2 mm inside radius, 30 mm wide
        profile = Sketch() + Pos(20, t / 2) * Rectangle(40, t) + Pos(t / 2, 15) * Rectangle(t, 30)
        profile = fillet([v for v in profile.vertices() if abs(v.X - t) < 1e-6 and abs(v.Y - t) < 1e-6], r)
        profile = fillet([v for v in profile.vertices() if abs(v.X) < 1e-6 and abs(v.Y) < 1e-6], r + t)
        bracket = extrude(Plane.XZ * profile, amount=-30) - Pos(8, 15, 0) * Cylinder(1.5, 10)
        with tempfile.TemporaryDirectory() as temp:
            export_step(bracket, str(Path(temp) / "l.step"))
            checks = {c["name"]: c for c in dfm.dfm(Path(temp) / "l.step", "sheet", k_factor=0.4)["parts"][0]["checks"]}
        blank = checks["flat_blank"]
        straight, angle = (40 - 4) + (30 - 4), math.pi / 2
        self.assertAlmostEqual(blank["length_mm"], straight + angle * (r + 0.4 * t), delta=0.1)
        self.assertAlmostEqual(blank["width_mm"], 30, places=3)
        self.assertAlmostEqual(blank["bends"][0]["angle_deg"], 90, delta=0.1)
        self.assertEqual(checks["hole_to_bend"]["status"], "warn")


if __name__ == "__main__":
    unittest.main()

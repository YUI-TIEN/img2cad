"""img2cad parts / urdf / dfm / slice."""

from __future__ import annotations

import json
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
            arm_body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "arm")
            arm_geom = next(g for g in range(model.ngeom) if model.geom_bodyid[g] == arm_body)
            self.assertAlmostEqual(float(data.geom_xpos[arm_geom][2]), 0.03, places=6)  # the arm sits where it was modelled

    def test_urdf_guesses_shaft_joints_and_takes_materials(self) -> None:
        from build123d import Align, Box, Color, Compound, Cylinder, Pos, export_step
        import urdf_export

        base = Box(60, 60, 10) - Cylinder(4.1, 10) + Pos(30, 15, 9.5) * Box(10, 6, 9)  # a stop block the arm runs into
        arm = Pos(20, 0, 12) * Box(60, 12, 4) + Pos(0, 0, -4) * Cylinder(4, 22, align=(Align.CENTER, Align.CENTER, Align.MIN))
        arm -= Pos(45, 0, 12) * Cylinder(2.05, 4)
        finger = Pos(45, 0, 6) * Cylinder(2, 14, align=(Align.CENTER, Align.CENTER, Align.MIN))
        cover = Pos(-20, 20, 7) * Box(10, 10, 4)
        for part, label in ((base, "base"), (arm, "arm"), (finger, "finger"), (cover, "cover")):
            part.label, part.color = label, Color(0.5, 0.5, 0.5)
        with tempfile.TemporaryDirectory() as temp:
            export_step(Compound(children=[base, arm, finger, cover]), str(Path(temp) / "r.step"))
            report = urdf_export.export_urdf(Path(temp) / "r.step", Path(temp) / "out", materials={"base": "aluminium", "finger": 7.85e-6},
                                             guess=True)
            joints = {j["child"]: j for j in report["joints"]}
            self.assertEqual((joints["arm"]["parent"], joints["arm"]["type"], joints["arm"].get("guessed")), ("base", "revolute", True))
            # turning +Z, the arm's edge (y = 6) meets the stop's far corner (35, 12) at 18.92 - asin(6 / 37.0) = 9.59 degrees;
            # the other way it is free
            expected = math.degrees(math.atan2(12, 35) - math.asin(6 / math.hypot(35, 12)))
            self.assertAlmostEqual(math.degrees(joints["arm"]["limit"]["upper"]), expected, delta=0.6)
            self.assertAlmostEqual(joints["arm"]["limit"]["lower"], -math.pi, places=3)
            self.assertEqual((joints["finger"]["parent"], joints["finger"]["type"]), ("arm", "continuous"))  # a plain pin
            self.assertEqual(joints["cover"]["type"], "fixed")
            masses = {link["link"]: link for link in report["links"]}
            self.assertEqual(masses["base"]["density"], 2.7e-6)
            self.assertEqual(masses["arm"]["density"], 1.24e-6)
            self.assertEqual(masses["finger"]["density"], 7.85e-6)
            self.assertAlmostEqual(masses["base"]["mass_kg"], base.volume * 2.7e-6, places=6)
            guessed = json.loads(Path(report["joints_guessed"]).read_text())
            arm_joint = next(j for j in guessed["joints"] if j["child"] == "arm")
            self.assertEqual([abs(v) for v in arm_joint["axis"]], [0, 0, 1])
            self.assertAlmostEqual(arm_joint["origin"][0], 0, places=3)
            with self.assertRaisesRegex(ValueError, "material"):
                urdf_export.export_urdf(Path(temp) / "r.step", Path(temp) / "out", materials={"base": "cheese"})

    def test_urdf_guesses_a_slide_with_travel_limits_and_axis_frames(self) -> None:
        from build123d import Box, Color, Compound, Pos, export_step
        import urdf_export

        guide = Box(100, 30, 10) - Pos(0, 0, 3) * Box(100, 14, 7)  # a channel along X
        slider = Pos(-10, 0, 3) * Box(20, 14, 7)  # on its floor, between its walls
        lid = Pos(30, 12, 5.5) * Box(10, 4, 1)  # resting on the guide's top: one plane only
        for part, label in ((guide, "guide"), (slider, "slider"), (lid, "plate")):
            part.label, part.color = label, Color(0.5, 0.5, 0.5)
        with tempfile.TemporaryDirectory() as temp:
            export_step(Compound(children=[guide, slider, lid]), str(Path(temp) / "s.step"))
            report = urdf_export.export_urdf(Path(temp) / "s.step", Path(temp) / "out", guess=True)
            joints = {j["child"]: j for j in report["joints"]}
            self.assertEqual(joints["slider"]["type"], "prismatic")
            self.assertEqual((joints["slider"]["limit"]["lower"], joints["slider"]["limit"]["upper"]), (-0.03, 0.05))
            self.assertEqual(joints["plate"]["type"], "fixed")  # resting on one plane is not a slide
            self.assertTrue((Path(temp) / "out/meshes/slider_collision.stl").exists())
            robot = ET.parse(report["urdf"]).getroot()
            joint = robot.find("joint[@name='guide_to_slider']")
            self.assertEqual(joint.find("axis").get("xyz"), "0 0 1")  # the child frame's z runs along the slide
            # rpy of that joint frame rotates z onto world X
            rpy = [float(v) for v in joint.find("origin").get("rpy").split()]
            self.assertTrue(np.allclose(urdf_export.rpy_matrix(*rpy)[:, 2], [1, 0, 0], atol=1e-4))
            try:
                import mujoco
            except ImportError:
                return
            mjcf = urdf_export.export_urdf(Path(temp) / "s.step", Path(temp) / "mj", guess=True, fmt="mjcf")["mjcf"]
            model = mujoco.MjModel.from_xml_path(mjcf)
            data = mujoco.MjData(model)
            data.qpos[0] = 0.02
            mujoco.mj_forward(model, data)
            body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "slider")
            geom = next(g for g in range(model.ngeom) if model.geom_bodyid[g] == body)
            self.assertTrue(np.allclose(data.geom_xpos[geom], [0.01, 0, 0.003], atol=1e-6))  # moved +20 mm along X

    def test_sheet_unfolds_bends_on_two_axes_with_holes(self) -> None:
        from build123d import Box, Cylinder, Pos, Rot, export_step
        import dfm

        t, r = 2.0, 2.0  # a tray corner: 60 x 40 base, a 20 mm flange up along X = 60 and another along Y = 40

        def bend(along_x: bool, edge: float, lo: float, hi: float):
            if along_x:  # flange on the +X edge, bend axis along Y
                ring = Pos(edge, 0, t + r) * Rot(90, 0, 0) * (Cylinder(r + t, 200) - Cylinder(r, 200))
                quad = Pos(edge + (r + t) / 2, (lo + hi) / 2, (t + r) / 2) * Box(r + t, hi - lo, t + r)
                flange = Pos(edge + r + t / 2, (lo + hi) / 2, t + r + 10) * Box(t, hi - lo, 20)
            else:  # flange on the +Y edge, bend axis along X
                ring = Pos(0, edge, t + r) * Rot(0, 90, 0) * (Cylinder(r + t, 200) - Cylinder(r, 200))
                quad = Pos((lo + hi) / 2, edge + (r + t) / 2, (t + r) / 2) * Box(hi - lo, r + t, t + r)
                flange = Pos((lo + hi) / 2, edge + r + t / 2, t + r + 10) * Box(hi - lo, t, 20)
            return (ring & quad) + flange

        tray = Pos(30, 20, t / 2) * Box(60, 40, t) + bend(True, 60, 0, 40) + bend(False, 40, 0, 50)
        tray -= Pos(20, 20, 0) * Cylinder(3, 10)
        tray -= Pos(60 + r + t / 2, 20, t + r + 12) * Rot(0, 90, 0) * Cylinder(2.5, 10)
        tray -= Pos(25, 40 + r + t / 2, t + r + 12) * Rot(90, 0, 0) * Cylinder(2, 10)
        with tempfile.TemporaryDirectory() as temp:
            export_step(tray, str(Path(temp) / "tray.step"))
            checks = {c["name"]: c for c in dfm.dfm(Path(temp) / "tray.step", "sheet", thickness=t, k_factor=0.44,
                                                    flat_dxf=Path(temp) / "flat.dxf")["parts"][0]["checks"]}
            self.assertTrue((Path(temp) / "flat.dxf").read_text(errors="replace").startswith("  0\nSECTION"))
        flat = checks["flat_blank"]
        allowance = math.pi / 2 * (r + 0.44 * t)
        self.assertAlmostEqual(sorted(flat["size_mm"])[1], 60 + allowance + 20, places=2)
        self.assertAlmostEqual(sorted(flat["size_mm"])[0], 40 + allowance + 20, places=2)
        area = 60 * 40 + (allowance + 20) * (40 + 50) - math.pi * (3 ** 2 + 2.5 ** 2 + 2 ** 2)
        self.assertAlmostEqual(flat["area_mm2"], area, delta=0.05)
        self.assertEqual(flat["holes"], 3)
        self.assertEqual(flat["status"], "pass")
        self.assertEqual([b["direction"] for b in flat["bends"]], ["up", "up"])

    def test_dfm_setups_access_corners_and_threads(self) -> None:
        from build123d import Box, Cylinder, Pos, Rot, export_step
        import dfm
        import std_parts

        def checks(shape, axes="3"):
            with tempfile.TemporaryDirectory() as temp:
                export_step(shape, str(Path(temp) / "p.step"))
                return {c["name"]: c for c in dfm.dfm(Path(temp) / "p.step", "cnc", axes=axes)["parts"][0]["checks"]}

        tilted = Box(40, 40, 20) - Rot(0, 30, 0) * Cylinder(3, 60)  # a hole 30 degrees off vertical
        self.assertEqual(checks(tilted, "3")["setups"]["status"], "fail")
        indexed = checks(tilted, "3+2")["setups"]
        self.assertEqual(indexed["status"], "pass")
        self.assertTrue(any(p["direction"].startswith("(") for p in indexed["plan"]))  # a tilted, indexed setup
        self.assertEqual(len(checks(tilted, "5")["setups"]["plan"]), 1)
        groove = Box(40, 40, 20) - Pos(0, 0, 10) * Rot(0, 45, 0) * Box(10, 60, 10)  # a V groove along Y
        self.assertEqual(len(checks(groove)["inaccessible_corners"]["evidence"]), 1)
        tee = Pos(0, 0, 10) * Box(40, 20, 4) + Pos(0, 0, 4) * Box(10, 20, 8)  # a ledge hides its underside from +Z
        plan = checks(tee)["setups"]["plan"]
        self.assertEqual(sorted(p["direction"] for p in plan), ["+Z", "-Z"])
        self.assertEqual(plan[0]["jaw_opening_mm"], 20.0)
        nut = Box(10, 10, 6) - std_parts.threaded_rod(4, 0.7, 6)
        self.assertEqual([(t["thread"], t["kind"]) for t in checks(nut)["modelled_threads"]["evidence"]], [("M4", "internal")])
        screw = std_parts.socket_head_screw("M3", 10, threads=True)
        self.assertEqual([(t["thread"], t["kind"]) for t in checks(screw)["modelled_threads"]["evidence"]], [("M3", "external")])

    def test_inspect_lists_planar_faces_for_pockets(self) -> None:
        from build123d import Box, Pos
        from inspect_step import planar_faces

        part = Box(80, 50, 6, ) - Pos(20, 0, 3) * Box(20, 10, 6)  # a 3 mm deep pocket (top at z = 3)
        floors = [f for f in planar_faces(part) if f["normal"] == "+z" and abs(f["offset"]) < 1e-6]
        self.assertEqual(len(floors), 1)
        self.assertEqual((floors[0]["center"], floors[0]["size"]), ([20.0, 0.0], [20.0, 10.0]))

    def test_drawing_callouts_pockets_sections_and_auxiliary_views(self) -> None:
        from build123d import Axis, Box, BuildPart, Cylinder, CounterBoreHole, CounterSinkHole, Hole, Locations, Pos, Rot, export_step
        import drawing

        with BuildPart() as block:
            Box(80, 50, 12)
            with Locations(block.faces().sort_by(Axis.Z)[-1]):
                with Locations((-30, -15)):
                    CounterBoreHole(2, 4, 3)
                with Locations((-30, 15)):
                    CounterSinkHole(2, 4, counter_sink_angle=90)
                with Locations((30, 15)):
                    Hole(1.65, depth=8)  # M4 tap drill
        part = block.part - Pos(15, -8, 4) * Box(30, 16, 4)  # a pocket 30 x 16, 4 deep
        part -= Pos(-5, 0, 6) * Rot(0, 35, 0) * Cylinder(2.5, 40)  # a hole 35 degrees off vertical
        with tempfile.TemporaryDirectory() as temp:
            export_step(part, str(Path(temp) / "p.step"))
            report = drawing.make_drawing(Path(temp) / "p.step", Path(temp), ("svg",), "Test", "x@-30", "f")
            with self.assertRaises(ValueError):
                drawing.make_drawing(Path(temp) / "p.step", Path(temp), ("svg",), "Test", "w@3")
        callouts = sorted(f["callout"] for f in report["feature_dimensions"])
        self.assertEqual(callouts, ["M4x0.7 8 deep", "P1 30x16 depth 4", "\u00d84 CBORE \u00d88x3", "\u00d84 CSK 90deg"])
        pocket = next(f for f in report["feature_dimensions"] if f["kind"] == "pocket")
        self.assertEqual((pocket["from_datum"], pocket["size"], pocket["depth"]), ([40.0, 9.0], [30.0, 16.0], 4.0))
        self.assertEqual((report["section"]["plane"], report["section"]["seen_in"]), ("x = -30.000", "right"))
        self.assertEqual(len(report["auxiliary_views"]), 1)
        self.assertAlmostEqual(report["auxiliary_views"][0]["direction"][2], 0.819152, places=4)
        self.assertIn("General tolerances ISO 2768-f unless stated", report["notes"])

    def test_dfm_names_hole_types(self) -> None:
        from build123d import Axis, Box, BuildPart, CounterBoreHole, CounterSinkHole, Hole, Location, Locations, export_step
        import dfm

        with BuildPart() as block:
            Box(40, 20, 10)
            with Locations(block.faces().sort_by(Axis.Z)[-1]):
                with Locations((-12, 0)):
                    CounterBoreHole(2, 4, 3)
                with Locations((0, 0)):
                    CounterSinkHole(2, 4, counter_sink_angle=90)
                with Locations((12, 0)):
                    Hole(1.25, depth=8)  # M3 tap drill, blind
            with Locations(Location((20, 6, 0), (0, 90, 0))):
                Hole(1.65, depth=15)  # M4 tap drill, too deep to tap
        with tempfile.TemporaryDirectory() as temp:
            export_step(block.part, str(Path(temp) / "h.step"))
            check = next(c for c in dfm.dfm(Path(temp) / "h.step", "cnc")["parts"][0]["checks"] if c["name"] == "hole_types")
        holes = {(h["type"], h["bore_mm"]): h for h in check["evidence"]}
        self.assertEqual(holes[("counterbore", 4.0)]["counterbore_mm"], 8.0)
        self.assertEqual(holes[("countersink", 4.0)]["countersink_deg"], 90.0)
        self.assertEqual(holes[("tapped", 2.5)]["likely_thread"], "M3")
        self.assertEqual(holes[("tapped", 3.3)]["likely_thread"], "M4")
        self.assertTrue(holes[("tapped", 3.3)]["notes"])
        self.assertFalse(holes[("tapped", 2.5)]["notes"])
        self.assertEqual(check["status"], "warn")

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

    def test_orient_respects_load_axis_and_cosmetic_faces(self) -> None:
        from build123d import Box, export_step
        import printcheck

        with tempfile.TemporaryDirectory() as temp:
            export_step(Box(100, 10, 10), str(Path(temp) / "bar.step"))
            parts = printcheck.load_parts(Path(temp) / "bar.step")
        self.assertEqual(printcheck.best_orientation(parts)["down"], [0.0, 0.0, -1.0])
        loaded = printcheck.best_orientation(parts, load_axis=(0, 0, 1))  # a vertical load must lie in the layers
        self.assertEqual(loaded["best"]["load_across_layers"], 0.0)
        self.assertEqual(abs(loaded["down"][2]), 0.0)
        self.assertEqual(loaded["as_given"]["load_across_layers"], 1.0)
        pretty = printcheck.best_orientation(parts, cosmetic=[(0, 0, -1)])  # keep the bottom face off the bed
        self.assertNotEqual(pretty["down"], [0.0, 0.0, -1.0])
        self.assertEqual(pretty["best"]["cosmetic_area_scarred_mm2"], 0.0)

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

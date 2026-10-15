#!/usr/bin/env python3
"""Local 3D viewer for img2cad outputs (STEP, GLB, STL, 3MF).

    img2cad view model.step other.glb            # serve and open in the browser
    img2cad view model.step --no-open --json     # print {"url": ...} and keep serving

Orbit/zoom, standard views, part list with colours and visibility, click a part
to see its name and size, measure the distance between two picked points,
section planes along X/Y/Z, wireframe, and PNG screenshots. STEP files are
converted to GLB (keeping part names and colours) on first view. Only the files
named on the command line (or registered by the MCP server) are served.

three.js is bundled (scripts/vendor/three), so the viewer works offline.
"""

from __future__ import annotations

import argparse
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import tempfile
import threading
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
import webbrowser

SUPPORTED = {".step", ".stp", ".glb", ".gltf", ".stl", ".3mf"}
CACHE_DIR = Path(tempfile.gettempdir()) / "img2cad-viewer"
VENDOR_DIR = (Path(__file__).resolve().parent / "vendor").resolve()


class Registry:
    """Files the viewer may serve, by id; STEP files get a cached GLB."""

    def __init__(self) -> None:
        self.files: dict[str, Path] = {}
        self.lock = threading.Lock()

    def add(self, path: Path) -> str:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix.lower() not in SUPPORTED:
            raise ValueError(f"unsupported file type {path.suffix}; use one of {sorted(SUPPORTED)}")
        file_id = hashlib.sha256(str(path).encode()).hexdigest()[:12]
        with self.lock:
            self.files[file_id] = path
        return file_id

    def listing(self) -> list[dict[str, str]]:
        with self.lock:
            return [{"id": file_id, "name": path.name, "path": str(path), "format": viewable_format(path)} for file_id, path in self.files.items()]

    def viewable(self, file_id: str) -> Path:
        with self.lock:
            path = self.files[file_id]
        if path.suffix.lower() in (".step", ".stp"):
            return step_to_glb(path)
        return path


def viewable_format(path: Path) -> str:
    suffix = path.suffix.lower()
    return "glb" if suffix in (".step", ".stp", ".glb", ".gltf") else suffix.lstrip(".")


def step_to_glb(path: Path) -> Path:
    from mesh_export import export_meshes

    stat = path.stat()
    key = hashlib.sha256(f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16]
    target = CACHE_DIR / key / f"{path.stem}.glb"
    if not target.is_file():
        export_meshes(path, target.parent, ("glb",), stem=path.stem)
    return target


class Handler(BaseHTTPRequestHandler):
    registry: Registry

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet server
        return

    def send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            self.send_bytes(VIEWER_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path.startswith("/vendor/"):
            # Bundled three.js (no CDN needed); only files under scripts/vendor.
            target = (VENDOR_DIR / url.path[len("/vendor/"):]).resolve()
            if VENDOR_DIR in target.parents and target.is_file():
                self.send_bytes(target.read_bytes(), "text/javascript; charset=utf-8")
            else:
                self.send_bytes(b"not found", "text/plain", HTTPStatus.NOT_FOUND)
        elif url.path == "/api/files":
            self.send_bytes(json.dumps(self.registry.listing()).encode(), "application/json")
        elif url.path == "/api/file":
            file_id = (query.get("id") or [""])[0]
            try:
                path = self.registry.viewable(file_id)
            except KeyError:
                self.send_bytes(b"unknown file id", "text/plain", HTTPStatus.NOT_FOUND)
                return
            except Exception as error:  # noqa: BLE001 - report conversion failures to the page
                self.send_bytes(f"could not load: {error}".encode(), "text/plain", HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix.lower() == ".glb":
                content_type = "model/gltf-binary"
            self.send_bytes(path.read_bytes(), content_type)
        else:
            self.send_bytes(b"not found", "text/plain", HTTPStatus.NOT_FOUND)


def start_server(registry: Registry, host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    server_class = type("Img2cadViewerHandler", (Handler,), {"registry": registry})
    server = ThreadingHTTPServer((host, port), server_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_address[1]}/"


def file_url(base: str, file_id: str) -> str:
    return f"{base}?file={quote(file_id)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="port to serve on (default: any free port)")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument("--json", action="store_true", help="print the URLs as one JSON line")
    args = parser.parse_args()
    registry = Registry()
    ids = [registry.add(path) for path in args.files]
    server, base = start_server(registry, args.host, args.port)
    urls = {str(path.resolve()): file_url(base, file_id) for path, file_id in zip(args.files, ids)}
    print(json.dumps({"url": base, "files": urls}) if args.json else f"img2cad viewer: {base}  (Ctrl+C to stop)\n" + "\n".join(urls.values()), flush=True)
    if not args.no_open:
        webbrowser.open(file_url(base, ids[0]))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


VIEWER_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>img2cad viewer</title>
<style>
  :root { --bg:#eef2f6; --panel:#ffffff; --ink:#18324b; --muted:#5b6b7b; --line:#d5dde6; --accent:#2f6fb0; }
  @media (prefers-color-scheme: dark) { :root { --bg:#12171d; --panel:#1b232c; --ink:#e3ebf3; --muted:#9aa9b8; --line:#2c3844; --accent:#6aa7e6; } }
  * { box-sizing: border-box; }
  body { margin:0; height:100vh; display:grid; grid-template-columns: 280px 1fr; font:14px/1.4 system-ui, sans-serif; background:var(--bg); color:var(--ink); }
  aside { background:var(--panel); border-right:1px solid var(--line); padding:14px; overflow:auto; }
  h1 { font-size:16px; margin:0 0 10px; } h2 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:16px 0 6px; }
  select, button { font:inherit; color:inherit; background:var(--bg); border:1px solid var(--line); border-radius:6px; padding:5px 8px; cursor:pointer; }
  button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .row { display:flex; flex-wrap:wrap; gap:6px; }
  .part { display:flex; align-items:center; gap:8px; padding:3px 0; cursor:pointer; }
  .swatch { width:14px; height:14px; border-radius:3px; border:1px solid var(--line); flex:none; }
  .part.sel { font-weight:600; color:var(--accent); }
  #info { font-family: ui-monospace, monospace; font-size:12px; white-space:pre-wrap; color:var(--muted); }
  main { position:relative; } canvas { display:block; }
  #status { position:absolute; left:12px; bottom:10px; color:var(--muted); font-size:12px; }
  input[type=range] { width:100%; }
  @media (max-width: 700px) { body { grid-template-columns: 1fr; grid-template-rows: 45vh 1fr; } aside { order:2; } }
</style>
<script type="importmap">{"imports": {"three": "/vendor/three/build/three.module.min.js", "three/addons/": "/vendor/three/examples/jsm/"}}</script>
</head>
<body>
<aside>
  <h1>img2cad viewer</h1>
  <select id="file" aria-label="File"></select>
  <h2>View</h2>
  <div class="row">
    <button data-view="front">Front</button><button data-view="right">Right</button>
    <button data-view="top">Top</button><button data-view="iso">Iso</button>
  </div>
  <h2>Tools</h2>
  <div class="row">
    <button id="measure">Measure</button><button id="wire">Wireframe</button><button id="shot">Screenshot</button>
  </div>
  <h2>Section</h2>
  <div class="row"><select id="clipAxis"><option value="">off</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select></div>
  <input id="clipPos" type="range" min="0" max="1" step="0.001" value="0.5" aria-label="Section position">
  <h2>Parts</h2>
  <div id="parts"></div>
  <h2>Selection</h2>
  <div id="info">Click a part, or use Measure and click two points.</div>
</aside>
<main id="stage"><div id="status">loading…</div></main>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/addons/loaders/3MFLoader.js";

const stage = document.getElementById("stage"), statusEl = document.getElementById("status"), info = document.getElementById("info");
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(devicePixelRatio); renderer.localClippingEnabled = true; stage.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(getComputedStyle(document.body).getPropertyValue("--bg").trim() || "#eef2f6");
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e7);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
const key = new THREE.DirectionalLight(0xffffff, 1.4); scene.add(key);
let model = null, parts = [], meshes = [], size = 1, center = new THREE.Vector3(), selected = null, measuring = false, picks = [], markers = [];
const clipPlane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);

function resize() { const r = stage.getBoundingClientRect(); renderer.setSize(r.width, r.height); camera.aspect = r.width / r.height; camera.updateProjectionMatrix(); }
addEventListener("resize", resize);

// CAD is Z-up; three.js is Y-up. Rotate the model so +Z points up on screen.
function setView(name) {
  const d = { front: [0, -1, 0], right: [1, 0, 0], top: [0, 0, 1], iso: [1, -1, 0.8] }[name];
  const dir = new THREE.Vector3(d[0], d[2], -d[1]).normalize();
  camera.position.copy(center).addScaledVector(dir, size * 1.8);
  camera.up.set(0, 1, 0); if (name === "top") camera.up.set(0, 0, -1);
  controls.target.copy(center); controls.update();
}

async function load(file) {
  statusEl.textContent = `loading ${file.name}…`;
  if (model) scene.remove(model);
  const url = `/api/file?id=${encodeURIComponent(file.id)}`;
  let object;
  if (file.format === "stl") {
    const geometry = await new STLLoader().loadAsync(url);
    object = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0xca9c66 })); object.name = file.name;
  } else if (file.format === "3mf") {
    object = await new ThreeMFLoader().loadAsync(url);
  } else {
    const response = await fetch(url);
    if (!response.ok) { statusEl.textContent = await response.text(); return; }
    object = (await new GLTFLoader().parseAsync(await response.arrayBuffer(), "")).scene;
  }
  if (file.format !== "glb") object.rotation.x = -Math.PI / 2;  // STL/3MF are Z-up mm; glTF is Y-up
  else object.scale.setScalar(1000);                             // glTF is in metres; show millimetres
  model = object; scene.add(model);
  const box = new THREE.Box3().setFromObject(model); box.getCenter(center); size = box.getSize(new THREE.Vector3()).length() || 1;
  camera.near = size / 1000; camera.far = size * 100; camera.updateProjectionMatrix();
  key.position.copy(center).add(new THREE.Vector3(size, size * 1.5, size));
  meshes = []; model.traverse(o => { if (o.isMesh) {
    const m = o.material.clone(); m.side = THREE.DoubleSide; m.clippingPlanes = [];
    if ("metalness" in m) { m.metalness = 0; m.roughness = 0.6; }  // CAD exports are often fully metallic, which renders dark
    o.material = m; meshes.push(o);
  } });
  // One entry per part: STEP->glTF writes one mesh per face (body_1, body_2, ...).
  const groups = new Map();
  meshes.forEach(o => { const name = partName(o).replace(/_\d+$/, ""); if (!groups.has(name)) groups.set(name, []); groups.get(name).push(o); });
  parts = [...groups].map(([name, list]) => ({ name, meshes: list }));
  listParts(); applyClip(); setView("iso");
  statusEl.textContent = `${file.name} · ${parts.length} part${parts.length === 1 ? "" : "s"} · ${(box.getSize(new THREE.Vector3()).toArray().map(v => v.toFixed(1)).join(" × "))} mm`;
}

function partName(mesh) { let o = mesh; while (o && !o.name) o = o.parent; return (o && o.name) || "part"; }
function listParts() {
  const host = document.getElementById("parts"); host.innerHTML = "";
  parts.forEach((part, i) => {
    const row = document.createElement("label"); row.className = "part"; row.dataset.index = i;
    const box = document.createElement("input"); box.type = "checkbox"; box.checked = true; box.onchange = () => { part.meshes.forEach(m => m.visible = box.checked); };
    const sw = document.createElement("span"); sw.className = "swatch"; sw.style.background = "#" + part.meshes[0].material.color.getHexString(THREE.SRGBColorSpace);
    const name = document.createElement("span"); name.textContent = part.name;
    name.onclick = e => { e.preventDefault(); select(part); };
    row.append(box, sw, name); host.append(row);
  });
}
function select(part) {
  if (selected) selected.meshes.forEach(m => m.material.emissive && m.material.emissive.setHex(0x000000));
  selected = part;
  document.querySelectorAll(".part").forEach(r => r.classList.toggle("sel", parts[r.dataset.index] === part));
  if (!part) return;
  part.meshes.forEach(m => { if (m.material.emissive) { m.material.emissive.setHex(0x2f6fb0); m.material.emissiveIntensity = 0.35; } });
  const box = new THREE.Box3(); part.meshes.forEach(m => box.expandByObject(m));
  const s = box.getSize(new THREE.Vector3());
  info.textContent = `${part.name}\ncolour #${part.meshes[0].material.color.getHexString(THREE.SRGBColorSpace)}\nsize ${s.x.toFixed(2)} × ${s.z.toFixed(2)} × ${s.y.toFixed(2)} mm (X × Y × Z)`;
}
const partOf = mesh => parts.find(p => p.meshes.includes(mesh));

const ray = new THREE.Raycaster(), pointer = new THREE.Vector2();
renderer.domElement.addEventListener("pointerdown", e => { renderer.domElement._down = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener("pointerup", e => {
  const [x0, y0] = renderer.domElement._down || [0, 0]; if (Math.hypot(e.clientX - x0, e.clientY - y0) > 4) return;  // a drag, not a click
  const r = renderer.domElement.getBoundingClientRect();
  pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(pointer, camera);
  const hit = ray.intersectObjects(meshes.filter(m => m.visible), false)[0];
  if (!hit) { select(null); info.textContent = "Nothing under the cursor."; return; }
  if (!measuring) { select(partOf(hit.object)); return; }
  picks.push(hit.point.clone());
  const dot = new THREE.Mesh(new THREE.SphereGeometry(size / 250), new THREE.MeshBasicMaterial({ color: 0xd94a3a }));
  dot.position.copy(hit.point); scene.add(dot); markers.push(dot);
  if (picks.length === 2) {
    const [a, b] = picks, d = b.clone().sub(a);
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0xd94a3a })); scene.add(line); markers.push(line);
    info.textContent = `distance ${a.distanceTo(b).toFixed(2)} mm\nΔX ${Math.abs(d.x).toFixed(2)}  ΔY ${Math.abs(d.z).toFixed(2)}  ΔZ ${Math.abs(d.y).toFixed(2)} mm`;
    picks = [];
  } else { info.textContent = "Pick the second point."; }
});

document.querySelectorAll("[data-view]").forEach(b => b.onclick = () => setView(b.dataset.view));
document.getElementById("measure").onclick = e => {
  measuring = !measuring; e.target.classList.toggle("on", measuring); picks = [];
  markers.forEach(m => scene.remove(m)); markers = [];
  info.textContent = measuring ? "Measure: click two points on the model." : "Click a part, or use Measure and click two points.";
};
document.getElementById("wire").onclick = e => { const on = !e.target.classList.contains("on"); e.target.classList.toggle("on", on); meshes.forEach(m => m.material.wireframe = on); };
document.getElementById("shot").onclick = () => { const a = document.createElement("a"); a.href = renderer.domElement.toDataURL("image/png"); a.download = "img2cad-view.png"; a.click(); };
function applyClip() {
  // Keep the part of the model where the CAD coordinate is >= the slider value
  // (the iso/front cameras look from -Y, so a Y section exposes the cut face).
  const axis = document.getElementById("clipAxis").value, t = +document.getElementById("clipPos").value;
  meshes.forEach(m => { m.material.clippingPlanes = axis ? [clipPlane] : []; m.material.needsUpdate = true; });
  if (!axis || !model) return;
  const box = new THREE.Box3().setFromObject(model);
  // three.js is Y-up: CAD x = x, CAD y = -z, CAD z = y.
  const range = { x: [box.min.x, box.max.x], y: [-box.max.z, -box.min.z], z: [box.min.y, box.max.y] }[axis];
  const value = range[0] + (range[1] - range[0]) * t;
  clipPlane.normal.set(...{ x: [1, 0, 0], y: [0, 0, -1], z: [0, 1, 0] }[axis]);
  clipPlane.constant = -value;
}
document.getElementById("clipAxis").onchange = applyClip; document.getElementById("clipPos").oninput = applyClip;

const files = await (await fetch("/api/files")).json();
const picker = document.getElementById("file");
files.forEach(f => picker.append(new Option(f.name, f.id)));
const wanted = new URLSearchParams(location.search).get("file");
if (wanted) picker.value = wanted;
picker.onchange = () => { history.replaceState(null, "", `?file=${picker.value}`); load(files.find(f => f.id === picker.value)); };
resize();
if (files.length) load(files.find(f => f.id === picker.value) || files[0]); else statusEl.textContent = "No files.";
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
// For automated checks (tests and the MCP server's screenshots).
window.img2cadViewer = { get meshes() { return meshes; }, get parts() { return parts; }, clipPlane, setView };
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())

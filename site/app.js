import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

// ---------- language toggle (English <-> 繁體中文) ----------
const LANG_KEY = "img2cad-lang";
function applyLanguage(lang) {
  document.documentElement.lang = lang === "zh" ? "zh-Hant" : "en";
  document.querySelectorAll("[data-zh]").forEach((el) => {
    if (!el.dataset.en) el.dataset.en = el.innerHTML;
    el.innerHTML = lang === "zh" ? el.dataset.zh : el.dataset.en;
  });
  document.getElementById("lang").textContent = lang === "zh" ? "English" : "中文";
  try { localStorage.setItem(LANG_KEY, lang); } catch { /* storage unavailable */ }
}
let lang = "en";
try { lang = localStorage.getItem(LANG_KEY) || (navigator.language.startsWith("zh") ? "zh" : "en"); } catch { /* default */ }
document.getElementById("lang").addEventListener("click", () => {
  lang = lang === "zh" ? "en" : "zh";
  applyLanguage(lang);
  renderGallery();
});

// ---------- install tabs ----------
document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b === button)));
    document.querySelectorAll(".tab-panels [data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== button.dataset.tab; });
  });
});

// ---------- 3D viewers (lazy, one renderer per visible card) ----------
const loader = new GLTFLoader();
const viewers = new Map();

function mountViewer(el) {
  if (viewers.has(el)) return;
  const status = document.createElement("div");
  status.className = "loading";
  status.textContent = "loading 3D…";
  el.appendChild(status);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8178, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(1, 1.4, 1.2);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.6);
  fill.position.set(-1.2, 0.4, -0.8);
  scene.add(fill);
  const camera = new THREE.PerspectiveCamera(32, 4 / 3, 0.1, 100000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = el.dataset.autorotate === "1";
  controls.autoRotateSpeed = 1.2;
  controls.addEventListener("start", () => { controls.autoRotate = false; });

  const state = { renderer, scene, camera, controls, visible: true };
  viewers.set(el, state);

  const resize = () => {
    const { clientWidth: w, clientHeight: h } = el;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(el);
  resize();

  loader.load(el.dataset.glb, (gltf) => {
    const model = gltf.scene;
    model.scale.setScalar(1000); // glTF is in metres; CAD is in mm
    model.traverse((node) => {
      if (node.isMesh) {
        const material = node.material;
        material.metalness = 0;
        material.roughness = 0.55;
        material.side = THREE.DoubleSide;
      }
    });
    scene.add(model);
    const box = new THREE.Box3().setFromObject(model);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length();
    model.position.sub(center);
    // Isometric-ish start: CAD front (-Y) faces the viewer; glTF is Y-up, so CAD -Y is +Z here.
    camera.position.set(size * 0.62, size * 0.42, size * 1.12);
    camera.near = size / 100;
    camera.far = size * 20;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.update();
    status.remove();
  }, undefined, () => { status.textContent = "could not load the model"; });
}

const observer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) mountViewer(entry.target);
    const state = viewers.get(entry.target);
    if (state) state.visible = entry.isIntersecting;
  }
}, { rootMargin: "200px" });

function observeViewers(root = document) {
  root.querySelectorAll(".viewer[data-glb]").forEach((el) => observer.observe(el));
}

function animate() {
  for (const [el, state] of viewers) {
    if (!state.visible || !el.isConnected) continue;
    state.controls.update();
    state.renderer.render(state.scene, state.camera);
  }
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

// ---------- gallery ----------
let data = null;
const T = {
  en: { "3d": "3D", reference: "Input", comparison: "Views", registered: "Overlay", silhouette: "Silhouette", drawing: "Drawing",
        visual_approximation: "visual approximation", dimension_constrained: "dimension-constrained",
        size: "size", parts: "parts", silhouetteIou: "silhouette IoU", registeredIou: "registered IoU",
        revisions: "revisions", source: "Source, plan and review →", check: "check", expected: "expected", measured: "measured" },
  zh: { "3d": "3D", reference: "輸入", comparison: "多視角", registered: "疊圖", silhouette: "輪廓", drawing: "工程圖",
        visual_approximation: "外觀近似", dimension_constrained: "尺寸約束",
        size: "尺寸", parts: "零件", silhouetteIou: "輪廓 IoU", registeredIou: "對位 IoU",
        revisions: "版本", source: "原始碼、規劃與審查 →", check: "檢查", expected: "預期", measured: "量測" },
};
const t = (key) => (T[lang] || T.en)[key] || key;
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function card(example) {
  const views = ["3d", "reference", "comparison", "registered", "silhouette", "drawing"].filter((v) => v === "3d" || example.files[v]);
  const metrics = [
    `<span>${t("size")} <b>${example.size_mm.join(" × ")} mm</b></span>`,
    example.parts > 1 ? `<span>${t("parts")} <b>${example.parts}</b></span>` : "",
    example.registered_iou != null ? `<span>${t("registeredIou")} <b>${example.registered_iou.toFixed(2)}</b></span>` : "",
    example.registered_iou == null && example.silhouette_iou != null ? `<span>${t("silhouetteIou")} <b>${example.silhouette_iou.toFixed(2)}</b></span>` : "",
  ].join("");
  const checks = example.dimension_checks.length ? `<table class="checks"><tbody>${example.dimension_checks.map((c) => `
      <tr><td>${escapeHtml(c.name)}${c.diameter ? ` Ø${c.diameter}` : ""}</td><td>${t("expected")} ${c.expected}</td><td>${t("measured")} ${c.measured}</td>
      <td class="${c.passed ? "ok" : "no"}">${c.passed ? "✓" : "✗"}</td></tr>`).join("")}</tbody></table>` : "";
  const revisions = example.revisions.length > 1
    ? `<div class="revisions">${t("revisions")}: ${example.revisions.map((r) => `${r.id} <i>${escapeHtml(r.review || "")}</i>${r.reason ? ` (${escapeHtml(r.reason)})` : ""}`).join(" → ")}</div>` : "";
  return `
    <article class="example" data-name="${escapeHtml(example.name)}">
      <div class="views" role="group" aria-label="View">
        ${views.map((v, i) => `<button type="button" data-view="${v}" aria-pressed="${i === 0}">${t(v)}</button>`).join("")}
      </div>
      <div class="media"><div class="viewer" data-glb="${escapeHtml(example.files.glb)}" aria-label="3D model of ${escapeHtml(example.title)}"></div></div>
      <div class="body">
        <h3>${escapeHtml(example.title)}</h3>
        <div><span class="tag ${example.target_type === "dimension_constrained" ? "dim" : ""}">${t(example.target_type)}</span></div>
        <div class="metrics">${metrics}</div>
        <ul class="techniques">${example.techniques.slice(0, 4).map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
        ${checks}
        ${revisions}
        <a class="more" href="${escapeHtml(example.source)}">${t("source")}</a>
      </div>
    </article>`;
}

function renderGallery() {
  if (!data) return;
  const gallery = document.getElementById("gallery");
  for (const [el, state] of viewers) {
    if (gallery.contains(el)) { state.renderer.dispose(); viewers.delete(el); }
  }
  gallery.innerHTML = data.examples.map(card).join("");
  gallery.querySelectorAll(".example").forEach((article) => {
    const example = data.examples.find((e) => e.name === article.dataset.name);
    const media = article.querySelector(".media");
    const viewer = media.querySelector(".viewer");
    article.querySelectorAll(".views button").forEach((button) => {
      button.addEventListener("click", () => {
        article.querySelectorAll(".views button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
        media.querySelector("img")?.remove();
        const view = button.dataset.view;
        viewer.hidden = view !== "3d";
        if (view !== "3d") {
          const img = document.createElement("img");
          img.src = example.files[view];
          img.alt = `${example.title}: ${t(view)}`;
          img.loading = "lazy";
          media.appendChild(img);
        }
      });
    });
  });
  observeViewers(gallery);
}

function renderFishScores() {
  const fish = data?.examples.find((e) => e.name === "fish");
  const caption = document.getElementById("fish-iou");
  if (!fish || !caption) return;
  const swatches = Object.entries(fish.color_iou)
    .map(([color, iou]) => `<span class="swatch"><i style="background:${escapeHtml(color)}"></i>${iou.toFixed(2)}</span>`).join("");
  caption.innerHTML = `${lang === "zh" ? "魚的對位疊圖：各顏色區域與原圖的 IoU" : "The fish drawn in the image's pixel frame; IoU of each colour region against the image"}<div class="swatches">${swatches}</div>`;
}

fetch("examples.json")
  .then((response) => response.json())
  .then((json) => {
    data = json;
    document.getElementById("version").textContent = `v${json.version}`;
    renderGallery();
    renderFishScores();
  })
  .catch(() => { document.getElementById("gallery").textContent = "examples.json not found — build the site with scripts/build_site.py"; });

applyLanguage(lang);
observeViewers();
document.getElementById("lang").addEventListener("click", renderFishScores);

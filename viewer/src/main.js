// LipScan Viewer: plays game lipsync clips and LipScan curves on a real head, through the rebuilt face solver.
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { FaceSolver } from "./solver.js";
import { loadAnimation } from "./anims.js";
import { MOODS } from "./moods.js";

const $ = (id) => document.getElementById(id);
const FPS = 30;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---------------- 3D scene ----------------
const view = $("view");
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
view.prepend(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(28, 1, 0.01, 50);
camera.position.set(-0.18, 1.7, -0.75);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1.65, 0);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8478, 1.6));
const key = new THREE.DirectionalLight(0xffffff, 2.2);
key.position.set(-0.6, 2.2, -1.4);
scene.add(key);
const rim = new THREE.DirectionalLight(0xffffff, 0.8);
rim.position.set(1, 1.9, 0.8);
scene.add(rim);

function resize() {
  const r = view.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / Math.max(1, r.height);
  camera.updateProjectionMatrix();
  drawTimeline();
}
new ResizeObserver(resize).observe(view);

// Moves a material's vertices `metres` toward the camera after skinning (depth only; on screen they barely move).
function liftTowardCamera(material, metres) {
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader.replace("#include <project_vertex>",
      `#include <project_vertex>
  mvPosition.xyz -= normalize(mvPosition.xyz) * ${metres.toFixed(4)};
  gl_Position = projectionMatrix * mvPosition;`);
  };
  return material;
}

const MATERIALS = {
  head: () => new THREE.MeshStandardMaterial({ color: 0xc9b8aa, roughness: 0.62 }),
  // eyebrow cards sit a hair above the skin; when the brows move the skin slides over them (the game's own clips too),
  // so draw them a few millimetres toward the camera (like a decal) instead of relying on a depth bias alone
  eyebrows: () => liftTowardCamera(new THREE.MeshStandardMaterial({ color: 0x3a2f28, roughness: 0.9, transparent: true, opacity: 0.85 }), 0.003),
  eyes: () => new THREE.MeshStandardMaterial({ color: 0xe9e6e0, roughness: 0.25 }),
  teeth: () => new THREE.MeshStandardMaterial({ color: 0xeee6d2, roughness: 0.4 }),
  other: () => new THREE.MeshStandardMaterial({ color: 0x8c8580, roughness: 0.7 }),
  hair: () => hairMaterial(),
};

// Hair is a set of cards (the game's own hair meshes) cut out by a strand alpha texture, in the hair profile's average colour. A spring
// simulation of the head's motion (stepHair) gives a displacement that this shader adds to the vertices, more for the outer, longer cards.
function hairMaterial() {
  const color = (state.pack && state.pack.hair && state.pack.hair.color) || "#2b2420";
  const m = new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: 0.78, side: THREE.DoubleSide });
  m.userData.hairOffset = { value: new THREE.Vector3() };
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uHairOff = m.userData.hairOffset;
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nattribute float hairW;\nuniform vec3 uHairOff;")
      .replace("#include <skinning_vertex>", "#include <skinning_vertex>\ntransformed += uHairOff * hairW;");
  };
  m.customProgramCacheKey = () => "hair-sway";
  return m;
}

// One plain color per vertex, chosen by the bone that moves it most (the teeth mesh holds teeth, gums and tongue).
function colorByBone(mesh, pick) {
  const g = mesh.geometry;
  const idx = g.attributes.skinIndex;
  const wt = g.attributes.skinWeight;
  const colors = new Float32Array(idx.count * 3);
  const c = new THREE.Color();
  for (let v = 0; v < idx.count; v++) {
    let best = 0;
    for (let k = 1; k < 4; k++) if (wt.getComponent(v, k) > wt.getComponent(v, best)) best = k;
    const bone = mesh.skeleton.bones[idx.getComponent(v, best)];
    c.setHex(pick(bone ? bone.name : ""));
    colors.set([c.r, c.g, c.b], v * 3);
  }
  g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  mesh.material.vertexColors = true;
  mesh.material.color.setHex(0xffffff);
}

// ---------------- the game's textures (build_textures.py adds them to a pack; optional) ----------------
// pack.textures: [{role, slot, file}]: role head or eyes, slot map (albedo), normalMap or roughnessMap. Only used when the pack has them.
const TEX_SLOTS = ["map", "normalMap", "roughnessMap", "alphaMap"];
async function loadTextures(pack, byName) {
  const out = {};
  const loader = new THREE.TextureLoader();
  for (const t of pack.textures || []) {
    const f = byName.get(t.file.split("/").pop().toLowerCase());
    if (!f || !TEX_SLOTS.includes(t.slot)) continue;
    const url = URL.createObjectURL(f);
    try {
      const tex = await loader.loadAsync(url);
      tex.flipY = false;                                   // glTF's UV origin is the top left, as in the exported meshes
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;        // the eyes' UVs run past 0..1
      tex.anisotropy = 8;
      if (t.slot === "map") tex.colorSpace = THREE.SRGBColorSpace;
      (out[t.role] = out[t.role] || {})[t.slot] = tex;
    } catch (e) { console.warn("texture", t.file, e); }
    URL.revokeObjectURL(url);
  }
  return out;
}
// Which meshes of a role take the texture: the head; the eyeball and its lash line, not the thin see-through overlay.
function takesTexture(role, mesh) {
  return role === "head" || role === "eyebrows" || role === "teeth" || role === "hair" || (role === "eyes" && !/doubled/i.test(mesh.name) && mesh.geometry.attributes.position.count >= 300);   // the eyeball, not the lash line
}
// The game's eye texture is a flat picture of one eye (pupil, iris, veined white) on a skin-coloured surround, and its material
// rescales the mesh's UVs. Each eyeball is mapped to it from the front instead: the picture's centre on the eye's centre, 0.27 of
// the picture across half the eyeball (so the iris is about half the eyeball's radius, as in a real eye).
const EYE_UV = { cx: 0.54, cy: 0.51, scale: 0.27 };
function mapEyeUV(mesh) {
  const g = mesh.geometry;
  if (g.userData.eyeUV || !g.attributes.position || g.attributes.position.count < 300) return;     // the lash line and the overlay keep theirs
  g.userData.eyeUV = true;
  const pos = g.attributes.position, n = pos.count, v = new THREE.Vector3();
  const xs = Array.from({ length: n }, (_, i) => pos.getX(i)).sort((a, b) => a - b);
  const mid = xs[n >> 1];
  const box = [new THREE.Box3(), new THREE.Box3()];
  for (let i = 0; i < n; i++) box[pos.getX(i) < mid ? 0 : 1].expandByPoint(v.fromBufferAttribute(pos, i));
  const uv = new Float32Array(n * 2), c = new THREE.Vector3();
  for (let i = 0; i < n; i++) {
    const b = box[pos.getX(i) < mid ? 0 : 1];
    b.getCenter(c);
    const R = Math.max(1e-4, (b.max.z - b.min.z) / 2);
    uv[i * 2] = EYE_UV.cx - ((pos.getX(i) - c.x) / R) * EYE_UV.scale;          // the viewer's right is -x
    uv[i * 2 + 1] = EYE_UV.cy - ((pos.getY(i) - c.y) / R) * EYE_UV.scale;
  }
  g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
}
function applyTextures(mesh, role) {
  const tex = state.textures && state.textures[role];
  if (tex && role === "eyes" && !/doubled/i.test(mesh.name) && mesh.geometry.attributes.position.count < 300) {
    // the small submesh over the pupil is the game's eye-wetness SHADOW layer (a red-brown shadow colour in a mask), not a surface:
    // drawn opaque it was a white disc, with the texture an orange one. The eyeball's own texture has the pupil.
    mesh.material.visible = !$("showTex").checked;
    return;
  }
  if (!tex || !takesTexture(role, mesh)) return;
  if (role === "hair") {                                   // cards are only hair through their strand alpha: without it they would be slabs
    const ok = $("showTex").checked && !!tex.alphaMap;
    const hm = mesh.material;
    hm.alphaMap = ok ? tex.alphaMap : null;
    hm.alphaTest = ok ? 0.4 : 0;
    hm.visible = ok && $("showHair").checked;
    hm.needsUpdate = true;
    return;
  }
  if (role === "eyes") mapEyeUV(mesh);
  const on = $("showTex").checked;
  const m = mesh.material;
  m.userData.tex = tex;
  m.map = on && tex.map ? tex.map : null;
  m.normalMap = on && tex.normalMap && NORMAL_MAPS ? tex.normalMap : null;
  const textured = on && !!tex.map;
  if (role === "teeth") {                              // the teeth mesh also holds gums and tongue: the texture colours them, so the per-bone colours step aside
    m.vertexColors = !textured;
    m.color.setHex(0xffffff);
  } else if (role === "eyebrows") {
    m.color.setHex(textured ? 0x4a3d33 : 0x3a2f28);                                    // the strand texture is grey: tinted brown
    if (!m.userData.strands) {                                                         // the strands are thin: make their alpha count for more
      m.userData.strands = true;
      const lift = m.onBeforeCompile;
      m.onBeforeCompile = (sh) => {
        if (lift) lift(sh);
        sh.fragmentShader = sh.fragmentShader.replace("#include <map_fragment>",
          "#include <map_fragment>\n#ifdef USE_MAP\n diffuseColor.a = clamp(sampledDiffuseColor.a * 3.5, 0.0, 1.0) * opacity;\n#endif");
      };
      m.customProgramCacheKey = () => "brows-strands";
    }
    m.opacity = textured ? 1.0 : 0.85;
  }
  else m.color.setHex(textured ? 0xffffff : (role === "eyes" ? 0xe9e6e0 : 0xc9b8aa));
  m.needsUpdate = true;
}
const NORMAL_MAPS = false;                                 // the game's normal maps need their channels checked before they are shown

// ---------------- state ----------------
const state = {
  pack: null, solver: null, meshFiles: [], heads: { A: null, B: null },
  anim: { A: null, B: null }, clip: { A: null, B: null },
  t: 0, playing: false, speed: 1, loop: true, audio: null, offset: 0, curves: { A: null, B: null },
  video: null, // {start, frames: [{t, src}]} from a LipScan trace folder
  textures: null,
};
const values = { A: null, B: null };

// ---------------- character ----------------
// Some hair meshes (Johnny's: 78% of the weight) are skinned to the game's own simulated hair bones (dyng_hair_*). The game drives them
// by its physics, so the exported file hangs their chains off the armature root, not the Head bone, and nothing here moves them: the hair
// stayed where it was while the head moved. Each such chain is parented to the mesh's own Head bone, keeping its rest position, so it rides with the head.
function followHead(mesh) {
  const sk = mesh.skeleton, head = sk.bones.find((b) => b.name === "Head");
  if (!head) return 0;
  let n = 0;
  mesh.parent.updateMatrixWorld(true);
  for (const b of sk.bones) {
    if (state.solver.boneIndex.has(b.name) || sk.bones.includes(b.parent)) continue;      // driven, or inside a chain whose root is handled
    head.attach(b);
    n++;
  }
  return n;
}

async function buildHead(slot) {
  const holder = new THREE.Group();
  holder.name = `head ${slot}`;
  const loader = new GLTFLoader();
  const bones = [];
  for (const m of state.meshFiles) {
    const gltf = await loader.parseAsync(await m.blob.arrayBuffer(), "");
    const role = m.role in MATERIALS ? m.role : "other";
    gltf.scene.traverse((o) => {
      if (o.isMesh) {
        o.material = MATERIALS[role]();
        o.frustumCulled = false;
        o.userData.role = m.role;
        if (role === "hair" && o.isSkinnedMesh) o.userData.loose = followHead(o);
        if (role === "teeth" && o.isSkinnedMesh) colorByBone(o, (name) => (/tongue/i.test(name) ? 0xb4625e : 0xece4d0));
        if (role === "eyes" && /doubled/i.test(o.name)) { o.material.transparent = true; o.material.opacity = 0.12; o.material.depthWrite = false; }
        applyTextures(o, role);
      }
    });
    holder.add(gltf.scene);
  }
  holder.updateMatrixWorld(true);
  const seen = new Set();
  holder.traverse((o) => {
    if (!o.isSkinnedMesh) return;
    for (const b of o.skeleton.bones) {
      if (seen.has(b)) continue;
      seen.add(b);
      const idx = state.solver.boneIndex.get(b.name);
      if (idx === undefined) continue;
      const holderInv = holder.matrixWorld.clone().invert();
      // Like the game, shared meshes (eyes, teeth) sit on THIS character's skeleton: keep the exported bone's
      // orientation but put it at the rig's rest position (RED -> glTF axes: x, z, -y).
      const restWorld = holderInv.clone().multiply(b.matrixWorld);           // relative to the holder
      const p = new THREE.Vector3().setFromMatrixPosition(state.solver.bindWorld[idx]); // meshes are bound to the rig as built
      restWorld.setPosition(p.x, p.z, -p.y);
      const parentInv = holderInv.clone().multiply(b.parent.matrixWorld).invert();
      b.matrixAutoUpdate = false;
      bones.push({ bone: b, idx, restWorld, parentInv });
    }
  });
  holder.userData.bones = bones;
  return holder;
}

// ---------------- hair physics ----------------
// One point that trails the head on a spring (the lower part of the hair, in the head's own frame, so it lags turns and nods as well as
// moves). Its lag behind the point it follows is the sway, applied to each vertex by its weight: how far it sits from the head's centre
// (roots near the skull barely move, outer cards and tips most), scaled by how long the hair is (the spread of those distances).
const HAIR = { stiffness: 110, damping: 0.4, limit: 0.06, gain: 1.6 };
function setupHair(holder) {
  const meshes = [];
  holder.traverse((o) => { if (o.isMesh && o.userData.role === "hair" && o.geometry.attributes.position) meshes.push(o); });
  const headB = holder.userData.bones.find((b) => b.bone.name === "Head");
  holder.userData.hair = null;
  if (!meshes.length || !headB) return;
  const H0 = new THREE.Vector3().setFromMatrixPosition(headB.restWorld), v = new THREE.Vector3();
  const rs = [], low = [];
  for (const m of meshes) {
    const p = m.geometry.attributes.position;
    for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i); rs.push(v.distanceTo(H0)); low.push(v.y); }
  }
  const sorted = [...rs].sort((a, b) => a - b), at = (f) => sorted[Math.min(sorted.length - 1, Math.floor(f * sorted.length))];
  const r0 = at(0.05), span = Math.max(1e-3, at(0.97) - r0);
  const length = THREE.MathUtils.clamp(span / 0.10, 0.25, 1.2);
  const ys = [...low].sort((a, b) => a - b), yLow = ys[Math.floor(ys.length * 0.15)];
  const anchor = new THREE.Vector3();
  let n = 0;
  for (const m of meshes) {
    const p = m.geometry.attributes.position, w = new Float32Array(p.count);
    for (let i = 0; i < p.count; i++) {
      v.fromBufferAttribute(p, i);
      const u = THREE.MathUtils.clamp((v.distanceTo(H0) - r0) / span, 0, 1);
      w[i] = length * Math.pow(u * u * (3 - 2 * u), 1.5);
      if (v.y <= yLow) { anchor.add(v); n++; }
    }
    m.geometry.setAttribute("hairW", new THREE.BufferAttribute(w, 1));
  }
  anchor.multiplyScalar(1 / Math.max(1, n));
  const local = anchor.applyMatrix4(headB.restWorld.clone().invert());
  holder.userData.hair = { meshes, bone: headB.bone, local, p: null, v: new THREE.Vector3(), length };
}
let frameDt = 0.016;
function stepHair(holder, dt) {
  const hs = holder.userData.hair;
  if (!hs) return;
  const A = hs.local.clone().applyMatrix4(hs.bone.matrixWorld);
  const live = $("hairPhys").checked && dt < 0.25;
  if (!hs.p || !live || hs.p.distanceTo(A) > 0.25) { hs.p = A.clone(); hs.v.set(0, 0, 0); }
  else {
    const k = HAIR.stiffness, c = 2 * HAIR.damping * Math.sqrt(k), step = Math.min(dt, 0.1);
    const sub = Math.max(1, Math.ceil(step / 0.008)), h = step / sub;
    for (let i = 0; i < sub; i++) {
      hs.v.addScaledVector(A.clone().sub(hs.p), k * h).addScaledVector(hs.v, -c * h);
      hs.p.addScaledVector(hs.v, h);
    }
  }
  const d = hs.p.clone().sub(A).multiplyScalar(HAIR.gain);
  if (d.length() > HAIR.limit) d.setLength(HAIR.limit);
  const o = new THREE.Vector3();
  for (const m of hs.meshes) {                             // the displacement is in world space; the shader works in the mesh's own
    const inv = m.matrixWorld.clone().invert();
    o.copy(d).applyMatrix4(inv).sub(new THREE.Vector3().applyMatrix4(inv));
    m.material.userData.hairOffset.value.copy(o);
  }
}

function poseHead(head, deform) {
  const m = new THREE.Matrix4();
  for (const x of head.userData.bones) {
    m.multiplyMatrices(deform[x.idx], x.restWorld);
    x.bone.matrix.multiplyMatrices(x.parentInv, m);
  }
  head.updateMatrixWorld(true);
}

async function loadCharacter(files) {
  const byName = new Map(files.map((f) => [f.name.toLowerCase(), f]));
  const cj = byName.get("character.json");
  if (!cj) throw new Error("The character folder needs character.json (made by build_character.py).");
  const pack = JSON.parse(await cj.text());
  if (pack.format !== "lipscan-character/1") throw new Error("character.json isn't a LipScan character pack.");
  state.pack = pack;
  state.textures = await loadTextures(pack, byName);
  $("texRow").hidden = !Object.keys(state.textures).length;
  state.solver = new FaceSolver(pack);
  state.meshFiles = pack.meshes.filter((m) => byName.has(m.file.toLowerCase())).map((m) => ({ ...m, blob: byName.get(m.file.toLowerCase()) }));
  for (const s of ["A", "B"]) {
    if (state.heads[s]) scene.remove(state.heads[s]);
    state.heads[s] = await buildHead(s);
    setupHair(state.heads[s]);
    scene.add(state.heads[s]);
    values[s] = new Float32Array(pack.tracks.length);
  }
  const box = new THREE.Box3().setFromObject(state.heads.A.children[0]);
  const c = box.getCenter(new THREE.Vector3());
  controls.target.copy(c);
  camera.position.set(c.x - 0.2, c.y + 0.02, c.z - 0.85); // the head faces -Z
  const p = pack.parts.face;
  $("info").textContent = `${pack.name}\n${state.meshFiles.length} meshes, ${pack.bones.names.length} bones\n` +
    `face: ${p.main.length} poses, ${p.correctives.length} correctives\ntongue: ${pack.parts.tongue.main.length} poses, eyes: ${pack.parts.eyes.main.length}`;
  const sel = $("poseTrack");
  sel.innerHTML = "";
  sel.add(new Option("(pick a face track)", -1));
  const posed = new Set(Object.values(pack.parts).flatMap((p) => p.main.map((m) => m.track)));
  pack.tracks.forEach((n, i) => { if (posed.has(i)) sel.add(new Option(n, i)); });
  applyVisibility();
  layout();
  setupCreator(pack.creator);
  for (const s of ["A", "B"]) if (state.anim[s]) computeCurve(s);
  $("drop").style.display = "none";
  $("drop").querySelector("div").innerHTML = "<b>Drop an animation</b><br>a WolvenKit <code>.anims</code> glTF export or a LipScan <code>.json</code>, or the voice audio.";
}

function layout() {
  const mode = $("viewMode").value;
  const { A, B } = state.heads;
  if (!A) return;
  A.visible = mode !== "B";
  B.visible = mode !== "A";
  A.position.x = mode === "AB" ? 0.13 : 0; // seen from the front, +x is on the left
  B.position.x = mode === "AB" ? -0.13 : 0;
  const lab = $("labels");
  lab.innerHTML = "";
  const tag = (s, color) => {
    const d = document.createElement("div");
    d.innerHTML = `<span class="dot" style="background:${color}"></span>${s}: ${state.clip[s] ? state.clip[s].name : "no animation"}`;
    lab.append(d);
  };
  if (mode !== "B") tag("A", "var(--accent)");
  if (mode !== "A") tag("B", "var(--accent-2)");
}

function applyVisibility() {
  const show = { eyebrows: $("showBrows").checked, eyes: $("showEyes").checked, teeth: $("showTeeth").checked, hair: $("showHair").checked };
  for (const h of Object.values(state.heads)) {
    if (!h) continue;
    h.traverse((o) => {
      if (!o.isMesh) return;
      o.visible = show[o.userData.role] ?? true;
      o.material.wireframe = $("wire").checked;
    });
  }
}

// ---------------- animations ----------------
async function loadAnim(slot, file) {
  if (!state.solver) throw new Error("Load a character first.");
  const a = await loadAnimation(file, state.solver);
  state.anim[slot] = a;
  $(`name${slot}`).textContent = `${slot}: ${file.name}`;
  const sel = $(slot === "A" ? "clipA" : "clipB");
  sel.innerHTML = "";
  a.clips.forEach((c, i) => sel.add(new Option(`${c.name}  (${c.duration.toFixed(2)} s)`, i)));
  selectClip(slot, 0);
  if (a.unknown && a.unknown.length) console.warn("tracks not on this rig:", a.unknown);
  $("drop").style.display = "none";
}

function selectClip(slot, i) {
  state.clip[slot] = state.anim[slot] ? state.anim[slot].clips[i] : null;
  computeCurve(slot);
  layout();
  seek(0);
}

function sampleValues(slot, t, out) {
  const clip = state.clip[slot];
  if (!clip) out.fill(0);
  else {
    clip.sample(Math.min(t, clip.duration), out);
    if (clip.additive) {
      const ref = state.solver.reference;
      for (let i = 0; i < ref.length && i < out.length; i++) out[i] += ref[i];
    }
  }
  applyMood(slot, out);
  if (state.tryTrack >= 0 && state.tryValue > 0) out[state.tryTrack] = Math.max(out[state.tryTrack], state.tryValue); // pose tester
}

// ---------------- character creator (player heads) ----------------
// One menu per face region (eyes, nose, mouth, jaw, ears): the base face or one of the game's 20 presets. A choice
// turns on that preset's morph target for the region (h<PP><R>) on every mesh that has it, and moves the face
// joints that belong to the region to the preset's places, so poses and lipsync work on the new face.
const creatorChoice = {};
const REGION_LABEL = { eyes: "Eyes", nose: "Nose", mouth: "Mouth", jaw: "Jaw", ear: "Ears" };
function setupCreator(c) {
  const box = $("creatorBox");
  const holder = $("creator");
  holder.innerHTML = "";
  for (const k of Object.keys(creatorChoice)) delete creatorChoice[k];
  box.hidden = !c;
  if (!c) return;
  c.regions.forEach((r) => {
    const label = document.createElement("label");
    label.textContent = REGION_LABEL[r] || r;
    const sel = document.createElement("select");
    sel.id = `cc_${r}`;
    sel.add(new Option("base", ""));
    for (const p of c.presets) sel.add(new Option(`${+p}`, p));
    sel.addEventListener("change", () => { creatorChoice[r] = sel.value; applyCreator(); });
    label.htmlFor = sel.id;
    holder.append(label, sel);
  });
  $("creatorInfo").textContent = `${c.presets.length} presets per region, from the game's character creator. Joints follow their region's preset (an approximation).`;
}
function applyCreator() {
  const c = state.pack && state.pack.creator;
  if (!c) return;
  const want = new Set();
  c.regions.forEach((r, i) => { if (creatorChoice[r]) want.add(`h${creatorChoice[r]}${i + 1}`); });
  for (const h of Object.values(state.heads)) {
    if (!h) continue;
    h.traverse((o) => {
      if (!o.isMesh || !o.morphTargetDictionary) return;
      for (const [name, i] of Object.entries(o.morphTargetDictionary)) o.morphTargetInfluences[i] = want.has(name.slice(0, 4)) ? 1 : 0;
    });
  }
  const offsets = new Map();
  for (const [bone, region] of Object.entries(c.boneRegion)) {
    const p = creatorChoice[region];
    const d = p && c.boneDeltas[p] && c.boneDeltas[p][bone];
    const i = state.solver.boneIndex.get(bone);
    if (d && i !== undefined) offsets.set(i, d);
  }
  state.solver.setRestOffsets(offsets);
  render();
}
function setCreator(choice) {
  const c = state.pack && state.pack.creator;
  if (!c) return;
  for (const r of c.regions) {
    const v = choice[r] ? String(choice[r]).padStart(2, "0") : "";
    creatorChoice[r] = c.presets.includes(v) ? v : "";
    $(`cc_${r}`).value = creatorChoice[r];
  }
  applyCreator();
}

// ---------------- mood ----------------
// A held expression added on top of LipScan clips (the voice-driven accents ride on it). Game clips already hold
// their own mood, so they're left alone. Like the game, raised brows give way while the eyes blink.
const moods = { ...MOODS };
const OPPOSITES = ["l", "r"].flatMap((s) => [
  [`eye_${s}_brows_lower`, [`eye_${s}_brows_raise_in`, `eye_${s}_brows_raise_out`]],
  [`eye_${s}_brows_raise_in`, [`eye_${s}_brows_lower`, `eye_${s}_brows_lateral`]],
  [`lips_${s}_corner_dn`, [`lips_${s}_corner_up`]],
  [`lips_${s}_corner_up`, [`lips_${s}_corner_dn`]],
]);
let moodPreset = null;
function setMood(name) {
  moodPreset = name && moods[name] && Object.keys(moods[name].tracks).length ? moods[name] : null;
  const sel = $("mood");
  if (sel.value !== name) sel.value = name;
  $("moodInfo").textContent = moods[name] ? `${moods[name].about} (${moods[name].source})` : "";
  for (const s of ["A", "B"]) computeCurve(s);
  render();
}
function fillMoods() {
  const sel = $("mood");
  sel.innerHTML = "";
  for (const name of Object.keys(moods)) sel.add(new Option(name, name));
  sel.add(new Option("Custom preset…", "__custom"));
  sel.value = moodPreset ? moodPreset.name : "neutral";
}
function applyMood(slot, out) {
  const clip = state.clip[slot];
  if (!moodPreset || !clip || clip.kind !== "lipscan" || !$(`mood${slot}`).checked || !state.solver) return;
  const idx = state.solver.trackIndex;
  // a track's value may sit under its own name or its dialogue-layer name (cyberpunk exports)
  const both = (name) => [idx.get(name), idx.get(`${name}LipsyncPoseOutput`)].filter((i) => i !== undefined);
  const value = (name) => both(name).reduce((a, i) => a + out[i], 0);
  // the game never raises the brows inside a held scowl (or smiles inside held down-turned corners): an accent on the
  // opposite shape becomes emphasis on the held one (same rule as the model's apply_mood)
  const held = moodPreset.tracks;
  for (const [keep, against] of OPPOSITES) {
    const h = held[keep] || 0;
    if (h <= 0) continue;
    const scale = Math.max(0, 1 - h / 0.2);
    let carry = 0;
    for (const name of against) {
      if (held[name]) continue;
      carry = Math.max(carry, value(name) * (1 - scale));
      for (const i of both(name)) out[i] *= scale;
    }
    const k = idx.get(keep);
    if (carry && k !== undefined) out[k] += 0.25 * carry;
  }
  for (const [name, level] of Object.entries(held)) {
    const i = idx.get(name);
    if (i !== undefined) out[i] = Math.min(1, out[i] + level);
  }
  for (const side of ["l", "r"]) {
    const b = idx.get(`eye_${side}_blink`);
    const bl = b === undefined ? 0 : Math.max(out[b], out[idx.get(`eye_${side}_blinkLipsyncPoseOutput`) ?? b]);
    if (bl <= 0) continue;
    for (const k of [`eye_${side}_brows_raise_in`, `eye_${side}_brows_raise_out`]) {
      const i = idx.get(k);
      if (i !== undefined) out[i] *= 1 - Math.min(1, bl / 0.85);
    }
  }
}

// Head angles for a slot at time t (LipScan .json with "head"), unless Head motion is off
function headAt(slot, t) {
  if (!$("headMotion").checked) return null;
  if (state.testHead) return state.testHead;
  const clip = state.clip[slot];
  if (!clip || !clip.head) return null;
  return clip.head(Math.min(t, clip.duration));
}

// Jaw and lips-shut curves for the timeline
function computeCurve(slot) {
  const clip = state.clip[slot];
  if (!clip || !state.solver) { state.curves[slot] = null; drawTimeline(); return; }
  const s = state.solver;
  const jaw = [s.trackIndex.get("jaw_mid_open"), s.trackIndex.get("jaw_mid_openLipsyncPoseOutput")];
  const shut = [s.trackIndex.get("lips_together_up"), s.trackIndex.get("lips_together_upLipsyncPoseOutput")];
  const n = Math.max(2, Math.ceil(clip.duration * FPS) + 1);
  const out = new Float32Array(s.tracks.length);
  const j = new Float32Array(n);
  const l = new Float32Array(n);
  const gap = new Uint8Array(n);
  for (let f = 0; f < n; f++) {
    sampleValues(slot, f / FPS, out);
    j[f] = jaw.reduce((a, i) => a + (i === undefined ? 0 : out[i]), 0);
    l[f] = shut.reduce((a, i) => a + (i === undefined ? 0 : out[i]), 0);
    gap[f] = clip.gap && clip.gap(f / FPS) ? 1 : 0;
  }
  state.curves[slot] = { jaw: j, shut: l, gap };
  drawTimeline();
}

function duration() {
  return Math.max(0.01, state.clip.A ? state.clip.A.duration : 0, state.clip.B ? state.clip.B.duration : 0,
    state.audio && isFinite(state.audio.duration) ? state.audio.duration : 0);
}

// ---------------- audio ----------------
function loadAudio(file) {
  if (state.audio) { state.audio.pause(); URL.revokeObjectURL(state.audio.src); }
  const a = new Audio(URL.createObjectURL(file));
  a.preload = "auto";
  $("nameAudio").textContent = `Audio: ${file.name}`;
  a.addEventListener("loadedmetadata", () => { $("nameAudio").textContent = `Audio: ${file.name} (${a.duration.toFixed(2)} s)`; drawTimeline(); });
  a.addEventListener("error", () => { $("nameAudio").textContent = `Audio: ${file.name} (can't play)`; });
  state.audio = a;
  seek(state.t);
}

// ---------------- source video (a LipScan trace folder) ----------------
// trace.json lists frames as {file, t} on the video's clock; t = 0 in the viewer is the trace's start
// (or the "video.start" a LipScan .json carries).
async function loadVideo(trace, srcFor, label) {
  if (!trace.frames || !trace.frames.length) throw new Error("This trace has no frames.");
  if (state.video) state.video.frames.forEach((f) => f.url && URL.revokeObjectURL(f.url));
  state.video = { start: trace.start ?? trace.frames[0].t, frames: trace.frames.map((f) => ({ t: f.t, src: srcFor(f.file) })) };
  $("nameVideo").textContent = `Video: ${label}`;
  $("videoPane").hidden = !$("showVideo").checked;
  showFrame();
}

async function loadVideoFolder(files) {
  const byName = new Map(files.map((f) => [f.name.toLowerCase(), f]));
  const tj = byName.get("trace.json");
  if (!tj) throw new Error("A video needs a LipScan trace folder (trace.json and frames).");
  const trace = JSON.parse(await tj.text());
  const folder = (tj.webkitRelativePath || "").split("/")[0] || (trace.source && trace.source.title) || "trace";
  await loadVideo(trace, (file) => { const f = byName.get(file.split("/").pop().toLowerCase()); return f ? { file: f } : null; }, folder);
}

let shownFrame = -1;
function showFrame() {
  const v = state.video;
  if (!v || $("videoPane").hidden) return;
  // the clip that came from this trace sets the clock (and says where no face was seen)
  const clip = [state.clip.A, state.clip.B].find((c) => c && c.video) || null;
  const start = clip ? clip.video.start : v.start;
  const vt = start + state.t;
  let lo = 0;
  let hi = v.frames.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (v.frames[mid].t <= vt) lo = mid; else hi = mid; }
  const k = Math.abs(v.frames[hi].t - vt) < Math.abs(v.frames[lo].t - vt) ? hi : lo;
  const gap = clip && clip.gap ? clip.gap(state.t) : false;
  $("videoPane").classList.toggle("noface", gap);
  $("videoNote").textContent = `video ${vt.toFixed(2)} s${gap ? "  ·  no face tracked" : ""}`;
  if (k === shownFrame) return;
  shownFrame = k;
  const fr = v.frames[k];
  if (!fr.src) return;
  if (fr.src.file) {
    if (!fr.url) fr.url = URL.createObjectURL(fr.src.file);
    $("videoImg").src = fr.url;
  } else $("videoImg").src = fr.src;
}

// ---------------- transport ----------------
function seek(t) {
  state.t = Math.max(0, Math.min(duration(), t));
  if (state.audio) {
    const at = state.t + state.offset;
    if (at >= 0 && isFinite(state.audio.duration)) state.audio.currentTime = Math.min(at, state.audio.duration);
  }
  render();
}

function setPlaying(p) {
  state.playing = p;
  $("play").textContent = p ? "Pause" : "Play";
  if (state.audio) {
    state.audio.playbackRate = state.speed;
    if (p) { state.audio.currentTime = Math.max(0, state.t + state.offset); state.audio.play().catch(() => {}); } else state.audio.pause();
  }
  last = performance.now();
}

let last = performance.now();
function tick(now) {
  const dt = (now - last) / 1000;
  last = now;
  frameDt = dt;
  if (state.playing) {
    if (state.audio && !state.audio.paused && state.t + state.offset >= 0) state.t = state.audio.currentTime - state.offset;
    else state.t += dt * state.speed;
    if (state.t >= duration()) {
      if (state.loop) { seek(0); if (state.audio) { state.audio.currentTime = Math.max(0, state.offset); state.audio.play().catch(() => {}); } }
      else { state.t = duration(); setPlaying(false); }
    }
  }
  controls.update();
  render();
  requestAnimationFrame(tick);
}

function render() {
  if (state.solver) {
    for (const s of ["A", "B"]) {
      const h = state.heads[s];
      if (!h || !h.visible) continue;
      sampleValues(s, state.t, values[s]);
      poseHead(h, state.solver.solve(values[s], headAt(s, state.t), state.clip[s] && state.clip[s].headSplit));
      stepHair(h, frameDt);
      if (s === "A" || !state.heads.A.visible) showActive(s);
    }
  }
  renderer.render(scene, camera);
  $("time").textContent = `${state.t.toFixed(2)} / ${duration().toFixed(2)} s   frame ${Math.round(state.t * FPS)}`;
  drawPlayhead();
  showFrame();
}

let activeStamp = 0;
function showActive() {
  const now = performance.now();
  if (now - activeStamp < 120) return;
  activeStamp = now;
  const s = state.solver;
  const top = [...s.active].sort((a, b) => b[1] - a[1]).slice(0, 14);
  $("active").innerHTML = top.map(([i, v]) =>
    `<div class="bar"><span title="${s.tracks[i]}">${s.tracks[i]}</span><i style="width:${Math.round(v * 60)}px"></i></div>`).join("") || "<div id=info>Rest pose.</div>";
}

// ---------------- timeline ----------------
const tl = $("timeline");
let tlBase = null;
function drawTimeline() {
  const r = tl.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  tl.width = Math.max(1, r.width * dpr);
  tl.height = Math.max(1, r.height * dpr);
  const g = tl.getContext("2d");
  g.clearRect(0, 0, tl.width, tl.height);
  const D = duration();
  const W = tl.width;
  const H = tl.height;
  // grey bands: stretches where the video trace saw no face
  g.fillStyle = css("--muted");
  g.globalAlpha = 0.18;
  for (const slot of ["A", "B"]) {
    const c = state.curves[slot];
    if (!c || !c.gap) continue;
    for (let f = 0; f < c.gap.length; f++) if (c.gap[f]) g.fillRect((f / FPS / D) * W, 0, Math.ceil(W / FPS / D) + 1, H);
  }
  g.globalAlpha = 1;
  for (const [slot, color] of [["B", css("--accent-2")], ["A", css("--accent")]]) {
    const c = state.curves[slot];
    if (!c) continue;
    for (const [arr, alpha] of [[c.shut, 0.35], [c.jaw, 1]]) {
      g.beginPath();
      g.globalAlpha = alpha;
      g.strokeStyle = color;
      g.lineWidth = 1.5 * dpr;
      for (let f = 0; f < arr.length; f++) {
        const x = (f / FPS / D) * W;
        const y = H - 4 * dpr - Math.min(1, arr[f]) * (H - 8 * dpr);
        f ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.stroke();
    }
  }
  g.globalAlpha = 1;
  tlBase = g.getImageData(0, 0, tl.width, tl.height);
  drawPlayhead();
}
function drawPlayhead() {
  if (!tlBase) return;
  const g = tl.getContext("2d");
  g.putImageData(tlBase, 0, 0);
  const x = (state.t / duration()) * tl.width;
  g.fillStyle = css("--text");
  g.fillRect(x - 1, 0, 2 * (window.devicePixelRatio || 1), tl.height);
}
let dragging = false;
const seekFromEvent = (e) => {
  const r = tl.getBoundingClientRect();
  seek(((e.clientX - r.left) / r.width) * duration());
};
tl.addEventListener("pointerdown", (e) => { dragging = true; tl.setPointerCapture(e.pointerId); seekFromEvent(e); });
tl.addEventListener("pointermove", (e) => { if (dragging) seekFromEvent(e); });
tl.addEventListener("pointerup", () => { dragging = false; });

// ---------------- inputs ----------------
const report = (e) => { console.error(e); alert(e.message || String(e)); };
$("fChar").addEventListener("change", (e) => loadCharacter([...e.target.files]).catch(report));
$("fA").addEventListener("change", (e) => e.target.files[0] && loadAnim("A", e.target.files[0]).catch(report));
$("fB").addEventListener("change", (e) => e.target.files[0] && loadAnim("B", e.target.files[0]).catch(report));
$("fAudio").addEventListener("change", (e) => e.target.files[0] && loadAudio(e.target.files[0]));
$("fVideo").addEventListener("change", (e) => loadVideoFolder([...e.target.files]).catch(report));
$("headMotion").addEventListener("change", () => render());
fillMoods();
$("creatorReset").addEventListener("click", () => setCreator({}));
$("creatorRandom").addEventListener("click", () => {
  const c = state.pack && state.pack.creator;
  if (c) setCreator(Object.fromEntries(c.regions.map((r) => [r, c.presets[Math.floor(Math.random() * c.presets.length)]])));
});
$("mood").addEventListener("change", (e) => {
  if (e.target.value === "__custom") { $("fMood").click(); return; }
  setMood(e.target.value);
});
$("fMood").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) { fillMoods(); return; }
  try {
    const j = JSON.parse(await f.text());
    if (!j.tracks || typeof j.tracks !== "object") throw new Error(`${f.name} isn't a mood preset (needs "tracks").`);
    const name = j.name || f.name.replace(/\.json$/i, "");
    moods[name] = { about: j.about || "custom preset", source: f.name, tracks: j.tracks };
    fillMoods();
    setMood(name);
  } catch (err) { report(err); fillMoods(); }
});
for (const s of ["A", "B"]) $(`mood${s}`).addEventListener("change", () => { computeCurve(s); render(); });
$("showTex").addEventListener("change", () => {
  for (const slot of ["A", "B"]) if (state.heads[slot]) state.heads[slot].traverse((o) => { if (o.isMesh) applyTextures(o, o.userData.role); });
});
$("showVideo").addEventListener("change", () => { $("videoPane").hidden = !state.video || !$("showVideo").checked; shownFrame = -1; showFrame(); });
// Hide the source video (the button on it, the V key, or &hidevideo=1); the choice is remembered in this browser.
function setVideoShown(on) {
  $("showVideo").checked = on;
  $("showVideo").dispatchEvent(new Event("change"));
  try { localStorage.setItem("lipscan.video", on ? "1" : "0"); } catch {}
}
$("videoHide").onclick = () => setVideoShown(false);
{
  let pref = null;
  try { pref = localStorage.getItem("lipscan.video"); } catch {}
  if (pref === "0" || new URLSearchParams(location.search).get("hidevideo") === "1") $("showVideo").checked = false;
}
$("clipA").addEventListener("change", (e) => selectClip("A", +e.target.value));
$("clipB").addEventListener("change", (e) => selectClip("B", +e.target.value));
$("viewMode").addEventListener("change", () => { if ($("viewMode").value !== "A" && !state.clip.B) $("viewMode").value = "A"; layout(); });
for (const id of ["showBrows", "showEyes", "showTeeth", "showHair", "wire"]) $(id).addEventListener("change", applyVisibility);
$("showHair").addEventListener("change", () => { for (const s of ["A", "B"]) if (state.heads[s]) state.heads[s].traverse((o) => { if (o.isMesh) applyTextures(o, o.userData.role); }); });
$("frontCam").addEventListener("change", () => {
  const t = controls.target;
  camera.position.set(t.x, t.y, t.z - 0.85);
});

// Camera keys (the view can also be dragged and scrolled): A/D turn around the heads, W/S tilt, Q/E zoom,
// 1 front, 2 three-quarter, 3 left profile, 4 right profile, 0 the starting view.
function orbit(yawDeg, pitchDeg, zoom = 1) {
  const t = controls.target;
  const off = camera.position.clone().sub(t);
  const sph = new THREE.Spherical().setFromVector3(off);
  sph.theta += THREE.MathUtils.degToRad(yawDeg);
  sph.phi = Math.min(Math.PI - 0.1, Math.max(0.1, sph.phi - THREE.MathUtils.degToRad(pitchDeg)));
  sph.radius = Math.min(4, Math.max(0.2, sph.radius * zoom));
  camera.position.copy(t).add(new THREE.Vector3().setFromSpherical(sph));
  camera.lookAt(t);
}
function viewFrom(deg, dist = 0.85) { // deg: 0 = front, 90 = the character's left, -90 = their right
  const t = controls.target;
  const r = THREE.MathUtils.degToRad(deg);
  camera.position.set(t.x - Math.sin(r) * dist, t.y + 0.02, t.z - Math.cos(r) * dist);
  camera.lookAt(t);
}
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  const step = e.shiftKey ? 45 : 15;
  if (k === "a") orbit(-step, 0);
  else if (k === "d") orbit(step, 0);
  else if (k === "w") orbit(0, step / 2);
  else if (k === "s") orbit(0, -step / 2);
  else if (k === "q") orbit(0, 0, 0.85);
  else if (k === "e") orbit(0, 0, 1 / 0.85);
  else if (k === "1") viewFrom(0);
  else if (k === "2") viewFrom(35);
  else if (k === "3") viewFrom(90, 1.0);
  else if (k === "4") viewFrom(-90, 1.0);
  else if (k === "0") { const t = controls.target; camera.position.set(t.x - 0.2, t.y + 0.02, t.z - 0.85); camera.lookAt(t); }
  else if (k === "v") { setVideoShown(!$("showVideo").checked); return; }
  else if (k === "p") { $("hairPhys").checked = !$("hairPhys").checked; return; }          // hair physics on / off
  else return;
  $("frontCam").checked = k === "1";
});
$("offset").addEventListener("input", (e) => { state.offset = (+e.target.value || 0) / 1000; seek(state.t); });
state.tryTrack = -1;
state.tryValue = 0;
$("poseTrack").addEventListener("change", (e) => { state.tryTrack = +e.target.value; render(); });
$("poseValue").addEventListener("input", (e) => { state.tryValue = +e.target.value; $("poseNum").textContent = state.tryValue.toFixed(2); render(); });
$("poseClear").addEventListener("click", () => { state.tryValue = 0; $("poseValue").value = 0; $("poseNum").textContent = "0.00"; render(); });
$("play").addEventListener("click", () => setPlaying(!state.playing));
$("speed").addEventListener("change", (e) => { state.speed = +e.target.value; if (state.audio) state.audio.playbackRate = state.speed; });
$("loop").addEventListener("change", (e) => { state.loop = e.target.checked; });
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" && e.target.type === "number") return;
  if (e.code === "Space") { e.preventDefault(); setPlaying(!state.playing); }
  if (e.code === "ArrowRight") { setPlaying(false); seek(state.t + 1 / FPS); }
  if (e.code === "ArrowLeft") { setPlaying(false); seek(state.t - 1 / FPS); }
  if (e.code === "Home") seek(0);
});

// Drag and drop: a character folder, animations (first to A, then B) and audio
async function filesFromDrop(dt) {
  const out = [];
  const walk = (entry) => new Promise((resolve) => {
    if (entry.isFile) entry.file((f) => { out.push(f); resolve(); }, resolve);
    else {
      const r = entry.createReader();
      const all = [];
      const more = () => r.readEntries(async (es) => { if (!es.length) { for (const x of all) await walk(x); resolve(); } else { all.push(...es); more(); } }, resolve);
      more();
    }
  });
  const entries = [...dt.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (entries.length) for (const e of entries) await walk(e);
  else out.push(...dt.files);
  return out;
}
// A dropped video becomes a finished demo: the dev server runs the whole pipeline (/api/import), this shows the steps, then reloads the list.
async function importVideo(f) {
  const bar = $("importBar");
  const say = (t, bad) => { bar.hidden = false; bar.textContent = t; bar.style.borderColor = bad ? "#b91c1c" : ""; };
  if (location.protocol === "file:") return say("Dropping a video needs the dev server (http://127.0.0.1:8770/).", true);
  const profile = $("dropProfile").value;
  say(`Sending ${f.name}…`);
  const sent = await new Promise((ok) => {
    const x = new XMLHttpRequest();
    x.open("POST", `/api/import?name=${encodeURIComponent(f.name)}&profile=${profile}`);
    x.setRequestHeader("X-LipScan", "1");
    x.upload.onprogress = (e) => e.lengthComputable && say(`Sending ${f.name}… ${Math.round(100 * e.loaded / e.total)}%`);
    x.onload = () => ok(x.status === 200 ? JSON.parse(x.responseText).job : null);
    x.onerror = () => ok(null);
    x.send(f);
  });
  if (!sent) return say("The server did not take the video.", true);
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    const j = await fetch(`/api/import?job=${sent}`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
    if (!j) return say("Lost the server.", true);
    if (j.state === "failed") return say(`Failed at "${j.step}": ${j.error}`, true);
    if (j.state === "done") break;
    say(`${f.name}: step ${j.n}/${j.of}, ${j.step}…`);
  }
  await startDemo(demoUrl);
  say(`${f.name} is ready: the first entry in the test set.`);
  setTimeout(() => { bar.hidden = true; }, 8000);
}
async function handleFiles(files) {
  const vids = files.filter((f) => /\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(f.name));
  if (vids.length) { files = files.filter((f) => !vids.includes(f)); for (const v of vids) await importVideo(v); }
  const charFiles = files.filter((f) => /^character\.json$/i.test(f.name) || /^(head|eyebrows|eyes|teeth|.+)\.(glb|png)$/i.test(f.name) && files.some((x) => /^character\.json$/i.test(x.name)));
  if (charFiles.some((f) => /^character\.json$/i.test(f.name))) await loadCharacter(charFiles);
  let rest = files.filter((f) => !charFiles.includes(f));
  if (rest.some((f) => /^trace\.json$/i.test(f.name))) {
    // a LipScan trace folder: its frames become the video; of its .json files only retarget-*.json is an animation
    await loadVideoFolder(rest);
    rest = rest.filter((f) => /^retarget-.*\.json$/i.test(f.name) || /^audio\.wav$/i.test(f.name));
  }
  for (const f of rest) {
    if (/\.(wav|ogg|mp3|opus|flac|m4a)$/i.test(f.name)) loadAudio(f);
    else if (/\.(glb|json)$/i.test(f.name)) await loadAnim(state.anim.A ? "B" : "A", f);
  }
  if (state.clip.B && $("viewMode").value === "A") { $("viewMode").value = "AB"; layout(); }
}
const drop = $("drop");
view.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); drop.style.display = ""; });
view.addEventListener("dragleave", () => { drop.classList.remove("over"); if (state.solver) drop.style.display = "none"; });
view.addEventListener("drop", async (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (state.solver) drop.style.display = "none";
  try { await handleFiles(await filesFromDrop(e.dataTransfer)); } catch (err) { report(err); }
});

// A clip by name: the exact name, the bare id without its f_/m_ prefix ("1A1FC24AE02C5000"), or the list label
// ("f_1A1FC24AE02C5000  (5.83 s)"), ignoring case and spacing.
function findClip(slot, want) {
  const a = state.anim[slot];
  if (!a || !want) return -1;
  const norm = (s) => s.toLowerCase().replace(/\s*\(\d+(\.\d+)?\s*s\)\s*$/, "").trim();
  const w = norm(want);
  let i = a.clips.findIndex((c) => norm(c.name) === w);
  if (i < 0) i = a.clips.findIndex((c) => norm(c.name).replace(/^[fm]_/, "") === w.replace(/^[fm]_/, ""));
  if (i < 0) i = a.clips.findIndex((c) => norm(c.name).includes(w));
  return i;
}

function useClip(slot, want) {
  const i = findClip(slot, want);
  if (i < 0) { console.warn(`clip "${want}" not found in ${slot}`); return false; }
  $(`clip${slot}`).value = i;
  selectClip(slot, i);
  return true;
}

// When served over http, files can be given in the address:
//   ?pack=folder/&a=file&b=file&audio=file&video=trace-folder/&clip=name&clipB=name&view=ab&t=seconds&head=0&cam=front&mood=scowl&jaw=7&eyes=3 (player heads)
//   clip (or clipA) picks A's clip, clipB picks B's: a bare id, the full name or the list label. view: a, b or ab.
const fetched = new Map(); // url -> File (animation files are big; fetch each once)
async function get(u) {
  if (fetched.has(u)) return fetched.get(u);
  const r = await fetch(u);
  if (!r.ok) throw new Error(`${u}: HTTP ${r.status}`);
  const f = new File([await r.blob()], decodeURIComponent(u.split("/").pop().split("?")[0]));
  if (/\.glb$/i.test(u)) fetched.set(u, f);
  return f;
}
let loadedPack = null;
async function loadPackUrl(url) {
  const base = url.replace(/\/?$/, "/");
  if (loadedPack === base) return;
  const cj = await get(base + "character.json");
  const pack = JSON.parse(await cj.text());
  await loadCharacter([cj, ...(await Promise.all([...pack.meshes.map((m) => m.file), ...(pack.textures || []).map((t) => t.file)].map((f) => get(base + f))))]);
  loadedPack = base;
}

// ---------------- demo: a test set of characters and lines (?demo=manifest.json) ----------------
// manifest: {characters: [{name, pack, creator?, lines: [{text, game, clip, lipscan, audio, mood}]}]}
let demo = null;
let demoUrl = "/pack/demo/manifest.json";
async function startDemo(url) {
  demoUrl = url;
  demo = await (await fetch(url)).json();
  $("demoBox").hidden = false;
  const cs = $("demoChar");
  cs.innerHTML = "";
  demo.characters.forEach((c, i) => cs.add(new Option(`${c.name} (${c.lines.length})`, i)));
  cs.onchange = () => { fillDemoLines(); loadDemo(); };
  $("demoLine").onchange = () => loadDemo();
  const step = (d) => {
    const ls = $("demoLine");
    let li = +ls.value + d;
    let ci = +cs.value;
    if (li < 0 || li >= ls.options.length) {
      ci = (ci + (d > 0 ? 1 : demo.characters.length - 1)) % demo.characters.length;
      cs.value = ci;
      fillDemoLines();
      li = d > 0 ? 0 : $("demoLine").options.length - 1;
    }
    $("demoLine").value = li;
    loadDemo();
  };
  $("demoPrev").onclick = () => step(-1);
  $("demoNext").onclick = () => step(1);
  const q = new URLSearchParams(location.search);
  if (q.get("demoChar")) cs.value = Math.min(demo.characters.length - 1, +q.get("demoChar"));
  fillDemoLines();
  if (q.get("demoLine")) $("demoLine").value = Math.min($("demoLine").options.length - 1, +q.get("demoLine"));
  await loadDemo();
}
function fillDemoLines() {
  const c = demo.characters[+$("demoChar").value];
  const ls = $("demoLine");
  ls.innerHTML = "";
  c.lines.forEach((l, i) => ls.add(new Option(`${i + 1}. ${l.text.slice(0, 48)}${l.text.length > 48 ? "…" : ""}`, i)));
}
// The dials re-run the voice model on this machine's dev server (/api/gen) and swap the result in without stopping playback.
// A line is live when the server answers; its B animation comes from the voice (and A too, if the line has a trace folder).
let live = null, liveTimer = 0, liveSeq = 0;
const dialValues = () => ({ articulation: +$("dialArt").value, expressiveness: +$("dialExp").value, coupling: +$("dialCp").value });
function setDialLabels() { $("artOut").textContent = (+$("dialArt").value).toFixed(2); $("expOut").textContent = (+$("dialExp").value).toFixed(2); $("cpOut").textContent = (+$("dialCp").value).toFixed(2); }
// What a head plays: "video" (everything from his face), "hybrid" (video + audio) or "audio" (the voice model alone).
// video is a file; hybrid and audio are made by the dev server with the dials' settings.
const SOURCE_LABEL = { video: "Video only", hybrid: "Video + audio (hybrid)", audio: "Audio only" };
async function genSource(kind) {
  const q = new URLSearchParams({ ...live.jobs[kind], ...dialValues(), rig: live.rig });
  const r = await fetch(`/api/gen?${q}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function showSource(slot, kind) {
  if (kind === "video") await loadAnim(slot, await get(live.line.sources.video));
  else {
    const json = await genSource(kind);
    live.settings = json.settings || live.settings;
    await loadAnim(slot, new File([JSON.stringify(json)], `lipscan-${kind}.json`));
  }
}
async function changeSource(slot) {
  if (!live || !live.line.sources) return;
  const kind = $(`src${slot}`).value, t = state.t, was = state.playing;
  live.slotKind[slot] = kind;
  $("dialInfo").textContent = "updating…";
  try {
    await showSource(slot, kind);
    seek(t);
    if (was) setPlaying(true);
    $("dialInfo").textContent = "";
  } catch (e) { $("dialInfo").textContent = String(e.message || e).slice(0, 120); }
}
$("srcA").onchange = () => changeSource("A");
$("srcB").onchange = () => changeSource("B");
async function regenerate() {
  if (!live) return;
  const seq = ++liveSeq, d = dialValues(), t = state.t, was = state.playing;
  $("dialInfo").textContent = "updating…";
  try {
    const slots = Object.entries(live.slotKind).filter(([, kind]) => kind !== "video");        // a video-only head doesn't depend on the dials
    const done = await Promise.all(slots.map(async ([slot, kind]) => [slot, kind, await genSource(kind)]));
    if (seq !== liveSeq) return;                                    // a newer change is already on its way
    for (const [slot, kind, json] of done) {
      await loadAnim(slot, new File([JSON.stringify(json)], `lipscan-${kind}.json`));
      live.settings = json.settings || live.settings;
    }
    seek(t);
    if (was) setPlaying(true);
    const jp = live.settings && live.settings.jaw_presence;
    $("dialInfo").textContent = jp ? `jaw presence ${(+jp).toFixed(2)} (from this face's rig)` : "";
  } catch (e) { $("dialInfo").textContent = String(e.message || e).slice(0, 120); }
}
function dialsChanged() { setDialLabels(); clearTimeout(liveTimer); liveTimer = setTimeout(regenerate, 250); }
for (const id of ["dialArt", "dialExp", "dialCp"]) $(id).oninput = dialsChanged;
$("dialReset").onclick = () => { for (const id of ["dialArt", "dialExp", "dialCp"]) $(id).value = 1; dialsChanged(); };

// Lyrics typed by the user: the dev server lines them up to the speech-to-text word times and rewrites the folder's word files, then both
// voice-based heads are generated again.
async function lyricsCall(url, init, ok) {
  $("lyricsInfo").textContent = "working…";
  try {
    const r = await fetch(url, init);
    if (!r.ok) throw new Error(await r.text());
    const res = await r.json();
    $("lyricsInfo").textContent = ok(res);
    await regenerate();
  } catch (e) { $("lyricsInfo").textContent = String(e.message || e).slice(0, 160); }
}
$("lyricsApply").onclick = () => {
  const text = $("lyricsText").value;
  if (!live || !text.trim()) return;
  lyricsCall(`/api/lyrics?folder=${encodeURIComponent(live.line.hybrid)}`, { method: "POST", body: text },
    (r) => `Using your ${r.words} words (${r.matched} of them heard the same by speech-to-text, the rest placed between), ${r.first.toFixed(1)} s to ${r.last.toFixed(1)} s.`);
};
$("lyricsReset").onclick = () => {
  if (!live) return;
  lyricsCall(`/api/lyrics?folder=${encodeURIComponent(live.line.hybrid)}&reset=1`, {}, () => "Back to the speech-to-text words.");
};
async function showLyrics(l) {
  const on = !!(live && l.hybrid && l.words);
  $("lyricsBox").hidden = !on;
  if (!on) return;
  $("lyricsInfo").textContent = "";
  $("lyricsText").value = "";
  try {                                                 // the lyrics last used with this clip, if any
    const r = await fetch(l.hybrid.replace(/\/?$/, "/") + "lyrics.txt", { cache: "no-store" });
    if (r.ok) { $("lyricsText").value = await r.text(); $("lyricsInfo").textContent = "Showing the lyrics last used here (the heads use them unless you went back to speech-to-text)."; }
  } catch {}
}

let demoBusy = false;
async function loadDemo() {
  if (demoBusy) return;
  demoBusy = true;
  const c = demo.characters[+$("demoChar").value];
  const l = c.lines[+$("demoLine").value];
  $("demoText").textContent = "loading…";
  try {
    setPlaying(false);
    await loadPackUrl(c.pack);
    setCreator(c.creator || {});
    await loadAnim("A", await get(l.game));
    if (l.clip) useClip("A", l.clip);
    await loadAnim("B", await get(l.lipscan));
    loadAudio(await get(l.audio));
    if (l.video) {                                       // a LipScan trace: its frames play in the corner pane
      const vb = l.video.replace(/\/?$/, "/");
      await loadVideo(JSON.parse(await (await get(vb + "trace.json")).text()), (file) => vb + file.split("/").map(encodeURIComponent).join("/"), c.name);
    } else if (state.video) { state.video = null; $("videoPane").hidden = true; $("nameVideo").textContent = "Video…"; }
    live = null;
    $("dials").hidden = true;
    $("srcBox").hidden = true;
    if (location.protocol !== "file:" && (l.hybrid || l.audio)) {   // the dials need the dev server; probe it once per line
      const ok = await fetch("/api/gen").then((r) => r.status !== 404, () => false);
      if (ok) {
        const base = { profile: l.profile || demo.profile || "speech" };
        const jobs = { audio: { mode: "voice", wav: l.audio, ...(l.text && !l.noText ? { text: l.text } : {}), ...(l.words ? { words: l.words } : {}), ...base } };
        if (l.hybrid) jobs.hybrid = { mode: "hybrid", folder: l.hybrid, ...base };
        live = { jobs, line: l, slotKind: l.sources ? { A: "hybrid", B: "audio" } : (l.hybrid ? { A: "hybrid", B: "audio" } : { B: "audio" }),
                 rig: c.pack.replace(/\/?$/, "/") + "character.json", settings: null };
        if (l.sources) {                                              // let each head play any of the sources
          const kinds = Object.keys(SOURCE_LABEL).filter((k) => l.sources[k]);
          for (const [slot, init] of [["A", "hybrid"], ["B", "audio"]]) {
            const sel = $(`src${slot}`);
            sel.innerHTML = "";
            kinds.forEach((k) => sel.add(new Option(SOURCE_LABEL[k], k)));
            sel.value = kinds.includes(init) ? init : kinds[0];
            live.slotKind[slot] = sel.value;
          }
          $("srcBox").hidden = false;
        }
        $("dials").hidden = false;
        $("dialInfo").textContent = "";
        for (const id of ["dialArt", "dialExp", "dialCp"]) $(id).value = 1;
        setDialLabels();
      }
    }
    await showLyrics(l);
    $("moodA").checked = !!l.moodA;                       // a line may hold the mood on head A too (its face comes from a video)
    $("moodB").checked = !l.noMood;
    setMood(!l.noMood && l.mood && moods[l.mood] ? l.mood : "neutral");
    $("viewMode").value = "AB";
    layout();
    seek(0);
    $("demoText").textContent = l.label || `"${l.text}"  ·  game mood: ${l.mood || "?"}  ·  A = game, B = LipScan (voice only)`;
  } catch (e) { $("demoText").textContent = String(e.message || e); }
  demoBusy = false;
}

async function fromUrl() {
  const q = new URLSearchParams(location.search);
  if (location.protocol === "file:") return;
  if (q.get("demo")) {
    await startDemo(q.get("demo"));
    if (q.get("cam") === "front") { $("frontCam").checked = true; $("frontCam").dispatchEvent(new Event("change")); }
    if (q.get("t")) seek(+q.get("t"));                    // &t=80 starts there; &play=1 starts playing (the browser may need a click first for sound)
    if (q.get("play") === "1") setPlaying(true);
    return;
  }
  if (!q.get("pack")) return;
  await loadPackUrl(q.get("pack"));
  for (const s of ["a", "b"]) if (q.get(s)) await loadAnim(s.toUpperCase(), await get(q.get(s)));
  const clipA = q.get("clipA") || q.get("clip");
  if (clipA) useClip(state.anim.A ? "A" : "B", clipA);
  if (q.get("clipB")) useClip("B", q.get("clipB"));
  if (q.get("audio")) loadAudio(await get(q.get("audio")));
  if (q.get("video")) {
    const vb = q.get("video").replace(/\/?$/, "/");
    const trace = await (await get(vb + "trace.json")).text();
    await loadVideo(JSON.parse(trace), (file) => vb + file.split("/").map(encodeURIComponent).join("/"), decodeURIComponent(vb.split("/").filter(Boolean).pop()));
  }
  if (q.get("head") === "0") $("headMotion").checked = false;
  if (q.get("mood") && moods[q.get("mood")]) setMood(q.get("mood"));
  // character creator: &eyes=3&nose=12&mouth=7&jaw=7&ear=1
  if (state.pack.creator && state.pack.creator.regions.some((r) => q.get(r))) setCreator(Object.fromEntries(state.pack.creator.regions.map((r) => [r, q.get(r)])));
  const view = (q.get("view") || (state.clip.B ? "ab" : "")).toUpperCase();
  if (["A", "B", "AB"].includes(view)) { $("viewMode").value = view; layout(); }
  if (q.get("cam") === "front") { $("frontCam").checked = true; $("frontCam").dispatchEvent(new Event("change")); }
  if (q.get("t")) seek(+q.get("t"));
  if (q.get("try")) { const i = state.solver.trackIndex.get(q.get("try")); if (i !== undefined) { state.tryTrack = i; state.tryValue = +(q.get("v") || 1); } render(); }
  // test hook: ?yaw=&pitch=&roll= poses the head (degrees) for checking directions
  if (["yaw", "pitch", "roll"].some((k) => q.has(k))) {
    state.testHead = { yaw: +(q.get("yaw") || 0), pitch: +(q.get("pitch") || 0), roll: +(q.get("roll") || 0) };
    render();
  }
}

resize();
requestAnimationFrame(tick);
fromUrl().catch(report);
window.lipscanViewer = { state, seek, setPlaying };

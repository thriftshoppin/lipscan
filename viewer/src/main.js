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
};

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

// ---------------- state ----------------
const state = {
  pack: null, solver: null, meshFiles: [], heads: { A: null, B: null },
  anim: { A: null, B: null }, clip: { A: null, B: null },
  t: 0, playing: false, speed: 1, loop: true, audio: null, offset: 0, curves: { A: null, B: null },
  video: null, // {start, frames: [{t, src}]} from a LipScan trace folder
};
const values = { A: null, B: null };

// ---------------- character ----------------
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
        if (role === "teeth" && o.isSkinnedMesh) colorByBone(o, (name) => (/tongue/i.test(name) ? 0xb4625e : 0xece4d0));
        if (role === "eyes" && /doubled/i.test(o.name)) { o.material.transparent = true; o.material.opacity = 0.12; o.material.depthWrite = false; }
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
  state.solver = new FaceSolver(pack);
  state.meshFiles = pack.meshes.filter((m) => byName.has(m.file.toLowerCase())).map((m) => ({ ...m, blob: byName.get(m.file.toLowerCase()) }));
  for (const s of ["A", "B"]) {
    if (state.heads[s]) scene.remove(state.heads[s]);
    state.heads[s] = await buildHead(s);
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
  const show = { eyebrows: $("showBrows").checked, eyes: $("showEyes").checked, teeth: $("showTeeth").checked };
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
for (const id of ["showBrows", "showEyes", "showTeeth", "wire"]) $(id).addEventListener("change", applyVisibility);
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
async function handleFiles(files) {
  const charFiles = files.filter((f) => /^character\.json$/i.test(f.name) || /^(head|eyebrows|eyes|teeth|.+)\.glb$/i.test(f.name) && files.some((x) => /^character\.json$/i.test(x.name)));
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
  await loadCharacter([cj, ...(await Promise.all(pack.meshes.map((m) => get(base + m.file))))]);
  loadedPack = base;
}

// ---------------- demo: a test set of characters and lines (?demo=manifest.json) ----------------
// manifest: {characters: [{name, pack, creator?, lines: [{text, game, clip, lipscan, audio, mood}]}]}
let demo = null;
async function startDemo(url) {
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
async function regenerate() {
  if (!live) return;
  const seq = ++liveSeq, d = dialValues(), t = state.t, was = state.playing;
  $("dialInfo").textContent = "updating…";
  try {
    const jobs = [];
    for (const [slot, job] of Object.entries(live.jobs)) {
      const q = new URLSearchParams({ ...job, ...d, rig: live.rig });
      jobs.push(fetch(`/api/gen?${q}`).then(async (r) => { if (!r.ok) throw new Error(await r.text()); return [slot, await r.json()]; }));
    }
    const done = await Promise.all(jobs);
    if (seq !== liveSeq) return;                                    // a newer change is already on its way
    for (const [slot, json] of done) {
      await loadAnim(slot, new File([JSON.stringify(json)], `lipscan-live-${slot}.json`));
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
    if (location.protocol !== "file:" && (l.hybrid || l.audio)) {   // the dials need the dev server; probe it once per line
      const ok = await fetch("/api/gen").then((r) => r.status !== 404, () => false);
      if (ok) {
        const base = { profile: l.profile || demo.profile || "speech" };
        const jobs = { B: { mode: "voice", wav: l.audio, ...(l.text && !l.noText ? { text: l.text } : {}), ...base } };
        if (l.hybrid) jobs.A = { mode: "hybrid", folder: l.hybrid, ...base };
        live = { jobs, rig: c.pack.replace(/\/?$/, "/") + "character.json", settings: null };
        $("dials").hidden = false;
        $("dialInfo").textContent = "";
        for (const id of ["dialArt", "dialExp", "dialCp"]) $(id).value = 1;
        setDialLabels();
      }
    }
    $("moodA").checked = false;
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

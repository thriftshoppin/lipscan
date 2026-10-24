// Starts the LipScan server as a child, drives it with the official MCP client, and plays the add-on with a fake
// WebSocket client. Checks the login, flood guard, YouTube-only rule, safe folder names, disk cap and a full trace.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import WebSocket from "ws";
import { fileURLToPath } from "node:url";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const PORT = "18766";
const CODE = "selftest-code-lipscan";
const EXT_ORIGIN = "moz-extension://selftest";
const ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "lipscan-selftest-"));
const server = fileURLToPath(new URL("../capture/server/server.js", import.meta.url));
const results = [];
const check = (name, cond, info = "") => {
  results.push({ name, ok: !!cond });
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${info ? "  (" + info + ")" : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const txt = (r) => r.content.filter((c) => c.type === "text").map((c) => c.text).join("\n");

async function mcp(env = {}) {
  const c = new Client({ name: "selftest", version: "1" });
  await c.connect(new StdioClientTransport({
    command: process.execPath, args: [server],
    env: { ...process.env, LIPSCAN_PORT: PORT, LIPSCAN_CODE: CODE, LIPSCAN_ROOT: ROOT, ...env }, stderr: "ignore",
  }));
  return c;
}

// What the fake add-on reports for the tab, and how much it "records".
const page = { url: "https://www.youtube.com/watch?v=abc", title: "Test video - YouTube", pulls: 2, frameBytes: 1000 };
let pullCount = 0;

function fakeExt(code, { origin = EXT_ORIGIN, legacy = false } = {}) {
  return new Promise((resolve) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}`, { headers: origin ? { Origin: origin } : {} });
    let expectedProof = null;
    if (legacy) ws.on("open", () => ws.send(JSON.stringify({ type: "hello", token: code, version: "0.0.1" })));
    ws.on("message", (d) => {
      const m = JSON.parse(d);
      if (m.type === "challenge") {
        if (legacy) return;
        const cnonce = crypto.randomBytes(32).toString("hex");
        expectedProof = crypto.createHmac("sha256", code).update(`server|${m.nonce}|${cnonce}`).digest("hex");
        ws.send(JSON.stringify({ type: "hello", v: 2, cnonce, proof: crypto.createHmac("sha256", code).update(`client|${m.nonce}|${cnonce}`).digest("hex"), version: "0.1.0" }));
        return;
      }
      if (m.type === "welcome") return resolve({ ws, accepted: true, serverProved: m.proof === expectedProof });
      const reply = (result) => ws.send(JSON.stringify({ id: m.id, ok: true, result }));
      if (m.cmd === "tab_info") reply({ tabId: 7, url: page.url, title: page.title });
      else if (m.cmd === "trace_begin") { pullCount = 0; reply({ tabId: 7, width: 640, height: 360, audioRate: 48000, audioClock: "worklet", frameClock: "video frame callback", title: page.title, url: page.url }); }
      else if (m.cmd === "trace_pull") {
        pullCount++;
        const base = 10 + (pullCount - 1);
        const frames = [0, 1, 2].map((k) => ({ t: base + k / 30, jpeg: Buffer.alloc(page.frameBytes, k).toString("base64") }));
        const audio = [{ t: base, pcm: Buffer.alloc(48000 * 2, 1).toString("base64") }]; // 1 s of sound per pull
        reply({ frames, audio, audioRate: 48000, state: { active: pullCount < page.pulls, reason: pullCount < page.pulls ? "" : "reached the requested length", capturedSeconds: pullCount, seeks: 1, adFramesSkipped: 0, droppedFrames: 0 } });
      }
      else if (m.cmd === "trace_end") reply({ stopped: true });
      else if (m.cmd === "trace_captions") reply({ tracks: [{ lang: "en", kind: "automatic" }], chosen: { lang: "en", kind: "automatic" }, events: [{ start: 10.2, dur: 1, text: "hello there", words: [{ t: 10.2, text: "hello" }, { t: 10.5, text: "there" }] }] });
      else ws.send(JSON.stringify({ id: m.id, ok: false, error: `fake add-on doesn't know ${m.cmd}` }));
    });
    ws.on("unexpected-response", (req, res) => resolve({ ws, accepted: false, httpStatus: res.statusCode }));
    ws.on("close", (c) => resolve({ ws, accepted: false, code: c }));
    ws.on("error", () => {});
  });
}

async function waitDone(client, ms = 15000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    const s = JSON.parse(txt(await client.callTool({ name: "lipscan_status", arguments: {} })));
    if (s.trace && s.trace.done) return s.trace;
    await sleep(300);
  }
  return null;
}

const client = await mcp();
await sleep(300);

const { tools } = await client.listTools();
check("exactly the four trace tools", tools.map((t) => t.name).sort().join(",") === "lipscan_list,lipscan_start,lipscan_status,lipscan_stop", tools.map((t) => t.name).join(","));

let r = await fakeExt("wrong-code-000000000");
check("wrong connection code is refused", !r.accepted && r.code === 4003, `close ${r.code}`);
r = await fakeExt(CODE, { legacy: true });
check("the old plaintext login doesn't exist", !r.accepted, `close ${r.code}`);
r = await fakeExt(CODE, { origin: "https://evil.example" });
check("a web page can't connect", !r.accepted && r.httpStatus === 403, `HTTP ${r.httpStatus}`);
r = await fakeExt(CODE, { origin: null });
check("an add-on login without a moz-extension origin is refused", !r.accepted, `close ${r.code}`);

// pre-login limits
{
  const ws = new WebSocket(`ws://127.0.0.1:${PORT}`, { headers: { Origin: EXT_ORIGIN } });
  const code = await new Promise((res) => {
    ws.on("message", () => ws.send("x".repeat(20 * 1024)));
    ws.on("close", (c) => res(c));
    ws.on("error", () => {});
  });
  check("before login, a 20 KB message is refused (8 KB cap)", code === 1009, `close ${code}`);
  const idle = [];
  const closes = [];
  for (let i = 0; i < 20; i++) {
    const s = new WebSocket(`ws://127.0.0.1:${PORT}`, { headers: { Origin: EXT_ORIGIN } });
    s.on("close", (c) => closes.push(c));
    s.on("error", () => {});
    idle.push(s);
  }
  await sleep(800);
  const turned = closes.filter((c) => c === 1013).length;
  check("flood guard: at most 16 connections may wait to log in", turned >= 4, `${turned} of 20 turned away`);
  idle.forEach((s) => s.terminate());
  await sleep(200);
}

const ext = await fakeExt(CODE);
check("right code accepted, and the server proves it knows the code", ext.accepted && ext.serverProved);
await sleep(200);

let st = JSON.parse(txt(await client.callTool({ name: "lipscan_status", arguments: {} })));
check("lipscan_status reports the add-on", st.connected && st.addon_version === "0.1.0", JSON.stringify(st).slice(0, 100));

// YouTube only
for (const url of ["https://example.com/watch?v=abc", "https://youtube.com.evil.example/x", "https://notyoutube.com/", "file:///C:/x.mp4", "https://evil.example/?u=https://www.youtube.com/"]) {
  page.url = url;
  r = await client.callTool({ name: "lipscan_start", arguments: {} });
  check(`a non-YouTube tab is refused: ${url}`, r.isError && /isn't on YouTube/.test(txt(r)), txt(r).slice(0, 80));
}
page.url = "https://music.youtube.com/watch?v=abc";

// folder names
for (const title of ["..\\..\\..\\Windows\\System32\\evil", "../../../../etc/passwd", "CON", "a/b\\c:d*e?f\"g<h>i|j", "....", "", "x".repeat(400)]) {
  page.title = title;
  page.pulls = 1;
  r = await client.callTool({ name: "lipscan_start", arguments: { maxSeconds: 1 } });
  const out = r.isError ? null : JSON.parse(txt(r));
  const done = out && await waitDone(client);
  const folder = done && done.folder;
  const inside = folder && path.dirname(folder) === ROOT && fs.existsSync(path.join(folder, "trace.json"));
  const name = folder ? path.basename(folder) : "";
  check(`crafted title stays inside the trace folder: ${JSON.stringify(title).slice(0, 40)}`, inside && name.length < 80 && !/[\\/:*?"<>|]|\.\./.test(name), name);
}

// a full trace
page.title = "Lipsync test - YouTube";
page.pulls = 3;
r = await client.callTool({ name: "lipscan_start", arguments: { maxSeconds: 5 } });
const startedOk = !r.isError;
const again = await client.callTool({ name: "lipscan_start", arguments: {} });
check("a second trace is refused while one runs", startedOk && again.isError && /already running/.test(txt(again)), txt(again).slice(0, 80));
const done = await waitDone(client);
const tj = done && JSON.parse(fs.readFileSync(path.join(done.folder, "trace.json"), "utf8"));
check("trace saves 9 frames, trace.json and a WAV", done && done.frames === 9 && tj.frames.length === 9 && fs.existsSync(path.join(done.folder, "frames", "f000009.jpg")), done && `${done.frames} frames`);
const wav = done && fs.readFileSync(path.join(done.folder, "audio.wav"));
check("WAV is laid out on the video clock (3 s at 48 kHz, starting at the first frame)", wav && wav.readUInt32LE(24) === 48000 && wav.readUInt32LE(40) === 3 * 48000 * 2 && tj.audio.start === 10, wav && `${wav.readUInt32LE(40)} bytes`);
check("captions.txt is written for corrections", done && fs.readFileSync(path.join(done.folder, "captions.txt"), "utf8") === "10.20\thello there\n");
const list = JSON.parse(txt(await client.callTool({ name: "lipscan_list", arguments: {} })));
check("lipscan_list shows the traces, newest first", list.traces.length >= 8 && list.traces[0].title === "Lipsync test - YouTube", `${list.traces.length} traces`);

// disk cap
{
  const capped = await mcp({ LIPSCAN_PORT: "18767", LIPSCAN_MAX_MB: "10" });
  const ws2 = await new Promise((resolve) => {
    // reuse the fake add-on on the second port
    const w = new WebSocket("ws://127.0.0.1:18767", { headers: { Origin: EXT_ORIGIN } });
    w.on("message", (d) => {
      const m = JSON.parse(d);
      if (m.type === "challenge") {
        const cnonce = crypto.randomBytes(32).toString("hex");
        w.send(JSON.stringify({ type: "hello", v: 2, cnonce, proof: crypto.createHmac("sha256", CODE).update(`client|${m.nonce}|${cnonce}`).digest("hex"), version: "0.1.0" }));
        return;
      }
      if (m.type === "welcome") return resolve(w);
      const reply = (result) => w.send(JSON.stringify({ id: m.id, ok: true, result }));
      if (m.cmd === "tab_info") reply({ tabId: 7, url: "https://www.youtube.com/watch?v=big", title: "Big" });
      else if (m.cmd === "trace_begin") reply({ tabId: 7, width: 640, height: 360, audioRate: 48000, audioClock: "worklet", frameClock: "x", title: "Big", url: "https://www.youtube.com/watch?v=big" });
      else if (m.cmd === "trace_pull") reply({ frames: [{ t: Math.random() * 100, jpeg: Buffer.alloc(4 * 1024 * 1024).toString("base64") }], audio: [], audioRate: 48000, state: { active: true } });
      else reply({ stopped: true, events: [] });
    });
    w.on("error", () => {});
  });
  await sleep(200);
  await capped.callTool({ name: "lipscan_start", arguments: { maxSeconds: 600 } });
  const until = Date.now() + 15000;
  let s;
  while (Date.now() < until) {
    s = JSON.parse(txt(await capped.callTool({ name: "lipscan_status", arguments: {} })));
    if (s.trace && s.trace.done) break;
    await sleep(300);
  }
  check("a trace stops cleanly at the disk cap", s.trace && s.trace.done && /disk cap/.test(s.trace.stopped) && s.trace.megabytes <= 16, s.trace && `${s.trace.megabytes} MB, ${s.trace.stopped}`);
  ws2.close();
  await capped.close();
}

// relay
const relay = await mcp();
await sleep(1500);
st = JSON.parse(txt(await relay.callTool({ name: "lipscan_status", arguments: {} })));
check("a second server copy joins as a relay and sees the add-on", st.connected && st.this_copy === "relay", JSON.stringify(st).slice(0, 100));
await relay.close();

ext.ws.close();
await client.close();
fs.rmSync(ROOT, { recursive: true, force: true }); // the test's own temporary folder
const failed = results.filter((x) => !x.ok).length;
console.log(failed ? `${failed} FAILED` : `ALL ${results.length} PASSED`);
process.exit(failed ? 1 : 0);

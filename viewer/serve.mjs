// Dev only: serves the viewer and local test files on http://127.0.0.1:8770 (this computer only).
//   /           -> dist/
//   /pack/...   -> LIPSCAN_PACKS (character packs)
//   /data/...   -> LIPSCAN_DATA (animations, audio)
//   /api/gen    -> runs the LipScan model again with the sliders' settings (needs Python: LIPSCAN_PY, and the repo: LIPSCAN_REPO)
//        ?mode=voice&wav=/pack/x.wav[&text=..][&words=/pack/x-words.json][&profile=speech][&rig=/pack/c/character.json]&articulation=1&expressiveness=1&coupling=1
//        ?mode=hybrid&folder=/pack/live/clip/ ...the same settings  (a LipScan trace folder: the video's head and brows, the voice's mouth)
//   /api/import -> a dropped video becomes a demo: POST the file, then poll ?job=<id> (ingest.py; needs LIPSCAN_SEP_PY and LIPSCAN_ASR for the full run)
//   /api/lyrics -> POST the lyrics as the body, ?folder=/pack/live/clip/ : lines them up to the speech-to-text times and writes the folder's
//                  words-timed.json and captions.json (analyze/lyrics.py); ?reset=1 puts the speech-to-text words back
import http from "node:http";
import { execFile, spawn } from "node:child_process";
import { createReadStream, createWriteStream, statSync, writeFileSync, mkdtempSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, normalize, extname, resolve, sep } from "node:path";

const roots = { "": resolve("dist"), pack: resolve(process.env.LIPSCAN_PACKS || "."), data: resolve(process.env.LIPSCAN_DATA || ".") };
const types = { ".html": "text/html", ".json": "application/json", ".glb": "model/gltf-binary", ".wav": "audio/wav", ".js": "text/javascript" };
const py = process.env.LIPSCAN_PY || "python";
const repo = resolve(process.env.LIPSCAN_REPO || "..");
const local = (u) => {                                   // "/pack/x" or "/data/x" -> a file path under that root, or null
  const [, first, ...rest] = decodeURIComponent(u || "").split("/");
  const f = first && Object.hasOwn(roots, first) ? normalize(join(roots[first], ...rest.filter(Boolean))) : null;
  return f && f.startsWith(roots[first]) ? f : null;
};
const num = (v) => (v === null || v === "" || isNaN(+v) ? null : Math.min(2, Math.max(0, +v)));
function gen(q, res) {
  const flags = [];
  for (const k of ["articulation", "expressiveness", "coupling"]) if (num(q.get(k)) !== null) flags.push(`--${k}`, String(num(q.get(k))));
  const rig = q.get("rig") && local(q.get("rig"));
  if (rig) flags.push("--rig", rig);
  let args;
  if (q.get("mode") === "hybrid") {
    const folder = local(q.get("folder"));
    if (!folder) return res.writeHead(400).end("bad folder");
    args = [join(repo, "retarget", "retarget.py"), folder, "--out", "-", ...flags];
    if (q.get("profile")) args.push("--profile", String(q.get("profile")).replace(/[^\w.-]/g, ""));     // the hybrid's voice side
  } else {
    const wav = local(q.get("wav"));
    if (!wav) return res.writeHead(400).end("bad wav");
    args = [join(repo, "model", "lipsync.py"), wav, "--out", "-", ...flags];
    if (q.get("text")) args.push("--text", q.get("text"));
    const words = q.get("words") && local(q.get("words"));            // a JSON file of timed words, [[seconds, "word"], ...]
    if (words) args.push("--words", words);
    if (q.get("profile")) args.push("--profile", String(q.get("profile")).replace(/[^\w.-]/g, ""));
  }
  execFile(py, args, { maxBuffer: 1 << 28, timeout: 120000 }, (err, out, errout) => {
    if (err) return res.writeHead(500).end(String(errout || err).slice(-600));
    res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" }).end(out);
  });
}
function lyrics(req, q, res) {
  const folder = local(q.get("folder"));
  if (!folder) return res.writeHead(400).end("bad folder");
  const run = (args) => execFile(py, [join(repo, "analyze", "lyrics.py"), ...args], { timeout: 60000 }, (err, out, errout) => {
    if (err) return res.writeHead(500).end(String(errout || err).slice(-400));
    res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" }).end(out);
  });
  if (q.get("reset")) return run(["reset", folder]);
  let body = "";
  req.on("data", (c) => { body += c; if (body.length > 200000) req.destroy(); });
  req.on("end", () => {
    const file = join(mkdtempSync(join(tmpdir(), "lipscan-lyrics-")), "lyrics.txt");
    writeFileSync(file, body, "utf8");
    run(["apply", folder, file]);
  });
}
// Dropped videos: POST the file as the body to /api/import?name=clip.mp4&profile=singing-hard (header X-LipScan: 1, so other web pages cannot
// post here). It is saved into LIPSCAN_PACKS/live/<name>/ and ingest.py runs the whole pipeline; /api/import?job=<id> reports the progress.
const jobs = new Map();
const slug = (s) => s.replace(/\.[^.]*$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "clip";
function importVideo(req, q, res) {
  const json = (code, o) => res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" }).end(JSON.stringify(o));
  if (q.get("job")) return jobs.has(q.get("job")) ? json(200, jobs.get(q.get("job"))) : json(404, { error: "no such job" });
  if (req.method !== "POST" || req.headers["x-lipscan"] !== "1") return json(403, { error: "POST with X-LipScan: 1" });
  const name = String(q.get("name") || "clip.mp4");
  let id = slug(name);
  for (let i = 2; existsSync(join(roots.pack, "live", id)); i++) id = `${slug(name)}-${i}`;
  const folder = join(roots.pack, "live", id);
  mkdirSync(folder, { recursive: true });
  const file = join(folder, "source" + (extname(name).replace(/[^\w.]/g, "") || ".mp4"));
  const job = { id, state: "uploading", step: "Receiving the file", n: 0, of: 0, error: "" };
  jobs.set(id, job);
  const out = createWriteStream(file);
  req.pipe(out);
  const fail = (why) => { job.state = "failed"; job.error = why; };
  req.on("error", () => fail("upload broken"));
  out.on("error", (e) => fail(String(e.message)));
  out.on("finish", () => {
    if (job.state === "failed") return;
    job.state = "working";
    const profile = String(q.get("profile") || "singing-hard").replace(/[^\w.-]/g, "");
    const p = spawn(py, [join(import.meta.dirname, "ingest.py"), file, folder, name.replace(/\.[^.]*$/, ""), "--manifest", join(roots.pack, "demo", "manifest.json"), "--profile", profile],
      { env: { ...process.env, LIPSCAN_REPO: repo, PYTHONIOENCODING: "utf-8" } });
    let buf = "";
    p.stdout.on("data", (c) => {
      buf += c;
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const l of lines) {
        const m = /^STEP (\d+)\/(\d+) (.*)/.exec(l);
        if (m) Object.assign(job, { n: +m[1], of: +m[2], step: m[3] });
        else if (l.startsWith("DONE")) job.state = "done";
        else if (l.startsWith("FAILED")) fail(l.slice(8));
      }
    });
    p.on("close", (code) => { if (job.state === "working") fail(`the pipeline stopped (exit ${code})`); });
  });
  req.on("end", () => json(200, { job: id }));
}
http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/api/import") return importVideo(req, u.searchParams, res);
  if (u.pathname === "/api/gen") return gen(u.searchParams, res);
  if (u.pathname === "/api/lyrics" && (req.method === "POST" || u.searchParams.get("reset"))) return lyrics(req, u.searchParams, res);
  const url = decodeURIComponent(u.pathname);
  const [, first, ...rest] = url.split("/");
  const [root, parts] = first && Object.hasOwn(roots, first) ? [roots[first], rest] : [roots[""], [first, ...rest]];
  const file = normalize(join(root, ...parts.filter(Boolean))) + (url.endsWith("/") || url === "/" ? `${sep}lipscan-viewer.html` : "");
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  try { statSync(file); } catch { res.writeHead(404).end("not found"); return; }
  res.writeHead(200, { "Content-Type": types[extname(file)] || "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(8770, "127.0.0.1", () => console.log("http://127.0.0.1:8770/"));

// Dev only: serves the viewer and local test files on http://127.0.0.1:8770 (this computer only).
//   /           -> dist/
//   /pack/...   -> LIPSCAN_PACKS (character packs)
//   /data/...   -> LIPSCAN_DATA (animations, audio)
//   /api/gen    -> runs the LipScan model again with the sliders' settings (needs Python: LIPSCAN_PY, and the repo: LIPSCAN_REPO)
//        ?mode=voice&wav=/pack/x.wav[&text=..][&words=/pack/x-words.json][&profile=speech][&rig=/pack/c/character.json]&articulation=1&expressiveness=1&coupling=1
//        ?mode=hybrid&folder=/pack/live/clip/ ...the same settings  (a LipScan trace folder: the video's head and brows, the voice's mouth)
import http from "node:http";
import { execFile } from "node:child_process";
import { createReadStream, statSync } from "node:fs";
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
http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/api/gen") return gen(u.searchParams, res);
  const url = decodeURIComponent(u.pathname);
  const [, first, ...rest] = url.split("/");
  const [root, parts] = first && Object.hasOwn(roots, first) ? [roots[first], rest] : [roots[""], [first, ...rest]];
  const file = normalize(join(root, ...parts.filter(Boolean))) + (url.endsWith("/") || url === "/" ? `${sep}lipscan-viewer.html` : "");
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  try { statSync(file); } catch { res.writeHead(404).end("not found"); return; }
  res.writeHead(200, { "Content-Type": types[extname(file)] || "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(8770, "127.0.0.1", () => console.log("http://127.0.0.1:8770/"));

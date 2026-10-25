// Dev only: serves the viewer and local test files on http://127.0.0.1:8770 (this computer only).
//   /           -> dist/
//   /pack/...   -> LIPSCAN_PACKS (character packs)
//   /data/...   -> LIPSCAN_DATA (animations, audio)
import http from "node:http";
import { createReadStream, statSync } from "node:fs";
import { join, normalize, extname, resolve, sep } from "node:path";

const roots = { "": resolve("dist"), pack: resolve(process.env.LIPSCAN_PACKS || "."), data: resolve(process.env.LIPSCAN_DATA || ".") };
const types = { ".html": "text/html", ".json": "application/json", ".glb": "model/gltf-binary", ".wav": "audio/wav", ".js": "text/javascript" };
http.createServer((req, res) => {
  const url = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const [, first, ...rest] = url.split("/");
  const [root, parts] = first in roots && first ? [roots[first], rest] : [roots[""], [first, ...rest]];
  const file = normalize(join(root, ...parts.filter(Boolean))) + (url.endsWith("/") || url === "/" ? `${sep}lipscan-viewer.html` : "");
  if (!file.startsWith(root)) { res.writeHead(403).end(); return; }
  try { statSync(file); } catch { res.writeHead(404).end("not found"); return; }
  res.writeHead(200, { "Content-Type": types[extname(file)] || "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(8770, "127.0.0.1", () => console.log("http://127.0.0.1:8770/"));

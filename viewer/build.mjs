// Bundles src/ into one self-contained HTML file: dist/lipscan-viewer.html (opens offline, no server needed).
import { build } from "esbuild";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";

const out = await build({ entryPoints: ["src/main.js"], bundle: true, minify: true, format: "iife", write: false, legalComments: "eof" });
const js = out.outputFiles[0].text.replace(/<\/script/gi, "<\/script");
const html = readFileSync("src/index.html", "utf8").replace("<!--APP-->", () => `<script>${js}</script>`);
mkdirSync("dist", { recursive: true });
writeFileSync("dist/lipscan-viewer.html", html);
console.log(`dist/lipscan-viewer.html  ${(html.length / 1024).toFixed(0)} KB`);

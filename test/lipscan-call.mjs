// Drive LipScan from a terminal.  node lipscan-call.mjs <tool> '<json args>' [--wait]
// --wait: after lipscan_start, keep polling lipscan_status until the trace is saved, then print the result.
// The code comes from LIPSCAN_CODE, or from the lipscan entry in the Claude desktop config, never printed.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

function findCode() {
  if (process.env.LIPSCAN_CODE) return process.env.LIPSCAN_CODE;
  const configs = [];
  if (process.env.APPDATA) configs.push(join(process.env.APPDATA, "Claude", "claude_desktop_config.json"));
  const cd = process.env.LOCALAPPDATA && join(process.env.LOCALAPPDATA, "Claude-Data"); // the Microsoft Store build
  if (cd && existsSync(cd)) for (const d of readdirSync(cd)) configs.push(join(cd, d, "claude_desktop_config.json"));
  for (const f of configs) {
    try { const t = JSON.parse(readFileSync(f, "utf8")).mcpServers?.lipscan?.env?.LIPSCAN_CODE; if (t) return t; } catch {}
  }
  throw new Error("No code: set LIPSCAN_CODE or add lipscan to the Claude desktop config.");
}

const [tool, rawArgs = "{}", flag] = process.argv.slice(2);
if (!tool) { console.error("usage: node lipscan-call.mjs <tool> '<json args>' [--wait]"); process.exit(2); }
const client = new Client({ name: "lipscan-call", version: "1" });
await client.connect(new StdioClientTransport({
  command: process.execPath, args: [fileURLToPath(new URL("../capture/server/server.js", import.meta.url))],
  env: { ...process.env, LIPSCAN_CODE: findCode() }, stderr: "ignore",
}));
const call = async (name, args = {}) => {
  const r = await client.callTool({ name, arguments: args }, undefined, { timeout: 120000 });
  return { text: r.content.map((c) => c.text).join("\n"), isError: r.isError };
};
// This copy may be the primary (the add-on reconnects to it within ~10 s) or a relay to Claude's copy.
for (let i = 0; i < 30; i++) {
  if (JSON.parse((await call("lipscan_status")).text).connected) break;
  await new Promise((r) => setTimeout(r, 500));
}
let res = await call(tool, JSON.parse(rawArgs));
console.log(res.text);
if (flag === "--wait" && tool === "lipscan_start" && !res.isError) {
  for (;;) {
    await new Promise((r) => setTimeout(r, 2000));
    const s = JSON.parse((await call("lipscan_status")).text);
    if (s.trace && s.trace.running) process.stderr.write(`  recording: ${s.trace.capturedSeconds}/${s.trace.maxSeconds} s, ${s.trace.frames} frames\n`);
    if (s.trace && s.trace.done) { console.log(JSON.stringify(s.trace, null, 2)); break; }
  }
}
await client.close();
process.exit(res.isError ? 1 : 0);

/* LipScan: background page. Keeps a WebSocket to the local LipScan server and runs its commands.
   Login is the same mutual challenge-response as Firefox MCP Connect: the code is never sent, and commands are
   accepted only after the server proves it knows the code. Only YouTube tabs can be traced. */
"use strict";

const DEFAULTS = { token: "", port: 8766, enabled: true };
const ALLOWED_HOSTS = ["youtube.com"]; // and their subdomains

let settings = { ...DEFAULTS };
let ws = null;
let connected = false;
let backoff = 1000;
let reconnectTimer = null;
let lastError = "";
let recordingTab = null; // tab id while a trace runs

// ---------------- badge / status ----------------
function setBadge() {
  let text, color;
  if (!settings.enabled) { text = "OFF"; color = "#808080"; }
  else if (recordingTab !== null) { text = "REC"; color = "#d0021b"; }
  else if (connected) { text = "ON"; color = "#1a9c3a"; }
  else { text = "…"; color = "#c98a00"; }
  browser.browserAction.setBadgeText({ text });
  browser.browserAction.setBadgeBackgroundColor({ color });
  browser.browserAction.setTitle({ title: recordingTab !== null ? "LipScan: RECORDING" : `LipScan: ${text}` });
}

function setRecording(tabId) {
  recordingTab = tabId;
  setBadge();
  browser.runtime.sendMessage({ type: "changed" }).catch(() => {}); // refresh an open popup
}

function status() {
  return { enabled: settings.enabled, connected, port: settings.port, hasToken: !!settings.token, lastError, recording: recordingTab !== null };
}

// ---------------- connection ----------------
function disconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (ws) {
    const s = ws;
    ws = null;
    s.onopen = s.onmessage = s.onclose = s.onerror = null;
    try { s.close(1000, "disabled"); } catch (e) { /* ignore */ }
  }
  connected = false;
  setBadge();
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  if (!settings.enabled) return;
  reconnectTimer = setTimeout(connect, backoff);
  backoff = Math.min(backoff * 2, 10000);
}

function randomHex(bytes) {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function hmacHex(key, text) {
  const enc = new TextEncoder();
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(text));
  return Array.from(new Uint8Array(sig), (b) => b.toString(16).padStart(2, "0")).join("");
}

function connect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (!settings.enabled) { setBadge(); return; }
  if (ws) return;
  if (!settings.token) { lastError = "No connection code."; setBadge(); scheduleReconnect(); return; }
  let s;
  try {
    s = new WebSocket(`ws://127.0.0.1:${settings.port}`);
  } catch (e) {
    lastError = String(e);
    scheduleReconnect();
    return;
  }
  ws = s;
  let authed = false;
  let expectedProof = null;
  s.onmessage = async (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (!authed) {
      if (msg.type === "challenge" && msg.v === 2 && typeof msg.nonce === "string" && /^[0-9a-f]{32,128}$/.test(msg.nonce) && !expectedProof) {
        const cnonce = randomHex(32);
        const token = settings.token;
        expectedProof = await hmacHex(token, `server|${msg.nonce}|${cnonce}`);
        const proof = await hmacHex(token, `client|${msg.nonce}|${cnonce}`);
        if (ws === s) s.send(JSON.stringify({ type: "hello", v: 2, cnonce, proof, configSource: "storage", version: browser.runtime.getManifest().version }));
        return;
      }
      if (msg.type === "welcome" && expectedProof && typeof msg.proof === "string" && msg.proof === expectedProof) {
        authed = true;
        connected = true;
        backoff = 1000;
        lastError = "";
        setBadge();
        return;
      }
      lastError = "Something on the port couldn't prove it knows the connection code.";
      try { s.close(4003); } catch (e) { /* ignore */ }
      return;
    }
    if (msg.id != null && typeof msg.cmd === "string") handleRequest(s, msg);
  };
  s.onclose = (ev) => {
    if (ws !== s) return;
    ws = null;
    connected = false;
    if (ev.code === 4003 && !lastError.startsWith("Something on the port")) lastError = "The server didn't accept the connection code. Copy it again and give it to Claude.";
    setBadge();
    scheduleReconnect();
  };
  s.onerror = () => { /* failed connects are normal while Claude is closed */ };
}

function newConnectionCode() {
  return randomHex(32);
}

async function loadSettings() {
  let st = await browser.storage.local.get(["token", "port", "enabled"]);
  if (!st.token) {
    await browser.storage.local.set({ token: newConnectionCode() }); // first run
    st = await browser.storage.local.get(["token", "port", "enabled"]);
  }
  settings = {
    token: st.token || "",
    port: parseInt(st.port, 10) || DEFAULTS.port,
    enabled: st.enabled !== undefined ? !!st.enabled : DEFAULTS.enabled,
  };
}

browser.storage.onChanged.addListener(async (changes, area) => {
  if (area !== "local") return;
  if (!("token" in changes || "port" in changes || "enabled" in changes)) return;
  await loadSettings();
  disconnect();
  backoff = 1000;
  if (!settings.enabled) await stopRecording(); // the kill switch also ends a running trace
  if (settings.enabled) connect();
});

// ---------------- tabs ----------------
function allowedUrl(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.protocol !== "http:") return false;
    const h = u.hostname.toLowerCase();
    return ALLOWED_HOSTS.some((d) => h === d || h.endsWith(`.${d}`));
  } catch (e) { return false; }
}

async function youtubeTab(tabId) {
  let tab;
  if (tabId != null) tab = await browser.tabs.get(tabId);
  else [tab] = await browser.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("No active tab found.");
  // Without the "tabs" permission Firefox only reveals the address of tabs on allowed sites.
  if (!tab.url || !allowedUrl(tab.url)) throw new Error("That tab isn't on YouTube. LipScan only records YouTube videos.");
  return tab;
}

async function page(tabId, cmd, args) {
  const tab = await youtubeTab(tabId);
  const [loaded] = await browser.tabs.executeScript(tab.id, { code: "!!window.__lipscanLoaded", runAt: "document_start" })
    .catch((e) => { throw new Error(`Cannot access this page: ${e.message}`); });
  if (!loaded) await browser.tabs.executeScript(tab.id, { file: "capture.js", runAt: "document_idle" });
  const res = await browser.tabs.sendMessage(tab.id, { __lipscan: true, cmd, args }, { frameId: 0 });
  if (!res) throw new Error("No response from the page.");
  if (!res.ok) throw new Error(res.error);
  return { tab, result: res.result };
}

async function stopRecording() {
  if (recordingTab === null) return;
  const id = recordingTab;
  await page(id, "end", {}).catch(() => {});
  setRecording(null);
}

browser.tabs.onRemoved.addListener((id) => { if (id === recordingTab) setRecording(null); });

// ---------------- commands from the server ----------------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const commands = {
  async tab_info({ tabId }) {
    const tab = await youtubeTab(tabId);
    return { tabId: tab.id, url: tab.url, title: tab.title };
  },

  // Video frames are only painted while the tab is showing, so tracing brings its tab to the front first.
  async trace_begin(args) {
    if (recordingTab !== null) throw new Error("A trace is already running.");
    let tab = await youtubeTab(args.tabId);
    if (!tab.active) {
      tab = await browser.tabs.update(tab.id, { active: true });
      await browser.windows.update(tab.windowId, { focused: true }).catch(() => {});
      await sleep(350);
    }
    const { result } = await page(tab.id, "begin", args);
    setRecording(tab.id);
    return { ...result, tabId: tab.id };
  },

  async trace_pull({ tabId }) {
    const { result } = await page(tabId, "pull", {});
    if (!result.state.active && recordingTab === tabId) setRecording(null);
    return result;
  },

  async trace_end({ tabId }) {
    const { result } = await page(tabId, "end", {});
    return result; // the badge clears on the pull that collects the last frames
  },

  async trace_captions({ tabId }) {
    return (await page(tabId, "captions", {})).result;
  },
};

async function handleRequest(sock, msg) {
  const { id, cmd, args = {} } = msg;
  try {
    const fn = Object.hasOwn(commands, cmd) ? commands[cmd] : null;
    if (!fn) throw new Error(`Unknown command: ${cmd}`);
    const result = await fn(args);
    if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ id, ok: true, result }));
  } catch (e) {
    if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ id, ok: false, error: (e && e.message) || String(e) }));
  }
}

// ---------------- popup messaging ----------------
browser.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "status") return Promise.resolve(status());
  if (msg && msg.type === "token") return Promise.resolve({ token: settings.token });
  if (msg && msg.type === "new-code") {
    const token = newConnectionCode();
    return browser.storage.local.set({ token }).then(() => ({ token }));
  }
  if (msg && msg.type === "stop") return stopRecording().then(() => status());
  return undefined;
});

// ---------------- start ----------------
(async () => {
  await loadSettings();
  setBadge();
  connect();
})();

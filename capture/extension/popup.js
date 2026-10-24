"use strict";
const $ = (id) => document.getElementById(id);

async function refresh() {
  const s = await browser.runtime.sendMessage({ type: "status" });
  $("enabled").checked = s.enabled;
  $("rec").style.display = s.recording ? "block" : "none";
  $("state").textContent = !s.enabled ? "Off."
    : s.connected ? `Connected to Claude (port ${s.port}).`
    : `Not connected. ${s.lastError || "Claude may be closed."}`;
}

$("enabled").addEventListener("change", async (e) => {
  await browser.storage.local.set({ enabled: e.target.checked });
  setTimeout(refresh, 300);
});
$("copy").addEventListener("click", async () => {
  const { token } = await browser.runtime.sendMessage({ type: "token" });
  await navigator.clipboard.writeText(token);
  $("msg").textContent = "Copied. Paste it to Claude Code.";
});
$("new").addEventListener("click", async () => {
  if (!confirm("Make a new code? Claude will need the new one before it can connect again.")) return;
  await browser.runtime.sendMessage({ type: "new-code" });
  $("msg").textContent = "New code made. Copy it and give it to Claude Code.";
  setTimeout(refresh, 300);
});
$("stop").addEventListener("click", async () => {
  await browser.runtime.sendMessage({ type: "stop" });
  refresh();
});
browser.runtime.onMessage.addListener((m) => { if (m && m.type === "changed") refresh(); });
refresh();

/* LipScan: content script, injected into a YouTube tab only when a trace starts. */
(() => {
  "use strict";
  if (window.__lipscanLoaded) return;
  window.__lipscanLoaded = true;

  // Records what the page's main <video> shows and plays: small JPEG frames and mono audio, both stamped with the
  // video's own clock (media time), so seeks, pauses and ads can't misalign them. Only that video element is read.
  // Live camera and call video (a MediaStream source) is refused.
  const MAX_WAITING_FRAMES = 2400; // frames not yet collected by the server; past this the trace stops
  const audioRoutes = new WeakMap(); // video -> { ctx, src }. A video can be routed into Web Audio only once.
  let trace = null;

  function mainVideo() {
    let best = null;
    let area = 0;
    for (const v of document.querySelectorAll("video")) {
      const r = v.getBoundingClientRect();
      if (v.readyState >= 2 && r.width * r.height > area) { best = v; area = r.width * r.height; }
    }
    return best;
  }

  const adShowing = () => !!document.querySelector(".ad-showing, .ad-interrupting"); // YouTube marks its player during ads

  async function audioRoute(video) {
    let route = audioRoutes.get(video);
    if (route) return route;
    const ctx = new AudioContext();
    await ctx.resume().catch(() => {});
    if (ctx.state !== "running") {
      ctx.close();
      throw new Error("Firefox hasn't let this page play sound yet. Ask the user to click the video once, then try again.");
    }
    const src = ctx.createMediaElementSource(video);
    src.connect(ctx.destination); // keeps the video audible, now and after the trace
    route = { ctx, src };
    audioRoutes.set(video, route);
    return route;
  }

  // An AudioWorklet stamps each block with its exact audio frame. If the page blocks the worklet, a ScriptProcessor
  // is used instead; its timing is only good to about one block (21 ms), and the trace says which one ran.
  async function audioTap(route, onBlock) {
    const { ctx, src } = route;
    try {
      await ctx.audioWorklet.addModule(browser.runtime.getURL("trace-worklet.js"));
      const node = new AudioWorkletNode(ctx, "lipscan-tap", { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1, channelCountMode: "explicit" });
      node.port.onmessage = (e) => onBlock(e.data.frame, e.data.data);
      src.connect(node);
      return { kind: "worklet", stop: () => { src.disconnect(node); node.port.onmessage = null; } };
    } catch (e) { /* fall back below */ }
    const size = 1024;
    const node = ctx.createScriptProcessor(size, 1, 1);
    const sink = ctx.createGain();
    sink.gain.value = 0;
    node.onaudioprocess = (e) => onBlock(Math.round((e.playbackTime - size / ctx.sampleRate) * ctx.sampleRate), e.inputBuffer.getChannelData(0).slice());
    src.connect(node);
    node.connect(sink);
    sink.connect(ctx.destination);
    return { kind: "scriptprocessor", stop: () => { src.disconnect(node); node.disconnect(); sink.disconnect(); node.onaudioprocess = null; } };
  }

  function int16Base64(f32) {
    const i16 = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) i16[i] = Math.max(-32768, Math.min(32767, Math.round(f32[i] * 32767)));
    const bytes = new Uint8Array(i16.buffer);
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  }

  function blobBase64(blob) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1]);
      r.onerror = () => reject(r.error);
      r.readAsDataURL(blob);
    });
  }

  function endTrace(t, reason) {
    if (!t.active) return;
    t.active = false;
    t.reason = reason;
    try { t.tap.stop(); } catch (e) { /* ignore */ }
    for (const [ev, fn] of t.listeners) t.video.removeEventListener(ev, fn);
  }

  async function begin({ seconds = 30, fps = 30, frameWidth = 640, startAt }) {
    if (trace && trace.active) throw new Error("A trace is already running in this tab.");
    const video = mainVideo();
    if (!video) throw new Error("No loaded video found on this page.");
    if (video.srcObject) throw new Error("This video is a live camera or call stream; those can't be traced.");
    const w = Math.max(2, Math.min(Math.round(frameWidth), video.videoWidth || frameWidth)) & ~1;
    const h = Math.max(2, Math.round((w * (video.videoHeight || 9)) / (video.videoWidth || 16))) & ~1;
    const canvas = document.createElement("canvas"); // never attached to the page
    canvas.width = w;
    canvas.height = h;
    const g = canvas.getContext("2d");
    try { g.drawImage(video, 0, 0, w, h); g.getImageData(0, 0, 1, 1); } catch (e) {
      throw new Error("This video's frames can't be read (it comes from another site without permission).");
    }
    const route = await audioRoute(video);
    const ctx = route.ctx;
    const minGap = 1 / Math.min(30, Math.max(1, fps)) - 0.004; // a little slack so 30 fps video isn't thinned

    const t = {
      active: true, reason: "", video, seconds, w, h, frames: [], audio: [], dropped: 0, adFrames: 0, seeks: 0,
      captured: 0, lastMedia: null, lastSaved: null, clock: null, seekGen: 0, prev: null, listeners: [],
      rate: ctx.sampleRate, title: document.title, url: location.href, tap: { kind: "none", stop() {} },
    };
    trace = t;
    const on = (ev, fn) => { video.addEventListener(ev, fn); t.listeners.push([ev, fn]); };
    on("seeking", () => { t.clock = null; t.prev = null; t.lastMedia = null; t.lastSaved = null; t.seekGen++; t.seeks++; });
    on("ended", () => endTrace(t, "video ended"));
    on("emptied", () => endTrace(t, "the video was replaced"));

    // Audio: map each block's audio frame to the moment it is heard, then to media time through the latest video frame.
    t.tap = await audioTap(route, (frame, data) => {
      if (!t.active || video.paused || video.seeking || adShowing() || !t.clock) return;
      const ts = ctx.getOutputTimestamp();
      const heard = ts.performanceTime + (frame / ctx.sampleRate - ts.contextTime) * 1000;
      let media = t.clock.media + ((heard - t.clock.shown) / 1000) * video.playbackRate;
      const p = t.prev;
      if (p && p.gen === t.seekGen && frame === p.frame + p.len) {
        const expected = p.media + (p.len / ctx.sampleRate) * video.playbackRate;
        if (Math.abs(expected - media) < 0.02) media = expected; // keep blocks seamless; re-anchor only on real drift
      }
      t.prev = { frame, len: data.length, media, gen: t.seekGen };
      t.audio.push({ t: media, pcm: int16Base64(data) });
    });

    // Frames: every new video frame updates the clock; up to fps of them per second are saved as JPEGs.
    const onFrame = (now, meta) => {
      if (!t.active) return;
      const media = meta ? meta.mediaTime : video.currentTime;
      const shown = meta ? meta.expectedDisplayTime : now;
      if (!video.paused && !video.seeking) {
        if (adShowing()) t.adFrames++;
        else if (t.lastMedia === null || media > t.lastMedia) {
          t.clock = { media, shown };
          if (t.lastMedia !== null) t.captured += Math.min(media - t.lastMedia, 0.25);
          t.lastMedia = media;
          if (t.lastSaved === null || media - t.lastSaved >= minGap) {
            t.lastSaved = media;
            g.drawImage(video, 0, 0, w, h);
            canvas.toBlob((blob) => { if (blob) t.frames.push({ t: media, blob }); else t.dropped++; }, "image/jpeg", 0.85);
          }
          if (t.captured >= t.seconds) endTrace(t, "reached the requested length");
          if (t.frames.length > MAX_WAITING_FRAMES) endTrace(t, "too many frames waiting to be collected");
        }
      }
      if (t.active) next();
    };
    const next = () => (video.requestVideoFrameCallback ? video.requestVideoFrameCallback(onFrame) : requestAnimationFrame((now) => onFrame(now, null)));
    next();

    if (typeof startAt === "number") video.currentTime = startAt;
    if (video.paused) {
      try { await video.play(); } catch (e) {
        endTrace(t, "Firefox blocked playback");
        throw new Error("Firefox blocked playback. Ask the user to press play, then try again.");
      }
    }
    return {
      width: w, height: h, audioRate: t.rate, audioClock: t.tap.kind,
      frameClock: video.requestVideoFrameCallback ? "video frame callback" : "animation frame (approximate)",
      title: t.title, url: t.url,
    };
  }

  async function pull() {
    const t = trace;
    if (!t) throw new Error("No trace in this tab.");
    const frames = t.frames.splice(0);
    const audio = t.audio.splice(0);
    const out = [];
    for (const f of frames) out.push({ t: f.t, jpeg: await blobBase64(f.blob) });
    return {
      frames: out, audio, audioRate: t.rate,
      state: {
        active: t.active, reason: t.reason, capturedSeconds: Math.round(t.captured * 100) / 100,
        mediaTime: t.video.currentTime, paused: t.video.paused, ad: adShowing(), adFramesSkipped: t.adFrames,
        droppedFrames: t.dropped, seeks: t.seeks,
      },
    };
  }

  function end() {
    if (!trace) return { stopped: false };
    endTrace(trace, trace.reason || "stopped");
    return { stopped: true, reason: trace.reason };
  }

  // Captions, when YouTube offers them. Automatic captions carry a time for every word.
  async function captions({ lang = "en" }) {
    const player = document.getElementById("movie_player");
    const page = player && player.wrappedJSObject;
    const resp = page && typeof page.getPlayerResponse === "function" ? page.getPlayerResponse() : null;
    const list = resp && resp.captions && resp.captions.playerCaptionsTracklistRenderer;
    const tracks = list && list.captionTracks ? Array.from(list.captionTracks) : [];
    if (!tracks.length) return { tracks: [], events: [], note: "This video has no captions." };
    const info = tracks.map((tr) => ({
      lang: String(tr.languageCode), kind: tr.kind === "asr" ? "automatic" : "uploaded",
      name: String((tr.name && (tr.name.simpleText || (tr.name.runs && tr.name.runs[0] && tr.name.runs[0].text))) || ""),
    }));
    const pick = (want) => info.findIndex((tr) => tr.lang.startsWith(lang) && tr.kind === want);
    let i = pick("uploaded");
    if (i < 0) i = pick("automatic");
    if (i < 0) i = 0;
    const url = new URL(String(tracks[i].baseUrl), location.href);
    if (url.hostname !== location.hostname) throw new Error("Unexpected caption address.");
    url.searchParams.set("fmt", "json3");
    const res = await fetch(url.href, { credentials: "include" });
    const body = res.ok ? await res.text() : "";
    if (!body) return { tracks: info, chosen: info[i], events: [], note: `YouTube returned no caption data (HTTP ${res.status}). Turn captions on in the player (press c) and try again.` };
    const data = JSON.parse(body);
    const events = [];
    for (const ev of data.events || []) {
      if (!ev.segs) continue;
      const start = (ev.tStartMs || 0) / 1000;
      const words = ev.segs.map((s) => ({ t: start + (s.tOffsetMs || 0) / 1000, text: String(s.utf8 || "") })).filter((w) => w.text.trim());
      if (!words.length) continue;
      events.push({
        start, dur: (ev.dDurationMs || 0) / 1000,
        text: words.map((w) => w.text).join("").replace(/\s+/g, " ").trim(),
        words: words.map((w) => ({ t: w.t, text: w.text.trim() })),
      });
    }
    return { tracks: info, chosen: info[i], events };
  }

  const handlers = { begin, pull, end, captions };

  browser.runtime.onMessage.addListener((msg) => {
    if (!msg || !msg.__lipscan) return undefined;
    const fn = Object.hasOwn(handlers, msg.cmd) ? handlers[msg.cmd] : null;
    return (async () => {
      if (!fn) throw new Error(`Unknown page command ${msg.cmd}`);
      return { ok: true, result: await fn(msg.args || {}) };
    })().catch((e) => ({ ok: false, error: (e && e.message) || String(e) }));
  });
})();

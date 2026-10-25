// Animation sources the viewer plays:
//   - WolvenKit .anims glTF exports (.glb): every clip's animations[].extras.trackKeys / constTrackKeys
//     ({trackIndex, time, value}); "Additive..." clips add onto the rig's reference track values.
//   - LipScan curve files (.json): {fps, tracks: {trackName: [value per frame]}} with raw or "...LipsyncPoseOutput" names,
//     optionally "head": {yaw, pitch, roll: [degrees per frame]} and, from a video trace, nulls where no face was seen
//     and "video": {start, trace}.
// Each becomes a list of clips: {name, duration, additive, sample(t, out)}.

function glbJson(buf) {
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== 0x46546c67) throw new Error("Not a .glb file.");
  const len = dv.getUint32(12, true);
  return JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, len)));
}

function lerpKeys(times, values, t) {
  const n = times.length;
  if (n === 0) return 0;
  if (t <= times[0]) return values[0];
  if (t >= times[n - 1]) return values[n - 1];
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid; else hi = mid;
  }
  const f = (t - times[lo]) / (times[hi] - times[lo] || 1);
  return values[lo] + (values[hi] - values[lo]) * f;
}

function clipFromKeys(name, extras, trackCount) {
  const per = new Map();
  let duration = 0;
  for (const k of extras.trackKeys || []) {
    if (!per.has(k.trackIndex)) per.set(k.trackIndex, []);
    per.get(k.trackIndex).push(k);
    duration = Math.max(duration, k.time);
  }
  const consts = new Map();
  for (const k of extras.constTrackKeys || []) { consts.set(k.trackIndex, k.value); duration = Math.max(duration, k.time); }
  const tracks = [...per.entries()].map(([i, ks]) => {
    ks.sort((a, b) => a.time - b.time);
    return [i, Float32Array.from(ks, (k) => k.time), Float32Array.from(ks, (k) => k.value)];
  });
  return {
    name, duration, kind: "game", additive: /additive/i.test(extras.animationType || ""), animatedTracks: tracks.length,
    sample(t, out) {
      out.fill(0);
      for (const [i, v] of consts) if (i < trackCount) out[i] = v;
      for (const [i, ts, vs] of tracks) if (i < trackCount) out[i] = lerpKeys(ts, vs, t);
    },
  };
}

export async function loadAnimation(file, solver) {
  const name = file.name;
  const buf = await file.arrayBuffer();
  const n = solver.tracks.length;
  if (/\.glb$/i.test(name)) {
    const j = glbJson(buf);
    const clips = (j.animations || []).filter((a) => a.extras && (a.extras.trackKeys || a.extras.constTrackKeys))
      .map((a, k) => clipFromKeys(a.name || `clip ${k + 1}`, a.extras, n));
    if (!clips.length) throw new Error(`${name} has no face-track animation (is it a WolvenKit .anims export?).`);
    return { source: name, clips };
  }
  const j = JSON.parse(new TextDecoder().decode(buf));
  if (!j.tracks || !j.fps) throw new Error(`${name} isn't a LipScan curve file (needs "fps" and "tracks").`);
  const map = [];
  const unknown = [];
  // null = no face seen in that frame (from a video trace): drawn as rest, and marked on the timeline
  const arr = (values) => Float32Array.from(values, (x) => (x === null ? NaN : x));
  for (const [track, values] of Object.entries(j.tracks)) {
    const i = solver.trackIndex.get(track);
    if (i === undefined) unknown.push(track); else map.push([i, arr(values)]);
  }
  if (!map.length) throw new Error(`None of ${name}'s track names exist on this face rig (ARKit exports can't drive it; use raw or cyberpunk).`);
  const frames = Math.max(...map.map(([, v]) => v.length));
  const head = j.head && Object.keys(j.head).length ? Object.fromEntries(Object.entries(j.head).map(([k, v]) => [k, arr(v)])) : null;
  const at = (v, a, w) => {
    const x0 = v[Math.min(v.length - 1, Math.max(0, a))];
    const x1 = v[Math.min(v.length - 1, Math.max(0, a + 1))];
    if (Number.isNaN(x0) || Number.isNaN(x1)) return NaN;
    return x0 + (x1 - x0) * w;
  };
  const probe = map.find(([i]) => solver.tracks[i].startsWith("jaw_mid_open"));
  return {
    source: name,
    unknown,
    clips: [{
      name: j.profile ? `${name} (${j.profile})` : name, duration: frames / j.fps, kind: "lipscan", additive: false, animatedTracks: map.length,
      video: j.video || null, headSplit: j.head_split || null, hasHead: !!head,
      sample(t, out) {
        out.fill(0);
        const f = t * j.fps;
        const a = Math.floor(f);
        const w = f - a;
        for (const [i, v] of map) {
          const x = at(v, a, w);
          out[i] = Number.isNaN(x) ? 0 : x;
        }
      },
      head(t) {
        if (!head) return null;
        const f = t * j.fps;
        const a = Math.floor(f);
        const r = {};
        for (const [k, v] of Object.entries(head)) { const x = at(v, a, f - a); r[k] = Number.isNaN(x) ? 0 : x; }
        return r;
      },
      // true where the trace saw no face
      gap(t) {
        if (!probe) return false;
        const a = Math.round(t * j.fps);
        return Number.isNaN(probe[1][Math.min(probe[1].length - 1, Math.max(0, a))]);
      },
    }],
  };
}

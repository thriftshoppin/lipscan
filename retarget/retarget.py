"""
LipScan retarget: a recorded performance (performance.json) -> face-rig curves a viewer or game can play.

    python retarget.py "<trace folder>"                          # writes <trace>/retarget-cyberpunk.json
    python retarget.py "<trace folder>" --export cyberpunk       # game dialogue-layer names ("...LipsyncPoseOutput")
    python retarget.py "<trace folder>" --export arkit52         # the cleaned MediaPipe values under ARKit names
    python retarget.py "<trace folder>" --mapping my-mapping.json --no-tongue --out x.json

The mapping (export/mediapipe_to_cyberpunk.json by default) says which face tracks each MediaPipe blendshape drives,
with a gain, offset and clamp. Head pose goes into "head" (degrees) and gaze into the eye-direction tracks.
Video tracking can't see the tongue, so by default the tongue tracks come from the audio model (model/lipsync.py)
run on the trace's own audio and caption words.

Output: {"fps": 30, "tracks": {name: [value per frame, null where no face was seen]}, "head": {"yaw", "pitch",
"roll": [...]}, "video": {...}} on the trace's clock (frame 0 = trace start), so the trace's audio.wav lines up.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "analyze"))
DEFAULT_MAPPING = os.path.join(ROOT, "export", "mediapipe_to_cyberpunk.json")
FPS = 30


def load_mapping(path=DEFAULT_MAPPING):
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    if m.get("format") != "lipscan-mapping/1":
        raise SystemExit(f"{path} isn't a LipScan mapping (format lipscan-mapping/1).")
    return m


def resample(times, col, n, longest=0.2):
    """Values at frame k / FPS. Spans between samples longer than `longest` (or outside them) stay NaN."""
    grid = np.arange(n) / FPS
    good = ~np.isnan(col)
    if good.sum() < 2:
        return np.full(n, np.nan)
    t, v = times[good], col[good]
    out = np.interp(grid, t, v)
    idx = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
    out[(t[idx] - t[idx - 1]) > longest + 1e-9] = np.nan
    out[(grid < t[0] - 1e-9) | (grid > t[-1] + 1e-9)] = np.nan
    return out


def apply_mapping(channels, mapping):
    """channels: {MediaPipe name: array}. Returns ({track: array}, unused sources)."""
    tracks, unused = {}, []
    for src, targets in mapping["map"].items():
        x = channels.get(src)
        if x is None:
            unused.append(src)
            continue
        for e in targets:
            lo, hi = e.get("clamp", [0, 1])
            y = np.clip(e.get("gain", 1.0) * x + e.get("offset", 0.0), lo, hi)
            cur = tracks.get(e["track"])
            # largest wins; NaN (no face) stays NaN
            tracks[e["track"]] = y if cur is None else np.where(np.isnan(cur), y, np.fmax(cur, y))
    return tracks, unused


def head_curves(channels, mapping):
    h = mapping.get("head", {})
    gain, limit = h.get("gain", {}), h.get("limit_deg", {})
    out = {}
    for k, name in (("yaw", "headYaw"), ("pitch", "headPitch"), ("roll", "headRoll")):
        x = channels.get(name)
        if x is not None:
            lim = limit.get(k, 90)
            out[k] = np.clip(x * gain.get(k, 1.0), -lim, lim)
    return out


# Tracks that speech drives (jaw, lip shapes, tongue, neck). A hybrid takes these from the voice model, because a
# small or turned face in a video gives a weak mouth reading (jaw ~2x too small, correlation with the voice 0.3-0.4,
# against 0.9+ for the voice model), and everything else (head, brows, eyes, blinks, gaze, cheeks, nose, smiles and
# frowns) from the video, which the voice can't know.
SPEECH_PREFIXES = ("tongue_", "neck_throat", "neck_tighten", "neck_l_platysma", "neck_r_platysma", "neck_l_stern", "neck_r_stern")
SPEECH_LIPS = ("together", "purse", "funnel", "suck", "lower_raise", "stretch", "pull", "chin_raise", "apart", "tighten",
               "upper_raise", "corner_stretch")


def is_speech_track(name):
    if name == "jaw_mid_open" or name.startswith(SPEECH_PREFIXES):
        return True
    return name.startswith("lips_") and any(k in name for k in SPEECH_LIPS)


def audio_tracks(folder, trace, n, profile="speech", **dials):
    """All of the voice model's tracks for the trace's own audio (caption words when there are any), on the trace's clock.
    dials: articulation, expressiveness (the model's own); the coupling is added afterwards, on the merged mouth."""
    import lipsync
    from analyze import caption_words
    audio = trace.get("audio")
    if not audio:
        return {}, 0
    words, _ = caption_words(folder, trace["start"], n / FPS)
    res = lipsync.simulate_lipsync(os.path.join(folder, audio["file"]), profile=profile, words=words or None, coupling=0, **dials)
    shift = round((audio.get("start", trace["start"]) - trace["start"]) * FPS)   # audio may start after the trace
    out = {}
    for k, v in res["tracks"].items():
        a = np.zeros(n)
        v = np.array(v[:max(0, n - shift)])
        a[shift:shift + len(v)] = v
        out[k] = a
    return out, len(words)


def mouth_size(jaw, window_s=0.6, floor=0.3):
    """How big his mouth movement really is, moment to moment, from the video's jaw: a slow envelope (the largest opening
    within +-window_s/2), relative to the clip's own 95th percentile, so a mumbler and a shouter both map onto the
    game's range. 1 = as wide as this clip gets; `floor` keeps a little syllable motion where the mouth barely opens.
    1 where the video has no face."""
    n = len(jaw)
    ok = ~np.isnan(jaw)
    if ok.sum() < 10:
        return np.ones(n)
    j = np.where(ok, jaw, 0.0)
    half = max(1, int(window_s * FPS / 2))
    env = np.array([j[max(0, i - half):i + half + 1].max() for i in range(n)])
    k = np.exp(-0.5 * (np.arange(-half, half + 1) / (half / 2)) ** 2)
    env = np.convolve(np.pad(env, half, mode="edge"), k / k.sum(), mode="valid")[:n]
    ref = max(1e-3, float(np.percentile(env[ok], 95)))
    return np.where(ok, np.clip(env / ref, floor, 1.0), 1.0)


def rig_presence(path):
    if not path:
        return 1.0
    sys.path.insert(0, os.path.join(ROOT, "model"))
    import coupling
    return coupling.rig_presence(path)


def add_coupling(tracks, n, strength, presence):
    """The cheeks, lip puff, nose and chin follow the mouth and jaw (model/coupling.py), on whatever mouth the tracks now have,
    whether it came from the voice or the video. Frames with no face stay empty."""
    if not strength or strength <= 0:
        return tracks
    sys.path.insert(0, os.path.join(ROOT, "model"))
    import coupling
    work = {k: np.nan_to_num(v).tolist() for k, v in tracks.items()}
    before = {k: list(v) for k, v in work.items()}
    coupling.couple(work, n, strength, presence)
    for k, v in work.items():
        new = np.array(v, dtype=float)
        if k not in tracks:
            tracks[k] = new
        elif list(v) != before.get(k):
            old = tracks[k]
            merged = np.fmax(old, new)
            tracks[k] = np.where(np.isnan(old) & (new == 0), np.nan, merged)
    return tracks


VIDEO_PURSE_MIN = 0.03       # below this (95th percentile) the video shows no pucker at all in this clip: the voice's stays
VIDEO_PURSE_TARGET = 0.15    # a small face reads pucker weakly (0.06 where the true value was 0.32, correlation still 0.69): lift it to this
VIDEO_PURSE_GAIN_MAX = 4.0
FORWARD_MAX = 0.6            # purse + funnel together; the most the game ever uses (model/lipsync.py LIP_FORWARD_MAX)


def forward_from_video(video, out):
    """Lips pushed forward (purse, funnel). The video reads the pucker well (a clip's mouthPucker reaches 0.3-0.9), while
    the voice only knows which sounds are rounded, and was scaled down by the mouth size besides, so the hybrid kept about
    a fifth of the video's pucker. Where the video reads pucker in this clip, it sets the purse wherever the face is seen
    (the voice's carries on in the gaps); a weak reading (a small face) is lifted toward VIDEO_PURSE_TARGET, a strong one is kept as it is. MediaPipe's funnel is nearly always 0 (95th percentile 0.01 here), so the funnel
    keeps the larger of the two. Purse + funnel stay within what the game uses."""
    for side in "lr":
        key = f"lips_{side}_purse"
        vp = video.get(key)
        if vp is not None:
            seen = ~np.isnan(vp)
            p95 = np.percentile(vp[seen], 95) if seen.sum() >= 10 else 0.0
            if p95 >= VIDEO_PURSE_MIN:
                gain = min(VIDEO_PURSE_GAIN_MAX, max(1.0, VIDEO_PURSE_TARGET / p95))
                out[key] = np.where(seen, np.minimum(1.0, vp * gain), out.get(key, np.zeros_like(vp)))
        key = f"lips_{side}_funnel"
        vf = video.get(key)
        if vf is not None and key in out:
            out[key] = np.fmax(out[key], np.nan_to_num(vf))
        pu, fu = out.get(f"lips_{side}_purse"), out.get(f"lips_{side}_funnel")
        if pu is not None and fu is not None:
            tot = np.nan_to_num(pu) + fu
            k = np.where(tot > FORWARD_MAX, FORWARD_MAX / np.maximum(tot, 1e-9), 1.0)
            out[f"lips_{side}_purse"], out[f"lips_{side}_funnel"] = pu * k, fu * k
    return out


VIDEO_MOUTH_TRUST = 0.3      # the video's jaw (95th percentile) must reach this, a rig-sized reading, before the mouth is led by the video
VIDEO_LED = ("jaw_mid_open", "lips_apart_dn", "lips_l_upper_raise", "lips_r_upper_raise", "lips_chin_raise")


def video_mouth_trusted(jaw):
    """True when the video reads the mouth at the rig's scale (a close, front-on face): the jaw's 95th percentile is at least
    VIDEO_MOUTH_TRUST (the game's speech is 0.35, its singing 0.8; the small, turned face in the first test clip read 0.16)."""
    ok = ~np.isnan(jaw)
    return bool(ok.sum() >= 30 and np.percentile(jaw[ok], 95) >= VIDEO_MOUTH_TRUST)


def lead_mouth_from_video(video, out, follow):
    """Lip separation. The voice only knows how loud the voice is, and its lips ride on its jaw (the singing profile opens the
    upper lip 1.3 times the jaw); a lip gap measured on the video is explained 0.96 by the jaw, the lower lip's drop and its roll
    (about 0.18 jaw + 0.16 drop - 0.18 roll), and in a tenth of the frames the lips were visibly apart with the jaw nearly
    shut, which only the drop shows. So with a trusted video the jaw, the lower lip's drop (apart_dn), the upper lip and the chin
    come from the video wherever the face is seen, and the tracks that ride on the jaw (follow_jaw, which have no video source)
    ride on the video's jaw instead of the voice's. The voice still places closures, the tongue and the neck."""
    vj = video.get("jaw_mid_open")
    if vj is None:
        return out
    seen = ~np.isnan(vj)
    for k in VIDEO_LED:
        v = video.get(k)
        if v is not None:
            out[k] = np.where(~np.isnan(v), v, out.get(k, np.zeros_like(v)))
    jaw = np.nan_to_num(out["jaw_mid_open"])
    for name, gain in (follow or {}).items():
        if name in video and name in VIDEO_LED or name.startswith(("lips_l_corner", "lips_r_corner")):
            continue                                             # the video has its own (or, for the corners, the smile comes from it)
        out[name] = np.where(seen, np.clip(gain * jaw, 0.0, 1.0), out.get(name, np.zeros_like(vj)))
    return out


def hybrid_tracks(video, voice, size=None, led=False, follow=None):
    """video, voice: {track: array}. Speech tracks come from the voice; the jaw also takes the video where the video
    shows the mouth open further than the voice suggests; every other track comes from the video. No face in a frame:
    the video-sourced tracks are empty there, the voice-sourced ones carry on."""
    out = {}
    for k, v in voice.items():
        if is_speech_track(k):
            # the voice sets WHEN the mouth moves; the video sets HOW MUCH (closures and the tongue keep their size)
            sized = size is not None and (k == "jaw_mid_open" or (k.startswith("lips_") and "together" not in k))
            out[k] = v * size if sized else v.copy()
    for k, v in video.items():
        if is_speech_track(k):
            if k == "jaw_mid_open":
                out[k] = np.fmax(out.get(k, np.zeros_like(v)), np.nan_to_num(v))
        else:
            out[k] = v
    if led:
        out = lead_mouth_from_video(video, out, follow)
    return forward_from_video(video, out)


def tongue_from_audio(folder, trace, n):
    """The audio model's tongue tracks for the trace's own audio (with caption words when there are any)."""
    import lipsync
    from analyze import caption_words
    audio = trace.get("audio")
    if not audio:
        return {}
    words, _ = caption_words(folder, trace["start"], n / FPS)
    res = lipsync.simulate_lipsync(os.path.join(folder, audio["file"]), profile="speech", words=words or None)
    shift = round((audio.get("start", trace["start"]) - trace["start"]) * FPS)   # audio may start after the trace
    out = {}
    for k, v in res["tracks"].items():
        if k.startswith("tongue_"):
            a = np.zeros(n)
            v = np.array(v[:max(0, n - shift)])
            a[shift:shift + len(v)] = v
            out[k] = a
    return out


def jl(a, nd=4):
    return [None if (isinstance(x, float) and math.isnan(x)) or (hasattr(x, "dtype") and np.isnan(x)) else round(float(x), nd) for x in a]


def retarget(folder, mapping_path=DEFAULT_MAPPING, export="raw", tongue=True, hybrid=True, size=True, mouth_from="auto",
             articulation=None, expressiveness=None, coupling=1.0, jaw_presence=1.0, profile="speech"):
    folder = os.path.abspath(folder)
    perf = json.load(open(os.path.join(folder, "performance.json"), encoding="utf-8"))
    if perf.get("format") != "lipscan-performance/1":
        raise SystemExit("performance.json has an unknown format; run analyze/performance.py again.")
    trace = json.load(open(os.path.join(folder, "trace.json"), encoding="utf-8"))
    times = np.array(perf["t"], dtype=float)
    n = int(math.floor(times[-1] * FPS)) + 1 if len(times) else 0
    if trace.get("audio"):
        n = max(n, int(round((trace["audio"].get("start", trace["start"]) - trace["start"] + trace["audio"]["seconds"]) * FPS)))
    longest = max(0.2, perf["settings"].get("fill_gaps_s") or 0.2)
    chan = {k: resample(times, np.array([np.nan if x is None else x for x in v], dtype=float), n, longest)
            for k, v in perf["channels"].items()}
    face_seen = ~np.isnan(chan["jawOpen"])
    mapping = load_mapping(mapping_path)
    base = {"fps": FPS, "profile": "performance", "duration": n / FPS,
            "source": perf.get("source", {}), "face_seen": round(float(face_seen.mean()), 3) if n else 0,
            "video": {"start": perf["clock"]["video_start"], "trace": os.path.basename(folder)}}
    if export == "arkit52":
        from performance import BLENDSHAPES
        return {**base, "target": "arkit52", "tracks": {k: jl(chan[k]) for k in BLENDSHAPES if k != "_neutral"},
                "head": {k: jl(chan[c], 2) for k, c in (("yaw", "headYaw"), ("pitch", "headPitch"), ("roll", "headRoll"))}}
    tracks, unused = apply_mapping(chan, mapping)
    mode = "video"
    if hybrid and trace.get("audio"):
        dials = {k: v for k, v in (("articulation", articulation), ("expressiveness", expressiveness)) if v is not None}
        voice, nwords = audio_tracks(folder, trace, n, profile, **dials)
        led = mouth_from == "video" or (mouth_from == "auto" and video_mouth_trusted(chan["jawOpen"]))
        import lipsync
        follow = lipsync.load_profile(profile).get("follow_jaw") if led else None
        tracks = hybrid_tracks(tracks, voice, mouth_size(chan["jawOpen"]) if size else None, led, follow)
        mode = "hybrid"
        base["hybrid"] = {"mouth": ("jaw, lower lip, upper lip and chin from the video; " if led else "") + "voice model"
                          + (f" with {nwords} caption words" if nwords else " (no words: jaw, tongue and neck only)"), "face": "video",
                          "mouth_led_by": "video" if led else "voice"}
    elif tongue:
        for k, v in tongue_from_audio(folder, trace, n).items():
            tracks[k] = np.where(face_seen, v, np.nan)
    tracks = add_coupling(tracks, n, coupling, jaw_presence)
    base["settings"] = {"articulation": articulation, "expressiveness": expressiveness, "coupling": coupling, "jaw_presence": jaw_presence}
    out = {**base, "target": "cyberpunk-raw", "mapping": os.path.basename(mapping_path),
           "tracks": {k: jl(v) for k, v in sorted(tracks.items())},
           "head": {k: jl(v, 2) for k, v in head_curves(chan, mapping).items()},
           "head_split": mapping.get("head", {}).get("split"),
           "unmapped_sources": sorted(set(unused) | set(mapping.get("unmapped_sources", {}))), "mouth_source": mode}
    if export == "cyberpunk":
        from export import cyberpunk
        out = cyberpunk(out)
    return out


def main():
    ap = argparse.ArgumentParser(description="Turn performance.json into face-rig curves.")
    ap.add_argument("folder", help="trace folder with performance.json (from analyze/performance.py)")
    ap.add_argument("--mapping", default=DEFAULT_MAPPING)
    ap.add_argument("--export", choices=["raw", "cyberpunk", "arkit52"], default="raw")
    ap.add_argument("--no-tongue", action="store_true", help="(video-only mode) don't add tongue tracks from the audio model")
    ap.add_argument("--articulation", type=float, help="the voice model's articulation dial (0.0-2.0; default: the profile's)")
    ap.add_argument("--expressiveness", type=float, help="the voice model's expressiveness dial (0.0-2.0; default: the profile's)")
    ap.add_argument("--coupling", type=float, default=1.0, help="how strongly the cheeks, lip puff, nose and chin follow the mouth (0.0-2.0, default 1.0)")
    ap.add_argument("--jaw-presence", type=float, default=None, help="how much this face's jaw shows, from the rig (0.7-1.3, default 1.0)")
    ap.add_argument("--rig", help="a character.json: sets --jaw-presence from that face's jaw (unless given)")
    ap.add_argument("--profile", default="speech", help="voice profile for the hybrid's voice side")
    ap.add_argument("--mouth-from", choices=("auto", "video", "voice"), default="auto",
                    help="(hybrid) who leads the jaw and lip separation: video when it reads the mouth at the rig's scale (auto), always, or never")
    ap.add_argument("--no-size", action="store_true", help="(hybrid) don't scale the voice's jaw and lips by the mouth size seen in the video")
    ap.add_argument("--video-only", action="store_true",
                    help="read the mouth from the video too. Default is a hybrid: jaw, lips, tongue and neck from the voice, "
                         "everything else (head, brows, eyes, blinks, gaze, smiles) from the video")
    ap.add_argument("--out")
    a = ap.parse_args()
    res = retarget(a.folder, a.mapping, a.export, not a.no_tongue, hybrid=not a.video_only, size=not a.no_size, mouth_from=a.mouth_from,
                   articulation=a.articulation, expressiveness=a.expressiveness, coupling=min(2.0, max(0.0, a.coupling)),
                   jaw_presence=min(1.3, max(0.7, a.jaw_presence if a.jaw_presence is not None else rig_presence(a.rig))), profile=a.profile)
    if a.out == "-":
        json.dump(res, sys.stdout)
        return
    out = a.out or os.path.join(os.path.abspath(a.folder), f"retarget-{'cyberpunk' if a.export != 'arkit52' else 'arkit52'}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, separators=(",", ":"))
    print(f"Wrote {out}: {len(res['tracks'])} tracks, {res['duration']:.2f} s at {FPS} fps, face seen {res['face_seen'] * 100:.0f}%")


if __name__ == "__main__":
    main()

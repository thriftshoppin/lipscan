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


def audio_tracks(folder, trace, n, profile="speech"):
    """All of the voice model's tracks for the trace's own audio (caption words when there are any), on the trace's clock."""
    import lipsync
    from analyze import caption_words
    audio = trace.get("audio")
    if not audio:
        return {}, 0
    words, _ = caption_words(folder, trace["start"], n / FPS)
    res = lipsync.simulate_lipsync(os.path.join(folder, audio["file"]), profile=profile, words=words or None)
    shift = round((audio.get("start", trace["start"]) - trace["start"]) * FPS)   # audio may start after the trace
    out = {}
    for k, v in res["tracks"].items():
        a = np.zeros(n)
        v = np.array(v[:max(0, n - shift)])
        a[shift:shift + len(v)] = v
        out[k] = a
    return out, len(words)


def hybrid_tracks(video, voice):
    """video, voice: {track: array}. Speech tracks come from the voice; the jaw also takes the video where the video
    shows the mouth open further than the voice suggests; every other track comes from the video. No face in a frame:
    the video-sourced tracks are empty there, the voice-sourced ones carry on."""
    out = {}
    for k, v in voice.items():
        if is_speech_track(k):
            out[k] = v.copy()
    for k, v in video.items():
        if is_speech_track(k):
            if k == "jaw_mid_open":
                out[k] = np.fmax(out.get(k, np.zeros_like(v)), np.nan_to_num(v))
        else:
            out[k] = v
    return out


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


def retarget(folder, mapping_path=DEFAULT_MAPPING, export="raw", tongue=True, hybrid=True):
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
        voice, nwords = audio_tracks(folder, trace, n)
        tracks = hybrid_tracks(tracks, voice)
        mode = "hybrid"
        base["hybrid"] = {"mouth": "voice model" + (f" with {nwords} caption words" if nwords else " (no words: jaw, tongue and neck only)"),
                          "face": "video"}
    elif tongue:
        for k, v in tongue_from_audio(folder, trace, n).items():
            tracks[k] = np.where(face_seen, v, np.nan)
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
    ap.add_argument("--video-only", action="store_true",
                    help="read the mouth from the video too. Default is a hybrid: jaw, lips, tongue and neck from the voice, "
                         "everything else (head, brows, eyes, blinks, gaze, smiles) from the video")
    ap.add_argument("--out")
    a = ap.parse_args()
    res = retarget(a.folder, a.mapping, a.export, not a.no_tongue, hybrid=not a.video_only)
    out = a.out or os.path.join(os.path.abspath(a.folder), f"retarget-{'cyberpunk' if a.export != 'arkit52' else 'arkit52'}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, separators=(",", ":"))
    print(f"Wrote {out}: {len(res['tracks'])} tracks, {res['duration']:.2f} s at {FPS} fps, face seen {res['face_seen'] * 100:.0f}%")


if __name__ == "__main__":
    main()

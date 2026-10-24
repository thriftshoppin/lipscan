"""
LipScan analysis: measure real mouth movement in a trace, score the model against it, and optionally save the
measurements as a new profile.

A trace is a folder written by the LipScan capture tool (Videos\\LipScan\\<date>_<title>\\):
frames\\*.jpg + audio.wav + trace.json, and captions.json / captions.txt when the video has captions.

    python analyze.py "<trace folder>"                           # compare with the speech profile
    python analyze.py "<trace folder>" --profile singing
    python analyze.py "<trace folder>" --no-captions             # ignore the words
    python analyze.py "<trace folder>" --save-profile my-singer  # write profiles/my-singer.json from this trace

What it does:
  1. Tracks the face in every frame with Google's MediaPipe Face Landmarker: 52 ARKit-style blendshapes
     (jawOpen, mouthClose, mouthFunnel, mouthPucker, ...) plus 478 face points, from which it also measures the
     lip gap directly. This is tracking only; nothing identifies the person.
  2. Puts face and sound on one 30 fps timeline (the trace's own clock, so they line up exactly).
  3. Measures how far the jaw leads the sound, the loudness-to-jaw curve, opening and closing speed, syllables per
     second, blinks per minute and left/right symmetry.
  4. Runs the model (model/lipsync.py) on the same audio, with the caption words and their times, and scores it.

To fix the captions, edit captions.txt in the trace folder: one caption per line, "start<TAB>text". Change only the
words. Your text is used in place of YouTube's, and the times stay.

Writes face-30fps.json and analysis.json into the trace folder.
Needs: pip install mediapipe, and MediaPipe's face_landmarker.task in models/ (or set LIPSCAN_FACE_MODEL).
"""

import argparse
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import lipsync as sim  # noqa: E402

FPS = sim.FPS
MODEL = os.environ.get("LIPSCAN_FACE_MODEL", os.path.join(ROOT, "models", "face_landmarker.task"))

# Face points (MediaPipe's 478-point mesh)
UPPER_LIP_INNER, LOWER_LIP_INNER = 13, 14
MOUTH_LEFT, MOUTH_RIGHT = 61, 291
EYE_OUTER_L, EYE_OUTER_R = 33, 263

# Blendshapes saved per frame (the mouth, jaw and eyes; brows and cheeks are left out)
KEEP = [
    "jawOpen", "jawLeft", "jawRight", "jawForward", "mouthClose", "mouthFunnel", "mouthPucker",
    "mouthPressLeft", "mouthPressRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthStretchLeft", "mouthStretchRight", "mouthSmileLeft", "mouthSmileRight", "mouthLowerDownLeft",
    "mouthLowerDownRight", "mouthUpperUpLeft", "mouthUpperUpRight", "mouthLeft", "mouthRight",
    "eyeBlinkLeft", "eyeBlinkRight",
]

# Which game track each simulator output is compared with on the real face
COMPARE = {
    "jaw_mid_open": "jawOpen",
    "lips_together_up": "mouthClose",
    "lips_l_purse": "mouthPucker",
    "lips_l_funnel": "mouthFunnel",
    "lips_suck_dn": "mouthRollLower",
    "lips_l_corner_stretch": "mouthStretchLeft",
}


# ----------------------------------------------------------------------------
# 1. Face tracking
# ----------------------------------------------------------------------------
def track_faces(folder, trace):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL), running_mode=vision.RunningMode.VIDEO,
        num_faces=1, output_face_blendshapes=True)
    rows, last_ms = [], -1
    with vision.FaceLandmarker.create_from_options(opts) as lm:
        for k, fr in enumerate(trace["frames"]):
            ms = max(last_ms + 1, round((fr["t"] - trace["start"]) * 1000))
            last_ms = ms
            res = lm.detect_for_video(mp.Image.create_from_file(os.path.join(folder, fr["file"])), ms)
            row = {"t": fr["t"] - trace["start"], "face": bool(res.face_blendshapes)}
            if row["face"]:
                row.update({b.category_name: b.score for b in res.face_blendshapes[0] if b.category_name in KEEP})
                p = res.face_landmarks[0]
                eyes = math.dist((p[EYE_OUTER_L].x, p[EYE_OUTER_L].y), (p[EYE_OUTER_R].x, p[EYE_OUTER_R].y)) or 1e-6
                row["lipGap"] = math.dist((p[UPPER_LIP_INNER].x, p[UPPER_LIP_INNER].y), (p[LOWER_LIP_INNER].x, p[LOWER_LIP_INNER].y)) / eyes
                row["mouthWidth"] = math.dist((p[MOUTH_LEFT].x, p[MOUTH_LEFT].y), (p[MOUTH_RIGHT].x, p[MOUTH_RIGHT].y)) / eyes
            rows.append(row)
            if k % 300 == 0:
                print(f"  face tracking: frame {k + 1} of {len(trace['frames'])}", flush=True)
    return rows


def to_30fps(rows, n):
    """Resample the tracked frames onto a 30 fps timeline. Frames without a face become NaN."""
    t = np.array([r["t"] for r in rows])
    grid = np.arange(n) / FPS
    out = {}
    for name in KEEP + ["lipGap", "mouthWidth"]:
        v = np.array([r.get(name, np.nan) if r["face"] else np.nan for r in rows], dtype=float)
        good = ~np.isnan(v)
        if good.sum() < 2:
            out[name] = np.full(n, np.nan)
            continue
        col = np.interp(grid, t[good], v[good])
        # don't bridge long gaps where no face was seen (cutaways, other shots)
        idx = np.searchsorted(t[good], grid)
        prev = t[good][np.clip(idx - 1, 0, good.sum() - 1)]
        nxt = t[good][np.clip(idx, 0, good.sum() - 1)]
        col[(nxt - prev) > 0.2] = np.nan
        col[(grid < t[good][0]) | (grid > t[good][-1])] = np.nan
        out[name] = col
    return out


# ----------------------------------------------------------------------------
# 2. Sound and words
# ----------------------------------------------------------------------------
def loudness(path):
    import wave
    with wave.open(path, "rb") as w:
        rate, raw = w.getframerate(), w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(float) / 32768
    per = int(round(rate / FPS))
    n = len(x) // per
    rms = np.sqrt((x[:n * per].reshape(n, per) ** 2).mean(axis=1))
    return 20 * np.log10(rms + 1e-6)


def caption_words(folder, start, length):
    """Timed words inside the traced stretch, as [(seconds from trace start, word)].
    Lines the user corrected in captions.txt replace YouTube's words; times are kept."""
    path = os.path.join(folder, "captions.json")
    if not os.path.exists(path):
        return [], 0
    events = json.load(open(path, encoding="utf-8"))["events"]
    fixes, edited = {}, 0
    txt = os.path.join(folder, "captions.txt")
    if os.path.exists(txt):
        for line in open(txt, encoding="utf-8"):
            if "\t" in line:
                t, text = line.rstrip("\n").split("\t", 1)
                fixes[t.strip()] = text.strip()
    words = []
    for ev in events:
        ws = [(w["t"], w["text"]) for w in ev["words"] if w["text"].strip()]
        fixed = fixes.get(f"{ev['start']:.2f}")
        if fixed is not None and fixed != ev["text"]:
            edited += 1
            new = fixed.split()
            if len(new) == len(ws):
                ws = [(t, w) for (t, _), w in zip(ws, new)]
            elif new:  # different word count: spread the corrected words over the caption's own times
                a, b = ws[0][0] if ws else ev["start"], (ws[-1][0] + 0.3) if ws else ev["start"] + ev["dur"]
                ws = [(a + (b - a) * k / len(new), w) for k, w in enumerate(new)]
            else:
                ws = []
        for t, w in ws:
            for part in w.split():  # uploaded captions can hold a whole phrase per entry
                if "[" in part or "]" in part:
                    continue  # [Music], [Applause]
                if start <= t < start + length:
                    words.append((t - start, part))
    words.sort()
    return words, edited


# ----------------------------------------------------------------------------
# 3. Measurements (the same ones taken from the game)
# ----------------------------------------------------------------------------
def corr(a, b):
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 10 or np.std(a[m]) == 0 or np.std(b[m]) == 0:
        return float("nan")
    return float(np.corrcoef(a[m], b[m])[0, 1])


def shifted(x, lag):
    """x moved later in time by lag frames (negative: earlier)."""
    y = np.full_like(x, np.nan)
    if lag >= 0:
        y[lag:] = x[:len(x) - lag]
    else:
        y[:lag] = x[-lag:]
    return y


def best_lag(mouth, sound, span=10):
    """Frames the mouth runs ahead of the sound (positive = mouth first)."""
    scores = {lag: corr(shifted(mouth, lag), sound) for lag in range(-span, span + 1)}
    scores = {k: v for k, v in scores.items() if not math.isnan(v)}
    if not scores:
        return None, float("nan")
    lag = max(scores, key=scores.get)
    return lag, scores[lag]


NORMALIZE_TO_DB = -18  # same reference level as the profiles


def measure(face, db, voiced_db):
    jaw = face["jawOpen"]
    out = {"frames": len(jaw), "face_seen": round(float(np.mean(~np.isnan(jaw))), 3)}
    voiced = db > voiced_db
    lag, r = best_lag(jaw, np.clip(db, voiced_db - 10, None))
    out["jaw_leads_sound_ms"] = None if lag is None else round(lag * 1000 / FPS)
    out["jaw_vs_loudness_corr"] = round(r, 3)
    lag2, r2 = best_lag(face["lipGap"], np.clip(db, voiced_db - 10, None))
    out["lip_gap_leads_sound_ms"] = None if lag2 is None else round(lag2 * 1000 / FPS)

    # loudness -> jaw, in 6 dB steps measured from the loud end (the simulator's normalize_to_db)
    loud = np.percentile(db[voiced], 95) if voiced.any() else 0
    rel = db - loud + NORMALIZE_TO_DB
    jaw_al = shifted(jaw, -(lag or 0))
    table = {}
    for lo in range(-60, -11, 6):
        m = (rel >= lo - 3) & (rel < lo + 3) & ~np.isnan(jaw_al)
        if m.sum() >= 5:
            table[lo] = {"mean": round(float(np.mean(jaw_al[m])), 3), "p90": round(float(np.percentile(jaw_al[m], 90)), 3), "frames": int(m.sum())}
    out["jaw_by_loudness_db"] = table

    # opening and closing speed (jawOpen units per second, 90th percentile of moving frames)
    d = np.diff(jaw) * FPS
    d = d[~np.isnan(d)]
    opening, closing = d[d > 0.3], -d[d < -0.3]
    out["open_speed_p90"] = round(float(np.percentile(opening, 90)), 2) if len(opening) > 5 else None
    out["close_speed_p90"] = round(float(np.percentile(closing, 90)), 2) if len(closing) > 5 else None

    # syllable rate: jaw peaks while voiced
    j = np.nan_to_num(jaw)
    peaks = [i for i in range(2, len(j) - 2) if voiced[i] and j[i] > 0.08 and j[i] == max(j[i - 2:i + 3]) and j[i] - min(j[max(0, i - 6):i + 7]) > 0.05]
    voiced_s = voiced.sum() / FPS
    out["jaw_peaks_per_voiced_second"] = round(len(peaks) / voiced_s, 2) if voiced_s > 1 else None

    # blinks per minute
    blink = np.nan_to_num((face["eyeBlinkLeft"] + face["eyeBlinkRight"]) / 2)
    starts = int(np.sum((blink[1:] > 0.5) & (blink[:-1] <= 0.5)))
    seen_min = np.sum(~np.isnan(face["eyeBlinkLeft"])) / FPS / 60
    out["blinks_per_minute"] = round(starts / seen_min, 1) if seen_min > 0.1 else None

    # left/right symmetry (1.0 = perfectly mirrored, like the game's dialogue layer)
    sym = {k: corr(face[k + "Left"], face[k + "Right"]) for k in ("mouthSmile", "mouthStretch", "mouthPress", "mouthLowerDown")}
    out["left_right_corr"] = {k: round(v, 3) for k, v in sym.items() if not math.isnan(v)}
    out["jaw_percentiles"] = {p: round(float(np.nanpercentile(jaw, p)), 3) for p in (50, 90, 99)} if not np.all(np.isnan(jaw)) else {}
    return out


def score_sim(result, face, n):
    """Correlation (best lag within +-3 frames) between each simulated track and its counterpart on the real face."""
    out = {}
    for track, shape in COMPARE.items():
        if track not in result["tracks"]:
            continue
        s = np.array(result["tracks"][track][:n], dtype=float)
        s = np.pad(s, (0, n - len(s)))
        best = max(((corr(shifted(s, lag), face[shape]), lag) for lag in range(-3, 4)), key=lambda x: -1 if math.isnan(x[0]) else x[0])
        out[f"{track} ~ {shape}"] = {"corr": round(best[0], 3), "sim_offset_frames": best[1]}
    return out


# ----------------------------------------------------------------------------
# 4. Measurements -> profile
# ----------------------------------------------------------------------------
def save_profile(name, m, base, trace):
    """Start from the base profile and replace what this trace measured. MediaPipe's jawOpen isn't on the same
    scale as a game rig's jaw, so the jaw tables are rescaled to keep the base profile's loudest value."""
    if not all(c.isalnum() or c in "-_" for c in name):
        raise SystemExit("Profile names may use letters, digits, - and _ only.")
    if m["face_seen"] < 0.5 or not m["jaw_by_loudness_db"]:
        return f"no profile written: the face was found in only {m['face_seen'] * 100:.0f}% of frames (need 50%). Try a closer shot."
    cfg = sim.load_profile(base)
    measured = {float(k): v for k, v in m["jaw_by_loudness_db"].items()}
    if len(measured) >= 3:
        top_base = max(cfg["jaw_mean"].values())
        top_meas = max(v["mean"] for v in measured.values()) or 1
        scale = top_base / top_meas
        keys = sorted(cfg["jaw_mean"])
        for table, field in (("jaw_mean", "mean"), ("jaw_peak", "p90")):
            known = sorted(measured)
            cfg[table] = {k: round(min(1.0, (measured[min(known, key=lambda x: abs(x - k))][field]) * scale), 3) for k in keys}
    if m.get("jaw_leads_sound_ms") is not None:
        cfg["open_lead_ms"] = max(0, m["jaw_leads_sound_ms"])
    if m.get("blinks_per_minute") is not None:
        cfg["blinks_per_minute"] = m["blinks_per_minute"]
    sym = list(m.get("left_right_corr", {}).values())
    if sym:
        cfg["symmetric"] = min(sym) > 0.95
    out = {"name": name, "about": f"Measured by LipScan from {trace['source'].get('title', 'a trace')}, based on {cfg.get('name', base)}.",
           "source": trace["source"].get("url", ""), "measured": {k: m[k] for k in ("jaw_leads_sound_ms", "jaw_vs_loudness_corr", "open_speed_p90", "close_speed_p90", "jaw_peaks_per_voiced_second", "blinks_per_minute", "face_seen", "traced_seconds")}}
    for k, v in cfg.items():
        if k in ("name", "about", "source"):
            continue
        out[k] = {str(kk): vv for kk, vv in v.items()} if k in ("jaw_mean", "jaw_peak") else v
    path = os.path.join(ROOT, "profiles", f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return path


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Measure mouth movement in a video trace and score lipsync_sim against it.")
    ap.add_argument("folder")
    ap.add_argument("--profile", default="speech", help="profile to score (name, speech, singing, or .json path)")
    ap.add_argument("--save-profile", metavar="NAME", help="also write profiles/NAME.json from these measurements")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--retrack", action="store_true", help="run face tracking again even if face-30fps.json exists")
    a = ap.parse_args()
    folder = os.path.abspath(a.folder)
    trace = json.load(open(os.path.join(folder, "trace.json"), encoding="utf-8"))
    if not trace.get("audio"):
        sys.exit("This trace has no audio.")
    wav = os.path.join(folder, trace["audio"]["file"])
    db = loudness(wav)
    n = len(db)

    cache = os.path.join(folder, "face-30fps.json")
    if os.path.exists(cache) and not a.retrack:
        face = {k: np.array(v, dtype=float) for k, v in json.load(open(cache))["tracks"].items()}
        face = {k: np.pad(v[:n], (0, max(0, n - len(v))), constant_values=np.nan) for k, v in face.items()}
    else:
        print(f"Tracking the face in {len(trace['frames'])} frames...")
        face = to_30fps(track_faces(folder, trace), n)
        json.dump({"fps": FPS, "start": trace["start"], "tracks": {k: [None if np.isnan(x) else round(float(x), 4) for x in v] for k, v in face.items()}}, open(cache, "w"))

    voiced_db = max(-50.0, float(np.percentile(db, 95)) - 30)
    m = measure(face, db, voiced_db)

    words, edited = ([], 0) if a.no_captions else caption_words(folder, trace["start"], n / FPS)
    result = sim.simulate_lipsync(wav, profile=a.profile, words=words or None)
    m["simulator_vs_face"] = score_sim(result, face, n)
    m["simulator_used_words"] = len(words)
    m["captions_lines_corrected"] = edited
    m["source"] = trace["source"]
    m["traced_seconds"] = round(n / FPS, 2)
    m["profile"] = result["profile"]
    json.dump(m, open(os.path.join(folder, "analysis.json"), "w"), indent=1)

    print(f"\n{trace['source']['title']}  ({m['traced_seconds']} s, face seen in {m['face_seen'] * 100:.0f}% of frames)")
    print(f"  jaw leads the sound by  {m['jaw_leads_sound_ms']} ms   (game: speech 33, singing 67)   corr {m['jaw_vs_loudness_corr']}")
    print(f"  lip gap leads by        {m['lip_gap_leads_sound_ms']} ms")
    print(f"  open / close speed p90  {m['open_speed_p90']} / {m['close_speed_p90']} per s   (game: closing faster than opening)")
    print(f"  jaw peaks per second    {m['jaw_peaks_per_voiced_second']}   (game singing: 1.14)")
    print(f"  blinks per minute       {m['blinks_per_minute']}   (game singing: 18.3)")
    print(f"  left/right correlation  {m['left_right_corr']}")
    print("  loudness -> jawOpen     " + "  ".join(f"{k}dB:{v['mean']}" for k, v in m["jaw_by_loudness_db"].items()))
    print(f"  model ({result['profile']}, {len(words)} caption words, {edited} lines corrected):")
    for k, v in m["simulator_vs_face"].items():
        print(f"    {k:40s} corr {v['corr']}")
    print(f"\nWrote {os.path.join(folder, 'analysis.json')}")
    if a.save_profile:
        result_path = save_profile(a.save_profile, m, a.profile, trace)
        print(result_path if result_path.startswith("no profile") else f"Wrote {result_path}")


if __name__ == "__main__":
    main()

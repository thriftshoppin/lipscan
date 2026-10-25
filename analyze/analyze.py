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


def measure_upper(folder, db, voiced_db, n):
    """Upper-face numbers from performance.json (analyze/performance.py): blinks, brows, head motion, gaze."""
    path = os.path.join(folder, "performance.json")
    if not os.path.exists(path):
        return None
    p = json.load(open(path, encoding="utf-8"))
    t = np.array(p["t"], dtype=float)
    grid = np.arange(n) / FPS

    def ch(name):
        v = np.array([np.nan if x is None else x for x in p["channels"][name]], dtype=float)
        good = ~np.isnan(v)
        if good.sum() < 2:
            return np.full(n, np.nan)
        out = np.interp(grid, t[good], v[good])
        idx = np.clip(np.searchsorted(t[good], grid), 1, good.sum() - 1)
        out[(t[good][idx] - t[good][idx - 1]) > 0.25] = np.nan
        out[(grid < t[good][0]) | (grid > t[good][-1])] = np.nan
        return out

    seen = ~np.isnan(ch("jawOpen"))
    minutes = seen.sum() / FPS / 60
    out = {"face_seen": round(float(seen.mean()), 3)}
    if minutes < 0.1:
        return out
    blink = np.nan_to_num((ch("eyeBlinkLeft") + ch("eyeBlinkRight")) / 2)
    starts = [i for i in range(1, n) if blink[i] > 0.5 >= blink[i - 1]]
    lens = []
    for s in starts:
        e = s
        while e < n and blink[e] > 0.5:
            e += 1
        lens.append((e - s) / FPS)
    voiced = db > voiced_db
    out["blinks_per_minute"] = round(len(starts) / minutes, 1)
    out["blink_seconds_median"] = round(float(np.median(lens)), 3) if lens else None
    out["blinks_in_pauses"] = round(float(np.mean([not voiced[s] for s in starts])), 2) if starts else None

    brow = (ch("browInnerUp") + (ch("browOuterUpLeft") + ch("browOuterUpRight")) / 2) / 2
    b = np.nan_to_num(brow)
    rises = [i for i in range(1, n) if b[i] > 0.25 >= b[i - 1]]
    out["brow_raises_per_minute"] = round(len(rises) / minutes, 1)
    # brows on emphasis: brow height at the loudest syllables vs the other syllables
    peaks, _ = sim.loudness_peaks(list(db), voiced_db)
    if len(peaks) >= 5:
        loud_order = sorted(peaks, key=lambda f: -db[f])
        top = loud_order[:max(1, len(peaks) // 5)]
        rest = loud_order[max(1, len(peaks) // 5):]
        out["brow_at_stressed_syllables"] = round(float(np.nanmean(brow[top])), 3)
        out["brow_at_other_syllables"] = round(float(np.nanmean(brow[rest])), 3)
    lag, r = best_lag(brow, np.clip(db, voiced_db - 10, None), span=15)
    out["brow_leads_loudness_ms"] = None if lag is None else round(lag * 1000 / FPS)
    out["brow_vs_loudness_corr"] = round(r, 3)
    out["frown_mean"] = round(float(np.nanmean((ch("browDownLeft") + ch("browDownRight")) / 2)), 3)

    yaw, pitch, roll = ch("headYaw"), ch("headPitch"), ch("headRoll")
    rms = lambda x: float(np.sqrt(np.nanmean((x - np.nanmedian(x)) ** 2)))
    out["head_rms_deg"] = {"yaw": round(rms(yaw), 2), "pitch": round(rms(pitch), 2), "roll": round(rms(roll), 2)}
    pz = np.nan_to_num(pitch - np.nanmedian(pitch))
    dips = [i for i in range(3, n - 3) if pz[i] < -1.5 and pz[i] == min(pz[i - 3:i + 4])]
    out["head_nods_per_minute"] = round(len(dips) / minutes, 1)
    out["head_nod_deg_median"] = round(float(-np.median(pz[dips])), 2) if dips else None
    g = np.nanmean([np.abs(ch("gazeLeftYaw")), np.abs(ch("gazeRightYaw"))], axis=0)
    out["gaze_yaw_abs_mean_deg"] = round(float(np.nanmean(g)), 2)
    gp = np.nanmean([ch("gazeLeftPitch"), ch("gazeRightPitch")], axis=0)
    out["gaze_pitch_mean_deg"] = round(float(np.nanmean(gp)), 2)
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
    up = m.get("upper_face") or {}
    if cfg.get("upper_face"):
        u = cfg["upper_face"]
        if up.get("blinks_per_minute") or m.get("blinks_per_minute"):
            u["blinks_per_minute"] = up.get("blinks_per_minute") or m["blinks_per_minute"]
        if up.get("brow_raises_per_minute") is not None:
            u["brow_raises_per_minute"] = up["brow_raises_per_minute"]
        if up.get("brow_leads_loudness_ms") is not None:
            u["brow_lead_ms"] = max(0, up["brow_leads_loudness_ms"])
        if up.get("head_nod_deg_median"):
            u["head_nod_deg"] = up["head_nod_deg_median"]
            u["head_nods_per_minute"] = up["head_nods_per_minute"]
        if up.get("head_rms_deg"):
            u["head_sway_deg"] = round(up["head_rms_deg"]["yaw"], 2)
        if up.get("gaze_pitch_mean_deg") is not None:
            u["gaze_down"] = round(max(0.0, -up["gaze_pitch_mean_deg"]) / 30, 3)   # the rig's eyes turn 30 deg down at 1
    elif m.get("blinks_per_minute") is not None:
        cfg["blinks_per_minute"] = m["blinks_per_minute"]
    sym = list(m.get("left_right_corr", {}).values())
    if sym:
        cfg["symmetric"] = min(sym) > 0.95
    out = {"name": name, "about": f"Measured by LipScan from {trace['source'].get('title', 'a trace')}, based on {cfg.get('name', base)}.",
           "source": trace["source"].get("url", ""), "measured": {k: m[k] for k in ("jaw_leads_sound_ms", "jaw_vs_loudness_corr", "open_speed_p90", "close_speed_p90", "jaw_peaks_per_voiced_second", "blinks_per_minute", "face_seen", "traced_seconds")}}
    if up:
        out["measured"]["upper_face"] = up
    for k, v in cfg.items():
        if k in ("name", "about", "source"):
            continue
        out[k] = {str(kk): vv for kk, vv in v.items()} if k in ("jaw_mean", "jaw_peak") else v
    path = os.path.join(ROOT, "profiles", f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return path


# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# 5. Settings sweep: which articulation / expressiveness / coupling score best against a real face
# ----------------------------------------------------------------------------
# What is compared: the model's rig tracks against the real face's tracks mapped onto the same rig (retarget.py --video-only), so
# sizes are comparable. Each pair is scored on shape (correlation at the best lag within +-4 frames), size (the model's 90th
# percentile of the track against the real face's, 1.0 = same) and, for mouth pairs, crispness (how fast it moves for its size).
PAIRS = {
    "jaw": (["jaw_mid_open"], "mouth"),
    "purse": (["lips_l_purse", "lips_r_purse"], "mouth"),
    "smile": (["lips_l_corner_up", "lips_r_corner_up"], "mouth"),
    "stretch": (["lips_l_stretch", "lips_r_stretch", "lips_l_pull", "lips_r_pull"], "mouth"),
    "brow raise": (["eye_l_brows_raise_in", "eye_r_brows_raise_in"], "face"),
    "frown": (["eye_l_brows_lower", "eye_r_brows_lower"], "face"),
    "squint": (["eye_l_oculi_squint_inner", "eye_r_oculi_squint_inner"], "face"),
    "cheek": (["lips_l_nasolabialDeepener", "lips_r_nasolabialDeepener"], "face"),
}


def _avg(tracks, names, n):
    cols = [np.array([np.nan if x is None else x for x in tracks[k]], float) for k in names if k in tracks]
    if not cols:
        return None
    cols = [np.pad(c, (0, max(0, n - len(c))), constant_values=np.nan)[:n] for c in cols]
    return np.nanmean(np.stack(cols), axis=0)


def _best_lag_corr(a, b, span=4):
    best = (float("nan"), 0)
    for lag in range(-span, span + 1):
        x, y = (a[lag:], b[:len(b) - lag]) if lag >= 0 else (a[:lag], b[-lag:])
        m = min(len(x), len(y))
        ok = ~(np.isnan(x[:m]) | np.isnan(y[:m]))
        if ok.sum() > 15 and x[:m][ok].std() > 1e-6 and y[:m][ok].std() > 1e-6:
            c = float(np.corrcoef(x[:m][ok], y[:m][ok])[0, 1])
            if math.isnan(best[0]) or c > best[0]:
                best = (c, lag)
    return best


def sweep_scores(model_tracks, reference_tracks, n):
    """{pair: {corr, size, crisp}} for one model result against one reference (both {track: [values per frame]})."""
    out = {}
    for name, (tracks, kind) in PAIRS.items():
        m, r = _avg(model_tracks, tracks, n), _avg(reference_tracks, tracks, n)
        if m is None or r is None or np.nanstd(r) < 1e-4:
            continue
        c, _ = _best_lag_corr(np.nan_to_num(m), r)
        p90 = lambda x: float(np.nanpercentile(x, 90)) + 1e-6
        speed = lambda x: float(np.nanpercentile(np.abs(np.diff(np.nan_to_num(x))) * FPS, 90)) / (float(np.nanstd(x)) + 1e-6)
        out[name] = {"corr": None if math.isnan(c) else round(c, 3), "size": round(p90(m) / p90(r), 2),
                     "crisp": round(speed(m) / (speed(r) + 1e-6), 2), "kind": kind}
    return out


def run_sweep(folder, profile, grid, words_from_captions=True):
    """Score the model, setting by setting, against the real face in a trace folder (needs performance.json).
    grid: {"articulation": [..], "expressiveness": [..], "coupling": [..]}: each dial is swept alone with the others at 1.0."""
    sys.path.insert(0, os.path.join(ROOT, "retarget"))
    import retarget as rt
    folder = os.path.abspath(folder)
    trace = json.load(open(os.path.join(folder, "trace.json"), encoding="utf-8"))
    ref = rt.retarget(folder, hybrid=False)
    n = int(round(ref["duration"] * FPS))
    wav = os.path.join(folder, trace["audio"]["file"])
    words, _ = caption_words(folder, trace["start"], n / FPS) if words_from_captions else ([], 0)
    results = []
    for dial, values in grid.items():
        for v in values:
            res = sim.simulate_lipsync(wav, profile=profile, words=words or None, **{dial: v})
            mt = dict(res["tracks"])
            results.append({"dial": dial, "value": v, "scores": sweep_scores(mt, ref["tracks"], n)})
    return {"folder": os.path.basename(folder), "profile": profile, "seconds": round(n / FPS, 1), "caption_words": len(words), "results": results}


def print_sweep(sw):
    print(f"\nSettings sweep against the real face in {sw['folder']} ({sw['seconds']} s, profile {sw['profile']}, {sw['caption_words']} caption words)")
    print("  each cell: corr/size  (corr = shape match; size = model 90th percentile / real face's, 1.0 = same)")
    for dial in dict.fromkeys(r["dial"] for r in sw["results"]):
        rows = [r for r in sw["results"] if r["dial"] == dial]
        names = [k for k in PAIRS if any(k in r["scores"] for r in rows)]
        print(f"\n  {dial}:  " + "  ".join(f"{k:>11s}" for k in names) + "     mouth-corr  face-corr")
        for r in rows:
            cells = []
            for k in names:
                sc = r["scores"].get(k)
                cells.append(f"{sc['corr']:5.2f}/{sc['size']:4.1f}" if sc and sc["corr"] is not None else "     -    ")
            mc = [sc["corr"] for sc in r["scores"].values() if sc["kind"] == "mouth" and sc["corr"] is not None]
            fc = [sc["corr"] for sc in r["scores"].values() if sc["kind"] == "face" and sc["corr"] is not None]
            print(f"  {r['value']:>13.2f}  " + "  ".join(f"{c:>11s}" for c in cells)
                  + f"       {np.mean(mc) if mc else float('nan'):.3f}      {np.mean(fc) if fc else float('nan'):.3f}")


def main():
    ap = argparse.ArgumentParser(description="Measure mouth movement in a video trace and score lipsync_sim against it.")
    ap.add_argument("folder")
    ap.add_argument("--profile", default="speech", help="profile to score (name, speech, singing, or .json path)")
    ap.add_argument("--save-profile", metavar="NAME", help="also write profiles/NAME.json from these measurements")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--retrack", action="store_true", help="run face tracking again even if face-30fps.json exists")
    ap.add_argument("--sweep", action="store_true", help="instead: score articulation, expressiveness and coupling settings against the real face "
                    "(needs performance.json from analyze/performance.py); writes sweep.json")
    ap.add_argument("--grid", nargs="*", metavar="DIAL=v1,v2,..", help="values to try with --sweep, e.g. articulation=0,0.5,1,1.5,2 expressiveness=0,0.5,1,1.5,2")
    a = ap.parse_args()
    if a.sweep:
        grid = {"articulation": [0.0, 0.5, 1.0, 1.5, 2.0], "expressiveness": [0.0, 0.5, 1.0, 1.5, 2.0], "coupling": [0.0, 1.0, 2.0]}
        if a.grid:
            grid = {kv.split("=")[0]: [float(x) for x in kv.split("=")[1].split(",")] for kv in a.grid}
        sw = run_sweep(a.folder, a.profile, grid, not a.no_captions)
        print_sweep(sw)
        with open(os.path.join(os.path.abspath(a.folder), "sweep.json"), "w") as fh:
            json.dump(sw, fh, indent=1)
        return
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
    m["upper_face"] = measure_upper(folder, db, voiced_db, n)
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
    up = m["upper_face"]
    if up is None:
        print("  upper face: run analyze/performance.py on this trace first for brows, blinks, head and gaze")
    elif "blinks_per_minute" in up:
        print(f"  upper face: blinks {up['blinks_per_minute']}/min ({up['blinks_in_pauses']} in pauses), "
              f"brow raises {up['brow_raises_per_minute']}/min, brows lead loudness by {up['brow_leads_loudness_ms']} ms "
              f"(corr {up['brow_vs_loudness_corr']}), head rms {up['head_rms_deg']} deg, nods {up['head_nods_per_minute']}/min")
    print(f"\nWrote {os.path.join(folder, 'analysis.json')}")
    if a.save_profile:
        result_path = save_profile(a.save_profile, m, a.profile, trace)
        print(result_path if result_path.startswith("no profile") else f"Wrote {result_path}")


if __name__ == "__main__":
    main()

"""
Measure a game character's upper face (blinks, brows, frowns) in their dialogue lipsync clips, and score the
model's voice-driven upper face against it. Works on files you export from your own copy of the game; nothing from
the game is stored, only the numbers it prints.

    python game_upper_face.py --anims kerry.anims.glb --tracks character.json --audio-dir <folder of voice .wav>
    python game_upper_face.py ... --profile speech --fit        # also search the brow settings that fit best

--anims     a WolvenKit .anims glTF export (.glb) of the character's lipsync clips (clip names f_<id> / m_<id>)
--tracks    the face rig's track names: a LipScan viewer character.json, or a WolvenKit .rig.json
--audio-dir voice lines as 16-bit WAV; a clip's audio is the file whose name contains its <id> (any case)

Scores (per clip, then averaged):
  jaw    correlation of jaw_mid_open (the existing mouth score, for comparison)
  brows  correlation of brows_raise_in, over the clips where the game raises the brows
  frown  correlation of brows_lower, over the clips where the game lowers them
  blinks share of the game's blinks with a model blink starting within 0.3 s (and the share expected by chance)
  head   the model's head-motion amount (degrees, RMS); the game's dialogue clips have no head turns to compare
"""

import argparse
import copy
import itertools
import json
import math
import os
import struct
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import lipsync  # noqa: E402

FPS = 30
LAYER = "LipsyncPoseOutput"


def track_names(path):
    j = json.load(open(path, encoding="utf-8"))
    if "tracks" in j:
        return j["tracks"]
    return [t["$value"] for t in j["Data"]["RootChunk"]["trackNames"]]


def clips(glb, names):
    b = open(glb, "rb").read()
    if struct.unpack("<I", b[0:4])[0] != 0x46546C67:
        raise SystemExit(f"{glb} isn't a .glb file.")
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    for a in j.get("animations", []):
        ex = a.get("extras") or {}
        per, dur = {}, 0.0
        for k in ex.get("trackKeys", []):
            per.setdefault(k["trackIndex"], []).append((k["time"], k["value"]))
            dur = max(dur, k["time"])
        frames = int(dur * FPS) + 1
        grid = np.arange(frames) / FPS
        out = {}
        for i, ks in per.items():
            ks.sort()
            out[names[i]] = np.interp(grid, [t for t, _ in ks], [v for _, v in ks])
        yield a.get("name", ""), out, frames


def corr(a, b):
    if len(a) < 10 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def starts(x, level=0.4):
    return [i for i in range(1, len(x)) if x[i] > level >= x[i - 1]]


def get(c, name, n):
    v = c.get(name + LAYER)
    if v is None:
        v = c.get(name, np.zeros(n))
    return v


def run(data, profile, quiet=False):
    rows = []
    for name, c, n, wav, db in data:
        res = lipsync.simulate_lipsync(wav, profile=profile)
        m = lambda k: np.pad(np.array(res["tracks"].get(k, [0.0] * n), dtype=float), (0, n))[:n]
        r = {"clip": name, "seconds": round(n / FPS, 2)}
        r["jaw"] = corr(m("jaw_mid_open"), get(c, "jaw_mid_open", n))
        g_raise, g_lower, g_blink = get(c, "eye_l_brows_raise_in", n), get(c, "eye_l_brows_lower", n), get(c, "eye_l_blink", n)
        r["game_raise"] = float(g_raise.max())
        r["game_lower"] = float(g_lower.max())
        r["brows"] = corr(m("eye_l_brows_raise_in"), g_raise) if g_raise.max() > 0.05 else float("nan")
        r["frown"] = corr(m("eye_l_brows_lower"), g_lower) if g_lower.max() > 0.05 else float("nan")
        gb, mb = starts(g_blink), starts(m("eye_l_blink"))
        r["game_blinks"], r["model_blinks"] = len(gb), len(mb)
        r["blink_hits"] = sum(any(abs(a - b) <= 9 for b in mb) for a in gb)
        h = res.get("head", {})
        r["head_rms_deg"] = float(np.sqrt(np.mean(np.square(h.get("pitch", [0.0])))) if h else 0.0)
        rows.append(r)
    seconds = sum(r["seconds"] for r in rows)
    mb = sum(r["model_blinks"] for r in rows)
    gb = sum(r["game_blinks"] for r in rows)
    rate = mb / seconds if seconds else 0
    summary = {
        "clips": len(rows),
        "jaw_corr": round(float(np.nanmean([r["jaw"] for r in rows])), 3),
        "brow_corr": round(float(np.nanmean([r["brows"] for r in rows])), 3),
        "brow_clips": int(sum(not math.isnan(r["brows"]) for r in rows)),
        "frown_corr": round(float(np.nanmean([r["frown"] for r in rows])), 3),
        "frown_clips": int(sum(not math.isnan(r["frown"]) for r in rows)),
        "blink_hit_rate": round(sum(r["blink_hits"] for r in rows) / gb, 3) if gb else None,
        "blink_hit_rate_by_chance": round(1 - math.exp(-rate * 0.6), 3),
        "blinks_per_minute": {"game": round(gb / seconds * 60, 1), "model": round(rate * 60, 1)},
        "head_rms_deg": {"model": round(float(np.mean([r["head_rms_deg"] for r in rows])), 2), "game": None},
    }
    return summary, rows


def measure_game(data):
    """The game's own upper-face numbers (no model)."""
    seconds = sum(n for _, _, n, _, _ in data) / FPS
    blinks, durs, in_pause, raises, raise_peaks, raise_lens, lowers = 0, [], 0, 0, [], [], []
    for name, c, n, wav, db in data:
        loud_end = np.percentile(db, 95)
        bl = get(c, "eye_l_blink", n)
        for s in starts(bl, 0.3):
            e = s
            while e < n and bl[e] > 0.3:
                e += 1
            blinks += 1
            durs.append((e - s) / FPS)
            in_pause += db[min(s, len(db) - 1)] < loud_end - 25
        r = get(c, "eye_l_brows_raise_in", n)
        if r.max() > 0.05:
            above = r > 0.5 * r.max()
            ev = [i for i in range(n) if above[i] and (i == 0 or not above[i - 1])]
            raises += len(ev)
            raise_peaks.append(float(r.max()))
            raise_lens.append(float(above.sum()) / FPS / len(ev))
        lo = get(c, "eye_l_brows_lower", n)
        if lo.max() > 0.05:
            lowers.append(float(lo.max()))
    return {
        "seconds": round(seconds, 1),
        "blinks_per_minute": round(blinks / seconds * 60, 1),
        "blink_seconds_median": round(float(np.median(durs)), 3) if durs else None,
        "blinks_in_pauses": round(in_pause / blinks, 2) if blinks else None,
        "brow_raises_per_minute": round(raises / seconds * 60, 1),
        "brow_raise_peak_median": round(float(np.median(raise_peaks)), 2) if raise_peaks else None,
        "brow_raise_seconds_median": round(float(np.median(raise_lens)), 2) if raise_lens else None,
        "clips_with_raise": len(raise_peaks),
        "clips_with_frown": len(lowers),
        "frown_peak_median": round(float(np.median(lowers)), 2) if lowers else None,
    }


def load(args):
    names = track_names(args.tracks)
    wavs = {f.lower(): os.path.join(args.audio_dir, f) for f in os.listdir(args.audio_dir) if f.lower().endswith(".wav")}
    data = []
    for name, c, n in clips(args.anims, names):
        cid = name.split("_", 1)[-1].lower()
        wav = next((p for f, p in wavs.items() if cid and cid in f), None)
        if not wav:
            continue
        samples, rate = lipsync.load_wav(wav)
        db = np.array(lipsync.loudness_db(samples, rate) + [-120.0] * n)[:n]
        data.append((name, c, n, wav, db))
    if not data:
        raise SystemExit("No clip had a matching .wav in --audio-dir.")
    return data


def main():
    ap = argparse.ArgumentParser(description="Measure a game character's upper face and score the model against it.")
    ap.add_argument("--anims", required=True)
    ap.add_argument("--tracks", required=True)
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--profile", default="speech")
    ap.add_argument("--fit", action="store_true", help="search brow and frown settings for the best brow correlation")
    ap.add_argument("--out", help="write the numbers here as JSON")
    a = ap.parse_args()
    data = load(a)
    game = measure_game(data)
    print("Game:", json.dumps(game))
    cfg = lipsync.load_profile(a.profile)
    summary, rows = run(data, cfg)
    print("Model:", json.dumps(summary))
    best = None
    if a.fit and cfg.get("upper_face"):
        grid = {"brow_raises_per_minute": [8, 12, 16], "brow_raise_threshold": [0.6, 0.8], "brow_lead_ms": [0, 100, 200],
                "pitch_weight": [0.0, 0.3, 0.6], "frown_lead_ms": [100, 200, 300]}
        for combo in itertools.product(*grid.values()):
            trial = copy.deepcopy(cfg)
            trial["upper_face"].update(dict(zip(grid, combo)))
            s, _ = run(data, trial)
            score = s["brow_corr"] + s["frown_corr"]
            if best is None or score > best[0]:
                best = (score, dict(zip(grid, combo)), s)
        print("Best fit:", json.dumps(best[1]), json.dumps(best[2]))
    if a.out:
        json.dump({"game": game, "model": summary, "clips": rows, "fit": best and {"settings": best[1], "scores": best[2]}},
                  open(a.out, "w"), indent=1, default=lambda x: None if isinstance(x, float) and math.isnan(x) else x)


if __name__ == "__main__":
    main()

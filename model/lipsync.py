"""
LipScan model: turns a voice recording (WAV) into per-frame mouth animation curves.

How the jaw, lips and tongue move is set by a PROFILE (profiles/*.json): the loudness-to-jaw curve, how far the
mouth runs ahead of the sound, opening and closing speeds, and so on. The first two profiles were measured from
Cyberpunk 2077 (speech-cyberpunk, singing-cyberpunk); analyze/analyze.py can measure new ones from real people.

Give it the words too and it adds diction: lips press shut on p/b/m, the lower lip tucks on f/v, lips purse on
oo/w, the tongue moves on t/d/n/l/th, and so on. With word times (for example from captions) each word's shapes
stay inside its own time span.

No add-ons needed: plain Python 3.8+.

    python lipsync.py voice.wav --text "Maybe you should hang onto this." --preview
    python lipsync.py vocal.wav --profile singing-cyberpunk --out song.json
    python lipsync.py clip.wav --words words.json --export arkit52 --out clip.json   # [[0.42, "maybe"], ...]

Output: JSON {"fps": 30, "profile": ..., "tracks": {"jaw_mid_open": [...], ...}}.
The model's own track names are those of the REDengine face rig the first profiles were measured on (it has tongue
tracks, which ARKit lacks). --export arkit52 converts them to the 52 ARKit blendshape names; --export cyberpunk
gives the game's dialogue-layer names. See export/.

The diction shapes are in VISEMES below; everything else is in the profile.
"""

import argparse
import json
import math
import os
import random
import re
import sys
import wave

FPS = 30

# ----------------------------------------------------------------------------
# PROFILES: profiles/<name>.json. "speech" and "singing" are short for the Cyberpunk-measured ones.
# ----------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(os.path.dirname(HERE), "profiles")
ALIASES = {"speech": "speech-cyberpunk", "singing": "singing-cyberpunk"}


def load_profile(name_or_path):
    """A profile by name (profiles/<name>.json), alias, or path to a JSON file."""
    name = ALIASES.get(name_or_path, name_or_path)
    path = name if name.endswith(".json") and os.path.exists(name) else os.path.join(PROFILE_DIR, f"{name}.json")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    for table in ("jaw_mean", "jaw_peak"):
        cfg[table] = {float(k): v for k, v in cfg[table].items()}
    return cfg


def profile_names():
    return sorted(f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith(".json"))


# ----------------------------------------------------------------------------
# DICTION: letters -> viseme -> face-track targets.
# Shape values are the peak strengths the game used in Kerry's dialogue.
# The jaw is left to the audio: the game presses the lips together over an open
# jaw rather than closing it. (Add "jaw": 0.5 to a shape to scale the jaw anyway.)
# ----------------------------------------------------------------------------
VISEMES = {
    "BMP": {"lips_together_up": 1.0, "lips_together_dn": 1.0},              # p b m
    "FV":  {"lips_suck_dn": 0.57, "lips_l_lower_raise": 0.31, "lips_r_lower_raise": 0.31},  # f v
    "OO":  {"lips_l_purse": 0.53, "lips_r_purse": 0.53, "lips_l_funnel": 0.35, "lips_r_funnel": 0.35},
    "W":   {"lips_l_purse": 0.53, "lips_r_purse": 0.53},
    "O":   {"lips_l_funnel": 0.35, "lips_r_funnel": 0.35, "lips_l_purse": 0.25, "lips_r_purse": 0.25},
    "CH":  {"lips_l_funnel": 0.35, "lips_r_funnel": 0.35, "lips_l_purse": 0.3, "lips_r_purse": 0.3,
            "tongue_mid_base_up": 1.0},                                       # sh ch j
    "TD":  {"tongue_mid_tip_up": 0.32, "tongue_mid_lift": 0.5},               # t d n
    "L":   {"tongue_mid_lift": 1.0, "tongue_mid_tip_up": 0.32},
    "TH":  {"tongue_mid_base_fwd": 0.5, "tongue_mid_tip_dn": 0.31},
    "S":   {"lips_l_stretch": 0.31, "lips_r_stretch": 0.31, "tongue_mid_base_up": 0.7},
    "K":   {"tongue_mid_base_back": 1.0, "tongue_mid_base_up": 0.6},                      # k g ng
    "R":   {"lips_l_purse": 0.3, "lips_r_purse": 0.3, "tongue_mid_lift": 0.5},
    "EE":  {"lips_l_pull": 0.37, "lips_r_pull": 0.37, "lips_l_corner_stretch": 0.32, "lips_r_corner_stretch": 0.32},
    "EH":  {"lips_l_pull": 0.2, "lips_r_pull": 0.2},
    "Y":   {"lips_l_pull": 0.3, "lips_r_pull": 0.3},                                      # y glide (consonant)
    "AA":  {},                                                                            # open vowels
    "UH":  {},
    "H":   {},
}
VOWELS = {"OO", "O", "EE", "EH", "AA", "UH"}

# Shortest time (frames at 30 fps) a shape is held, so it reads on screen.
# The game holds a p/b/m closure for about 4-6 frames.
MIN_HOLD = {"BMP": 5, "FV": 4, "OO": 4, "W": 4, "CH": 4, "TD": 3, "L": 4, "TH": 3, "S": 3, "K": 3, "R": 3}

# Spelling -> viseme, longest match first. Rough English rules; swap in a
# pronouncing dictionary later if you want exact phonemes.
SPELLING = [
    ("tch", "CH"), ("igh", "AA"), ("ough", "O"),
    ("th", "TH"), ("sh", "CH"), ("ch", "CH"), ("ph", "FV"), ("wh", "W"), ("ck", "K"), ("ng", "K"), ("qu", "K"),
    ("oo", "OO"), ("ou", "AA"), ("ow", "O"), ("ee", "EE"), ("ea", "EE"), ("ie", "EE"),
    ("ai", "EH"), ("ay", "EH"), ("oa", "O"), ("oi", "O"), ("er", "R"), ("ur", "R"), ("ir", "R"),
    ("a", "AA"), ("e", "EH"), ("i", "EE"), ("o", "O"), ("u", "UH"), ("y", "EE"),
    ("b", "BMP"), ("m", "BMP"), ("p", "BMP"), ("f", "FV"), ("v", "FV"),
    ("t", "TD"), ("d", "TD"), ("n", "TD"), ("l", "L"), ("s", "S"), ("z", "S"), ("x", "S"), ("c", "K"),
    ("k", "K"), ("g", "K"), ("q", "K"), ("r", "R"), ("w", "W"), ("j", "CH"), ("h", "H"),
]


# ----------------------------------------------------------------------------
# Audio
# ----------------------------------------------------------------------------
def load_wav(path):
    """Read a 16-bit PCM WAV, mix to mono. Returns (samples -1..1, sample_rate)."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("Please give a 16-bit PCM WAV (convert with vgmstream, Audacity or ffmpeg).")
        ch, rate, raw = w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())
    ints = memoryview(raw).cast("h")
    mono = [sum(ints[i:i + ch]) / (ch * 32768.0) for i in range(0, len(ints), ch)]
    return mono, rate


def loudness_db(samples, rate, fps=FPS):
    """RMS loudness per video frame, in dB."""
    per = int(round(rate / fps))
    out = []
    for f in range(len(samples) // per):
        chunk = samples[f * per:(f + 1) * per]
        rms = math.sqrt(sum(s * s for s in chunk) / per)
        out.append(20 * math.log10(rms + 1e-6))
    return out


def normalize(db, target):
    """Shift levels so this recording's loud parts sit where the game's did."""
    voiced = sorted(d for d in db if d > -50)
    if not voiced:
        return db
    loud = voiced[int(len(voiced) * 0.95) - 1]
    return [d + (target - loud) for d in db]


# ----------------------------------------------------------------------------
# Jaw from loudness
# ----------------------------------------------------------------------------
def lookup(table, db):
    """Linear interpolation in a {dB: value} table."""
    keys = sorted(table)
    if db <= keys[0]:
        return table[keys[0]]
    if db >= keys[-1]:
        return table[keys[-1]]
    for a, b in zip(keys, keys[1:]):
        if a <= db <= b:
            return table[a] + (table[b] - table[a]) * (db - a) / (b - a)


def smooth(target, cfg, fps=FPS):
    """Ease toward the target with separate open/close speeds, like the game's jaw."""
    up = 1 - math.exp(-1000 / (cfg["attack_ms"] * fps))
    down = 1 - math.exp(-1000 / (cfg["release_ms"] * fps))
    out, v = [], target[0] if target else 0
    for t in target:
        step = (t - v) * (up if t > v else down)
        step = max(-cfg["max_close_speed"] / fps, min(cfg["max_open_speed"] / fps, step))
        v += step
        out.append(v)
    return out


def jaw_curve(db, cfg, fps=FPS):
    mix, top = cfg["peakiness"], lookup(cfg["jaw_peak"], 0)
    raw = []
    for d in db:
        j = (1 - mix) * lookup(cfg["jaw_mean"], d) + mix * lookup(cfg["jaw_peak"], d)
        j = top * (j / top) ** cfg["contrast"]             # contrast > 1: shut more between syllables, open more on them
        raw.append(max(cfg["rest_jaw"], min(1.0, j)))
    n = len(raw)
    lo, lc = round(cfg["open_lead_ms"] * fps / 1000), round(cfg["close_lead_ms"] * fps / 1000)
    ahead = lambda k: raw[min(n - 1, k)]
    # open `lo` frames early, close `lc` frames early
    target = [min(ahead(i + lo), ahead(i + lc)) for i in range(n)]
    return smooth(target, cfg, fps)


# ----------------------------------------------------------------------------
# Diction from text
# ----------------------------------------------------------------------------
# Exact pronunciations: the CMU Pronouncing Dictionary (cmudict.dict next to this
# script). Its sounds (ARPAbet) map onto the same visemes. Without the file the
# spelling rules above are used.
ARPABET = {
    "AA": "AA", "AE": "AA", "AH": "AA", "AW": "AA", "AY": "AA", "AO": "O", "OW": "O", "OY": "O",
    "UW": "OO", "UH": "OO", "IY": "EE", "IH": "EE", "EY": "EH", "EH": "EH", "ER": "R",
    "B": "BMP", "M": "BMP", "P": "BMP", "F": "FV", "V": "FV", "TH": "TH", "DH": "TH",
    "T": "TD", "D": "TD", "N": "TD", "L": "L", "S": "S", "Z": "S", "SH": "CH", "ZH": "CH",
    "CH": "CH", "JH": "CH", "K": "K", "G": "K", "NG": "K", "R": "R", "W": "W", "Y": "Y", "HH": "H",
}
_CMU = None


def cmu():
    global _CMU
    if _CMU is None:
        _CMU = {}
        try:
            import os
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cmudict.dict"), encoding="utf-8") as fh:
                for line in fh:
                    word, *phones = line.split("#")[0].split()
                    if "(" not in word:                        # keep the first pronunciation
                        _CMU[word] = phones
        except OSError:
            pass
    return _CMU


def text_to_visemes(text):
    """'Maybe you' -> [('BMP','maybe'), ('EH','maybe'), ...]."""
    out = []
    for word in re.findall(r"[a-z']+", text.lower()):
        phones = cmu().get(word) or cmu().get(word.replace("'", ""))
        if word == "v":
            phones = ["V", "IY1"]
        if phones:
            for p in phones:
                vis = ARPABET[p.rstrip("012")]
                if p.startswith("AH") and p.endswith("0"):
                    vis = "UH"                                 # unstressed "uh" barely opens
                if not (out and out[-1] == (vis, word)):
                    out.append((vis, word))
            continue
        w = word.replace("'", "")
        if len(w) > 2 and w.endswith("e") and w[-2] not in "aeiouy":
            w = w[:-1]
        i = 0
        while i < len(w):
            for spelling, vis in SPELLING:
                if w.startswith(spelling, i):
                    if not (out and out[-1] == (vis, word)):   # "ll", "mm" -> one shape
                        out.append((vis, word))
                    i += len(spelling)
                    break
            else:
                i += 1
    return out


def syllables(visemes):
    """Group visemes into syllables: [ (onset consonants, vowel, coda consonants), ... ]."""
    out, onset = [], []
    for i, (vis, word) in enumerate(visemes):
        if vis in VOWELS:
            if out and out[-1][3] == word and not onset and not out[-1][2]:
                continue                                   # two vowels in a row ("y" after "a"): one nucleus
            out.append([onset, (vis, word), [], word])
            onset = []
        else:
            next_vowel_same_word = any(v in VOWELS and w == word for v, w in visemes[i + 1:i + 4])
            if out and out[-1][3] == word and not next_vowel_same_word:
                out[-1][2].append((vis, word))             # coda of the current syllable
            else:
                onset.append((vis, word))
    if onset:
        if out:
            out[-1][2].extend(onset)
        else:
            out.append([onset, ("UH", onset[0][1]), [], onset[0][1]])
    return out


def loudness_peaks(db, voiced_db, min_gap=4):
    """Frames where the voice swells: syllable centres."""
    sm = [sum(db[max(0, i - 1):i + 2]) / len(db[max(0, i - 1):i + 2]) for i in range(len(db))]
    peaks = [i for i in range(1, len(sm) - 1) if sm[i] > voiced_db and sm[i] >= sm[i - 1] and sm[i] > sm[i + 1]]
    peaks.sort(key=lambda i: -sm[i])
    kept = []
    for p in peaks:
        if all(abs(p - k) >= min_gap for k in kept):
            kept.append(p)
    return sorted(kept), sm


def place_visemes(visemes, db, fps=FPS, voiced_db=-45):
    """Put each syllable's vowel on a loudness peak and its consonants in the dips around it."""
    syl = syllables(visemes)
    if not syl:
        return []
    peaks, sm = loudness_peaks(db, voiced_db)
    voiced = [i for i, d in enumerate(db) if d > voiced_db] or [0]
    if len(peaks) >= len(syl):
        peaks.sort(key=lambda i: -sm[i])                   # strongest peaks, back in time order
        centres = sorted(peaks[:len(syl)])
    else:                                                  # not enough peaks: spread evenly over the sound
        centres = [voiced[min(len(voiced) - 1, int((k + 0.5) / len(syl) * len(voiced)))] for k in range(len(syl))]
    bounds = [voiced[0]] + [(a + b) // 2 for a, b in zip(centres, centres[1:])] + [voiced[-1] + 1]
    placed = []
    for (onset, vowel, coda, _), c, lo, hi in zip(syl, centres, bounds, bounds[1:]):
        # onset consonants fill the dip before the peak, coda the dip after it
        on_end = max(lo, c - 2)
        for k, (vis, _) in enumerate(onset):
            a = lo + (on_end - lo) * k // max(1, len(onset))
            b = lo + (on_end - lo) * (k + 1) // max(1, len(onset))
            placed.append((vis, a, max(a, b - 1)))
        cd_start = min(hi - 1, c + 2)
        placed.append((vowel[0], on_end, cd_start))
        for k, (vis, _) in enumerate(coda):
            a = cd_start + (hi - cd_start) * k // max(1, len(coda))
            b = cd_start + (hi - cd_start) * (k + 1) // max(1, len(coda))
            placed.append((vis, a, max(a, b - 1)))
    return placed


def place_timed_words(words, db, fps=FPS, voiced_db=-45, longest=1.0):
    """words: [(start seconds, word), ...] in order. Each word's shapes are placed inside its own span
    (from its start to the next word's start, at most `longest` seconds)."""
    placed = []
    for k, (t, word) in enumerate(words):
        a = max(0, round(t * fps))
        end = words[k + 1][0] if k + 1 < len(words) else t + longest
        b = min(len(db), round(min(end, t + longest) * fps))
        if b - a < 2 or not text_to_visemes(word):
            continue
        part = db[a:b]
        floor = min(voiced_db, max(part) - 6)            # quiet word: still find its own peaks
        placed += [(vis, a + lo, a + hi) for vis, lo, hi in place_visemes(text_to_visemes(word), part, fps, floor)]
    return placed


def diction_tracks(placed, n, cfg, fps=FPS):
    """Each shape ramps in, holds, ramps out, a little ahead of the sound."""
    tracks, jaw_scale = {}, [1.0] * n
    lead = round(cfg["shape_lead_ms"] * fps / 1000)
    for vis, start, end in placed:
        shape = VISEMES[vis]
        short = MIN_HOLD.get(vis, 3) - (end - start + 1)     # too brief to read on screen: widen around its centre
        if short > 0:
            start, end = start - short // 2, end + short - short // 2
        for f in range(max(0, start - lead), min(n, end + 1 - lead)):
            for name, value in shape.items():
                if name == "jaw":
                    jaw_scale[f] = min(jaw_scale[f], value) if value < 1 else max(jaw_scale[f], value)
                else:
                    t = tracks.setdefault(name, [0.0] * n)
                    t[f] = max(t[f], value * cfg["viseme_strength"])
    quick = dict(cfg, attack_ms=cfg["shape_attack_ms"], release_ms=cfg["shape_release_ms"], max_open_speed=99, max_close_speed=99)
    return {k: smooth(v, quick, fps) for k, v in tracks.items()}, smooth(jaw_scale, quick, fps)


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------
def simulate_lipsync(wav_path, text=None, profile="speech", seed=1, words=None):
    """Returns {"fps", "profile", "duration", "tracks": {name: [value per frame]}}.
    profile: a name, alias ("speech", "singing"), path, or an already loaded profile dict.
    words: optional [(start seconds, word), ...]; used instead of text when given."""
    cfg = profile if isinstance(profile, dict) else load_profile(profile)
    samples, rate = load_wav(wav_path)
    db = normalize(loudness_db(samples, rate), cfg["normalize_to_db"])
    n = len(db)
    jaw = jaw_curve(db, cfg)
    tracks = {}
    if words or text:
        placed = place_timed_words(words, db) if words else place_visemes(text_to_visemes(text), db)
        tracks, jaw_scale = diction_tracks(placed, n, cfg)
        jaw = [min(1.0, j * s) for j, s in zip(jaw, jaw_scale)]
    tracks["jaw_mid_open"] = jaw
    for name, gain in cfg["follow_jaw"].items():
        base = tracks.get(name, [0.0] * n)
        tracks[name] = [min(1.0, max(b, gain * j)) for b, j in zip(base, jaw)]
    if not cfg["symmetric"]:  # mocap is a little lopsided; add a slow drift between sides
        for name in list(tracks):
            if name.startswith("lips_r_"):
                tracks[name] = [v * (0.9 + 0.1 * math.sin(f / FPS * 0.7)) for f, v in enumerate(tracks[name])]
    if cfg["blinks_per_minute"]:
        rnd, blink = random.Random(seed), [0.0] * n
        f = rnd.randint(0, FPS)
        while f < n:
            for k, v in enumerate((0.5, 1.0, 1.0, 0.6, 0.2)):   # ~170 ms blink
                if f + k < n:
                    blink[f + k] = v
            f += int(rnd.expovariate(cfg["blinks_per_minute"] / 60) * FPS) + 6
        tracks["eye_l_blink"] = tracks["eye_r_blink"] = blink
    return {"fps": FPS, "profile": cfg.get("name", "custom"), "duration": n / FPS,
            "tracks": {k: [round(v, 4) for v in vals] for k, vals in sorted(tracks.items())}}


def preview(result, names=("jaw_mid_open", "lips_together_up", "lips_l_purse", "tongue_mid_lift", "lips_suck_dn"), step=2):
    """Quick terminal bar chart."""
    t = result["tracks"]
    shown = [n for n in names if n in t]
    print("time  " + "  ".join(n[:14].ljust(14) for n in shown))
    for f in range(0, len(t["jaw_mid_open"]), step):
        print(f"{f / result['fps']:5.2f} " + "  ".join(("#" * round(t[n][f] * 14)).ljust(14) for n in shown))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(HERE))
    from export import EXPORTERS  # noqa: E402

    ap = argparse.ArgumentParser(description="Turn a voice WAV into mouth animation curves.")
    ap.add_argument("wav")
    ap.add_argument("--text", help="the words spoken or sung, for diction")
    ap.add_argument("--words", help='JSON file of timed words, [[seconds, "word"], ...]; overrides --text')
    ap.add_argument("--profile", default="speech", help=f"one of {', '.join(profile_names())}, speech, singing, or a .json path")
    ap.add_argument("--export", choices=sorted(EXPORTERS), default="raw", help="track naming (default: raw rig names)")
    ap.add_argument("--out", help="write JSON here")
    ap.add_argument("--preview", action="store_true", help="print a bar chart")
    a = ap.parse_args()
    words = None
    if a.words:
        with open(a.words, encoding="utf-8") as fh:
            words = [(float(t), str(w)) for t, w in json.load(fh)]
    res = simulate_lipsync(a.wav, a.text, a.profile, words=words)
    if a.preview or not a.out:
        preview(res)
    res = EXPORTERS[a.export](res)
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(res, fh)
        print(f"wrote {a.out}: {len(res['tracks'])} tracks, {res['duration']:.2f} s at {res['fps']} fps ({a.export} names)")

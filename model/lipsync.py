"""
LipScan model: turns a voice recording (WAV) into per-frame face animation curves: the mouth, and (with a profile
that has an "upper_face" section) blinks, brows, squints, gaze and small head nods driven by the voice.

How the jaw, lips and tongue move is set by a PROFILE (profiles/*.json): the loudness-to-jaw curve, how far the
mouth runs ahead of the sound, opening and closing speeds, and so on. The first two profiles were measured from
Cyberpunk 2077 (speech-cyberpunk: averaged over six characters; speech-kerry and singing-kerry: one character);
analyze/analyze.py can measure new ones from real people.

Give it the words too and it adds diction: lips press shut on p/b/m, the lower lip tucks on f/v, lips purse on
oo/w, the tongue moves on t/d/n/l/th, and so on. With word times (for example from captions) each word's shapes
stay inside its own time span.

No add-ons needed: plain Python 3.8+.

    python lipsync.py voice.wav --text "Maybe you should hang onto this." --preview
    python lipsync.py vocal.wav --profile singing --out song.json
    python lipsync.py clip.wav --words words.json --export arkit52 --out clip.json   # [[0.42, "maybe"], ...]

Output: JSON {"fps": 30, "profile": ..., "tracks": {"jaw_mid_open": [...], ...}, "head": {"pitch": [...], ...}}.
"head" holds head angles in degrees (pitch > 0 = chin up, yaw > 0 = toward the character's left), when the profile
asks for head motion.
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
ALIASES = {"speech": "speech-cyberpunk", "singing": "singing-kerry", "singing-cyberpunk": "singing-kerry"}  # 0.2.1 name kept


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
    # purse and funnel never stack in the game (when one is up the other is ~0); stacked, they push the lips over the teeth
    "OO":  {"lips_l_purse": 0.53, "lips_r_purse": 0.53},
    "W":   {"lips_l_purse": 0.53, "lips_r_purse": 0.53},
    "O":   {"lips_l_funnel": 0.35, "lips_r_funnel": 0.35},
    "CH":  {"lips_l_funnel": 0.35, "lips_r_funnel": 0.35},                   # sh ch j
    "TD":  {},                                                                # t d n (tongue: see TONGUE_BY_VISEME)
    "L":   {},
    "TH":  {},
    "S":   {"lips_l_stretch": 0.31, "lips_r_stretch": 0.31},
    "K":   {},                                                                # k g ng
    "R":   {"lips_l_purse": 0.3, "lips_r_purse": 0.3},
    "EE":  {"lips_l_pull": 0.37, "lips_r_pull": 0.37, "lips_l_corner_stretch": 0.32, "lips_r_corner_stretch": 0.32},
    "EH":  {"lips_l_pull": 0.2, "lips_r_pull": 0.2},
    "Y":   {"lips_l_pull": 0.3, "lips_r_pull": 0.3},                                      # y glide (consonant)
    "AA":  {},                                                                            # open vowels
    "UH":  {},
    "H":   {},
}
# TONGUE: what the game's tongue does during each sound, learned from the dialogue lipsync of six Cyberpunk 2077
# characters (140 lines; averages, numbers only). The tongue body stays raised through speech (~0.45), rises further on
# t d n l th r y, the back rises on k g h (and f v ch), the front lifts on "o", and the tip barely moves. "_voiced" is
# speech with no sound placed. Tracks are tongue_mid_<name>. TONGUE_CONTRAST (profile "tongue_contrast") restores the
# contrast that averaging over imperfectly timed sounds blurs.
TONGUE_BY_VISEME = {
    "BMP":     {"base_up": 0.41, "base_back": 0.17, "lift": 0.12, "tip_dn": 0.09},
    "FV":      {"base_up": 0.36, "base_back": 0.41, "lift": 0.16, "tip_dn": 0.07, "base_fwd": 0.02},
    "OO":      {"base_up": 0.44, "base_back": 0.21, "lift": 0.12, "tip_dn": 0.06, "base_fwd": 0.02},
    "W":       {"base_up": 0.39, "base_back": 0.12, "lift": 0.17, "tip_dn": 0.09},
    "O":       {"base_up": 0.44, "base_back": 0.16, "lift": 0.30, "tip_dn": 0.05, "base_fwd": 0.02, "tip_up": 0.03},
    "CH":      {"base_up": 0.27, "base_back": 0.34, "lift": 0.16, "tip_dn": 0.10, "base_fwd": 0.05},
    "TD":      {"base_up": 0.60, "base_back": 0.16, "lift": 0.10, "tip_dn": 0.07, "base_fwd": 0.02},
    "L":       {"base_up": 0.58, "base_back": 0.21, "lift": 0.06, "tip_dn": 0.08},
    "TH":      {"base_up": 0.62, "base_back": 0.25, "lift": 0.09, "tip_dn": 0.10, "base_fwd": 0.03},
    "S":       {"base_up": 0.39, "base_back": 0.21, "lift": 0.09, "tip_dn": 0.08, "base_fwd": 0.09},
    "K":       {"base_up": 0.46, "base_back": 0.45, "lift": 0.18, "tip_dn": 0.07},
    "R":       {"base_up": 0.58, "base_back": 0.20, "lift": 0.08, "tip_dn": 0.09, "base_fwd": 0.02},
    "EE":      {"base_up": 0.48, "base_back": 0.20, "lift": 0.08, "tip_dn": 0.13, "base_fwd": 0.03},
    "EH":      {"base_up": 0.49, "base_back": 0.21, "lift": 0.05, "tip_dn": 0.12, "base_fwd": 0.03},
    "Y":       {"base_up": 0.58, "base_back": 0.14, "lift": 0.09, "tip_dn": 0.04},
    "AA":      {"base_up": 0.45, "base_back": 0.21, "lift": 0.17, "tip_dn": 0.08, "base_fwd": 0.02},
    "UH":      {"base_up": 0.49, "base_back": 0.22, "lift": 0.16, "tip_dn": 0.09, "base_fwd": 0.02},
    "H":       {"base_up": 0.30, "base_back": 0.45, "lift": 0.16, "tip_dn": 0.07},
    "_voiced": {"base_up": 0.40, "base_back": 0.20, "lift": 0.10, "tip_dn": 0.06, "base_fwd": 0.03},
}

# LIPS: the game's lip shapes during each sound (both sides alike), learned like the tongue from six characters'
# dialogue lipsync. Unlike VISEMES (one fixed shape per sound, at full strength), these are soft mixes that blend
# from sound to sound, which is how the game's speech looks. Keys are lips_<name> or, for sided shapes,
# lips_l_<name> and lips_r_<name>. p/b/m presses still come from VISEMES (sharp peaks).
SIDED = {"lower_raise", "purse", "funnel", "stretch", "corner_stretch", "pull", "corner_up", "corner_dn", "upper_raise", "corner_wide"}
LIPS_BY_VISEME = {
    "BMP":     {"suck_dn": 0.063, "suck_up": 0.048, "lower_raise": 0.043, "purse": 0.065, "stretch": 0.043, "corner_stretch": 0.053, "pull": 0.061, "corner_up": 0.090, "corner_dn": 0.043, "chin_raise": 0.044, "puff_up": 0.035},
    "FV":      {"suck_dn": 0.142, "lower_raise": 0.046, "purse": 0.035, "stretch": 0.046, "corner_stretch": 0.057, "pull": 0.064, "corner_up": 0.096, "corner_dn": 0.046, "upper_raise": 0.024, "chin_raise": 0.033},
    "OO":      {"suck_dn": 0.024, "lower_raise": 0.036, "purse": 0.120, "stretch": 0.036, "corner_stretch": 0.047, "pull": 0.058, "corner_up": 0.088, "corner_dn": 0.036},
    "W":       {"lower_raise": 0.049, "purse": 0.135, "stretch": 0.049, "corner_stretch": 0.060, "pull": 0.072, "corner_up": 0.103, "corner_dn": 0.049},
    "O":       {"suck_dn": 0.023, "lower_raise": 0.037, "purse": 0.084, "stretch": 0.037, "corner_stretch": 0.047, "pull": 0.051, "corner_up": 0.077, "corner_dn": 0.037},
    "CH":      {"suck_dn": 0.040, "lower_raise": 0.036, "purse": 0.036, "funnel": 0.111, "stretch": 0.036, "corner_stretch": 0.043, "pull": 0.051, "corner_up": 0.075, "corner_dn": 0.036},
    "TD":      {"suck_dn": 0.025, "lower_raise": 0.049, "purse": 0.052, "stretch": 0.049, "corner_stretch": 0.061, "pull": 0.064, "corner_up": 0.100, "corner_dn": 0.049},
    "L":       {"suck_dn": 0.029, "lower_raise": 0.046, "purse": 0.054, "stretch": 0.046, "corner_stretch": 0.055, "pull": 0.064, "corner_up": 0.101, "corner_dn": 0.046},
    "TH":      {"suck_dn": 0.054, "lower_raise": 0.072, "purse": 0.031, "stretch": 0.072, "corner_stretch": 0.079, "pull": 0.072, "corner_up": 0.113, "corner_dn": 0.072},
    "S":       {"suck_dn": 0.031, "lower_raise": 0.074, "purse": 0.045, "stretch": 0.074, "corner_stretch": 0.099, "pull": 0.105, "corner_up": 0.159, "corner_dn": 0.074},
    "K":       {"suck_dn": 0.020, "lower_raise": 0.055, "purse": 0.046, "stretch": 0.055, "corner_stretch": 0.066, "pull": 0.065, "corner_up": 0.103, "corner_dn": 0.055},
    "R":       {"suck_dn": 0.048, "lower_raise": 0.049, "purse": 0.036, "stretch": 0.049, "corner_stretch": 0.059, "pull": 0.071, "corner_up": 0.106, "corner_dn": 0.049},
    "EE":      {"suck_dn": 0.037, "lower_raise": 0.064, "purse": 0.038, "stretch": 0.063, "corner_stretch": 0.073, "pull": 0.088, "corner_up": 0.139, "corner_dn": 0.063},
    "EH":      {"suck_dn": 0.034, "lower_raise": 0.078, "purse": 0.033, "stretch": 0.078, "corner_stretch": 0.094, "pull": 0.102, "corner_up": 0.151, "corner_dn": 0.078},
    "Y":       {"suck_dn": 0.031, "lower_raise": 0.050, "purse": 0.096, "stretch": 0.050, "corner_stretch": 0.070, "pull": 0.072, "corner_up": 0.112, "corner_dn": 0.050},
    "AA":      {"suck_dn": 0.032, "lower_raise": 0.050, "purse": 0.045, "stretch": 0.050, "corner_stretch": 0.065, "pull": 0.064, "corner_up": 0.099, "corner_dn": 0.050},
    "UH":      {"suck_dn": 0.042, "lower_raise": 0.052, "purse": 0.039, "stretch": 0.052, "corner_stretch": 0.063, "pull": 0.069, "corner_up": 0.104, "corner_dn": 0.052},
    "H":       {"lower_raise": 0.040, "purse": 0.068, "stretch": 0.040, "corner_stretch": 0.049, "pull": 0.073, "corner_up": 0.111, "corner_dn": 0.040},
    "_voiced": {"suck_dn": 0.034, "lower_raise": 0.046, "purse": 0.041, "stretch": 0.045, "corner_stretch": 0.057, "pull": 0.062, "corner_up": 0.095, "corner_dn": 0.045},
}

VOWELS = {"OO", "O", "EE", "EH", "AA", "UH"}
CONS_FRAMES = 3   # about how long one consonant lasts (frames at 30 fps)

# Shortest time (frames at 30 fps) a shape is held, so it reads on screen.
# The game's p/b/m closure is a sharp peak, about 4 frames (130 ms) wide at half height.
MIN_HOLD = {"BMP": 4, "FV": 4, "OO": 4, "W": 4, "CH": 4, "TD": 3, "L": 4, "TH": 3, "S": 3, "K": 3, "R": 3}

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
    is_voiced = [d > voiced_db for d in db]

    def sound_start(lo, c):
        """First voiced frame of the run that leads into the peak at c (so a consonant after a pause sits where
        the sound starts, not back in the silence)."""
        f = c
        while f > lo and is_voiced[f - 1]:
            f -= 1
        return f

    def sound_end(c, hi):
        f = c
        while f < hi - 1 and is_voiced[f + 1]:
            f += 1
        return f

    placed = []
    for (onset, vowel, coda, _), c, lo, hi in zip(syl, centres, bounds, bounds[1:]):
        # onset consonants sit just before the vowel (about CONS_FRAMES each), coda consonants just after it,
        # both inside the sound around this syllable
        on_end = max(lo, c - 2)
        on_start = max(lo, min(on_end - 1, sound_start(lo, c) - 1), on_end - CONS_FRAMES * len(onset))
        for k, (vis, _) in enumerate(onset):
            a = on_start + (on_end - on_start) * k // max(1, len(onset))
            b = on_start + (on_end - on_start) * (k + 1) // max(1, len(onset))
            placed.append((vis, a, max(a, b - 1)))
        cd_start = min(hi - 1, c + 2)
        cd_end = min(hi, max(cd_start + 1, sound_end(c, hi) + 2), cd_start + CONS_FRAMES * len(coda))
        placed.append((vowel[0], on_end, cd_start))
        for k, (vis, _) in enumerate(coda):
            a = cd_start + (cd_end - cd_start) * k // max(1, len(coda))
            b = cd_start + (cd_end - cd_start) * (k + 1) // max(1, len(coda))
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


def tongue_tracks(placed, n, speaking, cfg, fps=FPS, art=1.0):
    """The tongue from the placed sounds (TONGUE_BY_VISEME): a steady raised body through speech, shaped by each
    sound, eased in and out, at rest in silence."""
    return learned_tracks(TONGUE_BY_VISEME, lambda k: [f"tongue_mid_{k}"], placed, n, speaking, cfg,
                          cfg.get("tongue_contrast", 1.5), cfg.get("tongue_attack_ms", 80), cfg.get("tongue_release_ms", 120), fps, art)


# Lips that push forward. The learned lip table gives the average over a sound's window, and smoothing a short window takes
# the rest, so the model's pursed lips peaked at about 60% of the game's (99th percentile 0.18 against 0.32) and its funnel
# almost never showed (0.04 against 0.18). These sounds get their own pulse, sized to the game's median peak (0.26).
# {sound: (track, share of the profile's lip_forward peak)}; the game's rounded vowels pucker, "sh/ch/j" funnel, "r" a little.
FORWARD = {"OO": ("purse", 1.0), "W": ("purse", 1.0), "O": ("purse", 0.8), "CH": ("funnel", 1.0), "R": ("purse", 0.3)}
FORWARD_HOLD = 5          # frames: the shortest forward push that reads on screen


def forward_tracks(placed, n, speaking, cfg, fps=FPS, art=1.0):
    """Purse and funnel pulses on the rounded and protruded sounds, ahead of the sound like the other lip shapes. The
    profile's lip_forward is the peak (0 = off, the code default); articulation scales both its size and its speed, so a
    crisp delivery pushes further and faster. Returns {track: values}; the caller keeps the larger of this and the learned lips."""
    peak = cfg.get("lip_forward", 0.0)
    if peak <= 0 or not placed:
        return {}
    ts = time_scale(art)
    lead = round(cfg["shape_lead_ms"] * fps / 1000)
    raw = {}
    for vis, start, end in placed:
        if vis not in FORWARD:
            continue
        kind, share = FORWARD[vis]
        hold = max(2, round(FORWARD_HOLD / ts)) if art != 1.0 else FORWARD_HOLD
        short = hold - (end - start + 1)
        if short > 0:
            start, end = start - short // 2, end + short - short // 2
        level = min(LIP_FORWARD_MAX, peak * share * art)
        t = raw.setdefault(kind, [0.0] * n)
        for f in range(max(0, start - lead), min(n, end + 1 - lead)):
            if speaking[min(n - 1, f + lead)]:
                t[f] = max(t[f], level)
    soft = dict(cfg, attack_ms=cfg.get("forward_attack_ms", 60) / ts, release_ms=cfg.get("forward_release_ms", 100) / ts,
                max_open_speed=99, max_close_speed=99)
    out = {}
    for kind, v in raw.items():
        sm = smooth(v, soft, fps)
        for side in "lr":
            out[f"lips_{side}_{kind}"] = sm
    return out


def lip_tracks(placed, n, speaking, cfg, fps=FPS, art=1.0):
    """Soft lip shapes from the placed sounds (LIPS_BY_VISEME), blending from sound to sound."""
    names = lambda k: [f"lips_l_{k}", f"lips_r_{k}"] if k in SIDED else [f"lips_{k}"]
    return learned_tracks(LIPS_BY_VISEME, names, placed, n, speaking, cfg,
                          cfg.get("lip_contrast", 2.5), cfg.get("soft_attack_ms", 100), cfg.get("soft_release_ms", 130), fps, art)


def learned_tracks(table, track_names, placed, n, speaking, cfg, contrast, attack_ms, release_ms, fps=FPS, art=1.0):
    """Per frame, the table row of the sound placed there ("_voiced" between sounds, rest in silence), pushed away
    from the speech average by `contrast` (averages over imperfectly timed sounds are blurred), then eased."""
    names = sorted({k for t in table.values() for k in t})
    centre = {k: table["_voiced"].get(k, 0.0) for k in names}
    at = [None] * n
    for vis, start, end in placed:
        for f in range(max(0, start), min(n, end + 1)):
            at[f] = vis
    lead = round(cfg["shape_lead_ms"] * fps / 1000)
    raw = {k: [0.0] * n for k in names}
    near = [0.0] * n                                     # 1 on and just around the articulated sounds (p b m f v oo w t d k g)
    for f in range(n):
        src = min(n - 1, f + lead)                       # like the lips, the tongue moves a little ahead of the sound
        if not speaking[src]:
            continue
        sound = at[src]
        row = table.get(sound or "_voiced", table["_voiced"])
        c = contrast * art if sound in ART_CLASSES else contrast   # articulation sharpens or softens these sounds' shapes
        if sound in ART_CLASSES:
            for g in range(max(0, f - 2), min(n, f + 3)):
                near[g] = 1.0
        for k in names:
            v = row.get(k, 0.0)
            raw[k][f] = max(0.0, min(1.0, centre[k] + c * (v - centre[k])))
    slow = dict(cfg, attack_ms=attack_ms, release_ms=release_ms, max_open_speed=99, max_close_speed=99)
    ts = time_scale(art)
    fast = dict(slow, attack_ms=attack_ms / ts, release_ms=release_ms / ts)       # around the articulated sounds only
    mix = gentle(near, 1.0) if art != 1.0 else None
    out = {}
    for k, v in raw.items():
        if max(v) > 0.01:
            sm = smooth(v, slow, fps)
            if mix is not None:
                sf = smooth(v, fast, fps)
                sm = [w * x + (1 - w) * y for w, x, y in zip(mix, sf, sm)]
            for name in track_names(k):
                out[name] = sm
    return out


def gentle(values, sigma_frames):
    """Zero-phase Gaussian smoothing (no lag): takes the hard edges off without moving anything in time."""
    if sigma_frames <= 0.05 or len(values) < 3:
        return list(values)
    r = max(1, int(round(3 * sigma_frames)))
    w = [math.exp(-0.5 * (k / sigma_frames) ** 2) for k in range(-r, r + 1)]
    n = len(values)
    out = []
    for f in range(n):
        acc = tot = 0.0
        for k, wk in zip(range(-r, r + 1), w):
            g = f + k
            if 0 <= g < n:
                acc += wk * values[g]
                tot += wk
        out.append(acc / tot)
    return out


# Kept crisp by the final smoothing: blinks and p/b/m presses are sharp in the game too.
CRISP = ("eye_l_blink", "eye_r_blink", "lips_together_up", "lips_together_dn")


CLOSURE = ("lips_together_up", "lips_together_dn")

# ARTICULATION: one dial for how crisp consonant mouth shapes are. 1.0 is the model as measured. Below 1.0 the shapes
# get smaller, slower and longer (mumbled); above 1.0 larger, faster and shorter (crisp). It acts on the sounds listed
# here: the p/b/m closure, the f/v tuck, oo/w pursing and the plosive tongue shapes (t d n, k g), both their size
# and how fast they come and go. Range 0.0 to 2.0.
ART_CLASSES = {"BMP", "FV", "OO", "W", "TD", "K"}
PARAM_RANGE = (0.0, 2.0)


def clamp_param(x, default=1.0):
    """A dial value (articulation, expressiveness) held to 0.0-2.0; None or junk gives the default."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    if x != x:                                             # NaN
        return default
    return max(PARAM_RANGE[0], min(PARAM_RANGE[1], x))


def time_scale(art):
    """How much faster shapes move at this articulation (0.25 at the floor, so 0.0 is slow, not frozen)."""
    return max(art, 0.25)


def sharpen(values, art, sigma=2.0):
    """Unsharp mask in time: art > 1 pushes peaks up and valleys down (crisper), art < 1 blurs them. Identity at 1.0."""
    if art == 1.0:
        return list(values)
    blur = gentle(values, sigma)
    return [max(0.0, min(1.0, v + (art - 1.0) * (v - b))) for v, b in zip(values, blur)]
SHARP_LIPS = ("lips_suck_dn",)   # with lip_mode "learned", these still come from VISEMES (crisp f/v)
LIP_FORWARD_MAX = 0.6   # purse + funnel together; the game's largest is 0.62 (99th percentile 0.42)


def diction_tracks(placed, n, cfg, fps=FPS, quiet=None, art=1.0):
    """Each shape ramps in, holds, ramps out, a little ahead of the sound. A p/b/m closure is a short peak, capped
    at the profile's closure_peak, and other lip shapes give way under it. quiet[f] = True in pauses: no shape whose sound
    falls in a pause."""
    tracks, jaw_scale = {}, [1.0] * n
    lead = round(cfg["shape_lead_ms"] * fps / 1000)
    ts = time_scale(art)
    art_tracks = {name for v in ART_CLASSES for name in VISEMES[v]}      # tracks the articulated sounds drive
    for vis, start, end in placed:
        shape = VISEMES[vis]
        if vis == "BMP" and end - start > 1:                  # a press is a peak, not a plateau
            mid = (start + end + 1) // 2
            start, end = mid - 1, mid
        hold = MIN_HOLD.get(vis, 3)
        if art != 1.0 and vis in ART_CLASSES:                 # crisper = shorter, mumbled = longer
            hold = max(2, round(hold / ts))
        short = hold - (end - start + 1)                     # too brief to read on screen: widen around its centre
        if short > 0:
            start, end = start - short // 2, end + short - short // 2
        for f in range(max(0, start - lead), min(n, end + 1 - lead)):
            for name, value in shape.items():
                if name == "jaw":
                    jaw_scale[f] = min(jaw_scale[f], value) if value < 1 else max(jaw_scale[f], value)
                else:
                    t = tracks.setdefault(name, [0.0] * n)
                    v = value * cfg["viseme_strength"]
                    if art != 1.0 and vis in ART_CLASSES:     # size follows articulation (full size is 1.0)
                        v = min(1.0, v * art)
                    t[f] = max(t[f], v)
    if quiet:
        for t in tracks.values():
            for f in range(n):
                if quiet[min(n - 1, f + lead)]:          # the shape runs `lead` frames ahead of its sound
                    t[f] = 0.0
    quick = dict(cfg, attack_ms=cfg["shape_attack_ms"] / ts, release_ms=cfg["shape_release_ms"] / ts, max_open_speed=99, max_close_speed=99)
    # p/b/m presses (and the jaw scale) are sharp in the game; the other lip and tongue shapes ease in and out more slowly
    soft = dict(cfg, attack_ms=cfg.get("soft_attack_ms", cfg["shape_attack_ms"]), release_ms=cfg.get("soft_release_ms", cfg["shape_release_ms"]),
                max_open_speed=99, max_close_speed=99)
    soft_art = dict(soft, attack_ms=soft["attack_ms"] / ts, release_ms=soft["release_ms"] / ts)   # the articulated shapes' own speed
    out = {k: smooth(v, quick if k in CLOSURE else (soft_art if k in art_tracks else soft), fps) for k, v in tracks.items()}
    # neighbouring shapes overlap after smoothing: keep purse + funnel within what the game ever uses
    for side in "lr":
        p_, f_ = out.get(f"lips_{side}_purse"), out.get(f"lips_{side}_funnel")
        if p_ and f_:
            for k in range(n):
                tot = p_[k] + f_[k]
                if tot > LIP_FORWARD_MAX:
                    p_[k], f_[k] = p_[k] * LIP_FORWARD_MAX / tot, f_[k] * LIP_FORWARD_MAX / tot
    cap = cfg.get("closure_peak", 1.0)
    if art != 1.0:
        cap = min(1.0, cap * art)                          # the press itself gets smaller or, up to full closure, larger
    if any(k in out for k in CLOSURE):
        press = [max(out.get(k, [0.0] * n)[f] for k in CLOSURE) for f in range(n)]
        for k in CLOSURE:
            if k in out:
                out[k] = [min(cap, v) for v in out[k]]
        for k, v in out.items():
            if k.startswith("lips_") and k not in CLOSURE:
                out[k] = [x * (1 - min(1.0, p)) for x, p in zip(v, press)]
    return out, smooth(jaw_scale, quick, fps)


# ----------------------------------------------------------------------------
# Upper face from the voice: blinks, brows, squints, gaze, head nods
# ----------------------------------------------------------------------------
def pitch_track(samples, rate, n, fps=FPS):
    """Voice pitch per frame in semitones above 100 Hz (None where unvoiced). Autocorrelation on audio cut down
    to about 8 kHz; uses numpy when it's installed (much faster), plain Python otherwise."""
    step = max(1, rate // 8000)
    x = samples[::step] if step > 1 else samples
    r = rate / step
    win, lo, hi = int(r * 0.04), int(r / 400), int(r / 60)
    out = [None] * n
    try:
        import numpy as np
        xa = np.asarray(x, dtype=float)
    except ImportError:
        np = None
    for f in range(n):
        a = int(f * r / fps)
        if np is not None:
            seg = xa[a:a + win]
            if len(seg) < win or float(np.sqrt((seg ** 2).mean())) < 0.01:
                continue
            seg = seg - seg.mean()
            ac = np.correlate(seg, seg, "full")[win - 1:]
            k = lo + int(np.argmax(ac[lo:hi]))
            ok = ac[0] > 0 and ac[k] / ac[0] > 0.4
        else:
            seg = x[a:a + win]
            if len(seg) < win or math.sqrt(sum(v * v for v in seg) / win) < 0.01:
                continue
            m = sum(seg) / win
            seg = [v - m for v in seg]
            e0 = sum(v * v for v in seg)
            best, k = -1.0, lo
            for lag in range(lo, hi, 2):                     # every other lag: close enough, twice as fast
                c = sum(seg[i] * seg[i + lag] for i in range(win - lag))
                if c > best:
                    best, k = c, lag
            ok = e0 > 0 and best / e0 > 0.4
        if ok:
            out[f] = 12 * math.log2(r / k / 100)
    return out


def gesture(n, centre, attack, hold, release, peak):
    """A raise-hold-relax curve (frames), as {frame: value}."""
    out = {}
    start = centre - attack
    for f in range(max(0, start), min(n, centre + hold + release + 1)):
        if f < centre:
            v = (f - start + 1) / max(1, attack)
        elif f <= centre + hold:
            v = 1.0
        else:
            v = 1 - (f - centre - hold) / max(1, release)
        if v > 0:
            out[f] = peak * (0.5 - 0.5 * math.cos(math.pi * min(1.0, v)))    # eased
    return out


def squash(x, expr):
    """The ceiling for an expression track. At expressiveness 1.0 and below it is the plain clip at 1.0 (the model as measured);
    above 1.0 the strongest values bend toward 1.0 instead of flattening against it, so turning the dial up keeps the shape."""
    if expr <= 1.0 or x <= 0.7:
        return min(1.0, x)
    return 0.7 + 0.3 * math.tanh((x - 0.7) / 0.3)


def prosody(db, samples, rate, n, voiced, loud, peaks, fps=FPS):
    """What the voice's tone is doing, per frame, each 0 to 1 unless noted:
      rise   pitch rising (about +8 semitones per second is 1): questions, lifts, emphasis
      tense  loud, fast, high delivery (stress, effort, anger)
      calm   low energy over about a second (slack, quiet, relaxed stretches)
      pitch  the pitch track itself (semitones, None where unvoiced)
    from energy (loudness), pitch and its movement, and speaking rate (loudness peaks per second against this voice's own)."""
    pitch = pitch_track(samples, rate, n, fps)
    heard = [p for p in pitch if p is not None]
    # fill unvoiced gaps shorter than 0.25 s so the slope is continuous through consonants
    fill, last, since = list(pitch), None, 0
    for f in range(n):
        if pitch[f] is not None:
            if last is not None and 0 < f - last <= round(0.25 * fps):
                for g in range(last + 1, f):
                    fill[g] = pitch[last] + (pitch[f] - pitch[last]) * (g - last) / (f - last)
            last = f
    k = max(2, round(0.13 * fps))
    rise = [0.0] * n
    for f in range(n):
        a, b = fill[max(0, f - k)], fill[min(n - 1, f + k)]
        if a is not None and b is not None and fill[f] is not None:
            rise[f] = max(0.0, min(1.0, ((b - a) / ((min(n - 1, f + k) - max(0, f - k)) / fps)) / 8.0))
    win = round(1.0 * fps)
    rates = []
    for f in range(n):
        rates.append(sum(1 for q in peaks if f - win <= q <= f + win) / 2.0)
    vr = sorted(r for r, v in zip(rates, voiced) if v)
    med = vr[len(vr) // 2] if vr else 0.0
    tempo = [(r / med if med > 0 else 1.0) for r in rates]                   # 1 = this voice's usual pace
    centre = sorted(heard)[len(heard) // 2] if heard else 0.0
    high = [0.0 if (p is None) else max(0.0, min(1.0, (p - centre) / 6.0)) for p in pitch]
    tense = [loud[f] * (0.5 + 0.5 * max(0.0, min(1.0, tempo[f] - 0.8))) * (0.7 + 0.3 * high[f]) if voiced[f] else 0.0 for f in range(n)]
    energy = gentle(loud, 0.5 * fps)
    calm = [max(0.0, min(1.0, 1.0 - 2.0 * e)) for e in energy]
    return {"rise": rise, "tense": tense, "calm": calm, "tempo": tempo, "pitch": pitch}


def upper_face(db, samples, rate, cfg, seed, fps=FPS, expr=1.0):
    """Tracks and head angles for the upper face, from the voice alone. Settings: the profile's "upper_face".
    expr (expressiveness): scales how strongly the face follows the voice's tone: brow raises, frowns, squints, cheek and
    nose engagement and head movement, in size and number. 1.0 is as measured; 0.0 leaves the upper face still.
    The profile's prosody_* weights (0 turns each off) tie the face to the voice's pitch rise, tension and calm."""
    u = cfg["upper_face"]
    n = len(db)
    rnd = random.Random(seed)
    ms = lambda x: max(1, round(x * fps / 1000))
    voiced_db = cfg["normalize_to_db"] - 30
    voiced = [d > voiced_db for d in db]
    loud = [max(0.0, min(1.0, (d - voiced_db) / 30)) for d in db]          # 0 at the voicing floor, 1 at the loud end
    w_rise, w_tense, w_calm = u.get("prosody_raise", 0.0), u.get("prosody_tense", 0.0), u.get("prosody_calm", 0.0)
    w_cheek, w_nose = u.get("prosody_cheek", 0.0), u.get("prosody_nose", 0.0)
    pro = None
    if w_rise or w_tense or w_calm or w_cheek or w_nose:
        peaks0, _ = loudness_peaks(db, voiced_db)
        pro = prosody(db, samples, rate, n, voiced, loud, peaks0, fps)
    pitch = pro["pitch"] if pro else (pitch_track(samples, rate, n, fps) if u.get("pitch_weight") else [None] * n)
    heard = sorted(p for p in pitch if p is not None)
    centre = heard[len(heard) // 2] if heard else 0.0
    prel = [0.0 if p is None else max(-1.0, min(1.0, (p - centre) / 6)) for p in pitch]   # +-6 semitones -> +-1
    emph = [(loud[f] + u.get("pitch_weight", 0) * prel[f]) if voiced[f] else 0.0 for f in range(n)]
    if pro and w_rise:                                   # rising pitch lifts the brows (a question, a lift, a stressed rise)
        emph = [e + w_rise * r if voiced[f] else e for f, (e, r) in enumerate(zip(emph, pro["rise"]))]
    relax = [1.0 - w_calm * c for c in pro["calm"]] if (pro and w_calm) else None        # calm stretches relax the face
    raise_peak = u["brow_raise_peak"] * expr

    tracks = {}
    head = {"pitch": [0.0] * n, "yaw": [0.0] * n, "roll": [0.0] * n}

    # Brow raises: on the strongest syllables, a short raise-and-relax gesture
    peaks, _ = loudness_peaks(db, voiced_db)
    ranked = sorted(peaks, key=lambda f: -emph[f])
    want = max(1 if ranked else 0, round(u["brow_raises_per_minute"] * expr * n / fps / 60)) if expr > 0 else 0
    events = []
    for f in ranked:
        if len(events) >= want or emph[f] < u["brow_raise_threshold"]:
            break
        if all(abs(f - e) >= u["brow_min_gap_s"] * fps for e in events):
            events.append(f)
    raise_ = [0.0] * n
    top = max((emph[f] for f in events), default=1.0) or 1.0
    for f in events:
        # the brows stay up while the stressed phrase stays loud (up to brow_follow_s)
        hold, end = ms(u["brow_hold_ms"]), min(n, f + round(u.get("brow_follow_s", 0) * fps))
        while f + hold < end and loud[f + hold] > 0.6 * loud[f]:
            hold += 1
        g = gesture(n, f - ms(u["brow_lead_ms"]), ms(u["brow_attack_ms"]), hold, ms(u["brow_release_ms"]),
                    raise_peak * (0.6 + 0.4 * emph[f] / top) * (relax[f] if relax else 1.0))
        for k, v in g.items():
            raise_[k] = max(raise_[k], v)
    if any(raise_):
        for side in "lr":
            tracks[f"eye_{side}_brows_raise_in"] = raise_
            tracks[f"eye_{side}_brows_raise_out"] = raise_

    # Frown: brows lower and eyes narrow a little ahead of loud stretches (speech: low-pitched ones; singing: effortful
    # ones, on top of a steady base); not while the brows are up
    if u.get("frown_level"):
        lead = ms(u["frown_lead_ms"])
        if u.get("frown_drive") == "effort":
            src = [max(0.0, (v - 0.6) / 0.4) ** 2 for v in loud]
            drive = [src[min(n - 1, f + lead)] for f in range(n)]
        else:
            drive = [loud[min(n - 1, f + lead)] * (1.0 if prel[min(n - 1, f + lead)] <= 0 else 0.4) for f in range(n)]
        slow = dict(cfg, attack_ms=u["frown_attack_ms"], release_ms=u["frown_release_ms"], max_open_speed=99, max_close_speed=99)
        if pro and w_tense:                              # loud, fast, tense stretches frown and squint further
            drive = [d + w_tense * t for d, t in zip(drive, pro["tense"])]
        frown = smooth(drive, slow, fps)
        base = u.get("frown_base", 0.0) * min(expr, 1.0)         # more expressive = bigger swings, not a higher resting scowl
        frown = [squash(base + u["frown_level"] * expr * v, expr) * (1 - min(1.0, r / max(1e-6, raise_peak))) for v, r in zip(frown, raise_)]
        if relax:
            frown = [x * r for x, r in zip(frown, relax)]
        for side in "lr":
            for name in ("brows_lower", "brows_lateral", "oculi_squint_inner", "oculi_squint_outer_upper", "oculi_squint_outer_lower"):
                tracks[f"eye_{side}_{name}"] = frown
    if pro and (w_cheek or w_nose):                      # cheeks lift and the nose wrinkles with tense delivery
        tn = smooth(pro["tense"], dict(cfg, attack_ms=120, release_ms=300, max_open_speed=99, max_close_speed=99), fps)
        for side in "lr":
            if w_cheek:
                tracks[f"lips_{side}_nasolabialDeepener"] = [min(1.0, w_cheek * expr * t) for t in tn]
            if w_nose:
                tracks[f"nose_{side}_snear"] = [min(1.0, w_nose * expr * t) for t in tn]

    # Effort (singing, shouting): squint and cheek raise on loud passages
    if u.get("loud_squint") or u.get("loud_cheek"):
        slow = dict(cfg, attack_ms=150, release_ms=400, max_open_speed=99, max_close_speed=99)
        effort = smooth([max(0.0, (v - 0.6) / 0.4) ** 2 for v in loud], slow, fps)
        for side in "lr":
            if u.get("loud_squint"):
                t = tracks.get(f"eye_{side}_oculi_squint_outer_lower", [0.0] * n)
                tracks[f"eye_{side}_oculi_squint_outer_lower"] = [squash(a + u["loud_squint"] * expr * e, expr) for a, e in zip(t, effort)]
            if u.get("loud_cheek"):
                tracks[f"lips_{side}_nasolabialDeepener"] = [u["loud_cheek"] * expr * e for e in effort]

    # Blinks: like the game, in the middle of each pause between phrases; during long stretches of speech without
    # a pause, extra blinks at about blinks_per_minute, on weak syllables
    if u.get("blinks_per_minute"):
        shape = [v * u["blink_peak"] for v in (0.15, 0.8, 1.0, 0.9, 0.45, 0.2, 0.1)]
        speaking = [d > cfg["normalize_to_db"] - 25 for d in db]
        first = speaking.index(True) if any(speaking) else n
        last = n - 1 - speaking[::-1].index(True) if any(speaking) else -1
        at, f = [], first
        while f <= last:                                                # pauses inside the speech
            if not speaking[f]:
                k = f
                while k <= last and not speaking[k]:
                    k += 1
                if (k - f) / fps >= u["blink_pause_min_s"]:
                    at.append((f + k) // 2)
                f = k
            else:
                f += 1
        longest = u.get("blink_max_gap_s") or 60 / u["blinks_per_minute"] * 1.3
        edges = [first] + at + [last]
        for a, b in zip(edges, edges[1:]):                              # long stretches: add blinks
            extra = int((b - a) / fps // longest)
            for j in range(extra):
                c = a + (b - a) * (j + 1) // (extra + 1) + rnd.randint(-fps // 3, fps // 3)
                near = range(max(a + 3, c - 6), min(b - 3, c + 7))
                if near:
                    at.append(min(near, key=lambda k: emph[k]))         # the weakest moment nearby
        blink = [0.0] * n
        for c in sorted(at):
            for k, v in enumerate(shape):
                if 0 <= c - 2 + k < n:
                    blink[c - 2 + k] = max(blink[c - 2 + k], v)
        tracks["eye_l_blink"] = tracks["eye_r_blink"] = blink
        # like the game, the brows don't raise during a blink (raised brows over shut lids also push the skin
        # through the eyebrow cards)
        for side in "lr":
            for name in (f"eye_{side}_brows_raise_in", f"eye_{side}_brows_raise_out"):
                if name in tracks:
                    tracks[name] = [r * (1 - min(1.0, b / max(1e-6, u["blink_peak"]))) for r, b in zip(tracks[name], blink)]

    # Gaze: the game's dialogue eyes rest slightly downward
    if u.get("gaze_down"):
        tracks["eye_l_dir_dn"] = tracks["eye_r_dir_dn"] = [u["gaze_down"]] * n

    # Head: a small nod (chin dips, then returns) on stressed syllables, and a slow sway
    if u.get("head_nod_deg") and peaks and expr > 0:
        nods = sorted(peaks, key=lambda f: -emph[f])[:max(1, round(u["head_nods_per_minute"] * expr * n / fps / 60))]
        for f in nods:
            if emph[f] < u["brow_raise_threshold"]:
                continue
            for k, v in gesture(n, f, ms(90), 0, ms(320), u["head_nod_deg"] * expr * min(1.0, emph[f])).items():
                head["pitch"][k] = min(head["pitch"][k], -v)
    if u.get("head_sway_deg"):
        a1, a2, a3 = (rnd.uniform(0, 6.3) for _ in range(3))
        for f in range(n):
            t = f / fps
            sway = u["head_sway_deg"] * expr * (relax[f] if relax else 1.0)
            head["yaw"][f] += sway * math.sin(0.37 * t * 6.283 + a1)
            head["roll"][f] += 0.5 * sway * math.sin(0.23 * t * 6.283 + a2)
            head["pitch"][f] += 0.4 * sway * math.sin(0.29 * t * 6.283 + a3)
    head = {k: v for k, v in head.items() if any(abs(x) > 1e-6 for x in v)}
    return tracks, head


# ----------------------------------------------------------------------------
# Mood: a held expression for the whole line, with the voice-driven accents on top
# ----------------------------------------------------------------------------
MOOD_DIR = os.path.join(PROFILE_DIR, "moods")


def mood_names():
    return sorted(f[:-5] for f in os.listdir(MOOD_DIR) if f.endswith(".json")) if os.path.isdir(MOOD_DIR) else []


def load_mood(mood):
    """A mood preset by name (profiles/moods/<name>.json), a path to one, or a dict {"tracks": {track: level}}."""
    if isinstance(mood, dict):
        return mood
    path = mood if mood.endswith(".json") and os.path.exists(mood) else os.path.join(MOOD_DIR, f"{mood}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def voice_pitch(wav_path):
    """A speaker's typical pitch (median, semitones above 100 Hz) from one recording; None if unvoiced."""
    s, r = load_wav(wav_path)
    heard = sorted(p for p in pitch_track(s, r, len(loudness_db(s, r))) if p is not None)
    return heard[len(heard) // 2] if len(heard) >= 5 else None


def estimate_mood(db, samples, rate, cfg, fps=FPS, speaker_pitch=None):
    """A GUESS at the mood from the voice alone: a louder, flatter delivery (and, when the speaker's own typical pitch
    is known, a higher one) reads as intense (the profile's "intense" mood), anything else as its "calm" mood.
    Pitch only counts relative to the same speaker: voices differ by an octave between people. Returns (name, score)."""
    m = cfg.get("mood_auto")
    if not m:
        return "neutral", 0.0
    n = len(db)
    voiced_db = cfg["normalize_to_db"] - 30
    heard = sorted(p for p in pitch_track(samples, rate, n, fps) if p is not None)
    raw_db = loudness_db(samples, rate, fps)
    loud = [d for d, v in zip(raw_db, db) if v > voiced_db]
    if len(heard) < 5 or not loud:
        return m["calm"], 0.0
    med = heard[len(heard) // 2]
    iqr = heard[3 * len(heard) // 4] - heard[len(heard) // 4]
    score = (sum(loud) / len(loud) - m["loud_ref"]) / m["loud_scale"] - (iqr - m["range_ref"]) / m["range_scale"]
    if speaker_pitch is not None:
        score += (med - speaker_pitch) / m["pitch_scale"]
    return (m["intense"] if score > m["threshold"] else m["calm"]), round(score, 2)


# Shapes that work against each other. The game never raises the brows inside a held scowl, or smiles inside held
# down-turned corners: under a held mood, an accent on the opposite shape becomes emphasis on the held one instead
# (raised brows over lowered ones also push the skin through the eyebrow cards).
OPPOSITES = [(f"eye_{s}_brows_lower", [f"eye_{s}_brows_raise_in", f"eye_{s}_brows_raise_out"]) for s in "lr"] + \
            [(f"eye_{s}_brows_raise_in", [f"eye_{s}_brows_lower", f"eye_{s}_brows_lateral"]) for s in "lr"] + \
            [(f"lips_{s}_corner_dn", [f"lips_{s}_corner_up"]) for s in "lr"] + \
            [(f"lips_{s}_corner_up", [f"lips_{s}_corner_dn"]) for s in "lr"]
OPPOSE_FULL = 0.2      # a held level this high removes the opposite accents completely
OPPOSE_CARRY = 0.25    # share of a removed accent that goes into the held shape as emphasis


def apply_mood(tracks, preset, n, blink_peak=0.85):
    """Hold the preset's levels for the whole line; the accents already in `tracks` ride on top. Accents that
    work against a held shape turn into emphasis on it (OPPOSITES)."""
    held = preset.get("tracks", {})
    for keep, against in OPPOSITES:
        h = held.get(keep, 0.0)
        if h <= 0:
            continue
        scale = max(0.0, 1 - h / OPPOSE_FULL)
        carry = [0.0] * n
        for name in against:
            if name in tracks and not held.get(name):
                carry = [max(c, v * (1 - scale)) for c, v in zip(carry, tracks[name])]
                tracks[name] = [v * scale for v in tracks[name]]
        if any(carry):
            base = tracks.get(keep, [0.0] * n)
            tracks[keep] = [b + OPPOSE_CARRY * c for b, c in zip(base, carry)]
    for name, level in held.items():
        base = tracks.get(name, [0.0] * n)
        tracks[name] = [min(1.0, level + v) for v in base]
    blink = tracks.get("eye_l_blink")
    if blink:                                            # brows still give way during blinks
        for name in [k for k in tracks if "brows_raise" in k]:
            tracks[name] = [r * (1 - min(1.0, b / blink_peak)) for r, b in zip(tracks[name], blink)]
    return tracks


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------
def simulate_lipsync(wav_path, text=None, profile="speech", seed=1, words=None, mood=None, speaker_pitch=None,
                     articulation=None, expressiveness=None, coupling=None, jaw_presence=None):
    """Returns {"fps", "profile", "duration", "tracks": {name: [value per frame]}}.
    profile: a name, alias ("speech", "singing"), path, or an already loaded profile dict.
    words: optional [(start seconds, word), ...]; used instead of text when given.
    mood: None, a preset name (neutral, calm, scowl, warm, sad, surprised), a preset path or dict, or "auto" (a guess
    from the voice). speaker_pitch: the speaker's typical pitch (voice_pitch() of another line of theirs), so --mood
    auto can use pitch relative to that voice.
    articulation: how crisp consonant mouth shapes are (0.0 mumbled, 1.0 as measured, 2.0 very crisp); None = the
    profile's "articulation", else 1.0. expressiveness: how strongly the face follows the tone of the voice (0.0 flat,
    1.0 as measured, 2.0 animated); None = the profile's "expressiveness", else 1.0. Both are held to 0.0-2.0.
    coupling: how strongly the cheeks, lip puff, nose, chin, upper lip and neck follow the mouth and jaw (0.0 off, 1.0 as
    measured, 2.0 doubled); None = the profile's "coupling", else 1.0. jaw_presence: how much this face's jaw shows
    (coupling.jaw_presence() from the rig; 1.0 average, held to 0.7-1.3); None = the profile's "jaw_presence", else 1.0."""
    cfg = profile if isinstance(profile, dict) else load_profile(profile)
    art = clamp_param(articulation if articulation is not None else cfg.get("articulation", 1.0))
    expr = clamp_param(expressiveness if expressiveness is not None else cfg.get("expressiveness", 1.0))
    coup = clamp_param(coupling if coupling is not None else cfg.get("coupling", 1.0))
    presence = max(0.7, min(1.3, clamp_param(jaw_presence if jaw_presence is not None else cfg.get("jaw_presence", 1.0), 1.0)))
    samples, rate = load_wav(wav_path)
    db = normalize(loudness_db(samples, rate), cfg["normalize_to_db"])
    n = len(db)
    jaw = jaw_curve(db, cfg)
    tracks = {}
    if words or text:
        placed = place_timed_words(words, db) if words else place_visemes(text_to_visemes(text), db)
        # a pause: more than 2 frames from any sound
        loud = [d > cfg["normalize_to_db"] - 30 for d in db]
        quiet = [not any(loud[max(0, f - 2):f + 3]) for f in range(n)]
        tracks, jaw_scale = diction_tracks(placed, n, cfg, quiet=quiet, art=art)
        jaw = [min(1.0, j * s) for j, s in zip(jaw, jaw_scale)]
        tracks.update(tongue_tracks(placed, n, loud, cfg, art=art))
        if cfg.get("lip_mode") == "learned":              # soft, blended lips; p/b/m presses stay sharp
            sharp = {k: tracks[k] for k in SHARP_LIPS if k in tracks}   # f/v tuck stays a crisp shape too
            for k in [k for k in tracks if k.startswith("lips_") and k not in CLOSURE]:
                del tracks[k]
            soft = lip_tracks(placed, n, loud, cfg, art=art)
            for k, v in sharp.items():
                soft[k] = [max(x, y) for x, y in zip(soft.get(k, [0.0] * n), v)]
            for k, v in forward_tracks(placed, n, loud, cfg, art=art).items():      # lips pushed forward on oo, w, o, sh/ch
                soft[k] = [max(x, y) for x, y in zip(soft.get(k, [0.0] * n), v)]
            for side in "lr":                                                      # purse + funnel stay within what the game uses
                p_, f_ = soft.get(f"lips_{side}_purse"), soft.get(f"lips_{side}_funnel")
                if p_ and f_:
                    for f in range(n):
                        tot = p_[f] + f_[f]
                        if tot > LIP_FORWARD_MAX:
                            p_[f], f_[f] = p_[f] * LIP_FORWARD_MAX / tot, f_[f] * LIP_FORWARD_MAX / tot
            press = [max(tracks.get(k, [0.0] * n)[f] for k in CLOSURE) for f in range(n)]
            for k, v in soft.items():
                tracks[k] = [x * (1 - min(1.0, p)) for x, p in zip(v, press)]
    else:                                                # no words
        loud = [d > cfg["normalize_to_db"] - 30 for d in db]
        learned = None
        if cfg.get("audio_lips", True):                  # lips and tongue from the sound alone (audio_lips.py, needs numpy)
            try:
                sys.path.insert(0, HERE)
                import audio_lips
                learned = audio_lips.predict_tracks(samples, rate, n)
            except (ImportError, OSError):
                learned = None
        if learned:
            # regression shrinks peaks toward the average (about half the game's size); these gains restore presence
            lg, tg = cfg.get("audio_lips_gain", 1.7), cfg.get("audio_tongue_gain", 1.4)
            tracks.update({k: [min(1.0, x * (tg if k.startswith("tongue_") else lg)) for x in sharpen(v, art)] for k, v in learned.items()})
        else:                                            # the tongue's resting speech posture only
            tracks.update(tongue_tracks([], n, loud, cfg, art=art))
    tracks["jaw_mid_open"] = jaw
    for name, gain in cfg["follow_jaw"].items():
        base = tracks.get(name, [0.0] * n)
        tracks[name] = [min(1.0, max(b, gain * j)) for b, j in zip(base, jaw)]
    if not cfg["symmetric"]:  # mocap is a little lopsided; add a slow drift between sides
        for name in list(tracks):
            if name.startswith("lips_r_"):
                tracks[name] = [v * (0.9 + 0.1 * math.sin(f / FPS * 0.7)) for f, v in enumerate(tracks[name])]
    if coup > 0:                                         # cheeks, lip puff, nose, chin, upper lip and neck follow the mouth and jaw
        sys.path.insert(0, HERE)
        import coupling as _coupling
        _coupling.couple(tracks, n, coup, presence)
    head = {}
    if cfg.get("upper_face"):
        upper, head = upper_face(db, samples, rate, cfg, seed, expr=expr)
        for name, v in upper.items():
            tracks[name] = [max(a, b) for a, b in zip(tracks.get(name, [0.0] * n), v)]
    elif cfg.get("blinks_per_minute"):                   # profiles from before 0.2.0: blinks only
        rnd, blink = random.Random(seed), [0.0] * n
        f = rnd.randint(0, FPS)
        while f < n:
            for k, v in enumerate((0.5, 1.0, 1.0, 0.6, 0.2)):   # ~170 ms blink
                if f + k < n:
                    blink[f + k] = v
            f += int(rnd.expovariate(cfg["blinks_per_minute"] / 60) * FPS) + 6
        tracks["eye_l_blink"] = tracks["eye_r_blink"] = blink
    # Neck: the game's throat and neck tracks don't follow the jaw, loudness or pitch (measured); they sit at a
    # steady level while someone talks. Ease them in and out with the speech.
    if cfg.get("neck_during_speech"):
        talking = [1.0 if d > cfg["normalize_to_db"] - 30 else 0.0 for d in db]
        env = smooth(talking, dict(cfg, attack_ms=150, release_ms=250, max_open_speed=99, max_close_speed=99))
        for name, level in cfg["neck_during_speech"].items():
            base = tracks.get(name, [0.0] * n)
            tracks[name] = [max(b, level * e) for b, e in zip(base, env)]
    mood_info = None
    if mood:
        guessed = mood == "auto"
        score = None
        if guessed:
            mood, score = estimate_mood(db, samples, rate, cfg, speaker_pitch=speaker_pitch)
        preset = load_mood(mood)
        apply_mood(tracks, preset, n, (cfg.get("upper_face") or {}).get("blink_peak", 0.85))
        mood_info = {"name": preset.get("name", "custom"), "source": preset.get("source", "custom")}
        if guessed:
            mood_info.update(auto=True, score=score, note="guessed from the voice; set --mood by hand when you know it")
    # a final, slight smoothing of the whole face (and more of the head), so motion reads as one face, not a set of
    # separate shapes
    face_sigma = cfg.get("face_smooth_ms", 40) * FPS / 1000
    tracks = {k: (v if k in CRISP else gentle(v, face_sigma)) for k, v in tracks.items()}
    if head:
        head_sigma = cfg.get("head_smooth_ms", 120) * FPS / 1000
        head = {k: gentle(v, head_sigma) for k, v in head.items()}
    out = {"fps": FPS, "profile": cfg.get("name", "custom"), "duration": n / FPS,
           "settings": {"articulation": art, "expressiveness": expr, "coupling": coup, "jaw_presence": round(presence, 3)},
           "tracks": {k: [round(v, 4) for v in vals] for k, vals in sorted(tracks.items())}}
    if head:
        out["head"] = {k: [round(v, 2) for v in vals] for k, vals in head.items()}
    if mood_info:
        out["mood"] = mood_info
    return out


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
    ap.add_argument("--mood", help=f"held expression: {', '.join(mood_names())}, a preset .json, or auto (a guess from the voice)")
    ap.add_argument("--voice-ref", help="another recording of the same speaker: lets --mood auto judge pitch against their own voice")
    ap.add_argument("--articulation", type=float, help="how crisp consonant mouth shapes are: 0.0 mumbled, 1.0 as measured "
                    "(default; or the profile's own), 2.0 very crisp. Held to 0.0-2.0")
    ap.add_argument("--expressiveness", type=float, help="how strongly the face follows the tone of the voice: 0.0 flat, 1.0 as "
                    "measured (default; or the profile's own), 2.0 animated. Held to 0.0-2.0")
    ap.add_argument("--coupling", type=float, help="how strongly the cheeks, lip puff, nose, chin, upper lip and neck follow the mouth "
                    "and jaw: 0.0 off, 1.0 as measured (default; or the profile's own), 2.0 doubled. Held to 0.0-2.0")
    ap.add_argument("--jaw-presence", type=float, help="how much this face's jaw shows, from the rig (the viewer's pack gives it): "
                    "1.0 average, up to 1.3 for a wide, long jaw. Scales the coupling")
    ap.add_argument("--rig", help="a character.json: sets --jaw-presence from that face's jaw (unless given)")
    ap.add_argument("--export", choices=sorted(EXPORTERS), default="raw", help="track naming (default: raw rig names)")
    ap.add_argument("--out", help="write JSON here ('-' writes it to the terminal and prints nothing else)")
    ap.add_argument("--preview", action="store_true", help="print a bar chart")
    a = ap.parse_args()
    if a.rig and a.jaw_presence is None:
        import coupling as _coupling
        a.jaw_presence = _coupling.rig_presence(a.rig)
    words = None
    if a.words:
        with open(a.words, encoding="utf-8") as fh:
            words = [(float(t), str(w)) for t, w in json.load(fh)]
    res = simulate_lipsync(a.wav, a.text, a.profile, words=words, mood=a.mood,
                           speaker_pitch=voice_pitch(a.voice_ref) if a.voice_ref else None,
                           articulation=a.articulation, expressiveness=a.expressiveness, coupling=a.coupling,
                           jaw_presence=a.jaw_presence)
    if a.out == "-":
        json.dump(EXPORTERS[a.export](res), sys.stdout)
        sys.exit(0)
    if a.preview or not a.out:
        preview(res)
    res = EXPORTERS[a.export](res)
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(res, fh)
        print(f"wrote {a.out}: {len(res['tracks'])} tracks, {res['duration']:.2f} s at {res['fps']} fps ({a.export} names)")

"""Pins the model's default output, so a new parameter can be shown to leave it unchanged.

    python test/golden.py            # print the hashes
    python test/golden.py --write    # rewrite test/golden_default.json (only when a change is meant to alter default output)

Each case runs the model on a made-up voice (no real audio) and hashes every track rounded to 4 decimals.
"""
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, ROOT)
import lipsync  # noqa: E402

WORDS = [(0.28, "maybe"), (0.68, "you"), (1.08, "should"), (1.5, "bob"), (1.9, "took"), (2.3, "kick")]
VOICES = {
    "speech": (((0.30, 0.25), (0.70, 0.25), (1.10, 0.30), (1.5, 0.3), (1.9, 0.3), (2.3, 0.3)), 2.8, 140),
    "high": (((0.20, 0.30), (0.65, 0.30), (1.20, 0.35), (1.7, 0.3)), 2.3, 220),
}
CASES = [
    ("text-speech", "speech", "speech", {"text": "maybe you should bob took kick"}),
    ("words-speech", "speech", "speech", {"words": WORDS}),
    ("nowords-speech", "speech", "speech", {}),
    ("words-singing", "high", "singing", {"words": WORDS}),
    ("nowords-singing", "high", "singing", {}),
    ("words-kerry", "speech", "speech-kerry", {"words": WORDS}),
    ("words-mood", "high", "speech", {"words": WORDS, "mood": "scowl"}),
]


def voice(path, syllables, length, f0, rate=16000):
    out = []
    for i in range(int(rate * length)):
        t = i / rate
        v = sum(0.5 * math.sin(math.pi * (t - a) / d) * (math.sin(2 * math.pi * f0 * t) + 0.4 * math.sin(4 * math.pi * f0 * t))
                for a, d in syllables if a <= t < a + d)
        out.append(int(max(-1, min(1, v)) * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(out)}h", *out))


def digest(res, only=None):
    h = hashlib.sha256()
    for k in sorted(res["tracks"]):
        if only and not only(k):
            continue
        h.update(k.encode())
        h.update(json.dumps(res["tracks"][k]).encode())
    for k in sorted(res.get("head", {})):
        h.update(("head" + k).encode())
        h.update(json.dumps(res["head"][k]).encode())
    return h.hexdigest()[:16]


MOUTH = lambda k: k.startswith(("lips_", "jaw_", "tongue_", "neck_"))


def run_all(**extra):
    """{case: {"all": hash, "mouth": hash}} for the default settings, plus any extra keyword arguments for the model."""
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, vname, profile, kw in CASES:
            syl, length, f0 = VOICES[vname]
            wav = os.path.join(tmp, f"{vname}.wav")
            if not os.path.exists(wav):
                voice(wav, syl, length, f0)
            cfg = lipsync.load_profile(profile)
            cfg["lip_forward"] = 0.0                    # 0.3.0 added the forward push on oo/w/o/sh/ch; the hashes are for it switched off
            res = lipsync.simulate_lipsync(wav, profile=cfg, seed=1, **kw, **extra)
            out[name] = {"all": digest(res), "mouth": digest(res, MOUTH)}
    return out


if __name__ == "__main__":
    got = run_all()
    if "--write" in sys.argv:
        with open(os.path.join(ROOT, "test", "golden_default.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"about": "Hashes of the model's default output on made-up voices (test/golden.py). Rewritten only on purpose.",
                       "cases": got}, fh, indent=1)
        print("wrote test/golden_default.json")
    for k, v in got.items():
        print(f"{k:16s} all {v['all']}  mouth {v['mouth']}")

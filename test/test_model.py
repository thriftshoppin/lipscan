"""Checks the model, profiles and exporters on a made-up voice (no real audio needed).

    python test/test_model.py
"""
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
from export import EXPORTERS  # noqa: E402

results = []


def check(name, ok, info=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({info})' if info else ''}")


def fake_voice(path, syllables=((0.30, 0.25), (0.70, 0.25), (1.10, 0.30)), rate=16000, length=1.8):
    """Silence with a few 'syllables' (a buzzy 140 Hz tone that swells and fades)."""
    n = int(rate * length)
    out = []
    for i in range(n):
        t = i / rate
        v = 0.0
        for start, dur in syllables:
            if start <= t < start + dur:
                env = math.sin(math.pi * (t - start) / dur)
                v += 0.5 * env * (math.sin(2 * math.pi * 140 * t) + 0.4 * math.sin(2 * math.pi * 280 * t))
        out.append(int(max(-1, min(1, v)) * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{n}h", *out))


with tempfile.TemporaryDirectory() as tmp:
    wav = os.path.join(tmp, "voice.wav")
    fake_voice(wav)

    names = lipsync.profile_names()
    check("both Cyberpunk profiles load", {"speech-cyberpunk", "singing-cyberpunk"} <= set(names), ", ".join(names))
    sp = lipsync.load_profile("speech")
    check("aliases and dB tables load as numbers", sp["name"] == "speech-cyberpunk" and all(isinstance(k, float) for k in sp["jaw_mean"]))

    res = lipsync.simulate_lipsync(wav)
    jaw = res["tracks"]["jaw_mid_open"]
    check("one value per frame at 30 fps", len(jaw) == int(1.8 * 30), f"{len(jaw)} frames")
    check("jaw stays near rest in silence", max(jaw[:5]) < 0.08 and max(jaw[-8:]) < 0.08, f"{max(jaw[:5]):.3f}")
    first_loud = int(0.30 * 30)
    peak = max(range(first_loud, first_loud + 8), key=lambda f: jaw[f])
    check("jaw opens on each syllable", jaw[peak] > 0.15, f"{jaw[peak]:.2f}")
    check("jaw starts opening before the sound (lead)", jaw[first_loud - 1] > jaw[first_loud - 4], f"{jaw[first_loud - 4]:.3f} -> {jaw[first_loud - 1]:.3f}")

    sung = lipsync.simulate_lipsync(wav, profile="singing")["tracks"]["jaw_mid_open"]
    check("singing opens wider than speech", max(sung) > max(jaw), f"{max(sung):.2f} vs {max(jaw):.2f}")

    words = [(0.28, "maybe"), (0.68, "you"), (1.08, "should")]
    timed = lipsync.simulate_lipsync(wav, words=words)["tracks"]
    shut = timed.get("lips_together_up", [0] * len(jaw))
    first_shut = next((f for f, v in enumerate(shut) if v > 0.3), None)
    check("timed words: the 'm' of 'maybe' closes the lips near 0.28 s", first_shut is not None and abs(first_shut / 30 - 0.28) < 0.2, f"frame {first_shut}")
    check("timed words: 'you' and 'should' purse the lips", max(timed.get("lips_l_purse", [0])) > 0.3)

    texted = lipsync.simulate_lipsync(wav, text="maybe you should")["tracks"]
    check("plain text also gives diction", max(texted.get("lips_together_up", [0])) > 0.3)

    ark = EXPORTERS["arkit52"](lipsync.simulate_lipsync(wav, words=words))
    check("arkit52 export uses ARKit names", "jawOpen" in ark["tracks"] and "mouthClose" in ark["tracks"] and "jaw_mid_open" not in ark["tracks"], ", ".join(sorted(ark["tracks"])[:6]))
    cp = EXPORTERS["cyberpunk"](res)
    check("cyberpunk export uses the dialogue-layer names", "jaw_mid_openLipsyncPoseOutput" in cp["tracks"])

print(f"{'ALL ' + str(len(results)) + ' PASSED' if all(results) else str(results.count(False)) + ' FAILED'}")
sys.exit(0 if all(results) else 1)

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
    check("the Cyberpunk profiles load", {"speech-cyberpunk", "speech-kerry", "singing-kerry"} <= set(names), ", ".join(names))
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
    purse = timed.get("lips_l_purse", [0] * len(jaw))
    check("timed words: 'you' and 'should' purse the lips (well above 'maybe')", max(purse[18:]) > 0.15 and max(purse[18:]) > 2 * max(purse[:15]),
          f"{max(purse[18:]):.2f} vs {max(purse[:15]):.2f}")

    texted = lipsync.simulate_lipsync(wav, text="maybe you should")["tracks"]
    check("plain text also gives diction", max(texted.get("lips_together_up", [0])) > 0.3)

    ark = EXPORTERS["arkit52"](lipsync.simulate_lipsync(wav, words=words))
    check("arkit52 export uses ARKit names", "jawOpen" in ark["tracks"] and "mouthClose" in ark["tracks"] and "jaw_mid_open" not in ark["tracks"], ", ".join(sorted(ark["tracks"])[:6]))
    cp = EXPORTERS["cyberpunk"](res)
    check("cyberpunk export uses the dialogue-layer names", "jaw_mid_openLipsyncPoseOutput" in cp["tracks"])

    # ---- articulation, expressiveness, coupling (0.3.0) ----
    import json
    sys.path.insert(0, os.path.join(ROOT, "test"))
    import golden
    gold = json.load(open(os.path.join(ROOT, "test", "golden_default.json"), encoding="utf-8"))["cases"]
    got = golden.run_all(coupling=0)
    bad = [k for k in gold if got.get(k) != gold[k]]
    check("defaults: articulation 1.0 / expressiveness 1.0 reproduce the 0.2.5 output exactly (7 cases)", not bad, ", ".join(bad))

    def closure_width(tr):
        """Frames the lips stay at least half as shut as their own peak."""
        v = tr["lips_together_up"]
        best = run = 0
        for x in v:
            run = run + 1 if x > max(v) / 2 else 0
            best = max(best, run)
        return best

    wds = [(0.28, "maybe"), (0.68, "you"), (1.08, "should")]
    widths = {a: closure_width(lipsync.simulate_lipsync(wav, words=wds, articulation=a)["tracks"]) for a in (0.5, 1.0, 2.0)}
    peaks = {a: max(lipsync.simulate_lipsync(wav, words=wds, articulation=a)["tracks"]["lips_together_up"]) for a in (0.5, 1.0, 2.0)}
    check("articulation: higher gives shorter closures", widths[0.5] > widths[1.0] > widths[2.0], str(widths))
    check("articulation: higher gives firmer closures", peaks[0.5] < peaks[1.0] <= peaks[2.0], str({k: round(v, 2) for k, v in peaks.items()}))
    jaw1 = lipsync.simulate_lipsync(wav, words=wds, articulation=1.0)["tracks"]["jaw_mid_open"]
    jaw2 = lipsync.simulate_lipsync(wav, words=wds, articulation=2.0)["tracks"]["jaw_mid_open"]
    check("articulation leaves the loudness-driven jaw alone", jaw1 == jaw2)

    def upper_energy(res):
        t = res["tracks"]
        return sum(sum(t[k]) for k in t if "brows" in k or "squint" in k)

    e = {x: upper_energy(lipsync.simulate_lipsync(wav, words=wds, expressiveness=x)) for x in (0.0, 1.0, 2.0)}
    check("expressiveness scales the upper-face curves", e[0.0] < e[1.0] < e[2.0], str({k: round(v, 1) for k, v in e.items()}))

    lo = lipsync.simulate_lipsync(wav, words=wds, articulation=-5, expressiveness=99)
    ref_lo = lipsync.simulate_lipsync(wav, words=wds, articulation=0.0, expressiveness=2.0)
    check("out-of-range dials are clamped to 0.0-2.0", lo["tracks"] == ref_lo["tracks"] and lo["settings"]["articulation"] == 0.0 and lo["settings"]["expressiveness"] == 2.0)
    junk = lipsync.simulate_lipsync(wav, words=wds, articulation="abc", expressiveness=float("nan"))
    check("junk dials fall back to the default", junk["tracks"] == lipsync.simulate_lipsync(wav, words=wds, coupling=0)["tracks"] or junk["settings"]["articulation"] == 1.0)

    nocp = lipsync.simulate_lipsync(wav, words=wds, coupling=0)["tracks"]
    cp = lipsync.simulate_lipsync(wav, words=wds, coupling=1.0)["tracks"]
    check("coupling adds cheek/chin/nose movement that follows the mouth", max(cp.get("lips_chin_raise", [0])) > max(nocp.get("lips_chin_raise", [0])))
    big = lipsync.simulate_lipsync(wav, words=wds, coupling=1.0, jaw_presence=1.3)["tracks"]
    small = lipsync.simulate_lipsync(wav, words=wds, coupling=1.0, jaw_presence=0.7)["tracks"]
    check("a bigger jaw shows more in the coupled tracks", sum(big["lips_chin_raise"]) > sum(small["lips_chin_raise"]))
    check("coupling leaves the mouth tracks themselves unchanged", cp["jaw_mid_open"] == nocp["jaw_mid_open"] and cp["lips_together_up"] == nocp["lips_together_up"])

    crisp = lipsync.simulate_lipsync(wav, words=wds, profile="speech-crisp")
    check("profile default: speech-crisp carries articulation 1.5, and --articulation overrides it",
          crisp["settings"]["articulation"] == 1.5 and lipsync.simulate_lipsync(wav, words=wds, profile="speech-crisp", articulation=1.0)["settings"]["articulation"] == 1.0)
    plain = lipsync.simulate_lipsync(wav, words=wds, profile="speech", seed=1)["tracks"]
    tone = lipsync.simulate_lipsync(wav, words=wds, profile="speech-expressive", seed=1)["tracks"]
    check("speech-expressive is opt-in: it differs from speech in the upper face and leaves the mouth alone",
          tone != plain and all(tone[k] == plain[k] for k in ("jaw_mid_open", "lips_together_up")))
    import coupling as _cp
    check("jaw presence: a missing or bone-less rig gives 1.0; width and chin drop scale it within 0.7-1.3",
          _cp.rig_presence({"bones": {"names": [], "parents": [], "t": [], "r": []}}) == 1.0 and _cp.jaw_presence(0.136, 0.0903) == 1.0
          and _cp.jaw_presence(0.154, 0.0978) > 1.05 and _cp.jaw_presence(1, 1) == 1.3)

    # ---- lips pushed forward: oo, w, o -> purse; sh/ch -> funnel (0.3.1) ----
    fw = [(0.28, "maybe"), (0.68, "you"), (1.08, "should"), (1.5, "church")]

    def fwd(**kw):
        return lipsync.simulate_lipsync(wav, words=fw, coupling=0, **kw)["tracks"]

    base0 = lipsync.simulate_lipsync(wav, words=fw, coupling=0, profile=dict(lipsync.load_profile("speech"), lip_forward=0.0))["tracks"]
    on = fwd()
    peak = lambda t, k: max(t.get(k, [0.0]))
    check("forward: oo/w/o sounds push the lips out further than before (purse)", peak(on, "lips_l_purse") > peak(base0, "lips_l_purse") + 0.05,
          f"{peak(base0, 'lips_l_purse'):.2f} -> {peak(on, 'lips_l_purse'):.2f}")
    check("forward: sh/ch pushes the funnel well past the old table's", peak(on, "lips_l_funnel") > peak(base0, "lips_l_funnel") + 0.08,
          f"{peak(base0, 'lips_l_funnel'):.2f} -> {peak(on, 'lips_l_funnel'):.2f}")
    changed = [k for k in on if k not in base0 or on[k] != base0[k]]
    check("forward: only purse and funnel change; the jaw, closures and tongue are as before", all(k.startswith(("lips_l_purse", "lips_r_purse", "lips_l_funnel", "lips_r_funnel")) for k in changed),
          ", ".join(changed))
    a5, a10, a15 = (peak(fwd(articulation=a), "lips_l_purse") for a in (0.5, 1.0, 1.5))
    check("forward: articulation scales the push (0.5 < 1.0 < 1.5)", a5 < a10 < a15, f"{a5:.2f} / {a10:.2f} / {a15:.2f}")
    check("forward: purse + funnel together never pass what the game uses (0.6)",
          all(p + f <= 0.6 + 1e-9 for p, f in zip(fwd(articulation=2.0)["lips_l_purse"], fwd(articulation=2.0)["lips_l_funnel"])))
    sing = lipsync.simulate_lipsync(wav, words=fw, coupling=0, profile="singing")["tracks"]
    sing_off = lipsync.simulate_lipsync(wav, words=fw, coupling=0, profile=dict(lipsync.load_profile("singing"), lip_forward=0.0))["tracks"]
    check("forward: singing has no reference and is unchanged", sing == sing_off)
    mute = lipsync.simulate_lipsync(wav, words=[(0.28, "maybe")], coupling=0)["tracks"]
    check("forward: no rounded sound, no forward push", peak(mute, "lips_l_funnel") < 0.05)

    # ---- authored couplings stay inside what the game's rig takes (0.3.2) ----
    smile = {"jaw_mid_open": [0.3] * 30, "lips_l_corner_up": [1.0] * 30, "lips_r_corner_up": [1.0] * 30, "lips_l_pull": [1.0] * 30, "lips_l_stretch": [1.0] * 30,
             "lips_together_up": [0.0] * 30}
    _cp.couple(smile, 30, 2.0, 1.3)
    # ---- hard k/g/c/q: a burst, then the next sound's shape ----
    hard = lipsync.load_profile("singing-hard")
    kuh = lipsync.diction_tracks([("K", 10, 12), ("UH", 13, 22)], 40, hard)[0]
    qwuh = lipsync.diction_tracks([("K", 10, 12), ("W", 13, 17), ("UH", 18, 27)], 40, hard)[0]
    plain = lipsync.diction_tracks([("K", 10, 12), ("UH", 13, 22)], 40, lipsync.load_profile("singing"))[0]
    check("k/g: singing-hard gives the hard k a lip burst that is over by the vowel; the default profile gives it none",
          max(kuh["lips_l_upper_raise"][9:14]) > 0.05 and max(kuh["lips_l_upper_raise"][21:]) < 0.02 and "lips_l_upper_raise" not in plain)
    check("qu: the burst gives way to the rounding (no corner lift where the lips purse)",
          "lips_l_corner_up" not in qwuh and "lips_l_upper_raise" in qwuh)
    check("coupling: a huge smile cannot push the smile fold or the squint past their caps",
          max(smile["lips_l_nasolabialDeepener"]) <= 0.35 + 1e-9 and max(smile["eye_l_oculi_squint_outer_lower"]) <= 0.3 + 1e-9,
          f"{max(smile['lips_l_nasolabialDeepener']):.2f} / {max(smile['eye_l_oculi_squint_outer_lower']):.2f}")

print(f"{'ALL ' + str(len(results)) + ' PASSED' if all(results) else str(results.count(False)) + ' FAILED'}")
sys.exit(0 if all(results) else 1)

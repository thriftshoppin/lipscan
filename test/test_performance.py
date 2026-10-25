"""Checks the whole-face pipeline without a video or a face model: clean-up steps, head pose, face lock, the mapping
and retargeting, and the model's voice-driven upper face.

    python test/test_performance.py
"""
import json
import math
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("analyze", "retarget", "model"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.path.insert(0, ROOT)
import performance as pf  # noqa: E402
import retarget as rt  # noqa: E402
import lipsync  # noqa: E402

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({info})' if info else ''}")


# ---- the mapping covers every MediaPipe blendshape, or says why not ----
mapping = rt.load_mapping()
covered = set(mapping["map"]) | set(mapping["unmapped_sources"])
missing = [b for b in pf.BLENDSHAPES if b not in covered]
check("mapping: all 52 MediaPipe blendshapes are mapped or listed as unmapped", len(pf.BLENDSHAPES) == 52 and not missing,
      f"{len(mapping['map'])} mapped, unmapped: {', '.join(k for k in mapping['unmapped_sources'] if k in pf.BLENDSHAPES)}")
sides_ok = all(e["track"].startswith(("eye_l", "lips_l", "nose_l", "cheek_l")) or "_l_" not in e["track"] and "_r_" not in e["track"]
               for src, es in mapping["map"].items() if src.endswith("Left") for e in es)
sides_ok &= all("_l_" not in e["track"] and not e["track"].startswith("eye_l") for src, es in mapping["map"].items() if src.endswith("Right") for e in es)
check("mapping: MediaPipe Left drives the rig's l side, Right the r side (both = the character's own side)", sides_ok)
regions = {"brows": "brows", "eyes": "blink", "gaze": "_dir_", "cheeks": "cheek", "nose": "nose", "jaw": "jaw", "lips": "lips"}
tracks = {e["track"] for es in mapping["map"].values() for e in es}
check("mapping: every face region is driven", all(any(k in t for t in tracks) for k in regions.values()),
      ", ".join(r for r, k in regions.items() if any(k in t for t in tracks)))
eye_poses = {f"eye_{s}_dir_{d}" for s in "lr" for d in ("up", "dn", "in", "out")}
check("mapping: gaze drives all 8 eye-direction poses (the other 4 eye poses are pupils, listed as unmapped)",
      eye_poses <= tracks and any("pupil" in k for k in mapping["unmapped_tracks"]))

# ---- gaps ----
t = np.arange(30) / 30
col = np.ones(30)
col[5:9] = np.nan      # 4 frames = 0.13 s: filled
col[15:25] = np.nan    # 10 frames = 0.33 s: kept as a gap
f = pf.fill_gaps(t, col, 0.2)
check("gaps: short gaps (< 0.2 s) are filled", not np.isnan(f[5:9]).any())
check("gaps: long gaps stay empty (null), never zero", np.isnan(f[15:25]).all() and not (f == 0).any())
r = rt.resample(t, f, 30)
check("gaps: resampling to 30 fps keeps long gaps empty", np.isnan(r[16:24]).all() and not np.isnan(r[:14]).any())

# ---- one-euro smoothing keeps blinks ----
t = np.arange(90) / 30
blink = np.zeros(90)
blink[40:43] = [0.6, 1.0, 0.6]                       # a 100 ms blink
noise = np.random.default_rng(1).normal(0, 0.02, 90)
s = pf.one_euro(t, blink + noise, pf.DEFAULTS["one_euro"]["fast_min_cutoff_hz"], pf.DEFAULTS["one_euro"]["fast_beta"])
check("smoothing: a 100 ms blink keeps most of its depth (eye settings)", s[40:44].max() > 0.75, f"peak {s[40:44].max():.2f}")
slow = pf.one_euro(t, noise + 0.3, 1.5, 0.5)
check("smoothing: jitter on a still face is reduced", np.std(slow[10:]) < np.std(noise[10:]) * 0.7,
      f"{np.std(noise[10:]):.3f} -> {np.std(slow[10:]):.3f}")

# ---- neutral calibration on a synthetic face with a naturally low brow ----
n = 300
vals = np.zeros((n, len(pf.CHANNELS)))
bd = pf.CHANNELS.index("browDownLeft")
jo = pf.CHANNELS.index("jawOpen")
yaw = pf.CHANNELS.index("headYaw")
vals[:, bd] = 0.3                                   # resting brow already reads as a 0.3 frown
vals[100:130, bd] = 0.8                             # a real frown
vals[:, jo] = 0.05 + 0.25 * (np.sin(np.arange(n) / 4) > 0.6)  # talking
vals[:, yaw] = 12.0                                 # sitting turned 12 deg from the camera
rest = pf.neutral_face(vals, 0.1)
out = pf.remove_neutral(vals, rest)
check("neutral: resting brow found and removed", abs(rest[bd] - 0.3) < 0.02 and out[:100, bd].max() < 0.02, f"rest {rest[bd]:.2f}")
check("neutral: a real frown survives, rescaled", 0.65 < out[115, bd] < 0.75, f"{out[115, bd]:.2f}")
check("neutral: head angles become relative to the resting pose", abs(out[:, yaw]).max() < 1e-6)

# ---- head pose conventions (subject-centred; checked against renders of a real game head) ----
def rot(axis, deg):
    c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    m = np.eye(4)
    if axis == "y":
        m[:3, :3] = [[c, 0, s_], [0, 1, 0], [-s_, 0, c]]
    if axis == "x":
        m[:3, :3] = [[1, 0, 0], [0, c, -s_], [0, s_, c]]
    if axis == "z":
        m[:3, :3] = [[c, -s_, 0], [s_, c, 0], [0, 0, 1]]
    return m


hp = pf.head_pose(rot("y", 20))
check("head: MediaPipe y-rotation +20 = yaw +20 (toward the subject's left)", abs(hp[0] - 20) < 1e-6 and abs(hp[1]) < 1e-6)
hp = pf.head_pose(rot("x", -15))
check("head: MediaPipe x-rotation -15 = pitch +15 (chin up)", abs(hp[1] - 15) < 1e-6, f"{hp[1]:.1f}")
hp = pf.head_pose(rot("z", -10))
check("head: MediaPipe z-rotation -10 = roll +10 (toward the left shoulder)", abs(hp[2] - 10) < 1e-6, f"{hp[2]:.1f}")
g = pf.gaze({"eyeLookOutLeft": 1.0, "eyeLookInRight": 1.0})
check("gaze: both eyes looking to the subject's left give positive yaw on both", g[0] > 0 and g[2] > 0, f"{g}")

# ---- one face only ----
lock = pf.FaceLock()
a, b = (0.3, 0.5, 0.2), (0.75, 0.5, 0.15)
picks = [lock.pick([a, b])]
picks.append(lock.pick([(0.31, 0.5, 0.2), (0.75, 0.5, 0.3)]))   # the other face grows larger
picks.append(lock.pick([(0.75, 0.5, 0.3)]))                       # main face leaves the frame
picks.append(lock.pick([(0.32, 0.5, 0.2), (0.75, 0.5, 0.3)]))   # and comes back
check("face lock: starts on the largest face, never jumps to the other", picks == [0, 0, None, 0], f"{picks}")

# ---- retargeting ----
ch = {"browDownLeft": np.array([0.0, 0.5, np.nan]), "eyeSquintLeft": np.array([0.0, 1.0, np.nan]),
      "mouthSmileLeft": np.array([1.0, 0.0, np.nan])}
mp, unused = rt.apply_mapping(ch, mapping)
check("retarget: gain/clamp applied, several sources -> largest wins",
      abs(mp["eye_l_oculi_squint_inner"][1] - 0.6) < 1e-6 and abs(mp["eye_l_brows_lower"][1] - 0.5) < 1e-6,
      f"squint_inner {mp['eye_l_oculi_squint_inner'][1]:.2f}")
check("retarget: frames with no face stay empty", np.isnan(mp["eye_l_brows_lower"][2]))
check("retarget: smile goes to the left corner of the character", mp["lips_l_corner_up"][0] == 1.0 and "lips_r_corner_up" not in mp)

# ---- the model's voice-driven upper face ----
def fake_voice(path, syllables, rate=16000, length=1.8):
    """Silence with a few 'syllables' (a buzzy 140 Hz tone that swells and fades), as in test_model.py."""
    import struct
    import wave
    out = []
    for i in range(int(rate * length)):
        t_ = i / rate
        v = sum(0.5 * math.sin(math.pi * (t_ - a) / d) * (math.sin(2 * math.pi * 140 * t_) + 0.4 * math.sin(2 * math.pi * 280 * t_))
                for a, d in syllables if a <= t_ < a + d)
        out.append(int(max(-1, min(1, v)) * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(out)}h", *out))


with tempfile.TemporaryDirectory() as tmp:
    wav = os.path.join(tmp, "voice.wav")
    # two phrases with a pause between them
    fake_voice(wav, syllables=((0.3, 0.25), (0.6, 0.25), (0.9, 0.3), (1.9, 0.25), (2.2, 0.3), (2.5, 0.3)), length=3.2)
    r1 = lipsync.simulate_lipsync(wav, profile="speech", seed=3)
    r2 = lipsync.simulate_lipsync(wav, profile="speech", seed=3)
    tr = r1["tracks"]
    check("model: upper-face tracks are produced (blinks, brows, frown, gaze)",
          all(k in tr for k in ("eye_l_blink", "eye_l_brows_raise_in", "eye_l_brows_lower", "eye_l_dir_dn")))
    bl = tr["eye_l_blink"]
    starts = [i for i in range(1, len(bl)) if bl[i] > 0.4 >= bl[i - 1]]
    check("model: a blink falls in the pause between the phrases", any(1.2 * 30 <= s <= 1.9 * 30 for s in starts), f"blinks at frames {starts}")
    check("model: left and right blink together", tr["eye_l_blink"] == tr["eye_r_blink"])
    check("model: head nods come out as degrees", "head" in r1 and min(r1["head"]["pitch"]) < -0.3, f"min pitch {min(r1['head']['pitch']):.2f}")
    check("model: same seed, same output", r1 == r2)
    old = lipsync.load_profile("speech")
    old.pop("upper_face")
    check("model: a profile without upper_face still works (mouth only)", "eye_l_brows_raise_in" not in lipsync.simulate_lipsync(wav, profile=old)["tracks"])

# ---- 0.2.1: closures, pauses, brows under blinks, moods, neck ----
with tempfile.TemporaryDirectory() as tmp:
    wav = os.path.join(tmp, "voice.wav")
    # "maybe", pause, "bob ate", with a 0.7 s pause between the phrases
    fake_voice(wav, syllables=((0.3, 0.25), (0.6, 0.25), (1.6, 0.25), (1.9, 0.3)), length=2.6)
    r = lipsync.simulate_lipsync(wav, text="maybe. bob ate", profile="speech", seed=2)
    tr = r["tracks"]
    shut = tr.get("lips_together_up", [])
    peaks = [i for i in range(1, len(shut) - 1) if shut[i] > 0.4 and shut[i] >= shut[i - 1] and shut[i] > shut[i + 1]]
    widths = []
    for p in peaks:
        a = b = p
        while a > 0 and shut[a - 1] > shut[p] / 2:
            a -= 1
        while b < len(shut) - 1 and shut[b + 1] > shut[p] / 2:
            b += 1
        widths.append(b - a + 1)
    check("closures: p/b/m presses are short peaks like the game's (<= 6 frames at half height)", peaks and max(widths) <= 6, f"widths {widths}")
    cap = lipsync.load_profile("speech").get("closure_peak", 1.0)
    check("closures: capped at the profile's closure_peak", max(shut) <= cap + 1e-6, f"max {max(shut):.2f}, cap {cap}")
    pause = range(int(1.0 * 30), int(1.45 * 30))
    check("pauses: no press (or any lip shape) in the middle of a pause",
          max(max(tr[k][f] for f in pause) for k in tr if k.startswith("lips_")) < 0.05)
    under = [p for p in tr.get("lips_l_purse", [0] * len(shut))]
    check("closures: other lip shapes give way under a press", all(u < 0.2 for u, s in zip(under, shut) if s > 0.9))
    bl = tr["eye_l_blink"]
    raised = tr.get("eye_l_brows_raise_in", [0.0] * len(bl))
    check("brows: no brow raise while the eyes are shut (as in the game)", all(rv < 0.05 for rv, b in zip(raised, bl) if b > 0.8))
    talk = [f for f in range(len(bl)) if 0.4 * 30 <= f <= 0.75 * 30]
    check("neck: throat tracks are active while talking and rest in silence",
          max(tr["neck_throat_open"][f] for f in talk) > 0.1 and max(tr["neck_throat_open"][f] for f in range(int(1.25 * 30), int(1.45 * 30))) < 0.04)

    scowl = lipsync.simulate_lipsync(wav, text="maybe. bob ate", profile="speech", seed=2, mood="scowl")
    st = scowl["tracks"]
    check("mood: scowl holds the brows down for the whole line, accents ride on top",
          min(st["eye_l_brows_lower"]) >= 0.31 and max(st["eye_l_brows_lower"]) >= max(tr.get("eye_l_brows_lower", [0])), f"{min(st['eye_l_brows_lower']):.2f}")
    check("mood: the result says which mood was used", scowl.get("mood", {}).get("name") == "scowl")
    auto = lipsync.simulate_lipsync(wav, profile="speech", mood="auto")
    check("mood: auto picks a preset and is labelled a guess", auto["mood"]["name"] in lipsync.mood_names() and auto["mood"].get("auto") is True,
          f"{auto['mood']}")
    custom = lipsync.simulate_lipsync(wav, profile="speech", mood={"name": "mine", "tracks": {"eye_l_widen": 0.5}})
    check("mood: a custom preset works", min(custom["tracks"]["eye_l_widen"]) >= 0.5)

    # ---- 0.2.2 ----
    plain = lipsync.simulate_lipsync(wav, text="maybe. bob ate", profile="speech", seed=2)["tracks"]
    raised = max(plain.get("eye_l_brows_raise_in", [0]))
    check("mood: under a held scowl the brows never raise (the game never combines them)",
          raised > 0.1 and max(st.get("eye_l_brows_raise_in", [0])) < 0.01, f"raise without mood {raised:.2f}")
    check("mood: a cancelled raise becomes a little scowl emphasis (<= 25% of it)",
          max(st["eye_l_brows_lower"]) <= 0.324 + max(plain.get("eye_l_brows_lower", [0])) + 0.25 * raised + 1e-6 and max(st["eye_l_brows_lower"]) > 0.33)
    check("mood: presets keep the game's lopsided sides", lipsync.load_mood("scowl")["tracks"]["eye_r_brows_lower"] < lipsync.load_mood("scowl")["tracks"]["eye_l_brows_lower"])
    check("mood: the game's calm preset is there", "calm" in lipsync.mood_names() and lipsync.load_mood("calm")["tracks"])
    ref = lipsync.voice_pitch(wav)
    a2 = lipsync.simulate_lipsync(wav, profile="speech", mood="auto", speaker_pitch=ref)
    check("mood: auto can judge pitch against the same speaker", ref is not None and a2["mood"]["name"] in lipsync.mood_names(), f"ref {ref}")
    oo = lipsync.simulate_lipsync(wav, text="who woo you", profile="speech")["tracks"]
    pf = [p + f for p, f in zip(oo.get("lips_l_purse", [0] * 99), oo.get("lips_l_funnel", [0] * 99))]
    check("lips: purse and funnel never stack past what the game uses (0.6)", max(pf) <= 0.6 + 1e-6, f"max {max(pf):.2f}")
    jumps = [abs(b - a) for k, v in plain.items() if k.startswith("lips_") and "together" not in k for a, b in zip(v, v[1:])]
    check("lips: shapes other than p/b/m presses ease in and out (no pops over 0.25 per frame)", max(jumps) <= 0.25, f"max jump {max(jumps):.2f}")
    # ---- 0.2.3: a tongue that behaves like the game's, soft lips, final smoothing ----
    tg = plain.get("tongue_mid_base_up", [0])
    talk_f = [f for f in range(len(tg)) if 0.35 * 30 <= f <= 0.8 * 30]
    check("tongue: the body rests raised while talking (~0.4-0.6 in the game) and relaxes in pauses",
          0.25 < sum(tg[f] for f in talk_f) / len(talk_f) < 0.8 and max(tg[int(1.2 * 30):int(1.45 * 30)]) < 0.1,
          f"talking {sum(tg[f] for f in talk_f) / len(talk_f):.2f}")
    check("tongue: the tip barely goes up (the game's almost never does)", max(plain.get("tongue_mid_tip_up", [0])) < 0.1)
    check("tongue: it doesn't follow the jaw open (that was the old, unnatural rule)",
          "tongue_mid_base_up" not in lipsync.load_profile("speech")["follow_jaw"])
    press = plain["lips_together_up"]
    check("smoothing: p/b/m presses stay crisp (still reach the cap)", max(press) > 0.9, f"{max(press):.2f}")
    # ---- 0.2.4: hybrid retarget (mouth from the voice, face from the video) ----
    nan = float("nan")
    video = {"jaw_mid_open": np.array([0.05, 0.4, nan]), "lips_l_purse": np.array([0.3, 0.3, 0.3]),
             "eye_l_blink": np.array([0.9, 0.0, nan]), "eye_l_brows_raise_in": np.array([0.2, 0.2, nan]),
             "lips_l_corner_up": np.array([0.5, 0.5, nan]), "tongue_mid_lift": np.array([0.9, 0.9, 0.9])}
    voice = {"jaw_mid_open": np.array([0.3, 0.1, 0.3]), "lips_l_purse": np.array([0.0, 0.5, 0.0]), "tongue_mid_lift": np.array([0.1, 0.1, 0.1]),
             "eye_l_blink": np.array([0.0, 1.0, 0.0])}
    hy = rt.hybrid_tracks(video, voice)
    check("hybrid: jaw is the voice's, unless the video shows the mouth wider", list(hy["jaw_mid_open"]) == [0.3, 0.4, 0.3])
    check("hybrid: lip shapes and tongue come from the voice, not the video", list(hy["lips_l_purse"]) == [0.0, 0.5, 0.0] and list(hy["tongue_mid_lift"]) == [0.1, 0.1, 0.1])
    check("hybrid: blinks, brows and smiles come from the video (and stay empty where no face was seen)",
          hy["eye_l_blink"][0] == 0.9 and np.isnan(hy["eye_l_blink"][2]) and hy["lips_l_corner_up"][1] == 0.5 and "eye_l_brows_raise_in" in hy)
    check("hybrid: speech tracks are recognised (jaw, lip shapes, tongue, neck) and face tracks are not",
          all(rt.is_speech_track(k) for k in ("jaw_mid_open", "lips_together_up", "lips_l_purse", "tongue_mid_lift", "neck_throat_open"))
          and not any(rt.is_speech_track(k) for k in ("eye_l_blink", "eye_l_brows_lower", "lips_l_corner_up", "jaw_mid_shift_l", "nose_l_snear")))
    # ---- 0.2.5: mouth size from the video, lips from the sound alone ----
    mumble = np.concatenate([np.full(60, 0.03), np.full(60, 0.3), np.full(15, np.nan)])
    sz = rt.mouth_size(mumble)
    check("mouth size: small where he mumbles, full where he opens wide, 1 where no face", sz[30] < 0.4 and sz[90] > 0.95 and sz[-1] == 1.0,
          f"{sz[30]:.2f} / {sz[90]:.2f}")
    hv = rt.hybrid_tracks({"jaw_mid_open": np.zeros(3)}, {"jaw_mid_open": np.full(3, 0.3), "tongue_mid_lift": np.full(3, 0.4),
                                                       "lips_together_up": np.full(3, 1.0), "lips_l_pull": np.full(3, 0.2)}, np.array([0.3, 0.3, 1.0]))
    check("hybrid: the voice's jaw and soft lips are scaled by the mouth size, closures and the tongue are not",
          abs(hv["jaw_mid_open"][0] - 0.09) < 1e-6 and abs(hv["lips_l_pull"][0] - 0.06) < 1e-6 and hv["lips_together_up"][0] == 1.0 and hv["tongue_mid_lift"][0] == 0.4)
    import audio_lips
    al_wav = os.path.join(tmp, "al.wav")
    fake_voice(al_wav, syllables=((0.3, 0.25), (0.7, 0.25), (1.1, 0.3)), length=1.8)
    smp, rate_ = lipsync.load_wav(al_wav)
    pred = audio_lips.predict_tracks(smp, rate_, int(1.8 * 30))
    check("sound-only lips: tracks come out for both sides, between 0 and 1, without the jaw or the press",
          "lips_l_pull" in pred and "lips_r_pull" in pred and "jaw_mid_open" not in pred and "lips_together_up" not in pred
          and all(0 <= min(v) and max(v) <= 1 for v in pred.values()), f"{len(pred)} tracks")
    nw = lipsync.simulate_lipsync(al_wav, profile="speech")["tracks"]
    check("sound-only lips: with no words the model now moves the lips and tongue from the sound",
          max(nw["lips_l_corner_up"]) > 0.1 and max(nw["tongue_mid_base_up"]) > 0.3 and max(nw["lips_l_pull"]) > 0.05)
    check("profiles: speech-kerry (one voice) and speech-cyberpunk (six characters) both load",
          lipsync.load_profile("speech-kerry")["name"] == "speech-kerry" and lipsync.load_profile("speech")["name"] == "speech-cyberpunk")

# ---- 0.3.0: mouth smoothing, sweep scoring, hybrid dials ----
perf = sys.modules["performance"]
times = np.arange(0, 6, 1 / 30)
raw = np.zeros((len(times), len(perf.CHANNELS)))
ji, bi, hi = perf.CHANNELS.index("jawOpen"), perf.CHANNELS.index("mouthClose"), perf.CHANNELS.index("headYaw")
raw[:, ji] = 0.3 + 0.2 * np.sin(2 * np.pi * 1.0 * times)
for f in range(30, len(times) - 10, 30):
    raw[f:f + 2, bi] = 0.9                                                  # a 2-frame (67 ms) lip closure
raw[:, hi] = 0.1 * np.sin(2 * np.pi * 8.0 * times)                          # fast jitter on the head
base = dict(perf.DEFAULTS, neutral=False, fill_gaps_s=0)
new, _ = perf.clean(times, raw, base)
old, _ = perf.clean(times, raw, dict(base, mouth_smoothing=False))
check("mouth smoothing: a 67 ms lip closure keeps more of its peak than with the head's smoothing",
      new[:, bi].max() > old[:, bi].max() + 0.05, f"{new[:, bi].max():.2f} vs {old[:, bi].max():.2f}")
check("mouth smoothing: head channels are smoothed exactly as before", np.allclose(new[:, hi], old[:, hi]))

sys.path.insert(0, os.path.join(ROOT, "analyze"))
import analyze as an  # noqa: E402
n = 120
t = np.arange(n) / 30
ref = {"jaw_mid_open": list(0.3 + 0.3 * np.sin(2 * np.pi * 1.5 * t))}
same = an.sweep_scores({"jaw_mid_open": list(ref["jaw_mid_open"])}, ref, n)
shifted = an.sweep_scores({"jaw_mid_open": list(0.3 + 0.3 * np.sin(2 * np.pi * 1.5 * t + 0.2))}, ref, n)
wrong = an.sweep_scores({"jaw_mid_open": list(0.3 + 0.3 * np.sin(2 * np.pi * 2.3 * t))}, ref, n)
check("sweep: identical curves score 1.0 with size 1.0", same["jaw"]["corr"] > 0.99 and abs(same["jaw"]["size"] - 1) < 0.05, str(same["jaw"]))
check("sweep: a small timing offset is forgiven, a different rhythm is not", shifted["jaw"]["corr"] > 0.95 > wrong["jaw"]["corr"], f"{shifted['jaw']['corr']} vs {wrong['jaw']['corr']}")
check("sweep: tracks missing from the reference are skipped", an.sweep_scores({"jaw_mid_open": ref["jaw_mid_open"]}, {}, n) == {})

tr = {"jaw_mid_open": np.full(60, 0.3), "lips_together_up": np.zeros(60)}
tr["lips_together_up"][20:24] = 1.0
cp0 = rt.add_coupling({k: v.copy() for k, v in tr.items()}, 60, 0, 1.0)
cp1 = rt.add_coupling({k: v.copy() for k, v in tr.items()}, 60, 1.0, 1.0)
check("hybrid coupling: strength 0 leaves the tracks as they were", set(cp0) == set(tr) and all(np.array_equal(cp0[k], tr[k]) for k in tr))
check("hybrid coupling: strength 1 adds the cheek, chin and nose tracks", len(cp1) > len(tr))
nan_tr = {k: v.copy() for k, v in tr.items()}
for v in nan_tr.values():
    v[40:] = np.nan
cpn = rt.add_coupling(nan_tr, 60, 1.0, 1.0)
check("hybrid coupling: frames with no face stay empty", all(np.isnan(cpn[k][45]) for k in tr))

# ---- 0.3.1: lips pushed forward kept from the video; forward check ----
n = 120
none = np.full(n, np.nan)
puck = np.zeros(n)
puck[30:45] = 0.6
puck[80:90] = 0.4
voice_p = np.zeros(n)
voice_p[30:45] = 0.2
h = rt.hybrid_tracks({"lips_l_purse": puck.copy(), "lips_r_purse": puck.copy()}, {"lips_l_purse": voice_p.copy(), "lips_r_purse": voice_p.copy()}, size=np.full(n, 0.5))
check("hybrid forward: a clearly puckering video sets the purse (the old merge kept a fifth of it)",
      np.allclose(h["lips_l_purse"], puck) and np.percentile(h["lips_l_purse"], 95) > 0.3, f"{h['lips_l_purse'].max():.2f}")
weak = puck * 0.1
h = rt.hybrid_tracks({"lips_l_purse": weak}, {"lips_l_purse": voice_p.copy()}, size=None)
check("hybrid forward: a weak reading (small face) is lifted, shape kept",
      np.percentile(h["lips_l_purse"], 95) > 2 * np.percentile(weak, 95) and np.corrcoef(h["lips_l_purse"], weak)[0, 1] > 0.99,
      f"{np.percentile(weak, 95):.3f} -> {np.percentile(h['lips_l_purse'], 95):.3f}")
h = rt.hybrid_tracks({"lips_l_purse": np.zeros(n)}, {"lips_l_purse": voice_p.copy()}, size=None)
check("hybrid forward: a video with no pucker at all leaves the voice's purse alone", np.allclose(h["lips_l_purse"], voice_p))
gap = puck.copy()
gap[50:70] = np.nan
h = rt.hybrid_tracks({"lips_l_purse": gap}, {"lips_l_purse": voice_p.copy()}, size=None)
check("hybrid forward: where no face is seen the voice's purse carries on", np.allclose(h["lips_l_purse"][50:70], voice_p[50:70]) and np.allclose(h["lips_l_purse"][30:45], 0.6))
fun = np.zeros(n)
fun[100:110] = 0.5
h = rt.hybrid_tracks({"lips_l_purse": puck.copy(), "lips_l_funnel": np.zeros(n)}, {"lips_l_funnel": fun.copy()}, size=None)
check("hybrid forward: the voice's funnel is kept (MediaPipe's is nearly always 0)", np.allclose(h["lips_l_funnel"], fun))
h = rt.hybrid_tracks({"lips_l_purse": puck.copy()}, {"lips_l_funnel": np.full(n, 0.5)}, size=None)
check("hybrid forward: purse + funnel stay within 0.6", np.all(h["lips_l_purse"] + h["lips_l_funnel"] <= 0.6 + 1e-9))

sys.path.insert(0, os.path.join(ROOT, "analyze"))
import analyze as an2  # noqa: E402
vid = {"lips_l_purse": list(puck)}
good = {"lips_l_purse": list(np.roll(puck, 1))}
flat = {"lips_l_purse": [0.0] * n}
segs = [("OO", 33, 40), ("W", 82, 86), ("OO", 8, 14)]                      # the third has no pucker in the video
sc_good = an2.forward_scores(good, vid, good, segs, n)["purse"]
sc_flat = an2.forward_scores(flat, vid, flat, segs, n)["purse"]
check("forward check: a model that puckers with the video hits both pucker sounds; a flat one hits none",
      sc_good["model"]["hit"] == 1.0 and sc_good["model"]["video_puckers"] == 2 and sc_flat["model"]["hit"] == 0.0,
      f"{sc_good['model']['hit']} vs {sc_flat['model']['hit']}")
check("forward check: whole-clip correlation is high for the matching curve and a pucker the video lacks counts as false",
      sc_good["model"]["corr"] > 0.95 and sc_good["model"]["false"] == 0.0 and an2.forward_scores({"lips_l_purse": [0.5] * n}, vid, good, segs, n)["purse"]["model"]["false"] > 0)

# ---- 0.3.2: lip separation led by the video when it reads the mouth at the rig's scale ----
n = 150
t_ = np.arange(n) / 30
jaw_v = np.clip(0.5 + 0.45 * np.sin(2 * np.pi * 0.8 * t_), 0, 1)             # a rig-sized reading (95th percentile ~0.9)
weak_v = jaw_v * 0.15
check("video-led mouth: a rig-sized jaw reading is trusted, a small face's is not", rt.video_mouth_trusted(jaw_v) and not rt.video_mouth_trusted(weak_v))
drop = np.zeros(n)
drop[60:90] = 0.7                                                             # lips apart with the jaw shut: only the lower lip's drop shows it
shut = jaw_v.copy()
shut[60:90] = 0.02
video = {"jaw_mid_open": shut, "lips_apart_dn": drop, "lips_l_upper_raise": drop * 0.5}
voice = {"jaw_mid_open": np.full(n, 0.7), "lips_apart_dn": np.full(n, 0.5), "lips_apart_up": np.full(n, 0.9), "lips_l_lower_raise": np.full(n, 0.6)}
h = rt.hybrid_tracks(video, voice, size=None, led=True, follow={"lips_apart_up": 1.29, "lips_l_lower_raise": 1.0, "lips_apart_dn": 0.82})
check("video-led mouth: the jaw and the lower lip's drop are the video's, so lips can part with the jaw shut",
      np.allclose(h["jaw_mid_open"], shut) and np.allclose(h["lips_apart_dn"], drop) and h["jaw_mid_open"][75] < 0.05 < h["lips_apart_dn"][75])
check("video-led mouth: the tracks that ride on the jaw ride on the video's jaw, not the voice's",
      np.allclose(h["lips_apart_up"], np.clip(1.29 * shut, 0, 1)) and np.allclose(h["lips_l_lower_raise"], np.clip(shut, 0, 1)))
h0 = rt.hybrid_tracks(video, voice, size=None, led=False)
check("voice-led mouth (the default for a weak reading) is unchanged", np.allclose(h0["lips_apart_dn"], 0.5) and h0["jaw_mid_open"][75] >= 0.7)
gap = shut.copy()
gap[:20] = np.nan
hg = rt.hybrid_tracks({"jaw_mid_open": gap, "lips_apart_dn": np.where(np.isnan(gap), np.nan, drop)}, voice, size=None, led=True, follow={"lips_apart_up": 1.0})
check("video-led mouth: where no face is seen the voice's mouth carries on", np.allclose(hg["jaw_mid_open"][:20], 0.7) and np.allclose(hg["lips_apart_dn"][:20], 0.5))

# ---- 0.3.4: a rounded mouth is a purse while the lips are shut and a funnel as they part ----
n = 120
pk = np.zeros(n)
pk[20:50] = 0.9                                    # a pout, lips shut
pk[70:100] = 0.9                                   # the same reading with the lips well apart: a sung "o"
gp = np.zeros(n)
gp[70:100] = 0.14
tk = {"lips_l_purse": pk.copy(), "lips_r_purse": pk.copy()}
tk = rt.split_round_mouth(tk, gp)
check("round mouth: lips shut keeps the purse and no funnel", tk["lips_l_purse"][35] > 0.55 and tk["lips_l_funnel"][35] < 0.05,
      f"purse {tk['lips_l_purse'][35]:.2f}, funnel {tk['lips_l_funnel'][35]:.2f}")
check("round mouth: lips apart moves the reading to the funnel", tk["lips_l_funnel"][85] > 0.5 and tk["lips_l_purse"][85] < 0.05,
      f"purse {tk['lips_l_purse'][85]:.2f}, funnel {tk['lips_l_funnel'][85]:.2f}")
mid = {"lips_l_purse": pk.copy()}
gm = np.full(n, 0.07)
mid = rt.split_round_mouth(mid, gm)
check("round mouth: in between it blends, and purse + funnel never pass 0.6", np.all(mid["lips_l_purse"] + mid["lips_l_funnel"] <= 0.6 + 1e-9) and 0.05 < mid["lips_l_funnel"][35] < mid["lips_l_purse"][35] + 0.6)
vf = {"lips_l_purse": np.zeros(n), "lips_l_funnel": np.full(n, 0.3)}
check("round mouth: a funnel MediaPipe did read is kept", np.allclose(rt.split_round_mouth(vf, np.zeros(n))["lips_l_funnel"], 0.3))
g2 = gp.copy()
nanp = pk.copy()
nanp[10:15] = np.nan
res = rt.split_round_mouth({"lips_l_purse": nanp}, g2)
check("round mouth: frames with no face stay empty", np.isnan(res["lips_l_purse"][10:15]).all() and not np.isnan(res["lips_l_purse"][40]))
check("round mouth: strength 0 leaves the mapped tracks alone", np.allclose(rt.split_round_mouth({"lips_l_purse": pk.copy()}, gp, 0.0)["lips_l_purse"], pk))

# ---- 0.3.5: the head's lips are parted wherever the video's are ----
n = 150
gap = np.zeros(n)
gap[40:80] = 0.09                                  # lips apart on the video, jaw at 0 (the upper lip lifts, the teeth show)
gap[100:120] = 0.005                               # shut
tr = {"jaw_mid_open": np.zeros(n), "lips_apart_dn": np.zeros(n), "lips_apart_up": np.zeros(n), "lips_l_upper_raise": np.full(n, 0.24)}
out = rt.fill_lip_gap({k: v.copy() for k, v in tr.items()}, gap)
shown = lambda T, f: 0.02 + 0.183 * T["jaw_mid_open"][f] + 0.156 * T["lips_apart_dn"][f] + 0.037 * T["lips_l_upper_raise"][f]
check("lip gap: lips parted on the video but shut on the head are opened (half the shortfall to each lip, 0.156 per unit of lower-lip drop)",
      shown(tr, 60) < 0.035 and abs(out["lips_apart_dn"][60] - 0.5 * (0.09 - shown(tr, 60)) / 0.156) < 0.03 and abs(out["lips_apart_up"][60] - out["lips_apart_dn"][60]) < 1e-6,
      f"lower {out['lips_apart_dn'][60]:.2f}, upper {out['lips_apart_up'][60]:.2f}")
check("lip gap: lips shut on the video stay shut", out["lips_apart_dn"][110] < 0.01 and out["lips_apart_up"][110] < 0.01)
big = {"jaw_mid_open": np.full(n, 0.8), "lips_apart_dn": np.full(n, 0.6), "lips_apart_up": np.full(n, 0.6)}
after = rt.fill_lip_gap({k: v.copy() for k, v in big.items()}, np.full(n, 0.02))
check("lip gap: it only opens the lips, never closes them", all(np.allclose(after[k], big[k]) for k in big))
clos = {k: v.copy() for k, v in tr.items()}
clos["lips_together_up"] = np.zeros(n)
clos["lips_together_up"][60:70] = 1.0
res = rt.fill_lip_gap(clos, gap)
check("lip gap: a p/b/m closure stays closed", np.allclose(res["lips_apart_dn"][60:70], 0) and res["lips_apart_dn"][50] > 0.05)
nf = gap.copy()
nf[40:50] = np.nan
res = rt.fill_lip_gap({k: v.copy() for k, v in tr.items()}, nf)
check("lip gap: frames with no face are left as they are", np.allclose(res["lips_apart_dn"][41:49], 0))
check("lip gap: strength 0 leaves the tracks alone", np.allclose(rt.fill_lip_gap({k: v.copy() for k, v in tr.items()}, gap, 0.0)["lips_apart_dn"], 0))

print(f"{'ALL ' + str(len(results)) + ' PASSED' if all(results) else str(results.count(False)) + ' FAILED'}")
sys.exit(0 if all(results) else 1)

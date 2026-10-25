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

print(f"{'ALL ' + str(len(results)) + ' PASSED' if all(results) else str(results.count(False)) + ' FAILED'}")
sys.exit(0 if all(results) else 1)

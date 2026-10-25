"""
LipScan performance capture: the whole face, frame by frame, from a trace.

A trace is a folder written by the LipScan capture tool (frames\\*.jpg + audio.wav + trace.json). For every frame,
on the video's own clock, this saves:
  - all 52 MediaPipe blendshape values (brows, eyes, cheeks, nose, jaw, mouth; "_neutral" included)
  - head pose: yaw, pitch, roll in degrees, plus position (x, y, z in cm, relative to the camera)
  - gaze per eye: yaw and pitch in degrees, worked out from the eyeLook* blendshapes
  - how sure the face detector was, and whether the face was seen at all (dropped frames are gaps, never zeros)

Then it cleans the curves up. Every step is on by default and can be switched off:
  - one face only: locks onto the main face (largest, steadiest) and never jumps to another face mid-trace
  - gaps shorter than 0.2 s are filled; longer ones stay empty (null)
  - neutral calibration: the person's resting face, estimated from their calmest frames, is subtracted, so a
    naturally low brow doesn't read as a frown
  - one-euro smoothing, with settings that keep blinks

    python performance.py "<trace folder>"
    python performance.py "<trace folder>" --no-neutral --no-smooth     # switch steps off
    python performance.py "<trace folder>" --keep-head-angle            # head angles stay relative to the camera
    python performance.py "<trace folder>" --reclean --gap 0.3           # clean again without re-tracking

Writes performance.json into the trace folder (format: docs/PERFORMANCE.md).

Tracking, not recognition: no face points, face prints or anything else that could identify a person is stored.
Only expression values, head pose, gaze and confidence.
Needs: pip install mediapipe numpy, and the models from analyze/get_model.py.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANDMARKER = os.environ.get("LIPSCAN_FACE_MODEL", os.path.join(ROOT, "models", "face_landmarker.task"))
DETECTOR = os.environ.get("LIPSCAN_DETECTOR_MODEL", os.path.join(ROOT, "models", "blaze_face_short_range.tflite"))
FORMAT = "lipscan-performance/1"

# MediaPipe's 52 blendshape categories, in its own order. "Left" is the SUBJECT's left (checked: docs/PERFORMANCE.md).
BLENDSHAPES = [
    "_neutral", "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight", "eyeLookDownLeft",
    "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft", "eyeLookOutRight", "eyeLookUpLeft",
    "eyeLookUpRight", "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight", "jawForward", "jawLeft",
    "jawOpen", "jawRight", "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthFunnel", "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight",
    "mouthPucker", "mouthRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft", "mouthStretchRight", "mouthUpperUpLeft",
    "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight",
]
HEAD = ["headYaw", "headPitch", "headRoll", "headX", "headY", "headZ"]
GAZE = ["gazeLeftYaw", "gazeLeftPitch", "gazeRightYaw", "gazeRightPitch"]
# Lip geometry, as ratios of the face's own eye distance (so the zoom doesn't matter; nothing here identifies anyone):
#   lipGap    the gap between the inner lips        mouthWidth  the width of the mouth
# Recorded for analysis; nothing is mapped from them. A p/b/m closure detector built on lipGap scored only 0.18-0.36 against known
# presses, with many false alarms, so it isn't used (MediaPipe's own mouthClose barely fires on a press either).
LIPGEO = ["lipGap", "mouthWidth"]
CHANNELS = BLENDSHAPES + HEAD + GAZE + LIPGEO

# How far the eyes turn at eyeLook* = 1, in degrees. MediaPipe doesn't publish this; these are typical eye ranges.
GAZE_DEG = {"yaw": 35.0, "pitch": 25.0}

# Blinks and eye moves are fast; smoothing them like the rest would erase them.
FAST = {"eyeBlinkLeft", "eyeBlinkRight", "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight"} | \
       {c for c in BLENDSHAPES if c.startswith("eyeLook")} | set(GAZE)

# Mouth shapes (jaw, lips, cheeks, nose) are fast too: a p/b/m closure lasts about 130 ms, and at the slow filter's 1.5 Hz base cutoff it
# is mostly smoothed away. They get their own lighter setting, between the slow channels (head pose, brows) and the eyes.
MOUTH_PREFIXES = ("jaw", "mouth", "cheek", "nose")
MOUTH = {c for c in BLENDSHAPES if c.startswith(MOUTH_PREFIXES)} | {"lipGap", "mouthWidth"}

DEFAULTS = {
    "lock_face": True, "fill_gaps_s": 0.2, "neutral": True, "neutral_head": True, "neutral_fraction": 0.1, "smooth": True,
    "one_euro": {"min_cutoff_hz": 1.5, "beta": 0.5, "fast_min_cutoff_hz": 6.0, "fast_beta": 4.0, "d_cutoff_hz": 1.0,
                 "mouth_min_cutoff_hz": 3.0, "mouth_beta": 2.0},
    # an optional second look at the locked face on an enlarged crop (blendshapes from the crop, head pose from the whole frame).
    # Off by default: on a clip with known mouth values it LOWERED the match (jaw 0.69 -> 0.60), so it isn't worth the time.
    "refine": False, "refine_scale": 1.8, "refine_px": 384,
    "mouth_smoothing": True,
}


# ----------------------------------------------------------------------------
# Head pose and gaze
# ----------------------------------------------------------------------------
def head_pose(matrix):
    """MediaPipe's facial transformation matrix (4x4, face model -> camera, cm) -> yaw, pitch, roll (degrees) and
    x, y, z (cm). Subject-centred: yaw > 0 turns to the subject's own left, pitch > 0 lifts the chin,
    roll > 0 tilts the head toward the subject's left shoulder."""
    m = np.asarray(matrix, dtype=float)
    r = m[:3, :3] / np.linalg.norm(m[:3, :3], axis=0)  # drop any scale
    yaw = math.degrees(math.atan2(r[0, 2], r[2, 2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, r[1, 2]))))
    roll = -math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return [yaw, pitch, roll, float(m[0, 3]), float(m[1, 3]), float(m[2, 3])]


def gaze(bs):
    """Per-eye gaze from the eyeLook* values. Yaw > 0 looks toward the subject's left, pitch > 0 looks up."""
    g = lambda k: bs.get(k, 0.0)
    return [
        (g("eyeLookOutLeft") - g("eyeLookInLeft")) * GAZE_DEG["yaw"],
        (g("eyeLookUpLeft") - g("eyeLookDownLeft")) * GAZE_DEG["pitch"],
        (g("eyeLookInRight") - g("eyeLookOutRight")) * GAZE_DEG["yaw"],
        (g("eyeLookUpRight") - g("eyeLookDownRight")) * GAZE_DEG["pitch"],
    ]


# ----------------------------------------------------------------------------
# One face only
# ----------------------------------------------------------------------------
def box(landmarks):
    xs = [p.x for p in landmarks]
    ys = [p.y for p in landmarks]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(max(xs) - min(xs), max(ys) - min(ys)))


class FaceLock:
    """Picks the main face and stays with it. Only position and size are used (never what the face looks like):
    the first pick is the largest face; after that, the face nearest the last one, of similar size. If the face
    is lost, it's picked up again only near where it was last seen (looser after a while), never a different
    face elsewhere in the frame."""

    def __init__(self):
        self.last = None   # (x, y, size)
        self.lost = 0

    def pick(self, boxes):
        if not boxes:
            self.lost += 1
            return None
        if self.last is None:
            i = max(range(len(boxes)), key=lambda k: boxes[k][2])
        else:
            x, y, s = self.last
            reach = s * (0.6 + min(1.0, self.lost / 30))   # up to 1.6 face widths after a second lost
            best, i = None, None
            for k, (bx, by, bs) in enumerate(boxes):
                d = math.hypot(bx - x, by - y)
                if d <= reach and 0.6 <= bs / s <= 1.6 and (best is None or d < best):
                    best, i = d, k
            if i is None:
                self.lost += 1
                return None
        self.last = boxes[i]
        self.lost = 0
        return i


# ----------------------------------------------------------------------------
# Tracking
# ----------------------------------------------------------------------------
def lip_geometry(lm):
    """(gap between the inner lips, mouth width), each divided by the distance between the outer eye corners."""
    eyes = math.dist((lm[33].x, lm[33].y), (lm[263].x, lm[263].y)) or 1e-6
    return (math.dist((lm[13].x, lm[13].y), (lm[14].x, lm[14].y)) / eyes,
            math.dist((lm[61].x, lm[61].y), (lm[291].x, lm[291].y)) / eyes)


def crop_face(path, landmarks, scale, px):
    """The locked face on an enlarged square crop, as a MediaPipe image (None if it can't be cut)."""
    import mediapipe as mp
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    xs, ys = [p.x for p in landmarks], [p.y for p in landmarks]
    cx, cy = (min(xs) + max(xs)) / 2 * w, (min(ys) + max(ys)) / 2 * h
    side = scale * max((max(xs) - min(xs)) * w, (max(ys) - min(ys)) * h)
    if side < 24:
        return None
    box_ = (int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2))
    out = im.crop(box_).resize((px, px), Image.LANCZOS)              # PIL pads outside the frame with black
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(out))


def track(folder, trace, lock=True, refine=False, refine_scale=1.8, refine_px=384):
    """Runs MediaPipe on every frame. Returns (times, raw values [frames x channels] with NaN gaps, confidence)."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    if not os.path.exists(LANDMARKER):
        sys.exit(f"Missing {LANDMARKER}. Run: python analyze/get_model.py")
    lm_opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=LANDMARKER), running_mode=vision.RunningMode.VIDEO,
        num_faces=4 if lock else 1, output_face_blendshapes=True, output_facial_transformation_matrixes=True)
    crop_lm = None
    if refine:                                          # still images, one face: no tracking state across crops
        crop_lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=LANDMARKER), running_mode=vision.RunningMode.IMAGE, num_faces=1,
            output_face_blendshapes=True))
    detector = None
    if os.path.exists(DETECTOR):
        detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=DETECTOR), running_mode=vision.RunningMode.VIDEO))
    else:
        print(f"  (no {os.path.basename(DETECTOR)}: confidence won't be saved; run analyze/get_model.py)")
    frames = trace["frames"]
    t0 = trace["start"]
    times = np.array([f["t"] - t0 for f in frames], dtype=float)
    raw = np.full((len(frames), len(CHANNELS)), np.nan)
    conf = np.full(len(frames), np.nan)
    faces = np.zeros(len(frames), dtype=int)
    locker = FaceLock()
    last_ms = -1
    refined = 0
    with vision.FaceLandmarker.create_from_options(lm_opts) as lm:
        for k, fr in enumerate(frames):
            ms = max(last_ms + 1, round(times[k] * 1000))
            last_ms = ms
            img = mp.Image.create_from_file(os.path.join(folder, fr["file"]))
            res = lm.detect_for_video(img, ms)
            boxes = [box(f) for f in res.face_landmarks]
            faces[k] = len(boxes)
            i = locker.pick(boxes) if lock else (0 if boxes else None)
            if i is not None:
                bs = {b.category_name: b.score for b in res.face_blendshapes[i]}
                lms = res.face_landmarks[i]
                if crop_lm is not None:
                    cimg = crop_face(os.path.join(folder, fr["file"]), res.face_landmarks[i], refine_scale, refine_px)
                    cres = crop_lm.detect(cimg) if cimg is not None else None
                    if cres is not None and cres.face_blendshapes:          # the crop's reading replaces the whole-frame one
                        bs = {b.category_name: b.score for b in cres.face_blendshapes[0]}
                        lms = cres.face_landmarks[0]
                        refined += 1
                row = [bs.get(c, np.nan) for c in BLENDSHAPES]
                row += head_pose(res.facial_transformation_matrixes[i]) if res.facial_transformation_matrixes else [np.nan] * 6
                row += gaze(bs)
                row += list(lip_geometry(lms))
                raw[k] = row
                if detector is not None:
                    det = detector.detect_for_video(img, ms).detections
                    bx, by, _ = boxes[i]
                    near = [d for d in det if abs((d.bounding_box.origin_x + d.bounding_box.width / 2) / img.width - bx) < 0.15
                            and abs((d.bounding_box.origin_y + d.bounding_box.height / 2) / img.height - by) < 0.15]
                    conf[k] = max((d.categories[0].score for d in near), default=0.0)
            if k % 300 == 0:
                print(f"  tracking: frame {k + 1} of {len(frames)}", flush=True)
    if detector is not None:
        detector.close()
    if crop_lm is not None:
        crop_lm.close()
        print(f"  enlarged-crop pass used on {refined} of {len(frames)} frames", flush=True)
    return times, raw, conf, faces


# ----------------------------------------------------------------------------
# Clean-up (pure functions, unit tested in test/test_performance.py)
# ----------------------------------------------------------------------------
def fill_gaps(times, col, longest):
    """Fill NaN runs no longer than `longest` seconds by straight lines; leave longer runs (and the ends) NaN."""
    out = col.copy()
    good = np.where(~np.isnan(col))[0]
    for a, b in zip(good, good[1:]):
        if b - a > 1 and times[b] - times[a] <= longest + 1e-9:
            out[a + 1:b] = np.interp(times[a + 1:b], [times[a], times[b]], [col[a], col[b]])
    return out


def one_euro(times, col, min_cutoff, beta, d_cutoff=1.0):
    """One-euro filter (Casiez et al. 2012): smooths slow movement a lot and fast movement little, so blinks keep
    their depth. Restarts after every gap."""
    out = np.full_like(col, np.nan)
    prev_t = prev_x = prev_dx = None
    alpha = lambda cutoff, dt: 1.0 / (1.0 + 1.0 / (2 * math.pi * cutoff * dt))
    for k, (t, x) in enumerate(zip(times, col)):
        if np.isnan(x):
            prev_t = prev_x = prev_dx = None
            continue
        if prev_t is None or t <= prev_t:
            out[k], prev_t, prev_x, prev_dx = x, t, x, 0.0
            continue
        dt = t - prev_t
        dx = (x - prev_x) / dt
        a_d = alpha(d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * prev_dx
        a = alpha(min_cutoff + beta * abs(dx_hat), dt)
        x_hat = a * x + (1 - a) * prev_x
        out[k], prev_t, prev_x, prev_dx = x_hat, t, x_hat, dx_hat
    return out


def calm_frames(values, fraction):
    """Indices of the calmest frames: least total expression (eyes open, mouth closed) and least movement."""
    bs = values[:, 1:len(BLENDSHAPES)]
    seen = ~np.isnan(bs).any(axis=1)
    if seen.sum() < 5:
        return np.array([], dtype=int)
    activity = np.nansum(bs, axis=1)
    motion = np.zeros(len(values))
    motion[1:] = np.nansum(np.abs(np.diff(bs, axis=0)), axis=1)
    score = np.where(seen, activity + 3 * motion, np.inf)
    n = max(5, int(seen.sum() * fraction))
    return np.argsort(score)[:n]


def neutral_face(values, fraction, head=True):
    """The person's resting value of each blendshape (median over the calmest frames), and (head=True) the head's
    resting orientation: the median over the whole trace, so someone sitting turned toward the camera faces forward.
    Blink and gaze channels are left alone (a resting eye is open and the camera decides where it looks)."""
    idx = calm_frames(values, fraction)
    rest = np.zeros(len(CHANNELS))
    if not len(idx):
        return rest
    med = np.nanmedian(values[idx], axis=0)
    for c, name in enumerate(CHANNELS):
        if name in BLENDSHAPES and not name.startswith(("eyeBlink", "eyeLook", "_")):
            rest[c] = med[c]
    if head:
        for name in ("headYaw", "headPitch", "headRoll"):
            c = CHANNELS.index(name)
            rest[c] = np.nanmedian(values[:, c])
    return rest


def remove_neutral(values, rest):
    """Blendshapes: (value - rest) / (1 - rest), clipped to 0..1, so the full range stays reachable.
    Head angles: relative to the resting orientation. Position and gaze: unchanged."""
    out = values.copy()
    for c, name in enumerate(CHANNELS):
        if name in BLENDSHAPES and rest[c]:
            out[:, c] = np.clip((values[:, c] - rest[c]) / max(1e-6, 1 - rest[c]), 0, 1)
        elif name in ("headYaw", "headPitch", "headRoll"):
            out[:, c] = values[:, c] - rest[c]
    return out


def clean(times, raw, settings):
    v = raw.copy()
    if settings["fill_gaps_s"]:
        v = np.stack([fill_gaps(times, v[:, c], settings["fill_gaps_s"]) for c in range(v.shape[1])], axis=1)
    rest = neutral_face(v, settings["neutral_fraction"], settings.get("neutral_head", True)) if settings["neutral"] else np.zeros(len(CHANNELS))
    if settings["neutral"]:
        v = remove_neutral(v, rest)
    if settings["smooth"]:
        e = settings["one_euro"]
        for c, name in enumerate(CHANNELS):
            fast = name in FAST
            if name in MOUTH and settings.get("mouth_smoothing", True):         # mouth shapes: lighter than slow channels
                mc, mb = e.get("mouth_min_cutoff_hz", e["min_cutoff_hz"]), e.get("mouth_beta", e["beta"])
            else:
                mc, mb = (e["fast_min_cutoff_hz"], e["fast_beta"]) if fast else (e["min_cutoff_hz"], e["beta"])
            v[:, c] = one_euro(times, v[:, c], mc, mb, e["d_cutoff_hz"])
            if name in BLENDSHAPES:
                v[:, c] = np.clip(v[:, c], 0, 1)
    return v, rest


# ----------------------------------------------------------------------------
# performance.json
# ----------------------------------------------------------------------------
def col_json(col, nd=4):
    return [None if np.isnan(x) else round(float(x), nd) for x in col]


def write(folder, trace, times, raw, values, conf, faces, rest, settings):
    seen = ~np.isnan(values[:, CHANNELS.index("jawOpen")])
    span = times[-1] - times[0] if len(times) > 1 else 0
    perf = {
        "format": FORMAT,
        "source": trace.get("source", {}),
        "clock": {"video_start": trace["start"], "note": "t is seconds from video_start, on the video's own clock; "
                  "audio.wav in the trace starts at the trace's audio.start"},
        "fps": round((len(times) - 1) / span, 3) if span > 0 else None,
        "frames": len(times),
        "face_seen": round(float(seen.mean()), 3) if len(seen) else 0,
        "settings": settings,
        "conventions": {
            "sides": "Left/Right = the SUBJECT's own left/right (MediaPipe convention, verified)",
            "head": "degrees; yaw > 0 turns to the subject's left, pitch > 0 chin up, roll > 0 toward the left shoulder; "
                    "x/y/z in cm from the camera (MediaPipe's face model space)",
            "gaze": f"degrees per eye; yaw > 0 toward the subject's left, pitch > 0 up; eyeLook = 1 taken as {GAZE_DEG}",
            "gaps": "null = no face (or a gap longer than fill_gaps_s); never 0",
        },
        "neutral": {c: round(float(rest[i]), 4) for i, c in enumerate(CHANNELS) if rest[i]},
        "t": [round(float(x), 4) for x in times],
        "file": [f["file"] for f in trace["frames"]],
        "confidence": col_json(conf, 3),
        "faces_in_frame": [int(x) for x in faces],
        "channels": {c: col_json(values[:, i], 3 if c in HEAD + GAZE else 4) for i, c in enumerate(CHANNELS)},
        "raw": {c: col_json(raw[:, i], 3 if c in HEAD + GAZE else 4) for i, c in enumerate(CHANNELS)},
    }
    path = os.path.join(folder, "performance.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(perf, fh, separators=(",", ":"))
    return path, perf


def load_raw(path):
    p = json.load(open(path, encoding="utf-8"))
    nan = lambda xs: np.array([np.nan if x is None else x for x in xs], dtype=float)
    raw = np.stack([nan(p["raw"].get(c, [None] * len(p["t"]))) for c in CHANNELS], axis=1)
    return np.array(p["t"]), raw, nan(p["confidence"]), np.array(p["faces_in_frame"])


def main():
    ap = argparse.ArgumentParser(description="Track the whole face in a LipScan trace and write performance.json.")
    ap.add_argument("folder")
    ap.add_argument("--no-lock", action="store_true", help="don't lock onto one face (use whichever MediaPipe sees first)")
    ap.add_argument("--gap", type=float, default=DEFAULTS["fill_gaps_s"], help="fill gaps up to this many seconds (0: off)")
    ap.add_argument("--no-neutral", action="store_true", help="don't subtract the resting face")
    ap.add_argument("--keep-head-angle", action="store_true", help="keep head angles relative to the camera (don't subtract the median)")
    ap.add_argument("--no-smooth", action="store_true", help="no one-euro smoothing")
    ap.add_argument("--reclean", action="store_true", help="re-use the raw values in performance.json; only clean again")
    ap.add_argument("--mouth-cutoff", type=float, help="smoothing for mouth shapes: base cutoff in Hz (default %s; lower = smoother)" % DEFAULTS["one_euro"]["mouth_min_cutoff_hz"])
    ap.add_argument("--mouth-beta", type=float, help="smoothing for mouth shapes: how fast it opens up on quick movement (default %s)" % DEFAULTS["one_euro"]["mouth_beta"])
    ap.add_argument("--refine", action="store_true", help="also re-read the face on an enlarged crop (slower; measured to lower the match, so off by default)")
    ap.add_argument("--legacy-mouth", action="store_true", help="the 0.2.x behaviour: mouth channels smoothed like slow ones, no enlarged-crop pass")
    a = ap.parse_args()
    folder = os.path.abspath(a.folder)
    trace = json.load(open(os.path.join(folder, "trace.json"), encoding="utf-8"))
    settings = json.loads(json.dumps(DEFAULTS))
    settings.update(lock_face=not a.no_lock, fill_gaps_s=max(0.0, a.gap), neutral=not a.no_neutral,
                    neutral_head=not a.keep_head_angle, smooth=not a.no_smooth)
    if a.legacy_mouth:
        settings.update(refine=False, mouth_smoothing=False)
    if a.refine:
        settings["refine"] = True
    if a.mouth_cutoff is not None:
        settings["one_euro"]["mouth_min_cutoff_hz"] = a.mouth_cutoff
    if a.mouth_beta is not None:
        settings["one_euro"]["mouth_beta"] = a.mouth_beta
    existing = os.path.join(folder, "performance.json")
    if a.reclean and os.path.exists(existing):
        times, raw, conf, faces = load_raw(existing)
        settings["lock_face"] = json.load(open(existing))["settings"]["lock_face"]
    else:
        print(f"Tracking the face in {len(trace['frames'])} frames...")
        times, raw, conf, faces = track(folder, trace, settings["lock_face"], settings["refine"], settings["refine_scale"], settings["refine_px"])
    values, rest = clean(times, raw, settings)
    path, perf = write(folder, trace, times, raw, values, conf, faces, rest, settings)
    print(f"Wrote {path}: {perf['frames']} frames, face seen in {perf['face_seen'] * 100:.0f}%, "
          f"{len(CHANNELS)} channels ({len(BLENDSHAPES)} blendshapes, head, gaze)")


if __name__ == "__main__":
    main()

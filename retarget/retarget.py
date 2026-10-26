"""
LipScan retarget: a recorded performance (performance.json) -> face-rig curves a viewer or game can play.

    python retarget.py "<trace folder>"                          # writes <trace>/retarget-cyberpunk.json
    python retarget.py "<trace folder>" --export cyberpunk       # game dialogue-layer names ("...LipsyncPoseOutput")
    python retarget.py "<trace folder>" --export arkit52         # the cleaned MediaPipe values under ARKit names
    python retarget.py "<trace folder>" --mapping my-mapping.json --no-tongue --out x.json

The mapping (export/mediapipe_to_cyberpunk.json by default) says which face tracks each MediaPipe blendshape drives,
with a gain, offset and clamp. Head pose goes into "head" (degrees) and gaze into the eye-direction tracks.
Video tracking can't see the tongue, so by default the tongue tracks come from the audio model (model/lipsync.py)
run on the trace's own audio and caption words.

Output: {"fps": 30, "tracks": {name: [value per frame, null where no face was seen]}, "head": {"yaw", "pitch",
"roll": [...]}, "video": {...}} on the trace's clock (frame 0 = trace start), so the trace's audio.wav lines up.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "model"))
sys.path.insert(0, os.path.join(ROOT, "analyze"))
DEFAULT_MAPPING = os.path.join(ROOT, "export", "mediapipe_to_cyberpunk.json")
FPS = 30


def load_mapping(path=DEFAULT_MAPPING):
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    if m.get("format") != "lipscan-mapping/1":
        raise SystemExit(f"{path} isn't a LipScan mapping (format lipscan-mapping/1).")
    return m


def resample(times, col, n, longest=0.2):
    """Values at frame k / FPS. Spans between samples longer than `longest` (or outside them) stay NaN."""
    grid = np.arange(n) / FPS
    good = ~np.isnan(col)
    if good.sum() < 2:
        return np.full(n, np.nan)
    t, v = times[good], col[good]
    out = np.interp(grid, t, v)
    idx = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
    out[(t[idx] - t[idx - 1]) > longest + 1e-9] = np.nan
    out[(grid < t[0] - 1e-9) | (grid > t[-1] + 1e-9)] = np.nan
    return out


def apply_mapping(channels, mapping):
    """channels: {MediaPipe name: array}. Returns ({track: array}, unused sources)."""
    tracks, unused = {}, []
    for src, targets in mapping["map"].items():
        x = channels.get(src)
        if x is None:
            unused.append(src)
            continue
        for e in targets:
            lo, hi = e.get("clamp", [0, 1])
            y = np.clip(e.get("gain", 1.0) * x + e.get("offset", 0.0), lo, hi)
            cur = tracks.get(e["track"])
            # largest wins; NaN (no face) stays NaN
            tracks[e["track"]] = y if cur is None else np.where(np.isnan(cur), y, np.fmax(cur, y))
    return tracks, unused


def head_curves(channels, mapping):
    h = mapping.get("head", {})
    gain, limit = h.get("gain", {}), h.get("limit_deg", {})
    out = {}
    for k, name in (("yaw", "headYaw"), ("pitch", "headPitch"), ("roll", "headRoll")):
        x = channels.get(name)
        if x is not None:
            lim = limit.get(k, 90)
            out[k] = np.clip(x * gain.get(k, 1.0), -lim, lim)
    return out


# Tracks that speech drives (jaw, lip shapes, tongue, neck). A hybrid takes these from the voice model, because a
# small or turned face in a video gives a weak mouth reading (jaw ~2x too small, correlation with the voice 0.3-0.4,
# against 0.9+ for the voice model), and everything else (head, brows, eyes, blinks, gaze, cheeks, nose, smiles and
# frowns) from the video, which the voice can't know.
SPEECH_PREFIXES = ("tongue_", "neck_throat", "neck_tighten", "neck_l_platysma", "neck_r_platysma", "neck_l_stern", "neck_r_stern")
SPEECH_LIPS = ("together", "purse", "funnel", "suck", "lower_raise", "stretch", "pull", "chin_raise", "apart", "tighten",
               "upper_raise", "corner_stretch")


def is_speech_track(name):
    if name == "jaw_mid_open" or name.startswith(SPEECH_PREFIXES):
        return True
    return name.startswith("lips_") and any(k in name for k in SPEECH_LIPS)


BURST = "burst:"


def voice_file(folder, audio):
    """The recording the voice model reads: vocals.wav (the isolated voice, made by analyze/separate.py) when the trace has one, else
    the trace's own audio. Playback always uses the audio itself, the full mix."""
    v = os.path.join(folder, "vocals.wav")
    return v if os.path.exists(v) else os.path.join(folder, audio["file"])


def audio_tracks(folder, trace, n, profile="speech", **dials):
    """All of the voice model's tracks for the trace's own audio (caption words when there are any), on the trace's clock.
    dials: articulation, expressiveness (the model's own); the coupling is added afterwards, on the merged mouth."""
    import lipsync
    from analyze import caption_words
    audio = trace.get("audio")
    if not audio:
        return {}, 0
    words, _ = caption_words(folder, trace["start"], n / FPS)
    res = lipsync.simulate_lipsync(voice_file(folder, audio), profile=profile, words=words or None, coupling=0, **dials)
    shift = round((audio.get("start", trace["start"]) - trace["start"]) * FPS)   # audio may start after the trace
    out = {}
    for k, v in res["tracks"].items():
        a = np.zeros(n)
        v = np.array(v[:max(0, n - shift)])
        a[shift:shift + len(v)] = v
        out[k] = a
    for k, v in (res.get("velar") or {}).items():                  # the k/g burst alone (a profile with velar_lips), for the hybrid to add
        a = np.zeros(n)
        v = np.array(v[:max(0, n - shift)])
        a[shift:shift + len(v)] = v
        out[BURST + k] = a
    return out, len(words)


def mouth_size(jaw, window_s=0.6, floor=0.3):
    """How big his mouth movement really is, moment to moment, from the video's jaw: a slow envelope (the largest opening
    within +-window_s/2), relative to the clip's own 95th percentile, so a mumbler and a shouter both map onto the
    game's range. 1 = as wide as this clip gets; `floor` keeps a little syllable motion where the mouth barely opens.
    1 where the video has no face."""
    n = len(jaw)
    ok = ~np.isnan(jaw)
    if ok.sum() < 10:
        return np.ones(n)
    j = np.where(ok, jaw, 0.0)
    half = max(1, int(window_s * FPS / 2))
    env = np.array([j[max(0, i - half):i + half + 1].max() for i in range(n)])
    k = np.exp(-0.5 * (np.arange(-half, half + 1) / (half / 2)) ** 2)
    env = np.convolve(np.pad(env, half, mode="edge"), k / k.sum(), mode="valid")[:n]
    ref = max(1e-3, float(np.percentile(env[ok], 95)))
    return np.where(ok, np.clip(env / ref, floor, 1.0), 1.0)


def rig_presence(path):
    if not path:
        return 1.0
    sys.path.insert(0, os.path.join(ROOT, "model"))
    import coupling
    return coupling.rig_presence(path)


def add_coupling(tracks, n, strength, presence):
    """The cheeks, lip puff, nose and chin follow the mouth and jaw (model/coupling.py), on whatever mouth the tracks now have,
    whether it came from the voice or the video. Frames with no face stay empty."""
    if not strength or strength <= 0:
        return tracks
    sys.path.insert(0, os.path.join(ROOT, "model"))
    import coupling
    work = {k: np.nan_to_num(v).tolist() for k, v in tracks.items()}
    before = {k: list(v) for k, v in work.items()}
    coupling.couple(work, n, strength, presence)
    for k, v in work.items():
        new = np.array(v, dtype=float)
        if k not in tracks:
            tracks[k] = new
        elif list(v) != before.get(k):
            old = tracks[k]
            merged = np.fmax(old, new)
            tracks[k] = np.where(np.isnan(old) & (new == 0), np.nan, merged)
    return tracks


ROUND_GAP = (0.04, 0.10)     # lip gap (over the eye distance): below, the lips are shut round a pout; above, the round mouth is open


def split_round_mouth(tracks, gap, strength=1.0):
    """MediaPipe has one score for a rounded mouth (mouthPucker) and almost none for the open "O" (mouthFunnel: 95th percentile 0.01),
    so a sung "o" with the jaw down came out as the rig's closed purse, a small pursed pout. Of one singer's frames with pucker
    above 0.5, 55% had the lips apart (gap above 0.06, jaw median 0.27) and 36% had them shut. The rig has both shapes and the game
    never stacks them (purse = lips shut and pushed out, funnel = the round open mouth), so the pucker goes to the purse while the
    lips are shut and to the funnel as the gap opens, by the measured lip gap. Purse + funnel stay within the game's 0.6.
    strength 0 leaves the tracks as mapped."""
    if strength <= 0 or gap is None:
        return tracks
    lo, hi = ROUND_GAP
    u = np.clip((gap - lo) / (hi - lo), 0.0, 1.0)
    share = u * u * (3 - 2 * u) * strength                       # smoothstep: 0 shut, 1 open
    for side in "lr":
        pk, fk = f"lips_{side}_purse", f"lips_{side}_funnel"
        if pk not in tracks:
            continue
        pucker = tracks[pk]
        fun = np.fmax(tracks[fk], pucker * share) if fk in tracks else pucker * share
        pur = pucker * (1 - share)
        tot = np.nan_to_num(pur) + np.nan_to_num(fun)
        k = np.where(tot > FORWARD_MAX, FORWARD_MAX / np.maximum(tot, 1e-9), 1.0)
        tracks[pk], tracks[fk] = pur * k, fun * k
    return tracks


# The lip gap a set of tracks shows, fitted on one close-up video (r = 0.96): the jaw, the lower lip's drop, the upper lip's lift and
# the lower lip's roll. gap = 0.02 + 0.183 jaw + 0.156 lower-lip drop + 0.037 upper-lip lift - 0.179 lower-lip roll.
GAP_FIT = {"const": 0.02, "jaw_mid_open": 0.183, "lips_apart_dn": 0.156, "lips_l_upper_raise": 0.037, "lips_suck_dn": -0.179}
GAP_FILL_MAX = 0.15          # the most a shortfall may add (in gap units)


def fill_lip_gap(tracks, gap, strength=1.0):
    """Lips that are parted on the video must be parted on the head. The blendshapes miss some separations (the upper lip lifts and
    the teeth show with the jaw at 0), so the head's visible gap ran below the measured one: median 0.05 against 0.09, and in 4% of
    one song's frames the head's lips were shut while the real ones were apart. Where the gap the tracks show is less than the
    measured lip gap, the lower and upper lips open to make up the difference (half each, by the fit above). It only ever opens
    the lips: closures (p/b/m) and frames without a face are left as they are. strength 0 leaves the tracks alone."""
    if strength <= 0 or gap is None or "jaw_mid_open" not in tracks:
        return tracks
    n = len(gap)
    g = lambda k: np.nan_to_num(tracks[k][:n]) if k in tracks else np.zeros(n)
    shown = GAP_FIT["const"] + sum(w * g(k) for k, w in GAP_FIT.items() if k != "const")
    short = np.clip(np.nan_to_num(gap) - shown, 0.0, GAP_FILL_MAX)
    short = np.where(np.isnan(gap), 0.0, short)
    k = np.ones(3) / 3
    short = np.convolve(np.pad(short, 1, mode="edge"), k, mode="valid")           # no flicker
    short = np.where(short < 0.01, 0.0, short) * strength
    shut = np.maximum(g("lips_together_up"), g("lips_together_dn")) > 0.4         # a real closure stays closed
    short = np.where(shut, 0.0, short)
    add = short / GAP_FIT["lips_apart_dn"] * 0.5
    for name in ("lips_apart_dn", "lips_apart_up"):
        cur = tracks.get(name, np.zeros(len(tracks["jaw_mid_open"])))
        out = np.array(cur, dtype=float)
        out[:n] = np.where(np.isnan(out[:n]), np.nan, np.minimum(1.0, np.nan_to_num(out[:n]) + add))
        tracks[name] = out
    return tracks


LOWER_TEETH_FROM, LOWER_TEETH_TO = 0.30, 0.60      # jaw: below FROM the lower lip's drop is mostly handed to the jaw, from TO it is kept whole


def lower_lip_to_jaw(tracks, teeth=0.3):
    """Make the opening with the jaw, not the lower lip. MediaPipe's lower-lip drop (mouthLowerDown) read about twice the jaw
    on a close-up singing video (median 0.13 against 0.06), so the head opened by dropping its lower lip, which bares the bottom
    teeth, where the real mouth opened with the jaw and showed hardly any of them except on a tall vowel. The share of the drop
    that the jaw has not earned (smoothstep of the jaw from 0.30 to 0.60; `teeth` is what is kept below 0.30) moves onto the jaw,
    scaled so the lip gap stays the same (GAP_FIT). teeth 1 leaves the tracks alone."""
    if teeth >= 1.0 or "jaw_mid_open" not in tracks or "lips_apart_dn" not in tracks:
        return tracks
    jaw, drop = tracks["jaw_mid_open"], tracks["lips_apart_dn"]
    x = np.clip((np.nan_to_num(jaw) - LOWER_TEETH_FROM) / (LOWER_TEETH_TO - LOWER_TEETH_FROM), 0.0, 1.0)
    keep = teeth + (1.0 - teeth) * x * x * (3.0 - 2.0 * x)
    moved = np.nan_to_num(drop) * (1.0 - keep)
    tracks["lips_apart_dn"] = np.where(np.isnan(drop), np.nan, np.nan_to_num(drop) * keep)
    tracks["jaw_mid_open"] = np.where(np.isnan(jaw), np.nan, np.minimum(1.0, np.nan_to_num(jaw) + moved * GAP_FIT["lips_apart_dn"] / GAP_FIT["jaw_mid_open"]))
    return tracks


def jaw_forward_with_opening(tracks, amount=0.25):
    """The jaw hinges and slides forward as it lowers (the condyle travels down the front of the joint): a little at a small opening
    and more as it goes wide, which is what sung vowels do. The rig has the pose (jaw_mid_shift_fwd) but nothing drove it: MediaPipe's
    jawForward reads about 0 and the game never uses the pose, so this is AUTHORED, not measured: shift = amount * jaw ** 1.3
    (0.25 at a full jaw, 0.1 at a jaw of 0.4), kept above any forward the video did read. amount 0 leaves the tracks alone."""
    if amount <= 0 or "jaw_mid_open" not in tracks:
        return tracks
    jaw = tracks["jaw_mid_open"]
    fwd = amount * np.power(np.clip(np.nan_to_num(jaw), 0.0, 1.0), 1.3)
    cur = tracks.get("jaw_mid_shift_fwd", np.zeros(len(jaw)))
    tracks["jaw_mid_shift_fwd"] = np.where(np.isnan(jaw), cur, np.minimum(1.0, np.fmax(np.nan_to_num(cur), fwd)))
    return tracks


CLOSE_SHUT, CLOSE_OPEN, CLOSE_MAXLEN, CLOSE_AROUND = 0.025, 0.045, 9, 8   # lip gap under SHUT, lips open (over OPEN) either side within AROUND frames
CLOSE_HOLD = 3                                                          # frames: the game's presses are 133 ms wide, the shortest that reads


def closures_from_gap(gap):
    """The brief lip closures (b, p, m and the like) read from the video's own lip gap: the gap dips under 0.025 for 1-9 frames
    with the lips open on both sides. A held-shut mouth (longer than 9 frames) is a posture, not a consonant, and is left to the
    video's own tracks. Returns (press curve 0-1, per frame), or None when there is no gap. On one close-up song this finds 81
    (0.4 a second, median 3 frames); the speech-to-text words for the sung b/p/m sounds were too loosely timed to find them
    (within 6 frames of a real closure for 19% of them, against 18% at random times)."""
    if gap is None:
        return None
    n = len(gap)
    g = np.nan_to_num(gap, nan=1.0)
    press = np.zeros(n)
    i = 0
    while i < n:
        if g[i] < CLOSE_SHUT:
            j = i
            while j < n and g[j] < CLOSE_SHUT:
                j += 1
            before, after = g[max(0, i - CLOSE_AROUND):i], g[j:j + CLOSE_AROUND]
            if 1 <= j - i <= CLOSE_MAXLEN and len(before) and len(after) and before.max() > CLOSE_OPEN and after.max() > CLOSE_OPEN:
                a, b = i, j
                if b - a < CLOSE_HOLD:                                       # widen about its centre to the shortest press that reads
                    a -= (CLOSE_HOLD - (b - a)) // 2
                    b = a + CLOSE_HOLD
                press[max(0, a):min(n, b)] = 1.0
            i = j
        else:
            i += 1
    return press


SEAL_SHUT, SEAL_MIN, SEAL_HELD = 0.03, 2, 0.4       # video lip gap under SEAL_SHUT for SEAL_MIN frames or more; a held seal presses at SEAL_HELD


def seal_from_video(tracks, gap, video, held=SEAL_HELD):
    """Hard-code the video's lip closure. Wherever the video's lips are shut (gap under SEAL_SHUT for at least SEAL_MIN frames, face
    seen) the head's mouth is the video's, whatever the sound says: the voice-driven lip shapes, the upper lip and the jaw fall back
    to what the video reads, so a backing vocal or a band the singer is not singing along to cannot move a closed mouth. A shut run
    longer than a consonant (over CLOSE_MAXLEN frames, a held mouth) also gets a gentle seal on lips_together (AUTHORED, not
    measured), so the lips meet. Outside shut frames nothing changes. On one close-up singing video the lips were shut in 22% of the
    frames, and the voice's lip shapes still leaked into 7% of them (corner stretch over 0.15). held 0 skips the seal."""
    if gap is None or video is None or "jaw_mid_open" not in tracks:
        return tracks
    n = len(gap)
    shut = np.nan_to_num(gap, nan=1.0) < SEAL_SHUT
    keep = np.zeros(n, bool)                                         # runs of SEAL_MIN frames or more
    held_run = np.zeros(n, bool)
    i = 0
    while i < n:
        if shut[i]:
            j = i
            while j < n and shut[j]:
                j += 1
            if j - i >= SEAL_MIN:
                keep[i:j] = True
                if j - i > CLOSE_MAXLEN:
                    held_run[i:j] = True
            i = j
        else:
            i += 1
    if not keep.any():
        return tracks
    for k in list(tracks):
        if k.startswith("lips_") and is_speech_track(k) and "together" not in k:
            cur = np.array(tracks[k], dtype=float)
            m = min(n, len(cur))
            v = video.get(k)
            back = np.zeros(m) if v is None else np.nan_to_num(np.array(v[:m], dtype=float))
            cur[:m] = np.where(keep[:m], back, cur[:m])
            tracks[k] = cur
    vj = video.get("jaw_mid_open")
    jaw = np.array(tracks["jaw_mid_open"], dtype=float)
    m = min(n, len(jaw))
    vjaw = np.zeros(m) if vj is None else np.nan_to_num(np.array(vj[:m], dtype=float))
    jaw[:m] = np.where(keep[:m], np.minimum(jaw[:m], vjaw), jaw[:m])
    tracks["jaw_mid_open"] = jaw
    if held > 0:
        for k in ("lips_together_up", "lips_together_dn"):
            cur = np.array(tracks.get(k, np.zeros(n)), dtype=float)
            m = min(n, len(cur))
            cur[:m] = np.where(held_run[:m], np.fmax(np.nan_to_num(cur[:m]), held), cur[:m])
            tracks[k] = cur
    return tracks


GATE_SEEN, GATE_NEAR = 0.035, 3       # a voice closure needs the video's lip gap under GATE_SEEN (his real closures: under 0.025) within GATE_NEAR frames


def gate_voice_closures(tracks, gap):
    """Blocked is not muffled. The voice places a p/b/m press from the word's timing, and sung words are timed loosely, so w, sh and
    uh (lips rounded or open) came out as b and m: on a close-up singing video 36% of the voice's presses fell where the video's lips
    were over 0.10 apart and 9% where they were under 0.04, and 26 of 86 were near one of his 74 real closures (whose sound does carry
    the low murmur of a b or m, 5 times the usual). So a press the voice proposes stays only where the video's lip gap gets under
    GATE_SEEN within GATE_NEAR frames; otherwise it is dropped and the sound keeps the rounded or open shape the voice gave it. Frames
    with no face are left alone. On that video: 136 closures with the voice's added, 104 gated (his 74 plus 30 where his lips nearly
    touched; the share near one of his real closures 57% to 74%). The video's own gap read shut at rest (median 0.004 while the voice
    was silent), so a beard did not stop it reading closed lips; it is still unknown whether it hides small gaps at the lip corners."""
    if gap is None or "lips_together_up" not in tracks:
        return tracks
    n = len(gap)
    near = np.full(n, np.inf)
    for d in range(-GATE_NEAR, GATE_NEAR + 1):                       # the lowest gap within +-GATE_NEAR frames
        sh = np.full(n, np.inf)
        g = np.where(np.isnan(gap), np.inf, gap)
        if d >= 0:
            sh[:n - d] = g[d:]
        else:
            sh[-d:] = g[:n + d]
        near = np.minimum(near, sh)
    seen = ~np.isnan(gap)
    for k in ("lips_together_up", "lips_together_dn"):
        cur = tracks.get(k)
        if cur is None:
            continue
        m = min(n, len(cur))
        c = np.array(cur, dtype=float)
        # whole events, not single frames: an event is kept if any frame of it has the video's lips together
        on = np.nan_to_num(c[:m]) > 0.05
        i = 0
        while i < m:
            if on[i]:
                j = i
                while j < m and on[j]:
                    j += 1
                if seen[i:j].any() and not (near[i:j] < GATE_SEEN).any():
                    c[i:j] = np.where(seen[i:j], 0.0, c[i:j])
                i = j
            else:
                i += 1
        tracks[k] = c
    return tracks


def apply_video_closures(tracks, gap, replace):
    """Put the video's closures on lips_together_up/dn: replacing the voice's where the face is seen (replace=True: the voice's
    come from words whose times are rough), or added to whatever is there. Frames with no face keep what they had."""
    press = closures_from_gap(gap)
    if press is None:
        return tracks
    seen = ~np.isnan(gap)
    for k in ("lips_together_up", "lips_together_dn"):
        cur = tracks.get(k, np.zeros(len(gap)))
        tracks[k] = np.where(seen, press if replace else np.fmax(np.nan_to_num(cur), press), cur)
    return tracks


VIDEO_PURSE_MIN = 0.03       # below this (95th percentile) the video shows no pucker at all in this clip: the voice's stays
VIDEO_PURSE_TARGET = 0.15    # a small face reads pucker weakly (0.06 where the true value was 0.32, correlation still 0.69): lift it to this
VIDEO_PURSE_GAIN_MAX = 4.0
FORWARD_MAX = 0.6            # purse + funnel together; the most the game ever uses (model/lipsync.py LIP_FORWARD_MAX)


def forward_from_video(video, out):
    """Lips pushed forward (purse, funnel). The video reads the pucker well (a clip's mouthPucker reaches 0.3-0.9), while
    the voice only knows which sounds are rounded, and was scaled down by the mouth size besides, so the hybrid kept about
    a fifth of the video's pucker. Where the video reads pucker in this clip, it sets the purse wherever the face is seen
    (the voice's carries on in the gaps); a weak reading (a small face) is lifted toward VIDEO_PURSE_TARGET, a strong one is kept as it is. MediaPipe's funnel is nearly always 0 (95th percentile 0.01 here), so the funnel
    keeps the larger of the two. Purse + funnel stay within what the game uses."""
    for side in "lr":
        key = f"lips_{side}_purse"
        vp = video.get(key)
        if vp is not None:
            seen = ~np.isnan(vp)
            p95 = np.percentile(vp[seen], 95) if seen.sum() >= 10 else 0.0
            if p95 >= VIDEO_PURSE_MIN:
                gain = min(VIDEO_PURSE_GAIN_MAX, max(1.0, VIDEO_PURSE_TARGET / p95))
                out[key] = np.where(seen, np.minimum(1.0, vp * gain), out.get(key, np.zeros_like(vp)))
        key = f"lips_{side}_funnel"
        vf = video.get(key)
        if vf is not None and key in out:
            out[key] = np.fmax(out[key], np.nan_to_num(vf))
        pu, fu = out.get(f"lips_{side}_purse"), out.get(f"lips_{side}_funnel")
        if pu is not None and fu is not None:
            tot = np.nan_to_num(pu) + fu
            k = np.where(tot > FORWARD_MAX, FORWARD_MAX / np.maximum(tot, 1e-9), 1.0)
            out[f"lips_{side}_purse"], out[f"lips_{side}_funnel"] = pu * k, fu * k
    return out


VIDEO_MOUTH_TRUST = 0.3      # the video's jaw (95th percentile) must reach this, a rig-sized reading, before the mouth is led by the video
VIDEO_LED = ("jaw_mid_open", "lips_apart_dn", "lips_l_upper_raise", "lips_r_upper_raise", "lips_chin_raise")


def video_mouth_trusted(jaw):
    """True when the video reads the mouth at the rig's scale (a close, front-on face): the jaw's 95th percentile is at least
    VIDEO_MOUTH_TRUST (the game's speech is 0.35, its singing 0.8; the small, turned face in the first test clip read 0.16)."""
    ok = ~np.isnan(jaw)
    return bool(ok.sum() >= 30 and np.percentile(jaw[ok], 95) >= VIDEO_MOUTH_TRUST)


def lead_mouth_from_video(video, out, follow):
    """Lip separation. The voice only knows how loud the voice is, and its lips ride on its jaw (the singing profile opens the
    upper lip 1.3 times the jaw); a lip gap measured on the video is explained 0.96 by the jaw, the lower lip's drop and its roll
    (about 0.18 jaw + 0.16 drop - 0.18 roll), and in a tenth of the frames the lips were visibly apart with the jaw nearly
    shut, which only the drop shows. So with a trusted video the jaw, the lower lip's drop (apart_dn), the upper lip and the chin
    come from the video wherever the face is seen, and the tracks that ride on the jaw (follow_jaw, which have no video source)
    ride on the video's jaw instead of the voice's. The voice still places closures, the tongue and the neck."""
    vj = video.get("jaw_mid_open")
    if vj is None:
        return out
    seen = ~np.isnan(vj)
    for k in VIDEO_LED:
        v = video.get(k)
        if v is not None:
            out[k] = np.where(~np.isnan(v), v, out.get(k, np.zeros_like(v)))
    jaw = np.nan_to_num(out["jaw_mid_open"])
    for name, gain in (follow or {}).items():
        if name in video and name in VIDEO_LED or name.startswith(("lips_l_corner", "lips_r_corner")):
            continue                                             # the video has its own (or, for the corners, the smile comes from it)
        out[name] = np.where(seen, np.clip(gain * jaw, 0.0, 1.0), out.get(name, np.zeros_like(vj)))
    return out


def hybrid_tracks(video, voice, size=None, led=False, follow=None, reinforce=True):
    """video, voice: {track: array}. Speech tracks come from the voice; the jaw also takes the video where the video
    shows the mouth open further than the voice suggests; every other track comes from the video. No face in a frame:
    the video-sourced tracks are empty there, the voice-sourced ones carry on."""
    out = {}
    for k, v in voice.items():
        if is_speech_track(k):
            # the voice sets WHEN the mouth moves; the video sets HOW MUCH (closures and the tongue keep their size)
            sized = size is not None and (k == "jaw_mid_open" or (k.startswith("lips_") and "together" not in k))
            out[k] = v * size if sized else v.copy()
    for k, v in video.items():
        if is_speech_track(k):
            if k == "jaw_mid_open":
                out[k] = np.fmax(out.get(k, np.zeros_like(v)), np.nan_to_num(v))
        else:
            out[k] = v
    if reinforce:
        # The voice reinforces the lips, it does not overwrite them: where the video reads a lip shape (stretch, pull, roll, lift...) the head keeps
        # at least that, and the consonants the voice finds come on top. The led tracks and the closures are handled where they are merged.
        for k, v in video.items():
            if k in out and k.startswith("lips_") and is_speech_track(k) and k not in VIDEO_LED and "together" not in k:
                out[k] = np.fmax(out[k], np.nan_to_num(v))
    if led:
        out = lead_mouth_from_video(video, out, follow)
    if reinforce:
        # The hard k/g/c/q: the voice's burst goes on top of whatever the video's corners and upper lip are doing, never under it
        for k, v in voice.items():
            if k.startswith(BURST):
                out[k[len(BURST):]] = np.fmax(out.get(k[len(BURST):], np.zeros_like(v)), v)
    return forward_from_video(video, out)


def tongue_from_audio(folder, trace, n):
    """The audio model's tongue tracks for the trace's own audio (with caption words when there are any)."""
    import lipsync
    from analyze import caption_words
    audio = trace.get("audio")
    if not audio:
        return {}
    words, _ = caption_words(folder, trace["start"], n / FPS)
    res = lipsync.simulate_lipsync(voice_file(folder, audio), profile="speech", words=words or None)
    shift = round((audio.get("start", trace["start"]) - trace["start"]) * FPS)   # audio may start after the trace
    out = {}
    for k, v in res["tracks"].items():
        if k.startswith("tongue_"):
            a = np.zeros(n)
            v = np.array(v[:max(0, n - shift)])
            a[shift:shift + len(v)] = v
            out[k] = a
    return out


def jl(a, nd=4):
    return [None if (isinstance(x, float) and math.isnan(x)) or (hasattr(x, "dtype") and np.isnan(x)) else round(float(x), nd) for x in a]


def retarget(folder, mapping_path=DEFAULT_MAPPING, export="raw", tongue=True, hybrid=True, size=True, mouth_from="auto",
             articulation=None, expressiveness=None, coupling=1.0, jaw_presence=1.0, profile="speech", round_split=1.0, gap_fill=1.0, video_diction=True, lower_teeth=0.3, jaw_forward=0.25, reinforce=True, seal=True):
    folder = os.path.abspath(folder)
    perf = json.load(open(os.path.join(folder, "performance.json"), encoding="utf-8"))
    if perf.get("format") != "lipscan-performance/1":
        raise SystemExit("performance.json has an unknown format; run analyze/performance.py again.")
    trace = json.load(open(os.path.join(folder, "trace.json"), encoding="utf-8"))
    times = np.array(perf["t"], dtype=float)
    n = int(math.floor(times[-1] * FPS)) + 1 if len(times) else 0
    if trace.get("audio"):
        n = max(n, int(round((trace["audio"].get("start", trace["start"]) - trace["start"] + trace["audio"]["seconds"]) * FPS)))
    longest = max(0.2, perf["settings"].get("fill_gaps_s") or 0.2)
    chan = {k: resample(times, np.array([np.nan if x is None else x for x in v], dtype=float), n, longest)
            for k, v in perf["channels"].items()}
    face_seen = ~np.isnan(chan["jawOpen"])
    mapping = load_mapping(mapping_path)
    base = {"fps": FPS, "profile": "performance", "duration": n / FPS,
            "source": perf.get("source", {}), "face_seen": round(float(face_seen.mean()), 3) if n else 0,
            "video": {"start": perf["clock"]["video_start"], "trace": os.path.basename(folder)}}
    if export == "arkit52":
        from performance import BLENDSHAPES
        return {**base, "target": "arkit52", "tracks": {k: jl(chan[k]) for k in BLENDSHAPES if k != "_neutral"},
                "head": {k: jl(chan[c], 2) for k, c in (("yaw", "headYaw"), ("pitch", "headPitch"), ("roll", "headRoll"))}}
    tracks, unused = apply_mapping(chan, mapping)
    tracks = split_round_mouth(tracks, chan.get("lipGap"), round_split)
    mode = "video"
    if hybrid and trace.get("audio"):
        dials = {k: v for k, v in (("articulation", articulation), ("expressiveness", expressiveness)) if v is not None}
        voice, nwords = audio_tracks(folder, trace, n, profile, **dials)
        led = mouth_from == "video" or (mouth_from == "auto" and video_mouth_trusted(chan["jawOpen"]))
        import lipsync
        follow = lipsync.load_profile(profile).get("follow_jaw") if led else None
        video_tracks = {k: v.copy() for k, v in tracks.items()}                # what the video alone reads, for the seal below
        tracks = hybrid_tracks(tracks, voice, mouth_size(chan["jawOpen"]) if size else None, led, follow, reinforce)
        mode = "hybrid"
        base["hybrid"] = {"mouth": ("jaw, lower lip, upper lip and chin from the video; " if led else "") + "voice model"
                          + (f" with {nwords} caption words" if nwords else " (no words: jaw, tongue and neck only)"), "face": "video",
                          "mouth_led_by": "video" if led else "voice"}
    elif tongue:
        for k, v in tongue_from_audio(folder, trace, n).items():
            tracks[k] = np.where(face_seen, v, np.nan)
    if video_diction and mode in ("hybrid", "video") and video_mouth_trusted(chan["jawOpen"]) and "lipGap" in chan:
        if mode == "hybrid" and reinforce:
            tracks = gate_voice_closures(tracks, chan["lipGap"])
        tracks = apply_video_closures(tracks, chan["lipGap"], replace=(mode == "hybrid" and not reinforce))      # diction from his own lips, with the voice's added on top
    tracks = fill_lip_gap(tracks, chan.get("lipGap"), gap_fill)
    tracks = lower_lip_to_jaw(tracks, lower_teeth)
    if mode == "hybrid" and seal and video_diction and video_mouth_trusted(chan["jawOpen"]) and "lipGap" in chan:
        tracks = seal_from_video(tracks, chan["lipGap"], video_tracks)                  # a shut mouth in the video is shut on the head
    tracks = jaw_forward_with_opening(tracks, jaw_forward)
    tracks = add_coupling(tracks, n, coupling, jaw_presence)
    base["settings"] = {"articulation": articulation, "expressiveness": expressiveness, "coupling": coupling, "jaw_presence": jaw_presence}
    out = {**base, "target": "cyberpunk-raw", "mapping": os.path.basename(mapping_path),
           "tracks": {k: jl(v) for k, v in sorted(tracks.items())},
           "head": {k: jl(v, 2) for k, v in head_curves(chan, mapping).items()},
           "head_split": mapping.get("head", {}).get("split"),
           "unmapped_sources": sorted(set(unused) | set(mapping.get("unmapped_sources", {}))), "mouth_source": mode}
    if export == "cyberpunk":
        from export import cyberpunk
        out = cyberpunk(out)
    return out


def main():
    ap = argparse.ArgumentParser(description="Turn performance.json into face-rig curves.")
    ap.add_argument("folder", help="trace folder with performance.json (from analyze/performance.py)")
    ap.add_argument("--mapping", default=DEFAULT_MAPPING)
    ap.add_argument("--export", choices=["raw", "cyberpunk", "arkit52"], default="raw")
    ap.add_argument("--no-tongue", action="store_true", help="(video-only mode) don't add tongue tracks from the audio model")
    ap.add_argument("--articulation", type=float, help="the voice model's articulation dial (0.0-2.0; default: the profile's)")
    ap.add_argument("--expressiveness", type=float, help="the voice model's expressiveness dial (0.0-2.0; default: the profile's)")
    ap.add_argument("--coupling", type=float, default=1.0, help="how strongly the cheeks, lip puff, nose and chin follow the mouth (0.0-2.0, default 1.0)")
    ap.add_argument("--jaw-presence", type=float, default=None, help="how much this face's jaw shows, from the rig (0.7-1.3, default 1.0)")
    ap.add_argument("--rig", help="a character.json: sets --jaw-presence from that face's jaw (unless given)")
    ap.add_argument("--profile", default="speech", help="voice profile for the hybrid's voice side")
    ap.add_argument("--mouth-from", choices=("auto", "video", "voice"), default="auto",
                    help="(hybrid) who leads the jaw and lip separation: video when it reads the mouth at the rig's scale (auto), always, or never")
    ap.add_argument("--round-split", type=float, default=1.0, help="how much of the video's rounded-mouth reading (pucker) goes to the open funnel "
                    "instead of the closed purse as the lips part (0 = all to the purse, as mapped; default 1)")
    ap.add_argument("--gap-fill", type=float, default=1.0, help="open the head's lips where they are less parted than the video's measured lip gap "
                    "(0 = off, default 1)")
    ap.add_argument("--lower-teeth", type=float, default=0.3, help="how much of the lower lip's drop (which bares the bottom teeth) is kept on a small "
                    "jaw opening; the rest moves onto the jaw, so only a tall vowel shows the bottom teeth (0-1; 1 = as mapped, default 0.3)")
    ap.add_argument("--jaw-forward", type=float, default=0.25, help="how far the jaw slides forward as it lowers (0-1, authored not measured; "
                    "0 = straight down, default 0.25)")
    ap.add_argument("--no-reinforce", action="store_true", help="(hybrid) the voice takes over the lip shapes and closures instead of adding to the video's")
    ap.add_argument("--no-seal", action="store_true", help="(hybrid) don't force the head's mouth to the video's wherever the video's lips are shut")
    ap.add_argument("--no-video-diction", action="store_true", help="don't take the p/b/m closures from the video's lip gap when the video reads the mouth well "
                    "(the voice model's word-placed closures are used)")
    ap.add_argument("--no-size", action="store_true", help="(hybrid) don't scale the voice's jaw and lips by the mouth size seen in the video")
    ap.add_argument("--video-only", action="store_true",
                    help="read the mouth from the video too. Default is a hybrid: jaw, lips, tongue and neck from the voice, "
                         "everything else (head, brows, eyes, blinks, gaze, smiles) from the video")
    ap.add_argument("--out")
    a = ap.parse_args()
    res = retarget(a.folder, a.mapping, a.export, not a.no_tongue, hybrid=not a.video_only, size=not a.no_size, mouth_from=a.mouth_from,
                   articulation=a.articulation, expressiveness=a.expressiveness, coupling=min(2.0, max(0.0, a.coupling)),
                   jaw_presence=min(1.3, max(0.7, a.jaw_presence if a.jaw_presence is not None else rig_presence(a.rig))), profile=a.profile,
                   round_split=min(1.0, max(0.0, a.round_split)), gap_fill=min(1.0, max(0.0, a.gap_fill)), video_diction=not a.no_video_diction,
                   lower_teeth=min(1.0, max(0.0, a.lower_teeth)), jaw_forward=min(1.0, max(0.0, a.jaw_forward)), reinforce=not a.no_reinforce, seal=not a.no_seal)
    if a.out == "-":
        json.dump(res, sys.stdout)
        return
    out = a.out or os.path.join(os.path.abspath(a.folder), f"retarget-{'cyberpunk' if a.export != 'arkit52' else 'arkit52'}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, separators=(",", ":"))
    print(f"Wrote {out}: {len(res['tracks'])} tracks, {res['duration']:.2f} s at {FPS} fps, face seen {res['face_seen'] * 100:.0f}%")


if __name__ == "__main__":
    main()

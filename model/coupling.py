"""
Coupling: the cheeks, lip puff, nose, chin, upper lip and neck follow the mouth and the jaw.

In the game's faces these secondary tracks are not free: they ride along with the mouth. A p/b/m press puffs the cheeks
and lips a little, an f/v tuck lifts the chin, wrinkles the nose and raises the upper lip, and the throat and platysma
work with the jaw. Predicted from the mouth and jaw tracks alone, they match the game at 0.7-0.96 correlation on
characters held out of the training (docs/MEASUREMENTS.md). coupling.json holds the learned weights (numbers only).

This runs on whatever mouth movement a set of tracks already has, so it works the same for movement made from a voice
and for movement read from a video: the secondary tracks follow either one.

    from coupling import couple
    couple(tracks, n, strength=1.0, presence=1.0)       # adds the secondary tracks to `tracks`

strength  the coupling dial: 0 off, 1 as measured, 2 doubled (0.0 to 2.0).
presence  how much a face's jaw shows: about 1.0 for an average jawline, above 1 for a wide or long jaw (jaw_presence()).
          The game animates every character's jaw by the same amount; a bigger jaw moves more skin, so the cheeks,
          chin and neck that follow it show more.
"""
import json
import math
import os

_MODEL = None
BOTH = ("lips_l_", "cheek_l_", "nose_l_", "neck_l_", "eye_l_")

# The most each authored coupling may reach. A big smile drove the smile fold to 1.0 and the mesh crumpled over the cheek: the game
# never takes it near that (its held "warm" mood has the squint at 0.22-0.3 and the cheek tracks stay under 0.01).
AUTHORED_MAX = {"lips_l_nasolabialDeepener": 0.35, "eye_l_oculi_squint_outer_lower": 0.3, "cheek_l_puff": 0.1}


def model():
    global _MODEL
    if _MODEL is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "coupling.json"), encoding="utf-8") as fh:
            _MODEL = json.load(fh)
    return _MODEL


# AUTHORED couplings, NOT measured: the game's dialogue layer never uses the cheek tracks (their 95th percentile is under
# 0.01), so there is nothing to learn them from. These keep the cheeks and eyes answering the mouth the way a face does:
# a smile lifts the cheek (the nasolabial fold) and narrows the eye a little (a "Duchenne" smile), and a press puffs the
# cheek slightly. Each is {target: {source track: weight}}, applied to both sides; the `strength` dial scales them too.
AUTHORED = {
    "lips_l_nasolabialDeepener": {"lips_l_corner_up": 1.2, "lips_l_pull": 0.8, "lips_l_stretch": 0.5},
    "eye_l_oculi_squint_outer_lower": {"lips_l_corner_up": 0.6, "lips_l_pull": 0.3},
    "cheek_l_puff": {"lips_together_up": 0.08},
}


def jaw_presence(width, chin_drop, ref_width=0.136, ref_drop=0.0903):
    """How much a face's jaw shows, from the rig: the jaw's width and the chin's drop below the eyes (world units, as in
    character.json), against the average of six game characters (Kerry, Judy, Panam, Jackie, Johnny, Takemura). The square
    root keeps it modest: about 0.9 (narrow, short) to 1.1 (wide, long)."""
    if not width or not chin_drop:
        return 1.0
    return max(0.7, min(1.3, math.sqrt((width * chin_drop) / (ref_width * ref_drop))))


def _world(bones):
    """World positions of every bone in a character.json (parent-relative translations and quaternions x y z w)."""
    names, parents, T, R = bones["names"], bones["parents"], bones["t"], bones["r"]
    pos, rot = [None] * len(names), [None] * len(names)

    def qmul(a, b):
        x1, y1, z1, w1 = a
        x2, y2, z2, w2 = b
        return (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)

    def qrot(q, v):
        ux, uy, uz, w = q
        cx, cy, cz = uy * v[2] - uz * v[1] + w * v[0], uz * v[0] - ux * v[2] + w * v[1], ux * v[1] - uy * v[0] + w * v[2]
        return (v[0] + 2 * (uy * cz - uz * cy), v[1] + 2 * (uz * cx - ux * cz), v[2] + 2 * (ux * cy - uy * cx))

    def go(i):
        if pos[i] is not None:
            return
        p = parents[i]
        if p is None or p < 0:
            pos[i], rot[i] = tuple(T[i]), tuple(R[i])
            return
        go(p)
        d = qrot(rot[p], T[i])
        pos[i] = (pos[p][0] + d[0], pos[p][1] + d[1], pos[p][2] + d[2])
        rot[i] = qmul(rot[p], R[i])

    for i in range(len(names)):
        go(i)
    return dict(zip(names, pos))


def rig_presence(character):
    """jaw_presence() for a character.json (a path or the loaded dict): the width between the jaw-ear bones and the drop from
    the upper eyelids to the chin. 1.0 if the rig doesn't have those bones."""
    if isinstance(character, str):
        with open(character, encoding="utf-8") as fh:
            character = json.load(fh)
    try:
        w = _world(character["bones"])
        a, b = w["l_J_jaw_ear_0_JNT"], w["r_J_jaw_ear_0_JNT"]
        eyes = [v[2] for k, v in w.items() if "eye_lid_up_root_1" in k]
        return jaw_presence(math.dist(a, b), sum(eyes) / len(eyes) - w["mid_J_mug_chin_rowA_0_JNT"][2])
    except (KeyError, ZeroDivisionError, TypeError, IndexError):
        return 1.0


def couple(tracks, n, strength=1.0, presence=1.0, only=None):
    """Add the secondary tracks the mouth and jaw imply. Existing tracks of the same name keep the larger value.
    Returns the names added or raised."""
    if strength <= 0:
        return []
    m = model()
    src = [tracks.get(name) for name in m["sources"]]
    if not any(src):
        return []
    gain = strength * presence
    touched = []
    for t, name in enumerate(m["targets"]):
        if only and name not in only:
            continue
        w = [row[t] for row in m["W"]]
        out = [0.0] * n
        for f in range(n):
            acc = w[-1]                                       # bias
            for j, s in enumerate(src):
                if s is not None and m["sd"][j] > 1e-3:           # a track the game never uses carries no information
                    acc += ((s[f] - m["mu"][j]) / m["sd"][j]) * w[j]
            out[f] = max(0.0, min(1.0, acc)) * gain
        out = [min(1.0, v) for v in out]
        names = [name] + ([name.replace("_l_", "_r_", 1)] if name.startswith(BOTH) else [])
        for nm in names:
            cur = tracks.get(nm)
            tracks[nm] = out if cur is None else [max(a, b) for a, b in zip(cur, out)]
            touched.append(nm)
    for name, weights in AUTHORED.items():
        if only and name not in only:
            continue
        cols = [(tracks.get(s), w) for s, w in weights.items() if tracks.get(s) is not None]
        if not cols:
            continue
        top = AUTHORED_MAX.get(name, 1.0)
        out = [min(top, sum(s[f] * w for s, w in cols) * gain) for f in range(n)]
        for nm in (name, name.replace("_l_", "_r_", 1) if name.startswith(BOTH) else None):
            if nm:
                cur = tracks.get(nm)
                tracks[nm] = out if cur is None else [max(a, b) for a, b in zip(cur, out)]
                touched.append(nm)
    return touched

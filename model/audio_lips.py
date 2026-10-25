"""
Lips, tongue and jaw from the sound alone (no words).

A ridge regression learned from the game's own dialogue lipsync: the voice's log-mel spectrum over +-167 ms, with the
line's average removed (voices and microphones differ), predicts each lip and tongue track. The weights are in
audio_lips.json (numbers only). Needs numpy. Without words it replaces the fixed resting tongue and gives the lips
soft, sound-driven shapes; p/b/m presses are NOT taken from it (from sound alone they come out 64% false), so crisp
closures still need words.

    from audio_lips import predict_tracks
    tracks = predict_tracks(samples, rate, n_frames)      # {"lips_l_pull": [...], "lips_r_pull": [...], ...}
"""
import json
import os

import numpy as np

FPS = 30
_MODEL = None
SIDED = ("lips_l_",)


def model():
    global _MODEL
    if _MODEL is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_lips.json"), encoding="utf-8") as fh:
            j = json.load(fh)
        _MODEL = {"bands": j["bands"], "ctx": j["context_frames"], "targets": j["targets"],
                  "mu": np.array(j["mu"]), "sd": np.array(j["sd"]), "W": np.array(j["W"])}
    return _MODEL


def logmel(samples, rate, n, bands):
    x = np.asarray(samples, dtype=float)
    win = int(rate * 0.032)
    w = np.hanning(win)
    top = min(8000.0, rate / 2 - 100)
    mel = lambda f: 2595 * np.log10(1 + f / 700)
    inv = lambda v: 700 * (10 ** (v / 2595) - 1)
    edges = inv(np.linspace(mel(60), mel(top), bands + 2))
    freqs = np.fft.rfftfreq(win, 1 / rate)
    fb = np.zeros((bands, len(freqs)))
    for b in range(bands):
        lo, mid, hi = edges[b], edges[b + 1], edges[b + 2]
        fb[b] = np.clip(np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)), 0, None)
    out = np.full((n, bands), -12.0)
    for f in range(n):
        c = int((f / FPS) * rate)
        seg = x[max(0, c - win // 2):c + win // 2]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        out[f] = np.log(fb @ (np.abs(np.fft.rfft(seg * w)) ** 2) + 1e-10)
    return out


def features(samples, rate, n, m):
    lm = logmel(samples, rate, n, m["bands"])
    level = lm.max(axis=1)
    voiced = level > level.max() - 14
    norm = lm - (lm[voiced].mean(axis=0) if voiced.any() else lm.mean(axis=0))
    base = np.concatenate([norm, np.clip((level - level.max()) / 8.0, -2, 0)[:, None]], axis=1)
    cols = []
    for d in m["ctx"]:
        sh = np.roll(base, -d, axis=0)
        if d > 0:
            sh[-d:] = base[-1]
        elif d < 0:
            sh[:-d] = base[0]
        cols.append(sh)
    return np.concatenate(cols, axis=1)


def predict_tracks(samples, rate, n, skip=("jaw_mid_open", "lips_together_up")):
    """{track: [value per frame]} for every learned track except `skip` (the jaw has its own loudness model; the press
    can't be told from sound). Sided lip tracks come out for both sides."""
    m = model()
    X = features(samples, rate, n, m)
    P = np.clip((np.concatenate([(X - m["mu"]) / m["sd"], np.ones((n, 1))], axis=1) @ m["W"]), 0, 1)
    out = {}
    for i, name in enumerate(m["targets"]):
        if name in skip or P[:, i].max() < 0.01:
            continue
        v = [float(x) for x in P[:, i]]
        if name.startswith("lips_l_"):
            out[name] = v
            out["lips_r_" + name[len("lips_l_"):]] = v
        else:
            out[name] = v
    return out

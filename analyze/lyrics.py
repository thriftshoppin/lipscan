"""Use lyrics you typed instead of the speech-to-text words, in a trace folder.

Speech-to-text hears a sung song loosely ("angel" for "angle"), but its word times are still the best clock there is. This
lines your lyrics up against what it heard (difflib, word by word) and gives each of your words a time:
  - a word it heard right takes that word's time;
  - a stretch it heard wrongly takes your words spread along the times of the words it heard there;
  - words it missed altogether go just after the word before them (about a third of a second each), but never past the next one.
Paste the whole lyrics, repeated choruses included: the order is what the lining-up goes by.

Then each word's time is moved to where the voice really starts that word: the first onset (a jump in the voice's loudness, from
vocals.wav if the folder has it, else audio.wav) within 0.25 s of the speech-to-text time. Sung words are timed from the middle of the
syllable: on one close-up singing video the b/p/m words were on average 0.17 s after his real lip closures, and snapped this way the
closures fell 0.007 s from the word time (spread 0.087 s to 0.040 s; within 0.10 s of the real closure 14% of words to 58%).
Needs numpy; without it, or with no audio, the times are left as they were.

It writes words-timed.json ([[seconds, "word"], ...], what the voice model reads) and captions.json (what the retarget reads) in
the folder, after saving the speech-to-text versions once as words-timed-whisper.json and captions-whisper.json. `reset` puts those
back. Standard library only.

    python analyze/lyrics.py apply "<trace folder>" lyrics.txt
    python analyze/lyrics.py reset "<trace folder>"
"""
import argparse
import difflib
import json
import os
import re
import shutil
import sys
import wave

WORD_S = 0.33          # about how long one sung word takes, for words the speech-to-text missed
MIN_STEP = 0.05


def tokens(text):
    """Words as the voice model wants them: lower case, letters and apostrophes. Hyphens and slashes split."""
    out = []
    for w in re.split(r"[\s/\-–—]+", text):
        w = re.sub(r"[^A-Za-z']", "", w).strip("'")
        if w:
            out.append(w)
    return out


def norm(w):
    return re.sub(r"[^a-z]", "", w.lower())


def similar(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def align(user, heard):
    """user: [word]; heard: [(seconds, word)]. Returns [(seconds, word)] for every user word, in order."""
    if not heard:
        return [(i * WORD_S, w) for i, w in enumerate(user)]
    times = [t for t, _ in heard]
    sm = difflib.SequenceMatcher(None, [norm(w) for w in user], [norm(w) for _, w in heard], autojunk=False)
    out = [None] * len(user)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = times[j1 + k]
        elif tag == "replace":
            m, k = i2 - i1, j2 - j1                     # m of yours against k it heard: spread yours along its times
            for a in range(m):
                pos = (a + 0.5) / m * k - 0.5
                lo = min(k - 1, max(0, int(pos)))
                hi = min(k - 1, lo + 1)
                frac = min(1.0, max(0.0, pos - lo))
                out[i1 + a] = times[j1 + lo] + frac * (times[j1 + hi] - times[j1 + lo])
    # words with no time yet (it heard nothing there): after the previous timed word, before the next one
    i = 0
    while i < len(user):
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < len(user) and out[j] is None:
            j += 1
        prev = out[i - 1] if i > 0 else None
        nxt = out[j] if j < len(user) else None
        n = j - i
        if prev is not None and nxt is not None:
            room = max(0.0, nxt - prev)
            step = min(WORD_S, room / (n + 1))
            for a in range(n):
                out[i + a] = prev + step * (a + 1)
        elif prev is not None:
            for a in range(n):
                out[i + a] = prev + WORD_S * (a + 1)
        elif nxt is not None:
            for a in range(n):
                out[i + a] = max(0.0, nxt - WORD_S * (n - a))
        else:
            for a in range(n):
                out[i + a] = a * WORD_S
        i = j
    for i in range(1, len(out)):                          # never backwards
        out[i] = max(out[i], out[i - 1] + (MIN_STEP if out[i] <= out[i - 1] else 0.0))
    return [(round(t, 2), w) for t, w in zip(out, user)]


SNAP_WINDOW, SNAP_GAP = 0.25, 0.06


def vocal_onsets(wav_path):
    """Seconds where the voice's loudness jumps (a syllable or a consonant's release starts). None without numpy or the file."""
    try:
        import numpy as np
        with wave.open(wav_path) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768
            ch, sr = w.getnchannels(), w.getframerate()
    except (ImportError, OSError, wave.Error):
        return None
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    hop = max(1, sr // 100)
    env = np.sqrt(np.convolve(x * x, np.ones(2 * hop) / (2 * hop), "same")[::hop] + 1e-10)
    level = 20 * np.log10(env + 1e-5)
    level = np.convolve(level, np.hanning(7) / np.hanning(7).sum(), "same")
    up = np.maximum(np.diff(level, prepend=level[0]), 0)
    up = np.convolve(up, np.ones(3) / 3, "same")
    thr = np.percentile(up, 85)
    return [i / 100.0 for i in range(2, len(up) - 2) if up[i] >= thr and up[i] >= up[i - 1] and up[i] >= up[i + 1]]


def snap_to_onsets(words, onsets):
    """Move each word to the first voice onset within SNAP_WINDOW of its time, never at or before the word before it (by SNAP_GAP)."""
    if not onsets:
        return words
    out, last = [], -1.0
    for t, w in words:
        lo = max(t - SNAP_WINDOW, last + SNAP_GAP)
        pick = next((o for o in onsets if lo <= o <= t + SNAP_WINDOW), None)
        t2 = pick if pick is not None else max(t, last + SNAP_GAP)
        out.append((round(t2, 2), w))
        last = t2
    return out


def refine(folder, words):
    for name in ("vocals.wav", "audio.wav"):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return snap_to_onsets(words, vocal_onsets(path))
    return words


def captions(words):
    """One caption event per run of words with gaps under 3 s, in the format the retarget reads."""
    events, cur = [], []
    for t, w in words:
        if cur and t - cur[-1][0] > 3:
            events.append(cur)
            cur = []
        cur.append((t, w))
    if cur:
        events.append(cur)
    return {"source": "lyrics typed by the user, lined up to the speech-to-text word times (analyze/lyrics.py)",
            "events": [{"start": e[0][0], "dur": round(e[-1][0] - e[0][0] + 0.4, 2), "text": " ".join(w for _, w in e),
                        "words": [{"t": t, "text": w} for t, w in e]} for e in events]}


def keep_whisper(folder):
    for name in ("words-timed", "captions"):
        src, bak = os.path.join(folder, name + ".json"), os.path.join(folder, name + "-whisper.json")
        if os.path.exists(src) and not os.path.exists(bak):
            shutil.copyfile(src, bak)


def apply(folder, text):
    keep_whisper(folder)
    bak = os.path.join(folder, "words-timed-whisper.json")
    heard = [(float(t), w) for t, w in json.load(open(bak, encoding="utf-8"))] if os.path.exists(bak) else []
    user = tokens(text)
    if not user:
        raise SystemExit("No words in the lyrics.")
    placed = refine(folder, align(user, heard))
    sm = difflib.SequenceMatcher(None, [norm(w) for w in user], [norm(w) for _, w in heard], autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    json.dump([[t, w] for t, w in placed], open(os.path.join(folder, "words-timed.json"), "w", encoding="utf-8"))
    json.dump(captions(placed), open(os.path.join(folder, "captions.json"), "w", encoding="utf-8"), indent=1)
    open(os.path.join(folder, "lyrics.txt"), "w", encoding="utf-8").write(text)
    return {"words": len(user), "heard": len(heard), "matched": matched, "first": placed[0][0], "last": placed[-1][0]}


def reset(folder):
    for name in ("words-timed", "captions"):
        bak = os.path.join(folder, name + "-whisper.json")
        if os.path.exists(bak):
            shutil.copyfile(bak, os.path.join(folder, name + ".json"))
    return {"reset": True}


def main():
    ap = argparse.ArgumentParser(description="Use typed lyrics instead of the speech-to-text words.")
    ap.add_argument("action", choices=["apply", "reset"])
    ap.add_argument("folder")
    ap.add_argument("lyrics", nargs="?", help="a text file with the lyrics (apply)")
    a = ap.parse_args()
    if a.action == "apply":
        if not a.lyrics:
            ap.error("apply needs a lyrics file")
        res = apply(a.folder, open(a.lyrics, encoding="utf-8").read())
    else:
        res = reset(a.folder)
    json.dump(res, sys.stdout)


if __name__ == "__main__":
    main()

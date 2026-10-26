"""Turn one dropped video into a finished viewer demo, start to finish. Run by serve.mjs (/api/import); can also be run by hand.

    python ingest.py "video.mp4" "<packs>\\live\\my-clip" "A title" --manifest "<packs>\\demo\\manifest.json" --profile singing-hard

Steps (each prints "STEP n/N text", the server shows them): trace folder, face tracking, vocal separation, speech-to-text, word files,
the three retargets, then a manifest entry. Env: LIPSCAN_REPO (the lipscan repo), LIPSCAN_SEP_PY (python with demucs, optional),
LIPSCAN_ASR (folder with transcribe.mjs and its node_modules). The video file is only read. Ends with "DONE" or "FAILED: why"."""
import argparse
import json
import os
import subprocess
import sys
import wave

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("folder")
ap.add_argument("title", nargs="?", default="")
ap.add_argument("--manifest", required=True)
ap.add_argument("--profile", default="singing-hard")
ap.add_argument("--keep-video", action="store_true", help="leave a video the server copied into the folder (default: delete it once frames are out)")
a = ap.parse_args()

repo = os.environ.get("LIPSCAN_REPO") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lipscan")
sep_py = os.environ.get("LIPSCAN_SEP_PY")
asr = os.environ.get("LIPSCAN_ASR")
F = a.folder
N = 9 if sep_py else 8
n = 0


def step(text):
    global n
    n += 1
    print(f"STEP {n}/{N} {text}", flush=True)


def run(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{what} failed: " + (r.stderr or r.stdout)[-400:].strip())
    return r.stdout


def tool(*p):
    return os.path.join(repo, *p)


try:
    step("Reading the video (frames and sound)")
    run([sys.executable, tool("analyze", "import_video.py"), a.video, F, a.title], "import")
    if a.keep_video is False and os.path.dirname(os.path.abspath(a.video)) == os.path.abspath(F):
        os.remove(a.video)

    step("Tracking the face")
    run([sys.executable, tool("analyze", "performance.py"), F], "face tracking")

    voice = os.path.join(F, "audio.wav")
    if sep_py:
        step("Pulling the voice out of the music")
        run([sep_py, tool("analyze", "separate.py"), F], "separation")
        voice = os.path.join(F, "vocals.wav")

    step("Listening for words")
    w = wave.open(voice)
    x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768
    if w.getnchannels() > 1:
        x = x.reshape(-1, w.getnchannels()).mean(1)
    k = w.getframerate() // 16000
    x = np.convolve(x, np.ones(k * 2 + 1) / (k * 2 + 1), "same")[::k]
    f32, raw = os.path.join(F, "_16k.f32"), os.path.join(F, "_asr.json")
    x.astype("<f4").tofile(f32)
    if not asr:
        sys.exit("LIPSCAN_ASR is not set (a folder with transcribe.mjs)")
    run(["node", os.path.join(asr, "transcribe.mjs"), f32, raw], "speech-to-text")
    res = json.load(open(raw, encoding="utf-8"))
    os.remove(f32)
    os.remove(raw)

    step("Timing the words")
    words = [(round(c["timestamp"][0], 2), c["text"].strip()) for c in res["chunks"] if c["timestamp"][0] is not None and c["text"].strip()]
    json.dump([[t, wd] for t, wd in words], open(os.path.join(F, "words-timed.json"), "w", encoding="utf-8"))
    events, cur = [], []
    for t, wd in words:
        if cur and t - cur[-1][0] > 3:
            events.append(cur)
            cur = []
        cur.append((t, wd))
    if cur:
        events.append(cur)
    json.dump({"source": "local speech-to-text (Whisper small) on the recording's own audio",
               "events": [{"start": e[0][0], "dur": round(e[-1][0] - e[0][0] + 0.4, 2), "text": " ".join(wd for _, wd in e),
                           "words": [{"t": t, "text": wd} for t, wd in e]} for e in events]},
              open(os.path.join(F, "captions.json"), "w", encoding="utf-8"), indent=1)

    step("Retargeting: video + voice")
    run([sys.executable, tool("retarget", "retarget.py"), F, "--profile", a.profile, "--out", os.path.join(F, "retarget-hybrid.json")], "hybrid")
    step("Retargeting: video only")
    run([sys.executable, tool("retarget", "retarget.py"), F, "--video-only", "--profile", a.profile, "--out", os.path.join(F, "retarget-video-only.json")], "video-only")
    step("Retargeting: voice only")
    run([sys.executable, tool("model", "lipsync.py"), voice, "--words", os.path.join(F, "words-timed.json"), "--profile", a.profile,
         "--mood", "neutral", "--out", os.path.join(F, "lipscan-audio-only.json")], "voice model")

    step("Adding it to the demo list")
    seconds = round(json.load(open(os.path.join(F, "trace.json")))["frames"][-1]["t"], 1)
    base = "/pack/live/" + os.path.basename(F.rstrip("\\/")) + "/"
    title = a.title or os.path.basename(F)
    m = json.load(open(a.manifest, encoding="utf-8"))
    template = next((c for c in m["characters"] if c["lines"][0].get("sources")), None)
    pack = template["pack"] if template else "/pack/kerry_old/"
    m["characters"] = [c for c in m["characters"] if c.get("dropped") != os.path.basename(F)]
    m["characters"].insert(0, {
        "name": f"Dropped: {title} on Kerry", "pack": pack, "dropped": os.path.basename(F),
        "lines": [{
            "text": f"{title}, {seconds:g} s", "noMood": True, "noText": True, "profile": a.profile,
            "label": "Dropped video. A = hybrid (head, brows, blinks, eyes and smiles from the video; jaw, lips, tongue and neck from the voice). "
                     "B = the base model, voice only. The video is in the corner. Head A / Head B switch each head between video only, video + audio and audio only.",
            "game": base + "retarget-hybrid.json", "lipscan": base + "lipscan-audio-only.json", "audio": base + "audio.wav",
            "video": base, "hybrid": base, "words": base + "words-timed.json", "seconds": seconds, "mood": "neutral",
            "sources": {"video": base + "retarget-video-only.json", "hybrid": base + "retarget-hybrid.json", "audio": base + "lipscan-audio-only.json"},
        }]})
    json.dump(m, open(a.manifest, "w", encoding="utf-8", newline="\n"), indent=1)
    print("DONE", flush=True)
except SystemExit as e:
    print(f"FAILED: {e.code}", flush=True)
    sys.exit(1)
except Exception as e:
    print(f"FAILED: {e}", flush=True)
    sys.exit(1)

"""Turn a video file into a LipScan trace folder, with no browser: frames, audio and trace.json.

    pip install av opencv-python numpy
    python analyze/import_video.py "my video.mp4" "<trace folder>" "a title"

The folder then goes through the same steps as a recording from the Firefox add-on (analyze/performance.py, retarget/retarget.py,
the viewer). See docs/IMPORTING.md.

  frames\\f000001.jpg ...   every 1/30 s tick of the video, long side 960 px (the face stays large)
  audio.wav                 mono, 48 kHz, 16-bit
  trace.json                the frame times, the audio's clock and the source's title

The video file is only read; nothing is written next to it."""
import argparse
import json
import os
import sys
import wave


def main():
    ap = argparse.ArgumentParser(description="Turn a video file into a LipScan trace folder.")
    ap.add_argument("video")
    ap.add_argument("folder", help="the trace folder to make (outside this repo: it holds your frames and sound)")
    ap.add_argument("title", nargs="?", default="", help="a title for the recording")
    ap.add_argument("--long-side", type=int, default=960, help="longest side of the saved frames in pixels (default 960)")
    a = ap.parse_args()
    try:
        import av
        import cv2
        import numpy as np
    except ImportError as e:
        sys.exit(f"{e}. Install the readers first: pip install av opencv-python numpy")

    os.makedirs(os.path.join(a.folder, "frames"), exist_ok=True)

    # audio: mono 48 kHz, 16-bit
    c = av.open(a.video)
    if not c.streams.audio:
        sys.exit("This video has no sound track; LipScan needs the voice.")
    res = av.AudioResampler(format="s16", layout="mono", rate=48000)
    chunks = []
    for fr in c.decode(audio=0):
        for r in res.resample(fr):
            chunks.append(r.to_ndarray().reshape(-1))
    for r in res.resample(None):
        chunks.append(r.to_ndarray().reshape(-1))
    pcm = np.concatenate(chunks).astype("<i2")
    with wave.open(os.path.join(a.folder, "audio.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(pcm.tobytes())
    seconds = len(pcm) / 48000
    print("audio", round(seconds, 2), "s", flush=True)

    # frames: one per 1/30 s tick
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames, i, k = [], 0, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = i / fps
        if t >= k / 30 - 1e-6:
            h, w_ = f.shape[:2]
            s = a.long_side / max(h, w_)
            f = cv2.resize(f, (round(w_ * s), round(h * s)), interpolation=cv2.INTER_AREA)
            k += 1
            name = f"frames/f{k:06d}.jpg"
            cv2.imwrite(os.path.join(a.folder, name), f, [cv2.IMWRITE_JPEG_QUALITY, 88])
            frames.append({"file": name, "t": round(t, 6)})
        i += 1
    if not frames:
        sys.exit("No frames could be read from this video.")
    print("frames", len(frames), flush=True)
    size = cv2.imread(os.path.join(a.folder, frames[0]["file"])).shape
    json.dump({"source": {"url": "local file", "title": a.title}, "tool": "lipscan local import", "frameSize": [size[1], size[0]],
               "frameClock": "video file timestamps", "audioClock": "video file", "start": 0.0, "frames": frames,
               "audio": {"file": "audio.wav", "rate": 48000, "start": 0.0, "seconds": round(seconds, 3)}},
              open(os.path.join(a.folder, "trace.json"), "w"), indent=1)
    print("done")


if __name__ == "__main__":
    main()

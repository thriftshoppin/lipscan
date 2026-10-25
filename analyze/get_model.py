"""Download MediaPipe's models (Apache 2.0, from Google) into models/:
  - Face Landmarker (about 3.7 MB): blendshapes, head pose
  - BlazeFace short-range face detector (about 0.2 MB): detection confidence per frame
"""
import os
import sys
import urllib.request

MODELS = {
    "face_landmarker.task": ("https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task", 1_000_000),
    "blaze_face_short_range.tflite": ("https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite", 100_000),
}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for name, (url, smallest) in MODELS.items():
    out = os.path.join(ROOT, "models", name)
    if os.path.exists(out) and "--force" not in sys.argv:
        print(f"Already there: {out} (use --force to download again)")
        continue
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, out + ".part")
    if os.path.getsize(out + ".part") < smallest:
        sys.exit(f"The download of {name} looks wrong (too small); nothing saved.")
    os.replace(out + ".part", out)
    print(f"Saved {out} ({os.path.getsize(out) / 1e6:.1f} MB)")

"""Download MediaPipe's Face Landmarker model (about 3.7 MB, Apache 2.0, from Google) into models/."""
import os
import sys
import urllib.request

URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(ROOT, "models", "face_landmarker.task")
if os.path.exists(out) and "--force" not in sys.argv:
    sys.exit(f"Already there: {out} (use --force to download again)")
os.makedirs(os.path.dirname(out), exist_ok=True)
print(f"Downloading {URL}")
urllib.request.urlretrieve(URL, out + ".part")
if os.path.getsize(out + ".part") < 1_000_000:
    sys.exit("The download looks wrong (too small); nothing saved.")
os.replace(out + ".part", out)
print(f"Saved {out} ({os.path.getsize(out) / 1e6:.1f} MB)")

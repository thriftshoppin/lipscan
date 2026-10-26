"""Isolate the voice from a recording that has music in it, and save it as vocals.wav next to audio.wav.

The voice model, the word timing and the consonant checks then read vocals.wav; playback keeps the full mix (audio.wav).
Needs demucs, which is not in the main environment (it brings torch):

    python -m venv separate-venv
    separate-venv\\Scripts\\pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
    separate-venv\\Scripts\\pip install demucs numpy
    separate-venv\\Scripts\\python analyze\\separate.py "<trace folder>"

The model (htdemucs) is downloaded once, from the demucs project, the first time it runs."""
import argparse
import os
import wave

import numpy as np


def read_wav(path):
    with wave.open(path) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768
        ch, rate = w.getnchannels(), w.getframerate()
    return x.reshape(-1, ch).mean(axis=1), rate


def write_wav(path, x, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes())


def isolate(mix, rate, model_name="htdemucs", shifts=0):
    import torch
    import torchaudio
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    model = get_model(model_name)
    model.eval()
    x = torch.from_numpy(mix).float()[None]
    x = torchaudio.functional.resample(x, rate, model.samplerate)
    stereo = x.repeat(2, 1)[None]                          # the trace's audio is mono: both channels the same
    ref = stereo.mean(0)
    stereo = (stereo - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        out = apply_model(model, stereo, shifts=shifts, split=True, overlap=0.25, progress=True)[0]
    voice = out[model.sources.index("vocals")] * (ref.std() + 1e-8) + ref.mean()
    voice = torchaudio.functional.resample(voice.mean(0, keepdim=True), model.samplerate, rate)[0]
    return voice.numpy()


def main():
    ap = argparse.ArgumentParser(description="Isolate the voice of a trace's audio.wav into vocals.wav.")
    ap.add_argument("folder")
    a = ap.parse_args()
    src = os.path.join(a.folder, "audio.wav")
    mix, rate = read_wav(src)
    voice = isolate(mix, rate)
    voice = voice[:len(mix)] if len(voice) >= len(mix) else np.pad(voice, (0, len(mix) - len(voice)))
    out = os.path.join(a.folder, "vocals.wav")
    write_wav(out, voice, rate)
    print(f"Wrote {out}: {len(voice) / rate:.2f} s at {rate} Hz")


if __name__ == "__main__":
    main()

# Importing a video

You don't need YouTube or Firefox to scan a video. Any video file with a face and a voice can be turned into a **trace folder**, the same folder the Firefox add-on makes, and then it goes through the same steps.

```
video file ──> import_video.py ──> trace folder ──> performance.py ──> performance.json ──> retarget.py ──> retarget-hybrid.json
                                        │                                                        ▲
                                        └─ audio.wav ─> (separate.py ─> vocals.wav) ─> words ────┘
```

Keep trace folders **outside the repo**. They hold your frames and your sound, and `.gitignore` guards against them.

## What you need

- Python 3.10 or newer, with `mediapipe` for the face (see the README's Setup), plus the video readers:
  ```
  .venv\Scripts\pip install av opencv-python numpy
  ```
- A video with the face in view and the voice on its sound track. A close, front-on, well-lit face reads best.

## 1. Make the trace folder

```
.venv\Scripts\python analyze\import_video.py "my video.mp4" "D:\lipscan\my-video" "A title"
```

This writes, in `my-video\`:

| File | What it is |
|---|---|
| `frames\f000001.jpg` ... | one frame per 1/30 s, longest side 960 px (`--long-side` changes it) |
| `audio.wav` | the sound, mono, 48 kHz, 16-bit |
| `trace.json` | the frame times, the audio's clock and the title |

The video file is only read. Frames are always sampled at 30 per second, whatever the video's own rate.

## 2. Track the face

```
.venv\Scripts\python analyze\performance.py "D:\lipscan\my-video"
```

Writes `performance.json`. The last line says how often the face was seen. Anything under about 90% means the face was small, turned away, or covered; check the frames.

## 3. Give it the words

The voice side of the hybrid needs **timed words**, `words-timed.json`: `[[seconds, "word"], ...]`, one pair per word, on the audio's clock. It also reads `captions.json` (the same words as caption events). Two ways to get them:

- **From a speech-to-text pass.** Any one that gives a time per word works (Whisper does; so does the captions file a YouTube recording saves). Sung words come out loosely, which is fine: step 5 fixes them with your own lyrics.
- **From your lyrics**, once a speech-to-text pass has given the times to line them up to (step 5).

Without any words the hybrid still runs, but with the jaw, tongue and neck only: no consonants.

## 4. Music in the sound? Isolate the voice first

The voice model, the word timing and the consonant checks all listen to the sound. With a band playing they are listening to the band. `analyze/separate.py` pulls the voice out into `vocals.wav`, beside `audio.wav`:

```
python -m venv separate-venv
separate-venv\Scripts\pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
separate-venv\Scripts\pip install demucs numpy
separate-venv\Scripts\python analyze\separate.py "D:\lipscan\my-video"
```

It needs its own environment, because demucs brings torch. The model (htdemucs) downloads once. A couple of minutes of CPU for a three-minute song. From then on everything reads `vocals.wav` when it is there, and the **viewer still plays the full mix** (`audio.wav`), so a demo has the vocals and the band.

Run the speech-to-text pass on `vocals.wav`, not the mix: it hears the words much better.

## 5. Your own lyrics (optional, recommended for singing)

Speech-to-text hears a sung song loosely ("angle" for "angel") and times each word from the middle of the syllable. If you have the lyrics:

- **In the viewer:** paste them into the **Lyrics** box and press **Use these lyrics** (see [USING_THE_VIEWER.md](USING_THE_VIEWER.md)).
- **From the command line:**
  ```
  python analyze\lyrics.py apply "D:\lipscan\my-video" lyrics.txt
  python analyze\lyrics.py reset "D:\lipscan\my-video"      # back to the speech-to-text words
  ```

It lines your words up to what the speech-to-text heard, so each one gets a time, then moves each word to where the voice really starts it (the first rise in the voice's loudness within 0.25 s). It rewrites `words-timed.json` and `captions.json` and keeps the speech-to-text versions as `*-whisper.json`. Paste the **whole** song, repeated choruses included: the order is what the lining-up goes by. On one close-up singing video, snapping to the voice moved the b/p/m words from 0.17 s after the singer's real lip closures to 0.03 s, and the share within 0.10 s of a real closure from 14% to 61%.

## 6. Retarget onto a rig

```
.venv\Scripts\python retarget\retarget.py "D:\lipscan\my-video" --profile singing-hard --out "D:\lipscan\my-video\retarget-hybrid.json"
.venv\Scripts\python retarget\retarget.py "D:\lipscan\my-video" --video-only --profile singing-hard --out "D:\lipscan\my-video\retarget-video-only.json"
```

- The default is the **hybrid**: the head, brows, blinks, gaze and smiles from the video; the jaw, lips, tongue and neck from the voice, **added on top of** the video's mouth and never replacing it. `--video-only` reads the whole mouth from the video. `--no-reinforce` makes the voice replace the video's lip shapes and closures instead.
- `--profile`: `speech` for talking, `singing` for singing, `singing-hard` for singing with a lip burst on hard k, g, c and q.
- The voice's lip presses (b, p, m) are kept only where the video's own lips meet. Rounded or open sounds (w, sh, uh) are never drawn as closures.
- The lower lip's drop is moved onto the jaw (`--lower-teeth`), and the jaw slides forward as it lowers (`--jaw-forward`). Details in [PERFORMANCE.md](PERFORMANCE.md) and the CHANGELOG.

You can also make the voice-only head (what the model does with the sound alone):

```
python model\lipsync.py "D:\lipscan\my-video\vocals.wav" --words "D:\lipscan\my-video\words-timed.json" --profile singing-hard --mood neutral --out "D:\lipscan\my-video\lipscan-audio-only.json"
```

## Getting the best result

- **Match all the vocals.** The diction layer follows the words, so it works best when the performer actually says or sings **every word** of the lyrics you give it. Where a line is skipped, mumbled or held out, there is nothing to follow, and the diction loses its place until the next words it recognises, then finds itself again. This was seen on a full song: a short stop in the singing was enough for the consonants to drift until the following words pulled them back. So upload (and paste lyrics for) a take that voices all of the vocals, and where words are cut, cut them from the lyrics too.
- **Face and mouth.** A close, steady, front-on face with the lips in view. Facial hair, a hand, or a microphone in front of the mouth makes the lip gap harder to read; check `lipGap` on the closed-mouth moments. A resting closed mouth should read near 0.
- **Clean words.** Run the speech-to-text on `vocals.wav`. Paste real lyrics when you have them.
- **Clips with no words** (humming, a held note) have no diction to add: use `--video-only` there.

## Then watch it

Add the folder to a test-set manifest and open it in the viewer: [USING_THE_VIEWER.md](USING_THE_VIEWER.md).

# Whole-face performance capture

LipScan 0.2.0 records the whole face, not only the mouth: brows, eyes, blinks, gaze, cheeks, nose, jaw, lips and head motion. It then plays that performance back on a face rig.

```
trace folder ──> analyze/performance.py ──> performance.json ──> retarget/retarget.py ──> retarget-cyberpunk.json
(frames, audio)   MediaPipe, every frame     the real face,        mapping JSON:            face-rig curves + head
                  + clean-up                 cleaned                 MediaPipe -> rig tracks   angles, for a viewer/game
```

```
python analyze\performance.py "<trace folder>"
python retarget\retarget.py "<trace folder>"                    # raw rig names (what the viewer plays)
python retarget\retarget.py "<trace folder>" --export cyberpunk  # game dialogue-layer names
python analyze\analyze.py "<trace folder>"                       # measurements, now including the upper face
```

## What's recorded per frame

All of it is on the **video's own clock**: `t` is seconds from the trace's start (`clock.video_start`, a time in the video).

| Channel | What it is |
|---|---|
| 52 blendshapes | Everything MediaPipe's Face Landmarker gives, in its order: `_neutral`, `browDownLeft` … `noseSneerRight`. Values 0 to 1. |
| `headYaw`, `headPitch`, `headRoll` | Degrees, from MediaPipe's facial transformation matrix. **Yaw > 0** turns to the subject's own left, **pitch > 0** lifts the chin, **roll > 0** tilts toward the left shoulder. |
| `headX`, `headY`, `headZ` | Head position in cm, relative to the camera (MediaPipe's face-model space). Not changed by clean-up. |
| `gazeLeftYaw`, `gazeLeftPitch`, `gazeRightYaw`, `gazeRightPitch` | Degrees per eye, from the `eyeLook*` blendshapes. Yaw > 0 looks toward the subject's left, pitch > 0 looks up. `eyeLook = 1` is taken as 35° sideways and 25° up or down. MediaPipe doesn't publish this scale, so treat it as approximate. |
| `confidence` | The BlazeFace detector's score for the tracked face (0 to 1). `null` when no face was found, or when the detector model isn't installed. |
| `faces_in_frame` | How many faces MediaPipe saw (up to 4), whichever one was tracked. |

**Dropped frames are gaps, never zeros.** A frame without the tracked face is `null` in every channel.

## Clean-up

Each step is on by default and can be switched off. The settings used are saved in the file.

| Step | Switch | What it does |
|---|---|---|
| One face only | `--no-lock` | Starts on the largest face. After that it follows the face nearest its last position with a similar size, and never jumps to another face elsewhere in the frame. If the face is lost, it's picked up again only near where it was last seen; the search widens a little the longer it's gone. **Only position and size are used, never what the face looks like.** This keeps it tracking-only, but it means a hard cut to a different person filmed at the same spot and size can't be told apart. |
| Fill short gaps | `--gap 0` (off), `--gap 0.3` | Gaps up to 0.2 s are bridged with straight lines. Longer ones stay `null`. |
| Neutral calibration | `--no-neutral` | Estimates the person's resting face from their calmest 10% of frames: least expression, least movement. Each blendshape's resting value is subtracted and the rest is rescaled: `(v − rest) / (1 − rest)`. A naturally low brow then doesn't read as a frown. Blink, gaze and `_neutral` are left alone. Head angles become relative to the median head pose, so someone sitting turned toward the camera faces forward. If their head motion over the trace is lopsided, the median shifts it too; `--keep-head-angle` keeps camera-relative angles. The resting values are saved under `neutral`. |
| One-euro smoothing | `--no-smooth` | The [one-euro filter](https://gery.casiez.net/1euro/) smooths slow movement a lot and fast movement little. Eye channels (blinks, squints, gaze) use fast settings so a 100 ms blink keeps about 90% of its depth (tested). Other channels use calmer settings. |

`--reclean` re-runs only the clean-up from the raw values saved in the file, without tracking again.

## Left and right

**MediaPipe's "Left" is the subject's own left**, not the left of the image. The face rig's `l` is also the character's own left, so the mapping sends Left to `l` with no swap.

How this was checked: renders of a game head were run through MediaPipe, each with one side posed. The rig's left mouth corner raised gave `mouthSmileLeft` 0.62 against `mouthSmileRight` 0.20. The left outer brow raised gave `browOuterUpLeft` +0.20 and nothing on the right. A right blink registered on the right eye (as a squint, because the render's eyes have no irises). The same renders confirmed the head-angle signs: turning the head +20° (character's left) read as +22°, chin-up +15° as +14°, and a +15° tilt toward the left shoulder as +15°.

One limit: if a video was **mirrored** by whoever made it (common with selfie cameras), left and right are swapped in the video itself, and nothing in the picture can tell.

## performance.json

```
{
  "format": "lipscan-performance/1",
  "source": {"url", "title"},
  "clock": {"video_start": 61.2, "note": ...},
  "fps": 29.97, "frames": 900, "face_seen": 0.97,
  "settings": {"lock_face", "fill_gaps_s", "neutral", "neutral_fraction", "smooth", "one_euro": {...}},
  "conventions": {...},
  "neutral": {"browDownLeft": 0.21, ...},        // resting values that were subtracted
  "t": [0.0, 0.0334, ...],                       // seconds from video_start, one per frame
  "file": ["frames/f000001.jpg", ...],
  "confidence": [0.97, null, ...],
  "faces_in_frame": [1, 0, ...],
  "channels": {"jawOpen": [...], "headYaw": [...], ...},   // cleaned; null = gap
  "raw": {...}                                              // as tracked, before clean-up
}
```

## Retargeting

`export/mediapipe_to_cyberpunk.json` is the mapping. It's meant to be edited. Each MediaPipe blendshape lists the face tracks it drives:

```json
"browDownLeft": [
  {"track": "eye_l_brows_lower",        "gain": 1.0, "offset": 0, "clamp": [0, 1]},
  {"track": "eye_l_brows_lateral",      "gain": 0.6, "offset": 0, "clamp": [0, 1]},
  {"track": "eye_l_oculi_squint_inner", "gain": 0.3, "offset": 0, "clamp": [0, 1]}
]
```

- **Value:** `clamp(gain × source + offset)`. When several sources drive one track, the largest value wins.
- **Regions:** brows (raise in and out, lower, lateral), eyes (blink, widen, three squints), gaze (all 8 eye-direction poses), cheeks, nose, jaw and lips.
- **Gaze gains:** these come from the rig itself. Its eye poses turn 40° in or out, 21° up and 30° down at 1.0, measured from the facial setup.
- **Head:** angles are passed through as degrees in `head`, not as face tracks. The rig's `neck_*` and `head_neck_*` poses only move neck skin and muscles (measured: they don't turn the head bone). In the game, the head turns with the body skeleton. A viewer applies the angles to the Neck, Neck1 and Head bones (30/30/40%).
- **Tongue:** video can't see the tongue, so by default its tracks come from the audio model run on the trace's own audio and caption words. `--no-tongue` leaves them out.

**Not mapped, and why.** These are listed in the mapping file too; nothing is dropped silently.

| | Why |
|---|---|
| `_neutral` | MediaPipe's "no expression" score; there's nothing to drive. |
| `tongueOut` | MediaPipe doesn't produce it (ARKit does). |
| Pupils (`eye_*_pupil_wide/narrow`) | MediaPipe doesn't measure pupils. |
| `nose_*_compress`, `nose_*_breathe_in/out`, `cheek_*_suck`, `jaw_mid_close`, `jaw_mid_shift_back`, `jaw_mid_clench` | No MediaPipe match. |
| `lips_*_pull`, `lips_*_corner_stretch`, `lips_*_corner_sharp_up`, `lips_mid_shift_up/dn`, `lips_apart_up`, `lips_*_lower_raise` | No clean MediaPipe match; left at rest. |
| `neck_*`, `head_neck_*`, `ear_*`, `face_gravity_*`, `sculp_*`, sticky-lip tracks | Not expression shapes, or not measurable from video. |

The output is `retarget-cyberpunk.json`: `{"fps": 30, "tracks": {...}, "head": {"yaw", "pitch", "roll"}, "video": {"start", "trace"}}`. Frame 0 is the trace's start, so the trace's `audio.wav` lines up. Frames with no face are `null`.

## Mouth smoothing

Mouth shapes (`jawOpen`, `mouth*`, plus `lipGap` and `mouthWidth`, which are measured from the landmarks) get their own one-euro filter, a 3 Hz base and beta 2, where the head, brows and gaze keep 1.5 Hz and beta 0.5 (blinks keep their own faster one). A lip closure is over in two or three frames; the slower filter cut it to about two thirds of its height. Settings: `one_euro.mouth_min_cutoff_hz`, `one_euro.mouth_beta`; `--mouth-cutoff` and `--mouth-beta` change them, and `--legacy-mouth` goes back to the single filter. `--refine` adds an enlarged-crop second look at the locked face; it is off, because it lowered the match on the test clip. Numbers: docs/MEASUREMENTS.md.

## Mouth: hybrid or video-only

A face that is small in the frame, turned away or low resolution gives a weak mouth reading. On a 640 px talking-head clip, the tracked jaw was about 2.3 times too small and matched the voice at 0.31–0.42. The voice model matched at 0.95. So `retarget.py` is a **hybrid** by default:

| From the voice | From the video |
|---|---|
| jaw, p/b/m closures and lip shapes (with caption words), tongue, neck | head, brows, blinks, gaze, cheeks, nose, smiles and frowns |

The jaw also takes the video where the mouth is clearly wider than the voice suggests. `--video-only` reads everything from the video instead; use it for a large, well-lit, face-on shot. Turn captions on before recording (press `c`) so the voice side has words.

The hybrid takes the same dials as the voice model: `--articulation`, `--expressiveness` (the voice side's), `--coupling` and `--jaw-presence` (or `--rig character.json`), and `--profile` for the voice side. The coupling is added after the merge, so the cheeks, nose and chin follow whichever mouth the tracks ended up with; frames with no face stay empty. `--out -` writes the result to the terminal.

Lips pushed forward: where the video reads pucker, the hybrid's purse is the video's (a weak reading lifted toward a 95th percentile of 0.15, at most 4 times; funnel is the larger of the two; purse + funnel at most 0.6). Without it the voice model's purse was scaled by the mouth size and the video's pucker was discarded. `analyze.py "<folder>" --forward` scores this against the video (docs/MEASUREMENTS.md).

Lip separation: when the video's jaw reaches the rig's scale (95th percentile 0.3 or more), the hybrid's jaw, lower-lip drop, upper lip and chin come from the video instead of the voice, and the lip tracks that ride on the jaw ride on the video's jaw; the voice keeps closures, tongue and neck. `--mouth-from auto|video|voice` (auto by default). A small or turned face reads weakly and stays voice-led. Numbers in docs/MEASUREMENTS.md.

Rounded mouths: MediaPipe's `mouthPucker` goes to the rig's purse while the lip gap says the lips are shut (under 0.04) and to the funnel as they part (to 0.10), so a sung "o" is an open round mouth instead of a pout. `--round-split 0` maps the pucker to the purse as before.

Lip gap: where the head's lips are less parted than the video's measured lip gap, they open to match (`--gap-fill 0` to turn off). It never closes lips, and it leaves closures and frames with no face alone.

Diction: when the video reads the mouth well, the p/b/m-type closures come from the video's own lip gap (brief dips with the lips open either side), replacing the word-placed ones where the face is seen; `--no-video-diction` turns it off. Sung words are timed too loosely to place a 2-frame closure.

## In the viewer

The face viewer (built with `claude/skills/cyberpunk-face-viewer`) plays `retarget-cyberpunk.json` in slot A or B:

- head motion, with a **Head motion** switch
- gaze, through the eye-direction poses
- grey bands on the timeline where the trace saw no face

Load the trace folder with **Video…** (or `video=<trace folder>/` in the address), and the real frames play in a corner pane in sync with the character.

## Privacy

Tracking, not recognition. `performance.json` holds only:
- expression values
- head pose
- gaze
- a detection score
- frame times and file names

It never stores face points (MediaPipe's 478-point mesh is used in memory and thrown away), face prints, identity embeddings, or anything that could recognise a person.

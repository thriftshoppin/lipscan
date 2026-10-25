# Changelog

## 0.2.0 (2026-10-24)

The whole face, not just the mouth.

- **New: `viewer/`.** The source of the 3D face viewer:
  - the character-pack converter
  - the solver, with head motion
  - the A/B player, with the video pane
  - one-file build

  You build packs from your own game install. No game data, packs or built viewer are included, and `.gitignore` guards against game files, audio, frames and screenshots.

- **New: `analyze/performance.py`.** Records the whole facial performance from a trace, frame by frame on the video's own clock, into `performance.json`:
  - all 52 MediaPipe blendshapes
  - head yaw, pitch, roll and position
  - gaze per eye
  - detection confidence (new BlazeFace model in `get_model.py`)
  - dropped frames saved as gaps, never zeros
- **Clean-up,** each step on by default and switchable:
  - one face only: locks onto the main face by position and size, never by identity
  - gaps under 0.2 s filled
  - neutral calibration: the person's resting face is subtracted
  - one-euro smoothing tuned to keep blinks
- **Left/right and head-angle conventions verified** on renders of a game head. MediaPipe's "Left" is the subject's own left, which matches the rig's `l`.
- **New: `retarget/retarget.py` and `export/mediapipe_to_cyberpunk.json`.**
  - **The mapping:** editable, from MediaPipe to the Cyberpunk face rig, with a gain, offset and clamp per link. It covers brows, eyes, gaze (all 8 eye-direction poses, with gains measured from the rig), cheeks, nose, jaw and lips.
  - **Unmapped:** every shape or track without a match is listed in the file and in the docs.
  - **Head:** head angles pass through as degrees.
  - **Tongue:** filled from the audio model, because video can't see it.
- **Model:** a voice-driven upper face, set by the profile's new `upper_face` section:
  - blinks in the middle of pauses, like the game
  - brow raises on stressed syllables (loudness and pitch)
  - frowns and squints on loud stretches (speech), or on effort (singing)
  - resting gaze
  - small head nods and sway
  - new numpy-or-plain-Python pitch tracker
  - seeded and repeatable
- **Profiles:** `speech-cyberpunk` and `singing-cyberpunk` gain `upper_face`, fitted to the game's dialogue clips and concert motion capture. Old profiles still work.
- **Analyze:** upper-face measurements from `performance.json` (blinks, brow raises and lead, head motion, gaze). `--save-profile` writes them into the profile.
- **New: `analyze/game_upper_face.py`.** Measures a game character's upper face from your own exports and scores the model against it, with an optional `--fit`.
- **Export:** `arkit52` now includes brows, squints, cheeks, wide eyes and gaze.
- **Viewer skill:** head motion, gaps on the timeline, a source-video pane, file names on the buttons, and `clip` / `view=ab` / `video` address parameters.
- **Docs:**
  - new: `docs/PERFORMANCE.md`
  - upper-face measurements and scores in `docs/MEASUREMENTS.md`
  - privacy wording for the new data in `docs/SECURITY.md`
  - correction: the game's dialogue layer does blink (18.3 a minute)
- **Tests:** 26 new checks in `test/test_performance.py`.

## 0.1.x (unreleased additions)

- **New: `claude/skills/cyberpunk-face-viewer`.** A Claude skill that builds a local 3D face viewer from the user's own Cyberpunk 2077 install:
  - a character-pack converter, using WolvenKit
  - the face-solver math, rebuilt from the game's facial setup
  - a one-file offline viewer with play/pause, a timeline, A/B comparison and a pose tester

  No game data or prebuilt viewer is distributed.
- **Docs:** the WolvenKit guide now explains the facial setup, and that the CLI can't re-import animations.

## 0.1.0 (2026-10-24)

First release.

- **Capture:** Firefox add-on and MCP server that record a YouTube video's frames, sound and captions, all on the video's own clock.
  - YouTube only, local only, with a mutual challenge-response login.
  - REC badge, Stop button and off switch.
  - 2 GB cap per recording.
- **Analyze:** MediaPipe face tracking, plus measurements of jaw lead, the loudness-to-jaw curve, speeds, syllable rate, blinks and symmetry.
  - Scores the model against the real face.
  - `--save-profile` makes a profile from a recording.
  - Uses corrected caption words, keeping YouTube's word times.
- **Model:** voice (with optional text or timed words) to mouth curves.
  - Settings live in profiles.
  - Includes `speech-cyberpunk` and `singing-cyberpunk`, measured from Cyberpunk 2077.
- **Export:** `arkit52`, `cyberpunk` and `raw` track names.
- **Docs:** history, WolvenKit guide, measurements, profiles, security.
- **Tests:** 28 capture/login checks and 12 model checks.

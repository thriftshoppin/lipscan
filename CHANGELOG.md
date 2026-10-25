# Changelog

## 0.2.2 (2026-10-25)

Brows that map properly, polish, and a test across characters.

- **Brows under a mood:**
  - **Cause:** a held scowl (brows down) got the voice's brow-raise accents (0.48) added on top. Raised and lowered brows together is a combination the game never uses, and it flattened the scowl and tore the brow mesh.
  - **The fix:** shapes that work against a held mood (raise vs lower, corners up vs down) now turn into a little emphasis on the held shape instead (25%). The same rule is in the model (`apply_mood`) and the viewer.
- **Mood presets, per side:** they're now measured per side; the game's scowl is lopsided (right brow 0.30 vs left 0.32, squints 0.25/0.18/0.20 vs 0.30/0.22/0.30). Staging gaze (looking off to the side) is left out of the presets.
- **Teeth through the lips:** purse and funnel no longer stack. In the game they never do: when one is up, the other is about 0. Their sum is capped at 0.6, so puckered lips stay over the teeth.
- **Pops:** lip and tongue shapes other than p/b/m presses now ease in over 100 ms and out over 130 ms (profile `soft_attack_ms` / `soft_release_ms`). Their frame-to-frame jumps were 3–5 times the game's; now they're 1.2–2 times, with shapes at about 90% strength and hits unchanged.
- **Across characters:** tested on six characters' own game lipsync (Kerry, Judy, Panam, Jackie, Johnny, Takemura), and on a V face built from character-creator presets.
  - **What carries over:** jaw corr 0.72–0.81, p/b/m hits 47–75%, blink hits 33–68% (chance 8–19%), and an upper-face error of 0.04–0.06 with the right mood, for every character.
  - **Rigs:** all six rigs are structurally identical.
  - **Verdict:** a face simulator, with caveats (docs/MEASUREMENTS.md).
- **Moods are the game's:** the held levels are identical across characters, so the presets describe the game, not Kerry. New: `calm` (the game's soft-squint default).
- **Profiles:**
  - `speech-cyberpunk` is now the cross-character average: blink and brow rates, frown strength, jaw size.
  - Kerry's own fit is `speech-kerry`.
  - `singing-cyberpunk` is renamed `singing-kerry`; the old name still works.
- **Auto mood:** pitch now only counts relative to the same speaker (`--voice-ref`). It didn't carry over between voices; set moods by hand.
- **Viewer:**
  - **Test-set panel** (`?demo=manifest.json`): pick a character and a line, or step with Prev/Next, to see the game's lipsync (A) next to LipScan's from the voice alone (B), with audio and the game's mood. `demoChar` and `demoLine` address parameters link straight to a line.
  - **Converter:** uses a character's own eyes and teeth when they have them (female heads had none before).
- **Viewer, eyebrows:** they're drawn 3 mm toward the camera, like a decal. When the brows move, the skin slides over the eyebrow cards; that tore even on the game's own clips. They're clean now with raises, blinks and frowns.

## 0.2.1 (2026-10-24)

Polish from a frame-by-frame review against the game.

- **Lip closures (p/b/m):**
  - **Shape:** they're now short, sharp peaks like the game's (133 ms at half height, as measured), not 170 ms plateaus.
  - **Strength:** capped by the profile's new `closure_peak` (0.95). Purse, funnel and the other lip shapes give way under a press instead of stacking on it.
- **Placement:**
  - Consonants now sit right next to their vowel, inside the sound. Before, a word's first consonant after a pause was spread back into the silence; that's why the "p" of "prove" pressed through a pause and landed late.
  - No mouth shape plays whose sound falls in a pause.
  - Presses during pauses: 7.3% of quiet frames → 1.4%.
  - Tongue shapes during pauses: 16% → 3.5%.
- **Brows and blinks:** the model no longer raises the brows while the eyes are shut, as the game does. In the viewer, eyebrows get a small depth bias, so skin no longer pokes through them during blinks.
- **Moods (new):** `--mood neutral|scowl|warm|sad|surprised|<preset.json>|auto` holds an expression for the whole line, and the voice-driven accents ride on top.
  - **Measured presets:** `scowl` and `warm` are the median held levels of the game character's two kinds of dialogue lines.
  - **Hand-made presets:** `sad` and `surprised`, labelled as such.
  - **`auto`:** a labelled guess from pitch, loudness and pitch range. It picked the game's mood for 89% of the lines it was tuned on.
  - **Effect:** with the right mood, the upper face's average error against the game drops from 0.147 to 0.045.
  - **Presets:** live in `profiles/moods/`.
- **Viewer:** a **Mood** menu applies a preset to LipScan clips (A and/or B), or loads a custom preset JSON. Also the `mood=` address parameter.
- **Viewer: V and the character creator.** For a player base head, `build_character.py` (new `creator.py`) exports the head, eyes, eyebrows and teeth with the character creator's face morphs, and records how each preset moves the face joints.
  - **The panel:** Eyes, Nose, Mouth, Jaw and Ears (base or a preset), plus Base face and Random, and `&jaw=7` style address parameters.
  - **What it does:** the viewer applies the morphs and rebuilds the rig's rest pose, so lipsync, moods and poses work on the new face.
  - **Approximation:** when regions are mixed, each joint follows the region that moves its skin most.
  - **Tested on:** male V (20 presets) and female V (21).
- **Neck:** throat and neck tracks are held at the game's average levels while someone talks (profile `neck_during_speech`). In the game data they don't follow jaw, loudness or pitch.
- **Fix:** `game_upper_face.py` now reads held (constant) track values. That's where the game stores a line's mood.
- **Tests:** `test_performance.py` adds 10 checks, 36 in all:
  - closure shape and cap
  - no lip shapes in pauses
  - lip shapes giving way under a press
  - no brow raise during blinks
  - neck at rest in silence
  - mood presets, auto and custom

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

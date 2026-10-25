# LipScan

LipScan measures how real faces move in video and audio: the mouth, and since 0.2.0 the whole face (brows, eyes, blinks, gaze, cheeks, nose and head motion). It then uses those measurements in two ways:

- to play a recorded performance back on a face rig
- to turn speech or singing alone into face animation curves

- **Tracking, not recognition.** It measures what a face is doing (jaw opening, lip shapes, brows, blinks, head turns). It never identifies who someone is, and it stores no face prints or face points.
- **A developer tool.** It runs entirely on your own PC, from source. It isn't published on addons.mozilla.org or in any plugin directory.
- **Built for Claude.** Claude (Claude Code or the Claude desktop app) drives it through MCP, but the model and analysis also run on their own from the command line.
- **Game-neutral.** Cyberpunk 2077 was the first target, but the core is game-neutral.

## How it started

It started as a Cyberpunk 2077 mod idea: in-game bands that sing your own music, with mouths that actually match the words. WolvenKit's lipsync tool can only copy the game's existing animations, so we cracked open the game's own lipsync instead. That meant one character's dialogue, and his face capture during a live concert, measured against their recordings. The results:

- The mouth moves before the sound.
- It closes faster than it opens.
- Singing opens about twice as wide as speech.
- Every p, b and m presses the lips shut.

Those rules became a model. To check them against real people rather than one game, LipScan learned to record YouTube videos and track the faces in them. The full story is in [docs/HISTORY.md](docs/HISTORY.md).

## What it does

```
 capture/        analyze/                       retarget/                  export/
 YouTube  --->   whole-face tracking  -------->  performance -> face-rig    arkit52 (Unreal, Unity,
 frames,         (MediaPipe: 52 shapes,          curves + head angles       Blender, VRChat...)
 sound,          head pose, gaze), clean-up,                                cyberpunk (REDengine
 captions        measurements -> profile/  ->  model/: voice (+ words) ->  face rig, via WolvenKit)
                                                mouth + upper-face curves
```

1. **Capture:** a Firefox add-on plus an MCP server record a YouTube video's frames, sound and captions. Sound and picture are both stamped with the video's own clock, so they stay in sync through seeks, pauses and ads.
2. **Performance:** `analyze/performance.py` tracks the whole face in every frame and writes `performance.json`:
   - all 52 MediaPipe blendshapes
   - head yaw, pitch and roll, plus position
   - gaze per eye
   - detection confidence
   - gaps where no face was seen

   It then cleans the curves up. It locks onto one face, fills short gaps, subtracts the person's resting face, and smooths with settings that keep blinks. See [docs/PERFORMANCE.md](docs/PERFORMANCE.md).
3. **Retarget:** `retarget/retarget.py` maps the performance onto a face rig through an editable mapping (`export/mediapipe_to_cyberpunk.json`, with a gain, offset and clamp per link). The result is face-track curves plus head angles that a viewer or game can play.
4. **Analyze:** measures the mouth and, from `performance.json`, the upper face:
   - **Mouth:** jaw lead, the loudness-to-jaw curve, speeds, syllables per second, symmetry
   - **Upper face:** blinks, brow raises and how they lead the voice, head motion, gaze

   It scores the model against the real face, and can save the measurements as a new **profile**.
5. **Model:** turns a voice recording, optionally with its words and their times, into per-frame curves:
   - **mouth:** jaw, lips and tongue
   - **upper face:** blinks placed in pauses, brow raises on stressed syllables, frowns and squints on loud stretches, resting gaze and small head nods
6. **Export:** writes those curves for a target: the generic 52 ARKit blendshape names, or Cyberpunk 2077's face-rig names (see [docs/WOLVENKIT.md](docs/WOLVENKIT.md)).

## Layout

| Folder | What it is |
|---|---|
| `capture/extension/` | Firefox add-on. It can only touch `youtube.com` tabs and only talks to `127.0.0.1:8766`. It never writes files. Its badge shows ON, OFF or REC, and the popup has an off switch and a Stop button. |
| `capture/server/` | MCP server `lipscan` (Node 18+, no dependencies). Tools: `lipscan_status`, `lipscan_start`, `lipscan_stop`, `lipscan_list`. |
| `analyze/` | Whole-face tracking (`performance.py`), measurements (`analyze.py`), and measuring a game character's upper face (`game_upper_face.py`). Python and MediaPipe. |
| `retarget/` | Recorded performance to face-rig curves and head angles. |
| `model/` | Voice and words to face curves (plain Python, no dependencies; numpy makes pitch tracking faster). Includes the CMU Pronouncing Dictionary. |
| `profiles/` | Measured settings: `speech-cyberpunk` (six characters), `speech-kerry` and `singing-kerry` (one character each), the game's mood presets in `moods/`, and any you make. |
| `export/` | Track naming for each target, and the editable MediaPipe-to-Cyberpunk mapping. |
| `test/` | Self-tests and a terminal driver. |
| `docs/` | History, WolvenKit guide, measurements, profiles, security. |
| `viewer/` | Source of the 3D face viewer: game clips and LipScan curves played on a Cyberpunk 2077 character's real head, side by side. You build the character from **your own** game files; no game data or prebuilt viewer is shipped. |
| `claude/skills/cyberpunk-face-viewer/` | A Claude skill explaining the viewer and the game's face system, so Claude can build or adapt it. |

## Requirements

- Windows 10 or 11 (other systems are untested)
- Firefox 140 or newer
- Node.js 18 or newer
- Python 3.10 or newer (only the analysis needs packages: `mediapipe`)

## Setup

1. **Python for the analysis:**
   ```
   python -m venv .venv
   .venv\Scripts\pip install mediapipe
   .venv\Scripts\python analyze\get_model.py      # downloads MediaPipe's face models into models\
   ```
2. **Firefox add-on:** go to `about:debugging` > This Firefox > Load Temporary Add-on, and pick `capture\extension\manifest.json`. For a permanent copy, sign it yourself with `sign.ps1`. This signs it privately ("unlisted"), and your AMO key stays in memory only.
3. **Connect Claude:** click the LipScan toolbar icon, then **Copy connection code**. Add the server to your Claude config:
   ```json
   "mcpServers": {
     "lipscan": {
       "command": "node",
       "args": ["C:\\path\\to\\lipscan\\capture\\server\\server.js"],
       "env": { "LIPSCAN_CODE": "<paste the code>" }
     }
   }
   ```

## Use

- **Record:** open a YouTube video, click it once (so Firefox allows its sound to be captured), and ask Claude to scan it, for example "LipScan the next 30 seconds". Each recording goes to `%USERPROFILE%\Videos\LipScan\<date>_<title>\`:
  - `frames\`
  - `audio.wav`
  - `captions.json` and `captions.txt`
  - `trace.json` (index of frame times, audio start and clocks)
- **Without Claude:**
  ```
  node test\lipscan-call.mjs lipscan_start "{\"maxSeconds\":30}" --wait
  ```
- **Fix captions:** edit `captions.txt` in the recording's folder. Change only the words after the tab; YouTube's per-word times are kept.
- **Record the whole face, then put it on a rig:**
  ```
  .venv\Scripts\python analyze\performance.py "<folder>"           # writes performance.json
  .venv\Scripts\python retarget\retarget.py "<folder>"             # writes retarget-cyberpunk.json
  ```
- **Analyze:**
  ```
  .venv\Scripts\python analyze\analyze.py "<folder>" [--profile speech|singing] [--save-profile my-singer]
  ```
- **Animate a voice:**
  ```
  python model\lipsync.py voice.wav --text "the words" --profile singing --export arkit52 --out curves.json
  python model\lipsync.py voice.wav --words words.json --export cyberpunk --out curves.json
  ```
  `--words` takes timed words: `[[0.42, "maybe"], [0.80, "you"], ...]`.
- **Dials** (all 0.0 to 2.0, 1.0 = as measured; a value outside is held to the range):
  ```
  python model\lipsync.py voice.wav --text "the words" --articulation 1.5     # crisper p b t d k g, f v, oo w
  python model\lipsync.py voice.wav --expressiveness 1.3 --profile speech-expressive   # the face follows the voice's tone
  python model\lipsync.py voice.wav --coupling 1.0 --rig character.json       # cheeks, nose and chin follow the lips; bigger jaws show more
  ```
  - `--articulation`: how high and how fast plosives, f/v and oo/w go. 1.0 matches the game's press width (133 ms). Try 1.3 to 1.5 for a clipped voice or a deliberate delivery, 0.6 to 0.8 for mumbling. `speech-crisp` is 1.5.
  - `--expressiveness`: scales the brow raises, frown, squint and nods. `speech-expressive` and `singing-expressive` also tie them to pitch rise and tension; the other profiles don't.
  - `--coupling` and `--jaw-presence` (or `--rig`): see docs/MEASUREMENTS.md.
  - Lips push forward on oo, w, o and sh/ch (profile key `lip_forward`, scaled by articulation). `analyze.py "<folder>" --forward` compares that with the video.
  - A profile can set its own defaults (`"articulation"`, `"expressiveness"`, `"coupling"`); the command line wins. `retarget.py` takes the same flags for the hybrid. `analyze.py "<folder>" --sweep` tries values against a real face.
  - In the viewer's Test set, three sliders re-run the model live next to the original, and Head A / Head B each switch between video only, video + audio (the hybrid) and audio only (dev server only).

## See it on a real head (Cyberpunk 2077)

`viewer/` holds the viewer's source code. LipScan doesn't ship any game data, so you build the character from **your own** install. See [viewer/README.md](viewer/README.md).

- **The converter** (`build_character.py`): reads a character's head, face skeleton and facial setup with WolvenKit, into a private character pack.
- **The viewer:** one offline HTML file, built with `npm install` then `node build.mjs`. It runs a rebuilt copy of the game's face solver and has:
  - play/pause and a timeline
  - A/B comparison
  - a pose tester
  - head motion
  - a source-video pane

`claude/skills/cyberpunk-face-viewer/SKILL.md` explains how it all works, so Claude can build, check or adapt it for you.

## How well it works

These numbers compare the model with Cyberpunk 2077's own lipsync, for the character it was measured on. Correlation is shape match (1.0 = identical); "hits" means the closure lands within about one frame of the game's.

| | Speech (26 lines) | Singing (2.5 min) |
|---|---|---|
| Jaw correlation | 0.79 | 0.76 |
| Lips shut on p/b/m | 75% hits | |
| Lower lip tucked on f/v | 77% hits | |
| Lips pursed on oo/w | 61% hits | |
| Blink timing (from audio alone) | 68% hits (15% by chance) | 26% hits (16% by chance) |
| Brow raise correlation | 0.32 | rare in the game |
| Frown correlation | 0.25 | 0.32 |
| Across 6 characters (both sexes, 3 body types): jaw corr / p/b/m hits | 0.72–0.81 / 47–75% | |
| Upper-face error with the right `--mood` (vs none) | 0.045 (0.147) | |
| p/b/m closure width (game 133 ms) | 133 ms | |

**A face simulator, not one character's.** Tested against six characters' own game lipsync, the jaw, closures, blink timing and the game's mood presets all carry over. Choosing the mood automatically from the voice doesn't; set it by hand. Details are in [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

The tongue and the brows are the weakest parts so far:
- **Tongue:** timed caption words are meant to improve it.
- **Brows:** whether a line gets a raise or a frown is often an actor's choice that the audio doesn't reveal.

The game's face clips contain no head turns, so the model's head motion has no game reference. Measure it from real video instead. Details are in [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

## Status

| Part | State |
|---|---|
| Model, profiles, exporters | Working. 12 checks in `test/test_model.py`. |
| Whole-face capture, clean-up, retarget, voice-driven upper face | Working. 56 checks in `test/test_performance.py`. Head angles and left/right checked on renders of a game head. |
| Capture server and add-on login | Working. 28 checks in `test/selftest.mjs` against a fake add-on. |
| Live capture on YouTube | Built, first live run pending |
| Analysis | Runs end to end; scoring on real faces pending the first live capture |
| Getting curves back into Cyberpunk 2077 | Not tested yet (see the WolvenKit guide) |
| Local video files (no browser) | Planned |

## Tests

```
cd test
npm install
node selftest.mjs
cd ..
python test\test_model.py
python test\test_performance.py
```

## Responsible use

LipScan tracks motion only; it doesn't identify people. Respect the terms of the sites and media you record, and use it on content you're allowed to analyze. Recordings stay on your PC.

No game files, extracted game data, game audio or recordings are included in this repository. Profiles hold measured numbers only.

Not affiliated with or endorsed by CD PROJEKT RED, Google, YouTube, Mozilla or Anthropic. Cyberpunk 2077 is a trademark of CD PROJEKT S.A.

## License

MIT. See [LICENSE](LICENSE). The software is provided "as is", without warranty of any kind. `model/cmudict.dict` is the CMU Pronouncing Dictionary, under its own BSD license (`model/cmudict.LICENSE`).

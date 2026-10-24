# LipScan

LipScan measures how real mouths move in video and audio. It then uses those measurements to turn speech or singing into lipsync animation curves.

- **Tracking, not recognition.** It measures what a face is doing (jaw opening, lip shapes, blinks). It never identifies who someone is, and it stores no face prints.
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
 capture/        analyze/                    model/                     export/
 YouTube  --->   face tracking (MediaPipe)   voice (+ words)  --->      arkit52 (Unreal, Unity,
 frames,         + measurements    ---->     mouth curves               Blender, VRChat...)
 sound,          (jaw lead, loudness curve,  shaped by a                cyberpunk (REDengine
 captions        speeds, blinks, symmetry)   profile/                   face rig, via WolvenKit)
```

1. **Capture:** a Firefox add-on plus an MCP server record a YouTube video's frames, sound and captions. Sound and picture are both stamped with the video's own clock, so they stay in sync through seeks, pauses and ads.
2. **Analyze:** tracks the face in every frame (52 ARKit-style blendshapes and the lip gap), then measures:
   - how far the jaw runs ahead of the sound
   - how loudness maps to jaw opening
   - opening and closing speeds
   - syllables per second
   - blinks
   - left/right symmetry

   It scores the model against the real face, and can save the measurements as a new **profile**.
3. **Model:** turns a voice recording, optionally with its words and their times, into per-frame curves for the jaw, lips and tongue.
4. **Export:** writes those curves for a target: the generic 52 ARKit blendshape names, or Cyberpunk 2077's face-rig names (see [docs/WOLVENKIT.md](docs/WOLVENKIT.md)).

## Layout

| Folder | What it is |
|---|---|
| `capture/extension/` | Firefox add-on. It can only touch `youtube.com` tabs and only talks to `127.0.0.1:8766`. It never writes files. Its badge shows ON, OFF or REC, and the popup has an off switch and a Stop button. |
| `capture/server/` | MCP server `lipscan` (Node 18+, no dependencies). Tools: `lipscan_status`, `lipscan_start`, `lipscan_stop`, `lipscan_list`. |
| `analyze/` | Face tracking and measurements (Python, MediaPipe). |
| `model/` | Voice and words to mouth curves (plain Python, no dependencies). Includes the CMU Pronouncing Dictionary. |
| `profiles/` | Measured settings: `speech-cyberpunk`, `singing-cyberpunk`, and any you make. |
| `export/` | Track naming for each target. |
| `test/` | Self-tests and a terminal driver. |
| `docs/` | History, WolvenKit guide, measurements, profiles, security. |

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
   .venv\Scripts\python analyze\get_model.py      # downloads MediaPipe's face model into models\
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

## How well it works

These numbers compare the model with Cyberpunk 2077's own lipsync, for the character it was measured on. Correlation is shape match (1.0 = identical); "hits" means the closure lands within about one frame of the game's.

| | Speech (26 lines) | Singing (2.5 min) |
|---|---|---|
| Jaw correlation | 0.79 | 0.76 |
| Lips shut on p/b/m | 75% hits | |
| Lower lip tucked on f/v | 77% hits | |
| Lips pursed on oo/w | 61% hits | |

The tongue is the weakest part so far. Timed caption words are meant to improve it. Details are in [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

## Status

| Part | State |
|---|---|
| Model, profiles, exporters | Working. 12 checks in `test/test_model.py`. |
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
```

## Responsible use

LipScan tracks motion only; it doesn't identify people. Respect the terms of the sites and media you record, and use it on content you're allowed to analyze. Recordings stay on your PC.

No game files, extracted game data, game audio or recordings are included in this repository. Profiles hold measured numbers only.

Not affiliated with or endorsed by CD PROJEKT RED, Google, YouTube, Mozilla or Anthropic. Cyberpunk 2077 is a trademark of CD PROJEKT S.A.

## License

MIT. See [LICENSE](LICENSE). The software is provided "as is", without warranty of any kind. `model/cmudict.dict` is the CMU Pronouncing Dictionary, under its own BSD license (`model/cmudict.LICENSE`).

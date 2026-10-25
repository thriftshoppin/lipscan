# LipScan Viewer (Cyberpunk 2077 face)

A small offline viewer that plays facial animation on a character's real Cyberpunk 2077 head. It uses a rebuilt copy of the game's face solver. It plays:

- the game's own lipsync clips (WolvenKit `.anims` glTF exports)
- LipScan curve files: the voice model's output, or a performance retargeted from video

You can play one animation, or two side by side (A/B).

**No game data is included.** You build a character pack from **your own** game install with `build_character.py`. Packs, exported animations, game audio and screenshots of game meshes are kept out of git by `.gitignore`. Please don't share them.

## Build

Needs Node.js 18+ and Python 3.8+.

```
cd viewer
npm install
node build.mjs            # -> dist/lipscan-viewer.html (one file, opens offline; double-click it)
```

On Windows, for an app-like window:

```
msedge.exe --app="file:///C:/path/to/viewer/dist/lipscan-viewer.html"
```

## Make a character pack from your game

You need the [WolvenKit CLI](https://github.com/WolvenKit/WolvenKit/releases) (8.x) and the depot path of a head mesh (`...\h0_*.mesh`). To find head meshes:

```
WolvenKit.CLI archive <archive> -l -r "<name>.*h0_.*\.mesh$"
```

Then:

```
python build_character.py --wolvenkit "<path>\WolvenKit.CLI.exe" --game "<Cyberpunk 2077 folder>" ^
    --head "<depot path of the h0_ .mesh>" --out "<somewhere outside this repo>\<name>"
```

The pack is a folder with `character.json` plus the head, eyebrows, eyes and teeth `.glb` files. It only reads the game archives; it never changes the game.

## V and the character creator

Point `--head` at a player base head, and the pack gets the character creator's face options:

- male V: `base\characters\head\player_base_heads\player_man_average\h0_000_pma_c__basehead\h0_000_pma_c__basehead.mesh`
- female V: the same under `player_female_average` with `pwa`

The viewer then shows a **Character creator** panel: Eyes, Nose, Mouth, Jaw and Ears, each "base" or one of the game's presets (20 for male V, 21 for female), with **Base face** and **Random** buttons. Address parameters work too: `&eyes=3&nose=12&mouth=7&jaw=7&ear=1`. Lipsync, moods and the pose tester all work on the chosen face.

How it works (`creator.py`):

- **Skin:** the game keeps each option as a morph target, `h<preset><region>` (for example `h074` = jaw 7), in `h0_/he_/heb_/ht_000_<pma|pwa>__morphs.morphtarget` for the head, eyes, eyebrows and teeth. The converter exports those files, with all their targets, as the pack's meshes.
- **Joints:** each target also stores where the face joints sit for that preset. The converter records how far each joint moves from the base head, and the viewer rebuilds the rig's rest pose from that, so expressions bend around the new jaw, nose and so on.
- **One approximation:** a preset's joint positions are shared by all five regions, so when regions are mixed (eyes 3, jaw 7) something has to decide which preset each joint follows. The game's rule isn't in the files. Here each joint follows the region whose morphs move the skin it drives most.

Not included yet: skin tones, textures, makeup, scars, tattoos, hair, beards (they have morphs of their own), and body types.

## Use

- **Load files:** with **Character…**, **Animation A…**, **Animation B…**, **Audio…** and **Video…** (a LipScan trace folder), or drag files and folders onto the window.
- **Play:** Play/Pause with Space, step one frame with the arrow keys. Click or drag the timeline to seek.
- **Compare:** A and B side by side.
- **Try a pose:** test any face track.
- **Head motion:** switch it on or off. It comes from LipScan curve files; the game's face clips have no head turns.
- **Mood:** a held expression (neutral, scowl, warm, sad, surprised, or a custom preset JSON) added to LipScan clips in A and/or B. The game's clips carry their own mood.
- **Video pane:** shows the source frames in sync when a trace folder is loaded.

**A test set to step through.** Serve a manifest and open `?demo=/pack/demo/manifest.json`. The viewer then shows a **Test set** panel:
- **Character** and **Line** menus, plus **Prev** and **Next** buttons
- each line plays the game's lipsync in A and LipScan's version from the voice alone in B, side by side with the voice, and the game's mood applied to B
- `&demoChar=2&demoLine=1` opens a specific line

The manifest lists your own files (keep them private, like packs):

```json
{"characters": [{"name": "Judy", "pack": "/pack/judy/", "creator": {"jaw": "07"},
  "lines": [{"text": "...", "game": "/pack/demo/judy/scene.glb", "clip": "f_1618640F842B6000",
             "lipscan": "/pack/demo/judy/line.json", "audio": "/pack/demo/judy/line.wav", "mood": "calm"}]}]}
```

`creator` (optional, player heads) sets character-creator presets.

**From a URL.** When served over http (`node serve.mjs`, with `LIPSCAN_PACKS` and `LIPSCAN_DATA` set; this computer only), files can be given in the address:

```
?pack=/pack/<name>/&a=/data/<anims.glb>&clip=<id>&b=/data/<lipscan.json>&audio=/data/<voice.wav>&video=/data/<trace>/&view=ab&cam=front
```

How it works (the solver, the file formats, head motion): see `../claude/skills/cyberpunk-face-viewer/SKILL.md` and `../docs/WOLVENKIT.md`.

## Files

| File | What it is |
|---|---|
| `build_character.py` | Converter: your game files → a private character pack. |
| `src/solver.js` | Track values → bone deformations, rebuilt from the facial setup, plus head motion. |
| `src/anims.js` | Loads WolvenKit `.anims` glTF exports and LipScan curve files. |
| `src/main.js`, `src/index.html` | The app: scene, A/B view, timeline, pose tester, video pane, address parameters. |
| `build.mjs` | Bundles everything with three.js (MIT) into one HTML file. |
| `serve.mjs` | Optional local dev server (127.0.0.1 only). |

MIT licensed, like the rest of LipScan. Not affiliated with CD PROJEKT RED. Cyberpunk 2077 is a trademark of CD PROJEKT S.A.

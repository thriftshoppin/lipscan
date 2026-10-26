# Using the viewer

The viewer plays LipScan's animation on a character's real Cyberpunk 2077 head, so you can see a performance next to the video it came from. It is one offline HTML page. **No game data is included**: you build a character pack from your own install ([viewer/README.md](../viewer/README.md) has the steps), and packs, game audio and built pages stay on your PC.

This page is about using it with your own videos. To get a video ready first, see [IMPORTING.md](IMPORTING.md).

## Start it

```
cd viewer
npm install
node build.mjs                      # makes dist\lipscan-viewer.html
```

For everything below that talks to the model (the dials, the head sources, the lyrics box) you also need the small dev server. It serves the page and your private files on 127.0.0.1 only (this computer):

```
set LIPSCAN_PY=C:\path\to\python.exe            (the Python with LipScan's packages)
set LIPSCAN_REPO=C:\path\to\lipscan
set LIPSCAN_PACKS=D:\lipscan\packs              (character packs, test sets, trace folders)
set LIPSCAN_DATA=D:\lipscan\packs
node serve.mjs                                  (then open http://127.0.0.1:8770/)
```

For the video drop zone below, also set the two optional tools (without them it still runs, but with no vocal separation or no words):

```
set LIPSCAN_SEP_PY=C:\path\to\separate-venv\Scripts\python.exe   (Python with demucs, see IMPORTING.md step 4)
set LIPSCAN_ASR=C:\path\to\asr                  (a folder with transcribe.mjs, Whisper through transformers.js, and its node_modules)
```

`LIPSCAN_PY` also needs `av` (`pip install av opencv-python numpy`) for the drop zone.

Opening `dist\lipscan-viewer.html` directly also works for playing files, without the model features.

## Drop a video, get a demo

With the dev server running (and the manifest at `LIPSCAN_PACKS\demo\manifest.json`, the one the viewer opened with `?demo=/pack/demo/manifest.json`), drop a video file anywhere on the stage. In the Test set panel say whether it is **singing** or **speech** first. A bar at the bottom shows the step (reading the video, tracking the face, pulling the voice out of the music, listening for words, timing the words, three retargets, adding it to the list). It takes several minutes for a song (about 8 for a 4.5 minute video on one CPU/GPU box). When it is done the list reloads and the new entry, "Dropped: <file name> on Kerry", is first. The files go to `LIPSCAN_PACKS\live\<file name>\`. Dropping the same name twice makes `name-2`. A video with no sound track fails at step 1.

The same steps run by hand: `python ingest.py video.mp4 "<packs>\live\clip" "title" --manifest "<packs>\demo\manifest.json" --profile singing-hard`.

## Put your video in a test set

A test set is a manifest of lines to step through. Put your trace folder under `LIPSCAN_PACKS` (for example `live\my-video\`), then add a character and a line:

```json
{
  "profile": "singing-hard",
  "characters": [{
    "name": "My video on Kerry",
    "pack": "/pack/kerry/",
    "lines": [{
      "text": "My video",
      "label": "A = hybrid (head, brows, blinks, smiles from the video; jaw, lips, tongue from the voice). B = the voice model alone.",
      "profile": "singing-hard",
      "game":    "/pack/live/my-video/retarget-hybrid.json",
      "lipscan": "/pack/live/my-video/lipscan-audio-only.json",
      "audio":   "/pack/live/my-video/audio.wav",
      "video":   "/pack/live/my-video/",
      "hybrid":  "/pack/live/my-video/",
      "words":   "/pack/live/my-video/words-timed.json",
      "sources": {"video":  "/pack/live/my-video/retarget-video-only.json",
                  "hybrid": "/pack/live/my-video/retarget-hybrid.json",
                  "audio":  "/pack/live/my-video/lipscan-audio-only.json"},
      "seconds": 190, "noText": true, "noMood": true
    }]
  }]
}
```

Then open `http://127.0.0.1:8770/?demo=/pack/demo/manifest.json`. What the fields do:

| Field | Meaning |
|---|---|
| `game` | what head **A** plays (here the hybrid) |
| `lipscan` | what head **B** plays (here the voice model alone) |
| `audio` | the sound to play. Use the **full mix** (`audio.wav`), not `vocals.wav`: the demo has the vocals and the band |
| `video` | the trace folder; its frames play in the corner pane, in sync |
| `hybrid`, `words`, `profile` | switch on the live features (head sources, dials, lyrics). `hybrid` is the trace folder, `words` the timed words, `profile` what the voice side is generated with |
| `sources` | the three files a head can switch between |
| `mood`, `noMood`, `moodA` | a held expression on B (`noMood` turns it off), and `moodA: true` holds it on A too |

`&t=80` starts at 80 seconds and `&play=1` starts playing (the browser may want a click first, for sound).

## Controls

- **Play / pause:** Space. **Step:** the arrow keys. **Seek:** click or drag the timeline.
- **View:** A/D turn around the heads, W/S tilt, Q/E zoom, 1 front, 2 three-quarter, 3 and 4 the profiles, 0 reset. Hold Shift for bigger steps. Dragging and scrolling work too. **A and B side by side**, or either alone, from the menu at the top.
- **Video pane:** the real footage in the corner, with a **Hide** button when it covers a head.
- **Mood:** a held expression (neutral, scowl, warm, sad, surprised, or your own preset JSON) added to A and/or B. It also tones down opposing shapes, so a held scowl softens raised brows and smiles.
- **Head motion:** turns the head's movement from the video on and off.
- **Pose tester:** drag any single face track to see what it does.

## Head sources

**Head A** and **Head B** each switch between:

- **Video only:** everything from the face in the video.
- **Video + audio (hybrid):** the video's head, brows, blinks, gaze and smiles, with the voice's consonants, tongue and neck **added to** the video's mouth. Where the video reads the lips well it keeps them.
- **Audio only:** the voice model alone, no video. With music in the sound it is a weak guide unless you made `vocals.wav`.

Playback keeps its place when you switch.

## Voice model dials

Three sliders re-run the model live: **Articulation** (how crisp b, p, d, t, k, g, f, v, oo, w are), **Expressiveness** (how much brows, squint and frown follow the voice's tone) and **Cheek / jaw follow**. 1.0 is as measured. **Reset to 1.0** puts them back. A video-only head doesn't depend on them.

## Lyrics

When the line has a trace folder and `words`, a **Lyrics** box appears under the dials.

1. Paste the lyrics: the **whole song, repeated choruses included**.
2. Press **Use these lyrics**.
3. Both voice-based heads are generated again with your words. The note under the box says how many of your words speech-to-text heard the same way; the rest are placed between the ones it did.

**Back to speech-to-text** restores the original words. Your text is kept as `lyrics.txt` in the folder and comes back the next time you open the line. Each word is moved to where the voice really starts it, so the consonants land on the right moment. See [IMPORTING.md](IMPORTING.md#5-your-own-lyrics-optional-recommended-for-singing).

For the best result, upload a take where **all of the vocals** are voiced and the lyrics match what is sung. Where words are skipped or the singing stops for a moment, the diction loses its place until the next words it recognises.

## If something looks off

| You see | Try |
|---|---|
| The bottom teeth show on small mouth openings | `retarget.py --lower-teeth` lower (default 0.3; 1 = off) |
| The jaw only drops straight down | `--jaw-forward` higher (default 0.25; 0 = off) |
| Lips press shut on w, sh or uh | make sure you are on the hybrid (it keeps a voice press only where the video's lips meet); on the voice-only head the press follows the words |
| Consonants early or late | paste the lyrics, so each word snaps to the voice; run `separate.py` so it listens to the vocals, not the band |
| Hard k, g, c, q do nothing on the lips | use `--profile singing-hard` |
| Dropping a video does nothing, or fails | open the viewer from `http://127.0.0.1:8770/` (not the .html file); the failure bar names the step; check `LIPSCAN_PY` has `av`, `LIPSCAN_SEP_PY` and `LIPSCAN_ASR` |
| The dials do nothing | the dev server isn't running, or the line has no `hybrid`/`audio` |

# Profiles

A profile is a JSON file in `profiles/` that tells the model how a mouth moves. Use one with `--profile <name>`. The aliases `speech` and `singing` mean `speech-cyberpunk` and `singing-cyberpunk`.

## What's in one

| Key | Meaning |
|---|---|
| `jaw_mean`, `jaw_peak` | Loudness (dB, after normalizing) → jaw opening (0 to 1): the average and the 90th percentile at that loudness. |
| `peakiness` | 0 follows the average curve, 1 follows the peaks. |
| `contrast` | Above 1, the mouth snaps shut between syllables and opens wider on them. |
| `normalize_to_db` | The recording's loud end is shifted to this level before the tables are used. |
| `open_lead_ms`, `close_lead_ms` | How far the jaw runs ahead of the sound when opening and when closing. |
| `attack_ms`, `release_ms` | Smoothing when opening and closing (larger is lazier). |
| `max_open_speed`, `max_close_speed` | Speed limits, in jaw units per second. |
| `rest_jaw` | Jaw opening in silence. |
| `follow_jaw` | Tracks that ride along with the jaw: value = gain × jaw. |
| `viseme_strength` | Scales all diction shapes (p/b/m, f/v, oo/w, ...). |
| `shape_lead_ms`, `shape_attack_ms`, `shape_release_ms` | Timing of the diction shapes. |
| `symmetric` | `true` keeps left and right identical; `false` adds a slight drift, like motion capture. |
| `blinks_per_minute` | 0 for none. |

`about`, `source` and `notes` are for people; the model ignores them. The diction shapes themselves are in `model/lipsync.py` (`VISEMES`), because they describe the face rig rather than a performer.

## Making one from a recording

1. Record a performer with LipScan. A close shot with the face filling a good part of the frame works best.
2. Fix the captions in `captions.txt` if needed.
3. Run:
   ```
   python analyze\analyze.py "<recording folder>" --profile singing --save-profile my-singer
   ```

This copies the base profile (`--profile`) and replaces what the recording measured:

- the loudness-to-jaw tables, rescaled to the base profile's range, because MediaPipe's jaw scale differs from a game rig's
- the jaw lead
- the blink rate
- whether the face is symmetric

The measured values are saved under `measured`. It refuses to write a profile if the face was found in less than half the frames.

Several recordings of the same performer give steadier numbers than one. For now, compare their `analysis.json` files and average by hand.

## Ideas

- One profile per style: conversation, rap, ballad, belting.
- One per character, so a quiet character and a loud one move differently with the same audio.

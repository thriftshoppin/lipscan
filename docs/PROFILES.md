# Profiles

A profile is a JSON file in `profiles/` that tells the model how a mouth moves. Use one with `--profile <name>`. The aliases `speech` and `singing` mean `speech-cyberpunk` and `singing-kerry`. `singing-cyberpunk`, the 0.2.1 name, still works.

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
| `lip_mode` | `learned` (default): the game's soft lip mixes per sound, blending from sound to sound; p/b/m and f/v stay crisp. `shapes`: one fixed shape per sound (0.2.2 and earlier). |
| `lip_contrast`, `tongue_contrast` | How much the learned lip and tongue shapes are pushed past the game's averages, which timing errors blur (2.5 and 1.5). |
| `face_smooth_ms`, `head_smooth_ms` | A final, slight zero-phase smoothing of the face (blinks and p/b/m presses stay crisp) and of head motion. 0 turns it off. |
| `soft_attack_ms`, `soft_release_ms` | How fast lip and tongue shapes other than p/b/m presses ease in and out (the game's never pop). |
| `closure_peak` | The strongest a p/b/m press gets (default 1.0). Other lip shapes give way under a press. |
| `neck_during_speech` | Neck and throat tracks, and the level each is held at while someone talks. |
| `mood_auto` | Settings for `--mood auto` (a guess): reference pitch, loudness and pitch range, the threshold, and which preset counts as `intense` and which as `calm`. |
| `upper_face` | The voice-driven upper face (below). Leave it out for mouth only. |

### Moods

`--mood <name>` holds an expression for the whole line, and the voice-driven accents ride on top. Presets are in `profiles/moods/`:

| Preset | Source |
|---|---|
| `neutral` | Nothing held. |
| `calm` | The game's relaxed default: soft squint only. Measured; identical in 3 characters' lines. |
| `warm` | Slight smile, brows a touch up. Measured; identical in 3 characters' lines. |
| `scowl` | Brows down and in, squint, one-sided nose sneer, mouth corners down. Measured; identical in 4 characters' lines. |
| `sad`, `surprised` | Hand-made, not measured. |

The measured presets are the game's own: every character's lines hold exactly the same levels, and they're lopsided the way the game's are.

While a mood holds a shape, voice accents that work against it are turned into a little emphasis on it instead (25%). For example, brow raises under a scowl, or smiling corners under down-turned ones. The game never combines them, and raised brows over lowered ones tear the brow mesh.

`--mood auto` is a guess, and it doesn't carry over well between voices (see docs/MEASUREMENTS.md). Pass `--voice-ref <another line of the same speaker>` so pitch is judged against that voice. Without it, only loudness and pitch range are used, and its default is `calm`. Setting the mood by hand works much better.

A custom preset is a JSON file, `{"name": "...", "tracks": {"eye_l_brows_lower": 0.2, ...}}`. Pass its path to `--mood`, or load it in the viewer's Mood menu.

`--mood auto` guesses from the voice: a higher, louder, flatter delivery reads as the profile's intense mood (scowl), anything else as its calm one (warm). It's a guess, and the result says so.

### `upper_face`

Since 0.2.0, the model also animates the upper face from the voice alone. These keys sit inside `"upper_face": {...}`:

| Key | Meaning |
|---|---|
| `blinks_per_minute` | The average rate. 0 for no blinks. |
| `blink_peak` | How far a blink closes the lids (0 to 1). |
| `blink_pause_min_s` | A pause between phrases at least this long gets a blink in its middle, as the game does. |
| `blink_max_gap_s` | During longer stretches without such a pause, extra blinks are added on weak syllables. |
| `brow_raises_per_minute`, `brow_raise_threshold` | Brow raises go on the most emphasised syllables: at most this many per minute, and only above this emphasis. Emphasis is loudness (0 to 1) plus `pitch_weight` × pitch above the voice's median. |
| `brow_raise_peak` | Brow raise strength. |
| `brow_lead_ms`, `brow_attack_ms`, `brow_hold_ms`, `brow_release_ms`, `brow_follow_s`, `brow_min_gap_s` | Raise timing, and the shortest time between raises. |
| `pitch_weight` | How much pitch counts towards emphasis. 0 skips pitch tracking. |
| `frown_level`, `frown_base`, `frown_drive` | Brows lower and eyes narrow by up to `frown_base + frown_level` on loud stretches. `frown_drive`: `"loud"` (speech: loud, low-pitched stretches) or `"effort"` (singing: the loudest passages). |
| `frown_lead_ms`, `frown_attack_ms`, `frown_release_ms` | Frown timing. The frown runs ahead of the voice. |
| `loud_squint`, `loud_cheek` | An extra squint and cheek raise on loud passages (effort). |
| `gaze_down` | The eyes rest this far down (`eye_*_dir_dn`, where 1.0 = 30°). |
| `head_nod_deg`, `head_nods_per_minute`, `head_sway_deg` | Head motion in degrees: a small chin dip on stressed syllables, and a slow sway. Written to the result's `head`. |

Profiles from 0.1.0 with only a top-level `blinks_per_minute` still work. They give the mouth plus blinks, as before.

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
- with `performance.json` in the folder (run `analyze\performance.py` first), the upper face:
  - brow raises per minute
  - how far the brows lead the voice
  - head nods (size and rate)
  - head sway
  - where the eyes rest

The measured values are saved under `measured`. It refuses to write a profile if the face was found in less than half the frames.

Several recordings of the same performer give steadier numbers than one. For now, compare their `analysis.json` files and average by hand.

## Ideas

- One profile per style: conversation, rap, ballad, belting.
- One per character, so a quiet character and a loud one move differently with the same audio.

# Measurements

These are the numbers behind the two Cyberpunk 2077 profiles, plus what each measurement means. All timings are at 30 fps (one frame = 33 ms).

## How they were taken

**Speech.** 26 spoken lines from one character in the side job "A Like Supreme". Each line's dialogue lipsync clip (the JALI layer, decoded from the game) was compared with its voice recording.

**Singing.** The same character's facial motion capture for the concert song (about 2.5 minutes), compared with the song's isolated vocal stem from the game's sound banks.

**The method for both:**

- **Loudness:** RMS loudness per frame, in dB.
- **Alignment:** the time shift that best lines up jaw opening with loudness, found by cross-correlation.
- **The curve:** loudness grouped in 6 dB steps, with the jaw's average and 90th percentile in each group.
- **The diction checks:** counted against the words of each line.

## Timing

| | Speech | Singing |
|---|---|---|
| Jaw starts opening before the sound | 33 ms | 67 ms (median; middle half: −100 to +167) |
| Jaw starts closing before the sound ends | 33 ms | 167 ms (median) |
| Closed to fully open | | 0.37 s median, 0.7 s at the 90th percentile |
| Jaw peaks per second | | 1.14 (median gap 0.5 s) |
| Diction shapes run ahead of the sound | about 3 frames (100 ms) | |

## Speed

In both speech and singing, closing is faster than opening. Singing, in jaw units per second:

| | Median | 90th percentile | Fastest |
|---|---|---|---|
| Opening | 0.49 | 4.07 | 10.65 |
| Closing | 0.98 | 4.58 | 14.73 |

## Loudness to jaw opening

Loudness is in dB after shifting each recording so its loud end (95th percentile of voiced frames) sits at −18 dB.

| dB | −60 | −54 | −48 | −42 | −36 | −30 | −24 | −18 | −12 |
|---|---|---|---|---|---|---|---|---|---|
| Speech, average | .03 | .07 | .10 | .13 | .17 | .22 | .27 | .30 | .35 |
| Speech, 90th pct | .10 | .20 | .23 | .24 | .30 | .35 | .44 | .46 | .47 |
| Singing, average | .03 | .08 | .12 | .15 | .17 | .24 | .31 | .60 | .49 |
| Singing, 90th pct | .06 | .18 | .36 | .39 | .42 | .52 | .61 | .98 | .86 |

It's the same shape for both, with singing about twice as wide. In silence the jaw rests barely parted (median 0.03) rather than clamped shut.

**Singing, overall:**
- jaw at the median: 0.15
- jaw at the 90th percentile: 0.84
- held notes (78 of them, median length 0.9 s): average jaw 0.47, with a wobble of 0.26

## Diction (speech)

How strongly each mouth shape's count follows the number of matching sounds in the line's words (correlation across lines):

| Shape | Sounds | Correlation |
|---|---|---|
| Lower lip tucked | f, v | 0.92 |
| Lips pressed shut | p, b, m | 0.82 |
| Lips pursed | oo, w | 0.65 |
| Tongue | t, d, n, l, th | 0.64 |

Other findings:
- The lips press shut over an **open** jaw. Letting consonants close the jaw made the match worse.
- The tongue stays raised (about 0.4) through all speech.

## Other

| | Speech | Singing |
|---|---|---|
| Left/right symmetry | perfect (JALI) | slightly lopsided (motion capture) |
| Blinks per minute | 18.3 (in the lipsync layer of 22 of 27 clips) | 18.7 |

## Upper face (0.2.0)

Measured with `analyze/game_upper_face.py` on 27 speech clips (102 s), and on the concert motion capture against its vocal stem.

**Speech: the game's dialogue layer**
- **Blinks:** 18.3 a minute. Each lasts about 0.1 s above half-closed, reaching 0.85 to 0.95.
  - **Where blinks fall:** 65% fall in pauses. Almost every pause between phrases longer than about 0.3 s has a blink **in its middle**: of a pause from frame 38 to 72, the blink is at 55. Lines with no pause mostly have no blink.
- **Brow raises:** 13 a minute, in 17 of 27 clips.
  - **Shape:** peak strength median 0.47, lasting about 0.4 s. The inner and outer raise always move together.
  - **What drives them:** their timing follows loudness (correlation 0.46 at zero lag) more than pitch (0.29).
- **Frown:** in 15 of 27 clips, at a low level (median peak 0.12).
  - **Shape:** brows lower, brows lateral and all three squints move together, as one gesture. A line usually has either a raise or a frown, rarely both.
  - **What drives it:** it leads loudness by about 200 to 300 ms and goes against pitch (−0.19): lower voice, more frown.
- **Gaze:** the eyes rest slightly down (`eye_*_dir_dn` about 0.1) in most clips.
- **Head:** the face clips have no head turns; the game turns the head with the body skeleton. The face rig's `neck_*` and `head_neck_*` poses only move neck skin (measured: they don't rotate the head bone).

**Singing: motion capture**
- **Blinks:** 18.7 a minute.
- **A strong, sustained frown:**
  - brows lower: mean 0.65
  - inner squint: mean 0.83
  - lower squint: mean 0.36
- **What drives it:** vocal **effort** (loudness above 60% of the range, squared), smoothed over a couple of seconds. That curve follows the frown at 0.43. Plain loudness only reaches 0.10.
- **Brow raises:** rare and small (mean 0.08).
- **Gaze:** the eyes rest further down (mean 0.27).

## Closures, moods and the neck (0.2.1)

**p/b/m closures, speech, 41 game closures in 26 lines.**

| | Game | 0.2.0 | 0.2.1 |
|---|---|---|---|
| Width at half height | 133 ms | 167 ms | 133 ms |
| Peak | 1.05 | 1.0 | 0.95 (capped) |
| Hit within ±3 frames | | 49% | 51% |
| Hit within ±8 frames | | 76% | 78% |
| False closures (none in the game nearby) | | 22% | 19% |
| Median timing (model − game) | | +1 frame | +1 frame |
| Pressed during pauses (share of quiet frames) | | 7.3% | 1.4% |

The other shapes held up or improved:
- **Lower lip tucked (f/v):** 67% / 81% hits within ±3 / ±8 frames
- **Purse:** 45% / 61%
- **Jaw correlation:** 0.79
- **Tongue during pauses:** down from 16% to 3.5%

The chin bunching seen during a press with the jaw open is how the rig looks; the game's own presses do the same.

**Moods.** The game holds a line's mood in constant track values. This character's lines fall into two groups:

| Mood | Lines | What's held |
|---|---|---|
| Scowl | 7 | brows lower and lateral 0.32; squints 0.30 / 0.30 / 0.22; nose sneer 0.28 left / 0.11 right; mouth corners down 0.20 |
| Default | 20 | the same squints; brows raised 0.10; mouth corners up 0.10 |

Scowling lines were about 3.8 semitones higher, 2 dB louder and a little flatter in pitch.

| Upper-face error (mean absolute, 9 tracks, vs the game) | |
|---|---|
| No mood | 0.147 |
| Mood set by hand to the game's | **0.045** |
| `--mood auto` (right for 89% of lines; tuned on these lines) | 0.059 |
| Always `warm` | 0.077 |

Correlations don't change with a mood: a held level doesn't change a curve's shape. The mood fixes how the face sits, and the accents still carry the timing.

**Neck.** The game moves throat and neck tracks during speech, but they don't follow the jaw (r ≈ 0), loudness or pitch. They sit at steady levels:
- throat open: 0.14
- Adam's apple down: 0.14
- neck tighten: 0.09
- platysma: 0.04

The model holds them there while someone talks.

## Across characters (0.2.2): a face simulator, or a Kerry simulator?

Everything above was first measured on one character. To test whether it carries over, LipScan was scored against the game's own dialogue lipsync of six characters. The test used their own voice lines and subtitle words, and each character's own head and rig.

| | Rig | Lines |
|---|---|---|
| Kerry | male, average build | 26 |
| Judy | female | 55 |
| Panam | female | 35 |
| Jackie | male, big build | 10 |
| Johnny | male, average build | 5 |
| Takemura | male, older | 11 |

Jackie, Johnny and Takemura have few lines in the lipsync system, so their numbers are rough.

**The rigs:** all six face rigs have the same 414 tracks in the same order, and the same 121 face poses, 255 correctives, 18 tongue poses and 12 eye poses. Female and big-male rigs don't differ in structure.

**Trained on Kerry, tested on everyone** (`speech-kerry`):

| | Jaw corr | p/b/m hits ±3 fr | False closures | Blink hits (chance) | Upper-face error, no mood | Upper-face error, right mood |
|---|---|---|---|---|---|---|
| Kerry (trained on) | 0.80 | 51% | 19% | 67% (15%) | 0.144 | 0.042 |
| Judy | 0.78 | 58% | 19% | 39% (10%) | 0.095 | 0.049 |
| Panam | 0.72 | 51% | 22% | 68% (19%) | 0.047 | 0.047 |
| Jackie | 0.80 | 58% | 17% | 40% (13%) | 0.129 | 0.055 |
| Johnny | 0.81 | 47% | 41% | 33% (10%) | 0.125 | 0.047 |
| Takemura | 0.79 | 75% | 33% | 33% (8%) | 0.131 | 0.050 |

**Leave one character out** (each character scored with a profile averaged over the other five): the mouth and blink scores don't change; jaw correlation is unaffected by jaw size. The upper-face error with the right mood is 0.049–0.062. So nothing in the mouth was Kerry-specific to begin with.

**The moods are the game's, not Kerry's.** The levels a line holds are identical across characters, to the third decimal. Every scowling line of Kerry, Judy, Jackie and Takemura holds the same brows-down 0.324/0.30 with the same squints and nose sneer, and Kerry's, Johnny's and Takemura's "warm" lines are identical too. There's also a game-wide `calm` (soft squint only), and lines that hold nothing (all of Panam's).

**Auto mood does NOT carry over.** It was right for 0–77% of a character's lines, and it often made the upper face worse than no mood. Pitch is the main reason: voices differ by up to 11 semitones between these characters (Johnny 0.9, Panam 11.9). Since 0.2.2, auto only uses pitch relative to the same speaker (`--voice-ref`), but even so, mood is better set by hand.

**Profiles.** `speech-cyberpunk` is now the cross-character average:
- blinks: 19.9 a minute
- brow raises: about 13 a minute
- frown: 40% stronger
- jaw: curve scaled to 0.91 to remove an overshoot on most characters

Kerry's own fit is kept as `speech-kerry`, and the singing profile is now `singing-kerry` (only one singer measured).

**A face the game never shipped:** V's base head with character-creator presets (eyes 3, nose 12, mouth 7, jaw 14, ears 5). It builds, solves and plays both a game clip and LipScan output cleanly.

**Verdict: a face simulator, with caveats.**
- Jaw, closures, blink timing and the game's moods carry over to every character tested: both sexes, three body types, young and old, and a creator-built face.
- Choosing the mood from the voice doesn't carry over; set it by hand.
- Brow timing within a line is still weak for everyone (an actor's choice the audio doesn't show).
- Singing is measured on one character only.

## The tongue and the soft lips (0.2.3)

**The tongue.** Averaged over 140 lines of six characters' game lipsync, by the sound being spoken:
- **The body** (`tongue_mid_base_up`) rests at about 0.45 through all speech and 0.1 in silence, rising to about 0.6 on t, d, n, l, th, r and y. It does NOT follow the jaw.
- **The back** rises on k, g and h (about 0.45, also f/v and ch).
- **The front lift** is used mostly on "o" (0.3).
- **The tip** goes up almost never (mean 0.01), and dips slightly on "ee" and "eh".

These averages are now the model's tongue (`TONGUE_BY_VISEME`, contrast 1.5).

**The lips.** The game's lip shapes per sound are soft mixes. Its "s", for example, has corners up 0.16, pull 0.10 and stretch 0.07, where the old model used one stretch at 0.31. These mixes are now the model's lips (`LIPS_BY_VISEME`, contrast 2.5), blending from sound to sound. p/b/m presses and the f/v tuck stay crisp shapes.

Correlation with the game, each character scored with tables learned from the other five:

| Track | 0.2.2 | 0.2.3 |
|---|---|---|
| tongue body | 0.38 | 0.57 |
| tongue back | 0.31 | 0.35 |
| tongue lift | 0.09 | 0.37 |
| tongue tip down | 0.14 | 0.57 |
| lips funnel | 0.19 | 0.47 |
| lips corners up | 0.44 | 0.58 |
| lips pull | 0.38 | 0.57 |
| lips stretch | 0.25 | 0.50 |
| lower lip raise | 0.24 | 0.46 |
| purse | 0.37 | 0.40 |
| f/v tuck | 0.39 | 0.39 |
| frame-to-frame jump (99th pct) | 0.10 | 0.03 |

The final 50 ms smoothing is included in the 0.2.3 column. Without it, the lips score about 0.02 lower.

## Lips from the sound alone (0.2.5)

Without words, LipScan now predicts lip and tongue shapes straight from the voice's spectrum (a ridge regression over the log-mel energies, ±167 ms, line average removed), learned from the game's lipsync. Scored on characters it never saw (leave-one-character-out):

| Track | From sound alone | From words (0.2.3) |
|---|---|---|
| jaw | 0.80 | 0.75 |
| lip pull | 0.62 | 0.57 |
| corners up | 0.64 | 0.58 |
| corner stretch | 0.53 | 0.50 |
| stretch | 0.51 | 0.50 |
| corners down | 0.51 | |
| lower lip raise | 0.46 | 0.46 |
| purse | 0.42 | 0.40 |
| tongue body | 0.56 | 0.57 |
| tongue tip down | 0.54 | 0.57 |
| tongue forward | 0.56 | 0.35 |
| tongue back | 0.38 | 0.35 |
| funnel | 0.23 | 0.47 |
| lower lip tuck (f/v) | 0.22 | 0.39 |
| **p/b/m closure** | **0.27** | **0.38** |

Where the words win (closures, funnel, f/v), the sound can't tell the shapes apart. A closure peak-picked from sound alone hits 56% of the game's but invents 64% false ones, so crisp presses stay words-only.

The regression shrinks peaks to about half the game's, so lips are scaled up ×1.7 and the tongue ×1.4 (mean absolute error 0.027 → 0.032; correlation is unchanged).

**Mouth size from video.** A hybrid retarget scales the voice's jaw and lip movement by how far the video shows the mouth opening, over a 0.6 s window and relative to that clip's own 95th percentile. On a mumbling talking-head clip this raised the jaw's match with his real mouth from 0.46 to 0.79, and the mumbled moments now keep the lips nearly shut while his wide-open moments open.

## Articulation, tone, coupling and the mouth reading (0.3.0)

All scored the way the rest of this file is: six game characters (140-142 lines), each held out of its own fit, against the game's JALI lipsync layer. Reference numbers from before (jaw 0.79 speech / 0.76 singing, p/b/m 75%, f/v 77%, oo/w 61%) are unchanged at the defaults: `test/golden.py` pins the default output of seven cases byte for byte.

**Articulation.** Speech, 246 game p/b/m presses. "Width" is how long the press stays above half its peak; "hit" is the share of the game's events the model has within a frame.

| Articulation | p/b/m press width | peak | hit / false | f/v hit | oo/w purse | jaw match |
|---|---|---|---|---|---|---|
| 0.5 | 300 ms | 0.47 | 0.42 / 0.25 | 0.01 | none | 0.789 |
| **1.0 (default)** | **133 ms** | 0.95 | 0.55 / 0.20 | 0.47 | none | 0.789 |
| 1.5 | 100 ms | 1.00 | 0.56 / 0.21 | 0.53 | rare | 0.789 |
| 2.0 | 67 ms | 1.00 | 0.53 / 0.21 | 0.53 | 0.38 / 0.78 | 0.789 |

The game's press is about 133 ms wide, which is what the default gives, so for game voices the default is the best-measured value. Up to 1.5 the hits rise slightly (p/b/m 0.55 to 0.56, f/v 0.47 to 0.53); at 2.0 the purse starts to fire often and falsely. Higher values are a style choice (a clipped or deliberate voice), not a better match, which is why `speech-crisp` says so. The jaw is untouched at every value. Singing has no game reference for these shapes, so no value is recommended for it.

**Tone (prosody).** Frown / squint / raise correlation against the game, speech: off 0.230 / 0.234 / 0.232; pitch rise .3 0.185 / 0.188 / 0.189 (worse); tense .3 0.233 / 0.237 / 0.232 and calm .6 0.230 / 0.234 / 0.232 (no change). Singing (concert capture): rise .3 frown 0.32 to 0.35, squint 0.30 to 0.31, raise 0.06 to 0.03. So in the game's data tone does not predict the face in speech, and in singing it helps a little. The prosody terms ship off; the `-expressive` profiles turn them on. Above expressiveness 1.0 the frown now holds its shape (singing: correlation 0.26 at 1.5 and 0.25 at 2.0; at 1.5 it had fallen to 0.15 before the base was held down and the top bent).

**Coupling.** The game's cheek, lip puff, nose, chin and lip-suck tracks follow the lips and jaw. Predicted from the mouth and jaw tracks alone, on characters held out of the fit:

| Track | game 95th pct | correlation off -> on |
|---|---|---|
| cheek puff | 0.004 | 0.00 -> 0.32 |
| lip puff | 0.028 | 0.18 -> 0.37 |
| nose sneer | 0.033 | 0.00 -> 0.43 |
| chin raise | 0.072 | 0.28 -> 0.46 |
| lip suck | 0.060 | 0.24 -> 0.45 |

Given the game's own mouth the same tracks reach 0.70 to 0.96; from the model's mouth the match is lower, because the mouth itself is. The neck tracks and the upper lip did not predict (correlation -0.24 to 0.22) and were left out. **Not measured:** the nasolabial fold, the Duchenne squint and the cheek puff on a press are authored, because the game's dialogue layer never moves them (95th percentile under 0.01) and there is no reference. They are scaled by the same dial.

**Jaw size.** The game animates every character's jaw track by about the same amount (90th percentile 0.27-0.32 across the six), so a bigger jaw shows through the rig, not the animation. From the rig (width between the jaw-ear bones, drop from the upper eyelids to the chin) the six characters are Jackie 1.11, Takemura 1.02, Johnny 0.99, Kerry 0.97, Panam 0.97, Judy 0.95 (the player bodies 0.93-0.95). Jackie's jaw is 17% wider than Kerry's. `jaw_presence` multiplies the coupling by this, and its range is held to 0.7-1.3. Creator jaw presets are not yet counted: the value comes from the base head.

**Mouth reading from video** (`analyze/performance.py`), the 30 s test recording, before and after the lighter mouth smoothing. "Kept" is the 99th-percentile speed of the cleaned channel over the raw channel's.

| Channel | fast motion kept | match with his voice | 95th pct |
|---|---|---|---|
| jawOpen | 0.47 -> 0.70 | 0.42 -> 0.39 | 0.153 -> 0.162 |
| mouthClose | 0.34 -> 0.53 | 0.39 -> 0.37 | 0.008 -> 0.008 |
| mouthFunnel | 0.33 -> 0.51 | 0.38 -> 0.35 | 0.009 -> 0.010 |
| mouthPucker | 0.60 -> 0.83 | 0.34 -> 0.32 | 0.312 -> 0.337 |
| mouthSmileLeft | 0.68 -> 0.79 | 0.19 -> 0.17 | 0.077 -> 0.080 |
| mouthLowerDownLeft | 0.45 -> 0.66 | 0.27 -> 0.24 | 0.039 -> 0.035 |

On a rendered clip with known mouth values (so the truth is exact): jaw 0.69 -> 0.73, pucker 0.64 -> 0.68, close 0.11 -> 0.16, smile 0.53 -> 0.55. The sizes stay far below the truth (jaw 0.37, pucker 0.19 of the true 95th percentile): the face in a small video frame gives a weak reading, so the hybrid takes the mouth from the voice and uses the video for how much. Where fast closures were lost: the one-euro filter used for the head (1.5 Hz base) cut a 67 ms lip closure from a 0.9 peak to 0.65 (0.83 with the mouth's own 3 Hz); the detector itself still misses most lip presses (`mouthClose` found 0 of 5 on the rendered clip). A lip-gap press detector built from the landmarks was too noisy (0.18-0.36 correlation, 38 false against 4 found) and was dropped. An enlarged-crop second look lowered the match (jaw 0.69 to 0.60) and is off by default (`--refine`).

**Settings sweep on a real face** (`analyze.py --sweep`; the 30 s recording above, voice only, no captions). Mouth correlation with the real face by articulation 0 / 0.5 / 1 / 1.5 / 2: 0.249 / 0.252 / 0.254 / 0.256 / 0.257; purse 0.41 to 0.44. The jaw stays at 0.41 (the model's jaw is 2.6 times the video's, which reads small). Upper face, expressiveness 0 / 0.5 / 1 / 1.5 / 2: mean correlation 0.079 / -0.059 / -0.045 / -0.027 / -0.021 (the model's brows do not follow this actor's, and with expressiveness 0 there are none to compare, so that 0.079 is the cheek alone). Coupling changes nothing measurable (the real cheek reading is 0.08). **Reading:** this clip cannot choose a best value. It is an acted skit with no captions, and the upper face of a person performing a character is not set by the pitch of their voice. The recommended values stay at 1.0 for speech; for singing the only reference is the game's concert capture, whose best measured setting is `prosody_raise` 0.3 at expressiveness 1.0.

## How well the voice-driven upper face matches

Same clips; the model hears only the audio. "Hit" = a model blink starting within 0.3 s of the game's. "By chance" is what blinks at the same rate, placed at random, would score.

| | Speech (27 lines) | Singing (2.5 min) |
|---|---|---|
| Jaw correlation (for comparison) | 0.80 | 0.76 |
| Brow raise correlation | 0.32 (17 clips with raises) | 0.06 (raises are rare) |
| Frown correlation | 0.25 (15 clips with frowns) | 0.32 |
| Blink timing hits | **68%** (by chance: 15%) | 26% (by chance: 16%) |
| Blinks per minute, model vs game | 15.9 vs 18.3 | 18 vs 18.7 |
| Head motion | model 0.4° RMS; no game reference | model 0.75° RMS; no game reference |

Notes:

- **Blinks** come out best, because the game's rule (blink mid-pause) is learnable from audio alone. In singing, pauses are fewer and blinks freer, so hits are lower.
- **Brows** are harder. Whether a line gets a raise, a frown or neither is largely an animator's or actor's choice, not something in the audio. A plain loudness curve correlates higher (0.46), but it moves the brows constantly, which the game never does. The model makes discrete gestures instead.
- **Head motion** can't be scored against the game, which has none in its face data. Real head motion should be measured from video traces (`analyze.py` on a trace with `performance.json`), and `--save-profile` takes it over.

## How well the model matches

| | Speech | Singing |
|---|---|---|
| Jaw correlation with the game | 0.79 | 0.76 |
| Jaw, median / 90th pct (model vs game) | 0.12 / 0.33 vs 0.11 / 0.31 | 0.16 / 0.73 vs 0.15 / 0.84 |
| Lips shut on p/b/m (within ~1 frame) | 75% | |
| Lower lip on f/v | 77% | |
| Purse on oo/w | 61% | |
| Tongue | about 20% (the weakest part) | |

## Measurements from real faces

`analyze/analyze.py` takes the same measurements from a LipScan recording, using MediaPipe's `jawOpen` in place of the game's jaw track. MediaPipe's jaw scale isn't the same as a game rig's, so compare shapes and timings rather than raw jaw values. `--save-profile` rescales for you.

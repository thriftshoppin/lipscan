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
| Blinks per minute | none in the lipsync layer | 18.3 |

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

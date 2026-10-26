# Changelog

## 0.5.0 (2026-10-26)

**Best results: the video you give LipScan should voice all the vocals you pair with it.** The diction layer follows the words, so it only works as well as the words it can hear. Where the singer skips a line, mumbles or holds a note, there is nothing to follow and the consonants lose their place until the next words they recognise, then find themselves again (seen on a full song: one short stop was enough). Give it a take that says all of the words, and cut any words the singer didn't say from the lyrics too. See docs/IMPORTING.md.

New docs: [docs/IMPORTING.md](docs/IMPORTING.md) (a video file to a trace folder, step by step, with the isolated voice and your own lyrics) and [docs/USING_THE_VIEWER.md](docs/USING_THE_VIEWER.md) (test sets, head sources, dials, the Lyrics box, moods, troubleshooting). New `analyze/import_video.py` (the browserless way in; the README's "Local video files" is no longer planned).

The voice reinforces the video's mouth (an auto-tune for lip sync), and the jaw hinges the way a singer's does. Found on a close-up singing video.

- **Reinforce, don't replace:** in the hybrid the voice's lip shapes and closures are now added on top of the video's (the larger of the two), where before they replaced them. The video's mouth is never made smaller; the consonants the voice finds come in where the video misses them. Lip presses (p/b/m) on 4.0% of frames before, 11.1% now. `--no-reinforce` gives the old behavior.
- **Blocked is not muffled:** sung words are timed loosely, so the voice's p/b/m presses landed on w, sh and uh (rounded or open lips drawn as b and m). On this video 36% of its presses fell where his lips were over 0.10 apart, 9% where they were under 0.04, and 26 of 86 were near one of his 74 real closures (whose sound carries 5 times the usual low murmur of a b or m). A voice press now stays only where his lip gap gets under 0.035 within 3 frames; the rest are dropped and the sound keeps its rounded or open shape. 136 closures to 104 (his 74 plus 30 where his lips nearly touched); the share near one of his real closures 57% to 74%. His gap read shut at rest (median 0.004), so a beard did not stop it reading closed lips; whether it hides small gaps at the lip corners is untested. The audio-only head is not changed.
- **Hard k, g, c and q:** these have no lip shape in the game's data (`K` was empty; only the tongue moved). They are two parts: a quick stop, then the next sound's shape (kuh = k then uh; qwuh = k then a rounded wuh). A new profile `singing-hard` (singing-kerry plus `velar_lips`) gives the stop a short lip burst: the corners lift and the upper lip rises, over by the vowel, and before a rounded sound (qu, w, oo, o, r) only the upper lip so the lift does not fight the purse. Authored, not measured against the game: on one close-up video at 46 hard k/g word starts the corners rose +0.10 and the upper lip +0.08 against the song mean (+0.07 / +0.07 at vowel starts, -0.06 / -0.04 at t/d/n), averaged over a loose window, so the shape is scaled up. The burst peaks near 0.2. In the hybrid it is added to the video's corners and upper lip (the larger of the two); on that video it raised the corner-lift peak at k/g from 0.45 to 0.49, because his video already lifts there. The default profiles are unchanged.
- **Typed lyrics (viewer):** a "Lyrics" box in the Test set panel (when the dev server is running and the line has a trace folder). Paste the words and press "Use these lyrics": `analyze/lyrics.py` lines them up to the speech-to-text words (difflib, word by word), so each of your words gets a time: a word it heard right keeps that time, a stretch it heard wrongly takes your words along its times, a word it missed goes just after the one before. It rewrites the folder's `words-timed.json` (the voice head) and `captions.json` (the hybrid), keeping the speech-to-text versions as `*-whisper.json`, and both heads are generated again. "Back to speech-to-text" restores them. Paste the whole song, repeated choruses included.
- **Lyrics start (word times snapped to the voice):** sung words are timed from the middle of the syllable. The b/p/m words fell on average 0.17 s after his real lip closures (14% within 0.10 s). Each word now moves to the first rise in the isolated voice's loudness within 0.25 s of its speech-to-text time, in order. On that video: median 0.17 s to 0.03 s, spread 0.087 s to 0.043 s, within 0.10 s of the real closure 14% to 61%; the voice head's presses within 0.10 s of a real closure 19% to 33% of all; the hybrid's closures 70% to 71% (they follow the video's own). The vocal onsets agree with the old word times to 0.02 s, so it is the speech-to-text clock, not the audio, that was late. Applied by `analyze/lyrics.py` when the lyrics are used (needs numpy; without it the times stay as they were).
- **Viewer:** a demo line may hold its mood on head A too (`moodA`); demo 3 now holds `scowl` on both heads.
- **Fix (dev server):** the hybrid head, when a dial moved, was generated without the line's profile (so with `speech`, not `singing`); it now gets the same profile as the voice head.
- **Isolated vocals:** `analyze/separate.py` (needs demucs, which is not in the main environment) writes `vocals.wav` beside `audio.wav`. The voice model, the timed words and the checks read `vocals.wav` when it is there; playback keeps the full mix.
- **Lower teeth:** the video's lower-lip drop (mouthLowerDown) read twice the jaw (median 0.13 against 0.06), so the head opened by dropping its lower lip and bared the bottom teeth. The share of the drop the jaw has not earned (smoothstep of the jaw 0.30 to 0.60) moves onto the jaw, keeping the lip gap the same. Lower-lip drop median 0.13 to 0.04, jaw 0.06 to 0.20. `--lower-teeth` (default 0.3; 1 = off).
- **Jaw slides forward as it lowers:** `jaw_mid_shift_fwd` = 0.25 x jaw^1.3. AUTHORED, not measured: the video's jawForward reads about 0 and the game never uses the pose. `--jaw-forward` (0 = straight down).

## 0.4.2 (2026-10-25)

Johnny's hair now moves with his head.

- **Found:** with the video and hybrid heads, Johnny's hair stayed where it was while his head moved. 78% of its weight is on the game's own simulated hair bones (`dyng_hair_*`, 67 bones in all). The game drives those by physics, so the exported file hangs their chains off the armature root, not the Head bone, and nothing in the viewer moved them (a chain's world position was identical at 10 s and at 90 s). Kerry's hair is skinned to head-skeleton bones only, which is why it was fine. Measured as the change in distance between 1,122 hair vertices at the scalp and their nearest skin vertex over seven moments of the clip, with the physics off: mean 3-18 mm, up to 62 mm.
- **Fix:** each such chain is parented to the hair mesh's own Head bone at load, keeping its rest position, so it rides with the head. Mean change 0.14-0.63 mm (Kerry unchanged, 0.01 mm); the median, 95th and 99th percentile are 0 mm; 31 of 1,063 sampled vertices (3%) still change by more than 5 mm, all about 28 cm below the top of the head, where long hair hangs past the neck and shoulders and the neck skin moves differently from the head. Checked at his largest turns (27 degrees of yaw, 31 of pitch, 27 of roll).
- **Viewer:** the demo list has a Johnny entry (the song, on Johnny's head); the P key and "Hair physics (P)" label turn the hair spring on and off.
- **Limits:** the hair rides rigidly with the head (plus the optional spring); the game's own simulation of those bones is not reproduced.

## 0.4.1 (2026-10-25)

Hair, and a basic hair physics.

- **`viewer/build_hair.py`** adds a character's hair to a pack you built with `build_character.py`, from your own install with the WolvenKit CLI. The game's hair is a set of textured cards skinned to the head skeleton (Kerry's: 17,140 vertices in two submeshes, no hair bones of its own), cut out by a strand alpha texture. The script finds the character's hair mesh from the head's name (the plain one, not the young, common or cutscene variants; `--hair` names one), exports it as `hair.glb`, uncooks the strand alpha, and reads an average colour from the game's hair profile: the root-to-tip gradient's mean times the per-strand (id) gradient's mean, from a profile named for the character if the game has one (Kerry's `..._brown_salt_n_pepper.hp`, giving #585553), else a natural dark colour (the hair mesh carries a material for every dye colour).
- **Viewer:** draws the hair cards with the strand alpha (double-sided; without the alpha texture they would be slabs, so they are hidden), with **Hair** and **Hair physics** checkboxes (the P key turns the physics on and off).
- **Hair physics:** one point trails the head on a spring (stiffness 110, damping ratio 0.4, in the head's own frame, anchored at the lowest part of the hair, so it lags turns and nods as well as moves). Its lag is the sway, added to each vertex in the shader by a weight: how far the vertex sits from the head's centre (roots near the skull barely move, the outer cards and tips most), scaled by how long the hair is, so a short cut sways little. Capped at 6 cm. On the 30 s test clip Kerry's hair drifts 3.3 mm on average and 11 mm at most, settles to 0.06 mm when the head is still, and is exactly 0 with the physics off.
- **Not done:** no collision with the head, shoulders or other hair; no gravity or wind; long hair (Judy, Panam) is moved as one lump, not strand by strand, because the game's own strand simulation is not in the mesh; beards are not added; the player's heads (V) have no named hair and get none.
- **Tests:** 4 new checks (102 in test_performance.py).

## 0.4.0 (2026-10-25)

The game's textures on the viewer's heads, and eyes that look like eyes.

- **`viewer/build_textures.py`** adds textures to a pack you built with `build_character.py`, from your own install with the WolvenKit CLI: the head's skin (albedo, normal, roughness), the eyebrows' strand texture, the teeth's albedo and the game's plain eye albedo, uncooked to PNG into `<pack>\textures\` and listed in `character.json`. Named characters have a plain skin material, so they work (all six of the test set); the player's layered heads keep their flat colour. The textures are game data, so they stay in the pack, outside the repo (`textures/` is in `.gitignore`).
- **Viewer:** uses them when the pack has them, with a **Textures** checkbox to compare with the flat colours. The skin and teeth take their albedo; the eyebrow's strand alpha is boosted so the strands read as brow hair; the eyeball is mapped to the eye picture from the front (the game's material rescales the mesh's UVs, which are not a plain map of the picture).
- **Eyes:** the eyes mesh has a small submesh that is the game's eye-wetness shadow layer (a mask with a red-brown shadow colour), not a surface. Drawn opaque it was a white disc over the pupil, and with the texture an orange one. It is hidden when the eyes are textured. The result is a brown iris, a dark pupil and veined whites.
- **Not done:** the normal and roughness maps are loaded but not shown (their channel layout is unchecked: `NORMAL_MAPS` in `main.js`); hair and beards are not in a pack; the player's layered heads (multilayer masks) are not covered; a character's own eye colour is not read (the plain eyeball is used for everyone).
- **Tests:** 3 new checks (98 in test_performance.py).

## 0.3.6 (2026-10-25)

Diction from the singer's own lips.

- **Found:** a song with no captions had no consonants at all in the hybrid (0 closures: "jaw, tongue and neck only"). Words from a local speech-to-text pass (Whisper small, timed per word; the sung b/p/m placed 77 closures) fixed that, but sung words are timed too loosely: the real lip gap was under 0.03 near 5% of those closures, and within 6 frames of a real closure for only 19% of the sung b/p/m words (random times: 18%). The word times cannot place a 2-frame closure.
- **Fix:** when the video reads the mouth well (jaw 95th percentile of 0.3 or more), the closures come from the video's own lip gap: a dip under 0.025 for 1-9 frames, with the lips open either side, is a b/p/m-type press; widened to 3 frames (133 ms, the game's width). A mouth held shut longer than that is a posture and is left alone. In the hybrid they replace the word-placed closures wherever the face is seen (the voice's carry on where no face is seen); video-only gets them added. On the song: 81 closures (0.4 a second, median 3 frames) where the head had 0. `--no-video-diction` keeps the word-placed ones. A render at one closure shows the lips open, meet for two frames and open again, as the video's do.
- **Words:** the voice model takes timed words (`captions.json` in a trace folder, or `--words`). The viewer's audio-only head now gets them too (`words` in a Test-set line). The tongue and the rounded sounds (oo, w, sh/ch) still follow the words' times, so they carry the same timing error.
- **Tests:** 6 new checks (95 in test_performance.py).
- **Limits:** the closure test above is by construction (the closures are read from the same gap). The tongue (k, g, t, d) has no video reading and rides on rough word times. The speech-to-text was a one-off scratch tool and is not in the repo; it hallucinated a run of "oh" over a quiet intro, which was removed.

## 0.3.5 (2026-10-25)

The head's lips are parted wherever the video's are.

- **Found on a close-up singing video, by checking the sealed stretches while the audio was active:** the long stretches where the hybrid's lips stayed shut (5 of 0.4 s or more, 4 s in all) are stretches where the singer's own lips are shut (landmark gap 0.004), including a 2.1 s one at 19.6 s; the head follows the video there, and the voice-only head, which hears the music too, opens. The real error was the opposite one: the head's lips ran less parted than the video's, with a visible gap median of 0.05 against 0.086, and in 4.2% of frames (232) the lips were parted on the video and shut on the head. Cause: the blendshapes miss some separations (the upper lip lifts and the teeth show with `jawOpen` at 0), and nothing used the measured lip gap.
- **Fix:** where the gap the head's tracks show (the fit in docs/MEASUREMENTS.md) is less than the measured lip gap, the lower and upper lip open to make up the difference, half each. It only opens: p/b/m closures, frames with no face and lips that are shut on the video are left as they are. `--gap-fill 0` turns it off. Parted-on-video but shut-on-head: 232 frames to 0 (hybrid), 144 to 0 (video-only); gap median 0.051 to 0.080 against 0.086, 95th percentile 0.148 to 0.185 against 0.184, match 0.95 to 0.97. The 985 frames where the real lips are shut stay shut (the head's gap there is unchanged, 0.019 median).
- **Not done, on purpose:** forcing the lips open whenever the audio is loud. In this recording the audio is voice and music, so loud does not mean he is speaking, and in his own video his lips are shut for 3 s of voiced audio. Say if you want it as an option.
- **Tests:** 6 new checks (89 in test_performance.py).
- **Limits:** one face, one song. The split between the lips is the rig's guess (a render at the one frame that was wrong shows the teeth between the lips, as in the video), and the audio-only head is unchanged.

## 0.3.4 (2026-10-25)

A rounded mouth read from video is a purse only while the lips are shut.

- **Found on a close-up singing video:** MediaPipe has one score for a rounded mouth (`mouthPucker`) and almost none for the open "O" (`mouthFunnel`, 95th percentile 0.01), and the retarget sent the pucker to the rig's purse, the closed pout. Of the frames with pucker above 0.5 (28% of the song), 55% had the lips apart (lip gap above 0.06, jaw median 0.27) and 36% had them shut. The pucker has nothing to do with the voice (correlation with loudness -0.02) and tracks a narrowed mouth (correlation with mouth width -0.83), so it is a real lip reading, but the open "O" came out as a small pursed pout. At 146 s his sung "O" is open and round; the head made a pout.
- **Fix:** the pucker goes to the purse while the measured lip gap is under 0.04 and to the funnel as the gap opens to 0.10 (smoothstep); purse + funnel stay within the game's 0.6; a funnel MediaPipe did read is kept. Applies to the video-only and the hybrid heads. `--round-split 0` gives the old mapping. Purse above 0.3: 32% of frames to 17%; purse mean 0.28 to 0.11; funnel mean 0.07 to 0.12. Rendered clip with known purse values: correlation 0.69, unchanged (its lips barely part).
- **Tried and dropped:** scaling the pucker down and removing held pouts. It made the head read less than the face really did.
- **Tests:** 6 new checks (83 in test_performance.py).
- **Limits:** one face, one song; the 0.04 to 0.10 gap range comes from that clip. The rig's funnel is a coarse stand-in for an open round mouth.

## 0.3.3 (2026-10-25)

Each head can play any source.

- **Viewer:** a "Head sources" panel in the Test set. Head A and Head B each switch between **Video only** (everything from the face), **Video + audio** (the hybrid) and **Audio only** (the voice model alone), while playback keeps its place. The dials re-run the heads that use the voice and leave a video-only head alone. A line offers it when its manifest entry has `sources: {video, hybrid, audio}` (clip URLs) and the dev server is running (the hybrid and audio heads are generated there).
- **Music in the audio:** the voice model hears everything in the track, so with music behind the vocals the audio-only head follows the music as well; this is why video only is the guide for such a clip. Separating the vocals first is not done here.

## 0.3.2 (2026-10-25)

Lip separation, found on a close-up singing video, and a video hide button.

- **Lip separation from the video.** The hybrid took the jaw and every lip-opening track from the voice, and in the singing profile the upper lip opens 1.3 times the jaw. His lips parted differently: in a tenth of the frames (642 of 5,794) they were visibly apart with the jaw nearly shut (a grin with the teeth showing), which only the lower lip's drop shows, and the hybrid had discarded that. On the 193 s song, his measured lip gap is explained 0.96 by `0.18 jaw + 0.16 lower-lip drop - 0.18 lower-lip roll`. When the video reads the mouth at the rig's scale (jaw 95th percentile of at least 0.3; the song reads 0.64, the first test clip 0.16), the hybrid now takes the jaw, the lower lip's drop (`lips_apart_dn`), the upper lip and the chin from the video wherever the face is seen, and the tracks that ride on the jaw ride on the video's. The voice still places closures, the tongue and the neck. `--mouth-from auto|video|voice`; auto is the default, so a weak reading stays voice-led as before. Gap match (the same proxy built from the hybrid's tracks, against the measured gap): 0.61 to 0.95; jaw median 0.27 to 0.15 (his: 0.16).
- **Authored couplings capped.** On a wide smile the authored smile fold reached 1.0, far beyond anything the game uses, and the mesh crumpled over the cheek. The smile fold now stops at 0.35, the smile squint at 0.3 (the game's held warm mood is 0.22-0.3) and the press puff at 0.1.
- **Viewer:** a Hide button on the video, the V key, `&hidevideo=1`; the choice is remembered in the browser. A Test-set line can set its own profile.
- **Tests:** 6 new checks (33 in test_model.py, 77 in test_performance.py).
- **Limits:** the 0.96 fit and the 0.3 trust level come from one clip (one face, one song); the gap proxy is a measure from the landmarks, not a render of the rig. Teeth and tongue visibility are not measured.

## 0.3.1 (2026-10-25)

Lips that push forward. The mouth had width and height but almost no depth: rounded sounds barely pursed and the hybrid threw away the video's pucker.

- **Where it was lost (measured):**
  - **Video reading:** fine. The recording's `mouthPucker` reaches 0.37 (95th percentile) and 0.94, and clean-up changes it by less than 0.01. `mouthFunnel` is the exception: MediaPipe itself gives about nothing (95th percentile 0.013). Head turns do not leak into it (correlation with head yaw, pitch, roll 0.06-0.13). Landmark depth is not used directly; MediaPipe's blendshapes already come from the 3D landmarks.
  - **Mapping:** fine. Pucker and funnel map to the rig's purse and funnel at gain 1.0, clamp 0-1. The rig's `jaw_mid_shift_fwd` is driven by nothing, and the game never uses it either (0 events in 140 lines).
  - **Hybrid (the main fault):** purse and funnel counted as speech tracks, so the hybrid took them from the voice and scaled them by the mouth size. The video's purse (95th percentile 0.34) came out at 0.07, a fifth, and correlation with the video's was 0.51.
  - **Voice model (second fault):** the learned lip table averages over each sound's window and the soft smoothing eats short ones, so purse peaked at 60% of the game's (99th percentile 0.18 vs 0.32) and funnel hardly appeared (0.04 vs 0.18; 4 events against the game's 39).
- **Hybrid:** where the video reads pucker, it sets the purse wherever the face is seen (the voice's carries on in gaps). A strong reading is kept as it is; a weak one (a small face) is lifted toward a 95th percentile of 0.15, at most 4 times, keeping its shape. Funnel keeps the larger of the two; purse + funnel stay within the game's 0.6. On the recording the hybrid's purse now matches the video's (95th percentile 0.07 to 0.34, correlation 0.51 to 0.99). On the rendered clip with known values, correlation with the true purse went from 0.40 to 0.69.
- **Voice model:** new profile key `lip_forward` (the peak of the push; 0 = off, the code default; 0.3 in the speech profiles). Rounded sounds get their own pulse: oo and w and o purse, sh/ch/j funnel, r a little, ahead of the sound like the other lip shapes. Articulation scales both size and speed. Against the game's lines purse 95th percentile 0.13 to 0.21 (game 0.20), funnel 99th 0.04 to 0.17 (game 0.18); purse hits within 8 frames 67% to 82%; funnel hits 5% to 72%. Jaw, p/b/m and f/v are identical to the byte. Singing and sound-only lips are unchanged.
- **Check:** `analyze.py "<folder>" --forward` scores the model's and the hybrid's purse and funnel against the video's, on the oo/w/o/sh/ch sounds of the caption words (hit rate and false rate) and over the whole clip (correlation and lag).
- **Tests:** 15 new checks (32 in test_model.py, 72 in test_performance.py). `test/golden.py` now pins the output with `lip_forward` off.

## 0.3.0 (2026-10-25)

Dials for how crisp the mouth is and how much the face follows the voice's tone, cheeks and chin that follow the lips and jaw, and a mouth reading that keeps fast closures.

- **Articulation** (`--articulation`, 0.0-2.0, default 1.0 = the 0.2.5 output exactly). Scales how high and how fast the sharp consonants go: p/b/m closures, t/d/k/g tongue, f/v tuck, oo/w purse. Against the game's lines the p/b/m press is 133 ms wide at 1.0 (the game's own width) and 100 ms at 1.5. A profile may set its own (`speech-crisp` = 1.5); the command line overrides it. The loudness-driven jaw is not touched.
- **Expressiveness** (`--expressiveness`, 0.0-2.0, default 1.0 = as before). Scales the voice-driven upper face (brow raises, frown, squint, head nods). Above 1.0 the strongest values bend toward 1.0 instead of flattening, so the shape holds.
- **Tone** (`upper_face.prosody_*` in a profile, off in every existing profile): a prosody track (pitch rise, tension, calm) from the voice. Rising pitch lifts the brows, loud tense stretches frown, squint and lift the cheeks, calm stretches relax. Against the game's faces it is neutral to slightly worse in speech and slightly better in singing, so it ships as the opt-in profiles `speech-expressive` and `singing-expressive`.
- **Coupling** (`--coupling`, `--jaw-presence`, `--rig character.json`; new `model/coupling.py`): cheek puff, lip puff, nose, chin and lip suck follow the mouth and jaw, learned from the game and tested on characters held out of the fit (correlation 0.32-0.46 where it was 0.00-0.28 without). The cheek's smile fold, the Duchenne squint and the press puff are authored, not measured, because the game never uses the cheek tracks. A face's jaw width and chin length (read from the rig) scale it: 0.93 to 1.11 across the game's characters, Jackie highest. The mouth and jaw tracks themselves are not changed by it.
- **Mouth reading from video** (`analyze/performance.py`): mouth shapes now get their own lighter smoothing (3 Hz base, beta 2) in place of the 1.5 Hz the head and brows use, which was flattening fast closures. Fast motion kept on the test recording: jaw 0.47 to 0.70, pucker 0.60 to 0.83, mouthClose 0.34 to 0.53. The match with the voice dropped a little (jaw 0.42 to 0.39), as expected from a signal that now follows faster mouth movement than the voice's smooth loudness does. Also records `lipGap` and `mouthWidth` from the landmarks. `--legacy-mouth` gives the old behaviour; `--refine` (an enlarged-crop second look) is available but off, because it lowered the match on the test clip.
- **Hybrid retarget:** takes `--articulation`, `--expressiveness`, `--coupling`, `--jaw-presence`, `--rig`, `--profile`, adds the coupling on the merged mouth, and prints to the terminal with `--out -`.
- **Settings sweep:** `analyze.py --sweep` scores each dial against a real face in a recording (shape, size, crispness) and writes `sweep.json`.
- **Viewer:** three sliders (articulation, expressiveness, cheek/jaw follow) re-run the model on the dev server (`/api/gen`) while a line keeps playing; jaw presence is read from the loaded character.
- **Tests:** 21 new checks (25 in test_model.py, 64 in test_performance.py) and `test/golden.py`, which pins the default output of seven cases so a change that alters it fails the build.
- **Limits:** the one real-face recording available is an acted skit with no captions, so the sweep cannot pick a best value (the jaw match stays 0.41, the dials move the mouth match by under 0.01) and the defaults stay at 1.0. Singing has no real-face reference at all. Cheeks cannot be checked against the game. Closures cannot be checked on the rendered test clip (its mouth barely closes).

## 0.2.5 (2026-10-25)

Better lips for the hybrid, found by watching it next to the real video.

- **Lips and tongue from the sound alone** (`model/audio_lips.py`, no words needed, numpy): learned from the game's lipsync, tested on characters it never saw. Jaw 0.80, pull 0.62, corners 0.64, stretch 0.51, tongue body 0.56, as good as the word-based ones. Closures, funnel and the f/v tuck still need words (docs/MEASUREMENTS.md). Profile settings `audio_lips`, `audio_lips_gain` (1.7), `audio_tongue_gain` (1.4).
- **Mouth size from the video:** a mumbled delivery barely opens the mouth, and the voice-driven jaw made it gape. The hybrid retarget now lets the voice set when the mouth moves and the video set how much, over a 0.6 s window, relative to the clip's own range. The jaw's match with the real mouth rose from 0.46 to 0.79; `--no-size` turns it off.
- **Viewer:** a live video test can sit in the Test set next to the game characters.
- **Tests:** 4 new checks, 56 in test_performance.py.

## 0.2.4 (2026-10-25)

First live test on a real video (a talking-head YouTube clip), and a hybrid retarget.

- **Finding:** a small face in a 640 px frame gives a weak mouth reading. The tracked jaw was about 2.3 times too small (90th percentile 0.13 against the game's 0.30), and matched the voice at only 0.31–0.42, against 0.95 for the voice model. A raw lip-distance measure was no better (0.31).
- **Hybrid retarget, now the default:** `retarget.py` takes the jaw, lip shapes, tongue and neck from the voice model, because the voice is what drives them, and everything else from the video. That covers head, brows, blinks, gaze, cheeks, nose, smiles and frowns, which the voice can't know.
  - **Wide-open mouths:** the jaw also takes the video wherever the video shows the mouth open further than the voice suggests (laughing, shouting).
  - **No face tracked:** the video tracks go empty there, and the voice tracks carry on.
  - **`--video-only`** reads the mouth from the video, as before.
  - **Words:** with caption words (YouTube's auto-captions), the voice side also places p/b/m closures and lip shapes. Without them it gives jaw, tongue and neck only.
- **Tests:** 4 new checks, 52 in test_performance.py.

## 0.2.3 (2026-10-25)

A tongue that moves like a tongue, and lips that aren't rigid.

- **Tongue, learned from the game:** from six characters' dialogue lipsync (140 lines).
  - **The game's tongue:** its body rests raised through speech (about 0.45) and rises further on t, d, n, l, th, r and y. Its back rises on k, g and h, its front lifts on "o", and the tip almost never goes up.
  - **The old tongue:** it rose with the jaw opening (×1.4), fired a full lift on l, and pointed the tip up on t, d and l.
  - **Correlation with the game,** each character scored with a table learned from the other five: body 0.38 → 0.57, lift 0.09 → 0.37, tip down 0.14 → 0.57, forward 0.03 → 0.35. Tip-up error 0.055 → 0.005.
- **Lips, learned and blended** (`lip_mode: learned`, the default): each sound's lip shapes are the game's own soft mixes, blending from sound to sound, instead of one fixed shape at full strength.
  - **The old "s":** stretched the lips at 0.31, about four times the game's level. The game's "s" is a soft pulled-back near-smile.
  - **p/b/m presses and the f/v tuck stay crisp.**
  - **Correlation,** leave-one-character-out: funnel 0.19 → 0.47, corners up 0.44 → 0.58, pull 0.38 → 0.57, stretch 0.25 → 0.50, lower lip 0.24 → 0.46. Purse and the f/v tuck are unchanged.
  - **Frame-to-frame jumps:** halved, then halved again by the smoothing.
- **Facial smoothing:** a slight, zero-phase (no lag) smoothing over the whole face, 50 ms (`face_smooth_ms`), and 120 ms on head motion (`head_smooth_ms`). Blinks and p/b/m presses stay crisp. It also raised every lip correlation a little.
- **Viewer:** camera keys. A/D turn around the heads, W/S tilt, Q/E zoom, 1 front, 2 three-quarter, 3/4 the two profiles, 0 reset (Shift = bigger steps).
- **Scores across six characters:** jaw corr 0.75–0.82, p/b/m hits 47–82%, blink hits 33–68%. No regressions.
- **Tests:** 48 checks in test_performance.py.

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

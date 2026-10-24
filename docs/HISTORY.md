# How LipScan started

## The idea

The goal was a Cyberpunk 2077 mod with in-game bands that perform songs from your own music library, where the singers' mouths actually match the words. Doing that needs lipsync for audio the game has never heard.

## The first wall

The first job was an inventory of the existing tools:

- **WolvenKit** has a lipsync tool, but it only copies the game's existing facial animations. It can't make new ones from new audio.
- **Audioware** plays custom audio in the game.
- **Convai** can produce mouth-shape timing (visemes), but it's a cloud service.

Nothing turned an audio file into game-ready face animation.

## Cracking the format

The game stores lipsync in `.anims` files, which convert to JSON in WolvenKit. At first the actual motion looked locked inside a compressed buffer that WolvenKit keeps as opaque bytes.

The breakthrough was WolvenKit's **glTF export**. It decodes that buffer, and every face track comes out as plain per-frame numbers. The mouth turned out not to be bone movement at all. It's a set of 414 named float tracks on the face rig (`jaw_mid_open`, `lips_together_up`, `tongue_mid_lift` and so on), and dialogue lipsync drives a separate layer of 141 of them. The details are in [WOLVENKIT.md](WOLVENKIT.md).

## A reference performance

We needed a performance where both speech and singing could be measured against clean audio. The concert in the side job **"A Like Supreme"** was ideal:

- one character's spoken lines before and after
- his live face capture during the song
- the song's isolated vocal stem inside the game's sound banks

Finding the stem meant following the Wwise sound-bank chain from the concert's start event down to the music tracks' source files.

## What the measurements showed

Comparing the face tracks with the loudness of the voice, frame by frame:

- **The mouth moves before the sound.** It leads by 33 ms in speech and 67 ms in singing.
- **It closes faster than it opens.**
- **Loudness maps to jaw opening on a steady curve.** Singing uses the same shape, about twice as wide.
- **Diction follows the words.** Every p, b and m presses the lips shut, and the game does that over an open jaw rather than by closing the jaw. f and v tuck the lower lip; oo and w purse the lips.
- **Dialogue lipsync is perfectly left/right symmetric.** Motion capture isn't.

The full numbers are in [MEASUREMENTS.md](MEASUREMENTS.md).

## From measurements to a model

Those rules became a small, dependency-free Python model. It takes a voice recording and, optionally, the words, and outputs per-frame face tracks.

Against the game's own lipsync, its jaw correlates 0.79 for speech and 0.76 for singing. It reproduces 75% of the game's lip closures on p/b/m, 77% of the f/v tucks and 61% of the oo/w purses, landing within about one frame.

## Real faces

One game character is a narrow base for a model of how mouths move. The next step was measuring real people. LipScan's capture tool records a YouTube video's frames, sound and captions on the video's own clock, so that a 33 ms lead isn't lost to timing jitter. Then Google's MediaPipe tracks the face in every frame.

YouTube's automatic captions carry a time for every word. Those timings let the model place each word's mouth shapes exactly, and you can correct the words while keeping YouTube's timings.

## Why it's its own project

The capture code first grew inside a browser-automation tool. Recording video belongs in its own narrowly scoped tool, so it was split out:

- the add-on can only touch YouTube
- it talks only to its own local server
- it has a visible recording indicator and an off switch

Because nothing in the method is specific to one game, the project became **LipScan**. Cyberpunk 2077 is one export target and the source of the first two profiles.

LipScan was built with Claude (Claude Code and Claude Cowork).

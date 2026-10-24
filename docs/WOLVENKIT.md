# LipScan and WolvenKit (Cyberpunk 2077)

This guide covers how Cyberpunk 2077 stores lipsync, how to read it with the WolvenKit command-line tool, and how LipScan's output maps back onto it. Everything here was worked out on game version 2.x with WolvenKit CLI 8.x. Paths below are inside the game's `.archive` files.

> LipScan contains no game files. To follow along you need your own copy of the game and WolvenKit.

## Where lipsync lives

| What | Where |
|---|---|
| Dialogue lipsync, one `.anims` per character | `base\localization\<lang>\lipsync\...\<character>.anims` |
| One clip per voice line | Clips are named `f_<id>` or `m_<id>` (female or male V version), where `<id>` is the line's ID in hex. |
| The voice line's audio | `base\localization\<lang>\vo\<character>_<quest>_f_<id>.wem`, in `lang_<lang>_voice.archive` |
| The line's text | `base\localization\<lang>\subtitles\quest\...\<scene>.json`. A subtitle's `stringId` written in hex is the clip's ID. |
| Scene motion capture (singing, performances) | `.scenerid` files: `actors[].facialAnimations`, stored in deferred buffers |
| The face rig and its track names | The character's head `.rig` file (`trackNames`) |
| Music and stems | Wwise sound banks (`.bnk`). Media files are `base\sound\soundbanks\media\<id>.wem`. |

Archive paths are hashed with FNV-1a 64 of the lowercased path. WolvenKit handles this for you.

## Reading an animation with WolvenKit

```
WolvenKit.CLI archive "<game>\archive\pc\content\lang_en_voice.archive" -l -r "lipsync"     # list
WolvenKit.CLI unbundle "<archive>" -o out -r "<regex for the file>"                         # extract
WolvenKit.CLI convert serialize out\<file>.anims -o json                                     # .anims -> JSON
WolvenKit.CLI export out\<file>.anims -o glb -gp "<game folder>"                             # .anims -> glTF
```

The JSON shows the wrapper:

- clip names and durations
- `animationType` (dialogue lipsync is additive)
- an `animAnimationBufferCompressed` whose motion is opaque bytes

**The glTF export is what decodes the motion.** In the `.glb`, each animation's `extras` holds:

- `trackKeys`: a list of `{trackIndex, time, value}`, one entry per animated track per frame (30 fps)
- `constTrackKeys`: tracks that hold one value for the whole clip

`trackIndex` points into the rig's `trackNames`, which you get from the rig with `convert serialize`.

### What the tracks mean

The face rig has **414 float tracks**. The mouth is driven by these tracks, not by bones; the bones barely move.

- **Base pose tracks**, such as `jaw_mid_open` (index 82 on the rigs examined), are what motion capture drives.
- **The dialogue lipsync layer** is the same pose names with `LipsyncPoseOutput` appended (141 tracks, indices 240 to 380; `jaw_mid_openLipsyncPoseOutput` is 309). JALI drives it through two master tracks, `jaliJaw` (7) and `jaliLips` (8).

LipScan's model uses the base pose names (`jaw_mid_open`, `lips_together_up`, `lips_l_purse`, `tongue_mid_lift`, ...). `--export cyberpunk` writes the dialogue-layer names.

### Scene motion capture

`.scenerid` facial animations aren't directly exportable. To read one:

1. Repack it into an `animAnimSet` JSON, with one clip per file and `BufferId` "0" (several clips per file exported as copies of the first).
2. Convert it back with `convert deserialize`.
3. Run `export` to get glTF.

### Audio

- Decode `.wem` voice and music files with [vgmstream](https://github.com/vgmstream/vgmstream) (`vgmstream-cli file.wem -o file.wav`).
- To find a song's isolated stems, follow the sound bank's HIRC chain: Event → Action → Music Switch → Random/Sequence → Segment → Music Track. The track's sources list the media IDs, which are files at `base\sound\soundbanks\media\<id>.wem`.

## Getting LipScan curves into the game (not yet tested)

The path should be the reverse of reading:

1. Run the model with `--export cyberpunk` to get per-frame values for the dialogue-layer tracks.
2. Take a vanilla glTF export of the same character as a template, and replace its `trackKeys` with LipScan's values (track name → `trackIndex` from the rig).
3. Import the glTF back to `.anims` with WolvenKit, and pack it into a mod archive under the line's clip name.

**This round trip hasn't been tested in-game yet.** The open questions:

- whether WolvenKit's glTF import rebuilds the compressed buffer from `extras`
- whether the game accepts a re-encoded lipsync clip

Reports and fixes are welcome.

## Notes

- WolvenKit's own lipsync tool remaps existing vanilla animations, which is useful for retiming but can't make new motion.
- `.lipmap` files map voice lines to lipsync clips per language.
- The game's dialogue lipsync is perfectly left/right symmetric. Motion capture isn't. The singing profile adds a slight drift to match.

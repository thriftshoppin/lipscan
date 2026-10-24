---
name: cyberpunk-face-viewer
description: Build, on the user's own PC and from their own Cyberpunk 2077 install, a lightweight viewer that plays game lipsync clips and LipScan curves on a character's real head, through a rebuilt copy of the game's face solver. Use when the user wants to preview, compare or debug Cyberpunk 2077 facial animation or LipScan output in 3D.
---

# Cyberpunk 2077 face viewer: build it locally from the user's game files

This skill tells Claude how to build two things on the user's machine:

1. **A converter.** It reads one character's head from the user's game, using the WolvenKit CLI, and writes a private "character pack".
2. **A viewer.** One self-contained HTML file: open a character pack, open an animation, then play/pause and scrub a timeline. It can compare A and B side by side and has a pose tester.

**Never ship or commit game-derived data.** That covers meshes, rigs, facial setups, animations, audio and character packs. The packs and the built viewer stay on the user's PC. Put them outside any git repository, or ignore them in git. This skill is the only thing that's shared: knowledge, not data.

## Before you start

Check, and ask the user for anything missing:

- **Cyberpunk 2077 installed:** the game folder, which contains `archive\pc\content\*.archive`.
- **The WolvenKit CLI** (`WolvenKit.CLI.exe`), from github.com/WolvenKit/WolvenKit releases. It's 8.x, and the commands below were verified against it.
- **Node.js 18 or newer** (for bundling the viewer) and **Python 3.8 or newer** (for the converter).
- **Which character.** You need the depot path of their head mesh, `...\h0_*.mesh`. Example: `base\characters\main_npc\kerry_eurodyne\h0_001_ma_c__kerry_eurodyne\h0_001_ma_c__kerry_eurodyne_old.mesh`. Find heads with `WolvenKit.CLI archive <archive> -l -r "<name>.*h0_.*\.mesh$"`; most are in `basegame_4_appearance.archive`.
- **Something to play:**
  - a WolvenKit export of a lipsync `.anims` (see "Animation files"), or
  - a LipScan curve JSON made with `--export raw` or `--export cyberpunk`. ARKit exports can't drive this rig.

Log what you do if the user keeps an action log, and send any files you delete to the Recycle Bin.

## Reference: what the game files contain

### Files for one head
| File | Usually found |
|---|---|
| Head mesh `h0_<id>_<body>_c__<name>.mesh` | `basegame_4_appearance` |
| Facial setup `<head folder>\<head>_rigsetup.facialsetup` (the name may drop a suffix: pick the one matching the head's last `__` part) | `basegame_4_appearance` |
| Face skeleton `<head folder>\<head name>_skeleton.rig` | `basegame_4_animation` |
| Eyebrows `<head folder>\heb_*<same suffix>.mesh` | `basegame_4_appearance` |
| Eyes and teeth (shared): `base\characters\head\<body>\h0_000_<body>_c__basehead\he_000_<body>_c__basehead.mesh` and `ht_000_...` (body `ma` = man average, `wa` = woman average; for `pma` and `pwa` use `ma` and `wa`) | `basegame_4_appearance` |

### WolvenKit CLI recipes
- **List:** `WolvenKit.CLI archive "<archive>" -l -r "<regex>"`. Use one simple regex per call; regexes with `|` across many archives have crashed it.
- **Extract:** `WolvenKit.CLI unbundle "<archive>" -o <dir> -r "<regex ending in the file name>$"`.
- **To JSON:** `WolvenKit.CLI convert serialize <file> -o <existing dir>` writes `<file>.json`; the data is under `Data.RootChunk`.
- **Mesh to glTF:** `WolvenKit.CLI export <file.mesh> -o <dir> -gp "<game folder>"`.
  - It fails with "Depot path is not set" unless mesh export options are given. **Don't edit the user's WolvenKit settings.** Pass them as environment variables for that one process: `MeshExportArgs__withMaterials=false`, `MeshExportArgs__MaterialRepo=<a temp folder>`, `MeshExportArgs__ExportGarmentSupport=false`.
- **Animation to glTF:** `WolvenKit.CLI export <file.anims> -o <dir> -gp "<game folder>"` writes a `.glb` whose `animations[].extras` hold the decoded face tracks.
- **glTF back to `.anims`:** `import` can't rebuild animations from the CLI; it can't find the rig because it doesn't load the game archives. Use the WolvenKit app for that. The viewer doesn't need it.

### Face skeleton (`.rig` JSON)
- `boneNames[]` (344 on the male face rig), `boneParentIndexes[]` (−1 = root), `boneTransforms[]` (local rest: `Rotation{i,j,k,r}`, `Translation{X,Y,Z}`, `Scale`).
- `trackNames[]`: 414 float tracks, the same order on every face rig checked.
  - Base pose tracks, for example `jaw_mid_open` = 82.
  - A dialogue lipsync layer: the same names plus `LipsyncPoseOutput`, indices 240–380 (`jaw_mid_openLipsyncPoseOutput` = 309).
  - `jaliJaw` (7) and `jaliLips` (8).
- `referenceTracks[]`: the rest value of each track.
- **Space:** REDengine is Z-up. The rig's rest pose, chained through the parents, lands exactly on WolvenKit's glTF bone positions under `gltf = (x, z, -y)`.

### Facial setup (`.facialsetup` JSON, `animFacialSetup`)
There are three parts: `Face`, `Tongue` and `Eyes`. For each part:

- **`bakedData.Data.<Part>.AllMainPoses[]`:** `{Track, NumInbetweens}`. Each main pose belongs to one track (an index into `trackNames`). Its in-between slots are consecutive. For the male face that's 121 main poses and 133 slots.
- **`bakedData.Data.<Part>.AllMainPosesInbetweens[]`:** one position per slot, for example `0.5, 1` for a pose with a half-way in-between. (`AllMainPosesInbetweenScopeMultipliers` are 1/(gap) for those, so they're redundant.)
- **`mainPosesData.Data.<Part>.Poses[slot]`:** `{TransformIdx, NumTransforms}` into `mainPosesData.Data.<Part>.Transforms[]`. Each transform is `{Bone, Rotation{i,j,k,r}, Translation{X,Y,Z}}`.
  - These are **offsets on top of the rest pose**. For example, `jaw_mid_open` rotates `mid_J_jaw_JNT` about 9° at 0.5 and about 20° at 1.0, with a small slide.
  - `Bone` indexes the rig's `boneNames`.
- **`correctivePosesData.Data.<Part>.Poses[k]`:** the same layout. The k-th corrective's name is `faceCorrectiveNames[k]` (or `tongueCorrectiveNames[k]`): driver tokens joined by `__`, ending in `__Corr`.
  - A token is either a track name, which means that track's value, or a track name followed by a digit, which means that in-between slot's weight. Example: `jaw_mid_open1__tongue_mid_base_up__Corr` is driven by slot 1 of `jaw_mid_open` together with `tongue_mid_base_up`.
  - The male face has 255 correctives and the tongue 4. They all parse this way.
- **Not used by the basic solver:**
  - `GlobalLimits`
  - `InfluencedPoses` / `InfluenceIndices`
  - `CorrectiveInfluencedPoses`
  - `GlobalCorrectiveEntries` (the index form of the corrective drivers)
  - `InbetweenCorrectiveEntries`
  - `LipsyncOverridesIndexMapping`
  - `Wrinkles`
  - `UpperLowerFace`
  - `LipsyncPosesSides`

  Refining the solver with these is a good next step.

### Animation files (WolvenKit `.anims` glTF export)
- `animations[k].name` is the clip name. Dialogue clips are `f_<voice line id in hex>` / `m_...`.
- `animations[k].extras` holds:
  - `trackKeys[]` = `{trackIndex, time, value}`
  - `constTrackKeys[]` (one value for the whole clip; its `time` is the clip length)
  - `animationType` (for example `AdditiveFromRefPose`)
- For "Additive" clips, the final track value = `referenceTracks[i]` + the clip's value.
- Dialogue lipsync lives in `base\localization\<lang>\lipsync\...\<character>.anims`. The voice is `base\localization\<lang>\vo\<character>_<quest>_f_<id>.wem`, in `lang_<lang>_voice.archive`; decode it with vgmstream.

## The solver (per frame)
1. **Sample** every track at time t (linear between keys) and add the reference values for additive clips.
2. **Merge the lipsync layer:** for every `<name>LipsyncPoseOutput` track, add its value onto `<name>`. Clamp all tracks to 0..1.
3. **Reset** each bone to a translation offset of zero and a rotation offset of identity.
4. **Main poses:** for each part and each main pose, take the track value v and the slot positions p0 < p1 < … ≤ 1.
   - Below p0, slot 0's weight is v/p0.
   - Between p(k−1) and pk, slot k's weight is f = (v − p(k−1)) / (pk − p(k−1)) and slot k−1's weight is 1 − f.
   - For each slot with weight w and each of its transforms: rotation offset ×= slerp(identity, q, w), and translation offset += w·t.

   Remember each slot's weight.
5. **Correctives:** w = the product of the driver values (track values or slot weights). If w > 0, apply the pose the same way.
6. **Local bone transform** = (rest translation + translation offset, rest rotation × rotation offset). Chain through the parents for world matrices W, and keep the rest world matrices W0.
7. **Deformation** per bone, in glTF axes: D = C · W · W0⁻¹ · C⁻¹, where C maps (x,y,z) to (x,z,−y).

## Putting it on the meshes
- WolvenKit's mesh glTF has a **flat skeleton**: every joint is a direct child of `Armature`, positioned at its world rest location, and all joints share one orientation. The inverse-bind matrices match that.
- For each joint whose name is in the rig, set its world matrix to D · R, where R is the joint's exported rest matrix **with its position replaced by the rig's rest position** (C applied to W0's translation). In three.js: `bone.matrixAutoUpdate = false`, and `bone.matrix = parentWorld⁻¹ · D · R`.
- **Why the position swap matters:** eyes and teeth are shared meshes. In the game they ride on the character's own skeleton, and the swap reproduces that. For the character's own head it changes nothing.
- **Materials:** without textures, use neutral shading. The teeth mesh holds teeth, gums and tongue together, so color its vertices by their strongest bone (`*tongue*` pink, the rest ivory). The eye mesh's `*_doubled` submesh is the cornea; make it nearly transparent.
- **Camera:** the head faces −Z in glTF, so put the camera on the −Z side.

## Viewer requirements
- **Open:** a character pack folder (use `<input webkitdirectory>` or drag a folder in), an animation for slot A, an optional animation for slot B, and optional audio. Clips go in a dropdown.
- **Transport:**
  - Play/Pause (Space), plus a step of 1/30 s with the arrow keys
  - a timeline canvas drawing the jaw curve (`jaw_mid_open` plus its lipsync layer) and the lips-shut curve, for each loaded slot
  - click or drag the timeline to seek
  - speed and loop controls
  - an audio offset in ms; the audio is the clock while it plays
- **Views:** A, B, or A and B side by side, as two head instances 0.26 m apart.
- **Extras:** an "active tracks" list (the strongest main poses), a pose tester (pick any posed track and drag 0–1), eyebrow/eye/teeth/wireframe toggles, and a front-camera button.
- **Build:** bundle three.js (MIT) and the app into **one HTML file** (esbuild, IIFE, inlined), so it opens from disk with no server. For an app-like window on Windows: `msedge.exe --app="file:///.../viewer.html"`.

## Checks before handing it over
- `jaw_mid_open` = 1 in the pose tester: the jaw drops about 20°, the lips part, the lower teeth and tongue follow the jaw, and nothing tears.
- `lips_together_dn` = 1: the lower lip rises cleanly to meet the upper one.
- A game dialogue clip played with its voice: the mouth closes on p/b/m and opens on the vowels.
- A LipScan curve file for the same line, in slot B, side by side: the timing and shapes are comparable.
- Not checked against the game itself: exact tongue placement, and the refinements listed under "Not used by the basic solver". Say so if asked.

## Privacy reminders for the user
- **Character packs and built viewers contain or reference game data.** Keep them private and out of repositories.
- **The converter only reads the game archives.** It never modifies the game.

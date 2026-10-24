# Contributing

LipScan is a small personal developer project, shared as is. Issues and pull requests are welcome, but there is no promise of support or a timeline.

Especially welcome:
- **A test of the WolvenKit round trip** (model curves to glTF to `.anims`, in game). See `docs/WOLVENKIT.md`.
- **Profiles measured from real performers,** as JSON numbers only, never recordings.
- **Exporters for other targets,** such as Blender shape keys, VRM or Live Link.

**Please don't** commit game files, extracted game data, audio, video or recordings, or anything you don't have the right to share.

Before a pull request, run the tests:
- `node test/selftest.mjs`
- `python test/test_model.py`

"""
Build a LipScan viewer pack for a Cyberpunk 2077 character from YOUR game install, using the WolvenKit CLI.

    python build_character.py --wolvenkit "C:\\tools\\wolvenkit\\WolvenKit.CLI.exe" \\
        --game "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Cyberpunk 2077" \\
        --head base\\characters\\main_npc\\kerry_eurodyne\\h0_001_ma_c__kerry_eurodyne\\h0_001_ma_c__kerry_eurodyne_old.mesh \\
        --out packs\\kerry

The pack is a folder with character.json (the face rig and its pose library) plus the head, eyebrows, eyes and teeth
as .glb files. Open the folder in lipscan-viewer.html. Packs contain game data: keep them on your PC, don't share them.

How a head's files are found (override any of them with the matching option):
  facial setup  <head folder>\\*_rigsetup.facialsetup  whose name matches the head (else the only one there)
  face skeleton <head name>_skeleton.rig (any archive)
  eyebrows      <head folder>\\heb_*<same suffix>.mesh
  eyes, teeth   the generic base head for the body type (ma = man average, wa = woman average, ...)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ARCHIVES = ("basegame_4_appearance", "basegame_4_animation", "basegame_3_nightcity", "basegame_1_engine", "basegame_2_mainmenu")


def run(cmd, env=None):
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 or "[ 0: Error" in out:
        raise RuntimeError(f"WolvenKit failed: {' '.join(cmd[1:3])}\n{out.strip()[-800:]}")
    return out


class Game:
    def __init__(self, wolvenkit, game, work):
        self.wk, self.game, self.work = wolvenkit, game, work
        self.content = os.path.join(game, "archive", "pc", "content")
        # Export meshes without materials, and without touching the user's WolvenKit settings (env overrides them).
        self.env = dict(os.environ, MeshExportArgs__withMaterials="false",
                        MeshExportArgs__MaterialRepo=os.path.join(work, "depot"), MeshExportArgs__ExportGarmentSupport="false")

    def list(self, regex):
        found = []
        for a in ARCHIVES:
            path = os.path.join(self.content, f"{a}.archive")
            if not os.path.exists(path):
                continue
            out = subprocess.run([self.wk, "archive", path, "-l", "-r", regex], capture_output=True, text=True).stdout
            found += [(a, line.strip()) for line in out.splitlines() if re.search(r"\.\w+$", line.strip()) and "\\" in line]
        return found

    def extract(self, depot_path):
        """Extract one file by its depot path; returns the local path."""
        want = depot_path.replace("/", "\\").lower()
        name_re = re.escape(os.path.basename(want)) + "$"
        for a, p in self.list(name_re):
            if p.lower() == want:
                run([self.wk, "unbundle", os.path.join(self.content, f"{a}.archive"), "-o", os.path.join(self.work, "raw"), "-r", name_re], self.env)
                local = os.path.join(self.work, "raw", *p.split("\\"))
                if os.path.exists(local):
                    return local
        raise FileNotFoundError(f"Not found in the game archives: {depot_path}")

    def to_json(self, local):
        out = os.path.join(self.work, "json")
        os.makedirs(out, exist_ok=True)
        run([self.wk, "convert", "serialize", local, "-o", out], self.env)
        with open(os.path.join(out, os.path.basename(local) + ".json"), encoding="utf-8") as fh:
            return json.load(fh)["Data"]["RootChunk"]

    def mesh_glb(self, local, dest):
        out = os.path.join(self.work, "glb")
        os.makedirs(out, exist_ok=True)
        run([self.wk, "export", local, "-o", out, "-gp", self.game], self.env)
        src = os.path.join(out, os.path.splitext(os.path.basename(local))[0] + ".glb")
        shutil.copy(src, dest)


def r6(x):
    return round(float(x), 6)


def pack_part(baked, poses, correctives, corrective_names, tracks):
    """One facial-setup part (face, tongue or eyes) in the viewer's compact form."""
    def transforms(block, pose):
        ts = block["Transforms"][pose["TransformIdx"]:pose["TransformIdx"] + pose["NumTransforms"]]
        return [[t["Bone"], r6(t["Rotation"]["i"]), r6(t["Rotation"]["j"]), r6(t["Rotation"]["k"]), r6(t["Rotation"]["r"]),
                 r6(t["Translation"]["X"]), r6(t["Translation"]["Y"]), r6(t["Translation"]["Z"])] for t in ts]

    at = baked["AllMainPosesInbetweens"]
    main, slot = [], 0
    for mp in baked["AllMainPoses"]:
        n = mp["NumInbetweens"]
        main.append({"track": mp["Track"], "at": [r6(x) for x in at[slot:slot + n]], "poses": list(range(slot, slot + n))})
        slot += n
    out = {"main": main, "poses": [transforms(poses, p) for p in poses["Poses"]], "correctives": [], "unparsed": []}

    index = {name: i for i, name in enumerate(tracks)}
    for k, pose in enumerate(correctives["Poses"] if correctives else []):
        name = corrective_names[k] if k < len(corrective_names) else f"corrective_{k}"
        drivers = []
        for token in name.split("__")[:-1]:  # "a__b__Corr"
            if token in index:
                drivers.append({"track": index[token]})
            else:
                m = re.match(r"^(.*?)(\d+)$", token)
                if m and m.group(1) in index:
                    drivers.append({"track": index[m.group(1)], "slot": int(m.group(2))})
                else:
                    drivers = None
                    break
        if drivers:
            out["correctives"].append({"name": name, "drivers": drivers, "pose": transforms(correctives, pose)})
        else:
            out["unparsed"].append(name)
    return out


def main():
    ap = argparse.ArgumentParser(description="Build a LipScan viewer pack from a Cyberpunk 2077 head.")
    ap.add_argument("--wolvenkit", required=True, help="path to WolvenKit.CLI.exe")
    ap.add_argument("--game", required=True, help="Cyberpunk 2077 install folder")
    ap.add_argument("--head", required=True, help="depot path of the head .mesh (h0_...)")
    ap.add_argument("--facialsetup", help="depot path of the .facialsetup (found automatically if omitted)")
    ap.add_argument("--rig", help="depot path of the face skeleton .rig (found automatically if omitted)")
    ap.add_argument("--extra", action="append", default=[], help="another .mesh to include (hair, beard...); repeatable")
    ap.add_argument("--out", required=True, help="folder to write the pack into")
    ap.add_argument("--keep-work", action="store_true", help="keep the temporary extraction folder")
    a = ap.parse_args()

    head = a.head.replace("/", "\\")
    folder, base = os.path.dirname(head), os.path.splitext(os.path.basename(head))[0]   # h0_001_ma_c__kerry_eurodyne_old
    body = (re.search(r"_(p?[mw]a)_", base) or re.search(r"_(p?[mw][a-z]{1,2})_", base))
    body = body.group(1) if body else "ma"
    os.makedirs(a.out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="lipscan-pack-")
    g = Game(a.wolvenkit, a.game, work)
    try:
        print("finding files...")
        setup = a.facialsetup
        if not setup:
            cands = [p for _, p in g.list(re.escape(os.path.basename(folder)) + r".*\.facialsetup$") if p.lower().startswith(folder.lower())]
            suffix = base.split("__")[-1]                                               # kerry_eurodyne_old
            match = [p for p in cands if suffix in p] or cands
            if not match:
                sys.exit("No .facialsetup found next to the head; pass --facialsetup.")
            setup = match[0]
        rig = a.rig or f"{folder}\\{base}_skeleton.rig"
        brows = [p for _, p in g.list(re.escape(os.path.basename(folder)) + r".*\\heb_.*\.mesh$")
                 if p.lower().startswith(folder.lower()) and base.split("__")[-1] in p]
        generic = f"base\\characters\\head\\{body.lstrip('p')}\\h0_000_{body.lstrip('p')}_c__basehead"
        meshes = [("head", head)] + [("eyebrows", b) for b in brows[:1]] + \
                 [("eyes", f"{generic}\\he_000_{body.lstrip('p')}_c__basehead.mesh"), ("teeth", f"{generic}\\ht_000_{body.lstrip('p')}_c__basehead.mesh")] + \
                 [(os.path.splitext(os.path.basename(x))[0], x.replace("/", "\\")) for x in a.extra]
        print(f"  facial setup: {setup}\n  skeleton:     {rig}")

        rig_json = g.to_json(g.extract(rig))
        setup_json = g.to_json(g.extract(setup))
        tracks = [t["$value"] for t in rig_json["trackNames"]]
        bones = {
            "names": [b["$value"] for b in rig_json["boneNames"]],
            "parents": rig_json["boneParentIndexes"],
            "t": [[r6(b["Translation"]["X"]), r6(b["Translation"]["Y"]), r6(b["Translation"]["Z"])] for b in rig_json["boneTransforms"]],
            "r": [[r6(b["Rotation"]["i"]), r6(b["Rotation"]["j"]), r6(b["Rotation"]["k"]), r6(b["Rotation"]["r"])] for b in rig_json["boneTransforms"]],
        }
        ref = rig_json.get("referenceTracks") or []
        baked = setup_json["bakedData"]["Data"]
        mains = setup_json["mainPosesData"]["Data"]
        corrs = setup_json["correctivePosesData"]["Data"]
        names = {"Face": [n["$value"] for n in setup_json.get("faceCorrectiveNames", [])],
                 "Tongue": [n["$value"] for n in setup_json.get("tongueCorrectiveNames", [])], "Eyes": []}
        parts = {}
        for part in ("Face", "Tongue", "Eyes"):
            parts[part.lower()] = pack_part(baked[part], mains[part], corrs.get(part), names[part], tracks)
            p = parts[part.lower()]
            print(f"  {part.lower():7s} {len(p['main'])} main poses, {len(p['poses'])} with in-betweens, "
                  f"{len(p['correctives'])} correctives" + (f" ({len(p['unparsed'])} not understood)" if p["unparsed"] else ""))

        files = []
        for role, depot in meshes:
            try:
                dest = os.path.join(a.out, f"{role}.glb")
                g.mesh_glb(g.extract(depot), dest)
                files.append({"role": role, "file": f"{role}.glb", "source": depot})
                print(f"  mesh {role}: {depot}")
            except Exception as e:  # a missing extra (eyebrows, teeth) isn't fatal
                print(f"  skipped {role}: {str(e).splitlines()[0]}")
        if not any(f["role"] == "head" for f in files):
            sys.exit("The head mesh couldn't be exported.")

        pack = {
            "format": "lipscan-character/1", "name": base,
            "note": "Made from your own Cyberpunk 2077 install with WolvenKit. Contains game data: keep it private.",
            "source": {"head": head, "facialsetup": setup, "rig": rig},
            "space": "REDengine (Z up); glTF meshes are Y up: gltf = (x, z, -y)",
            "tracks": tracks, "referenceTracks": [r6(x) for x in ref], "bones": bones, "parts": parts, "meshes": files,
        }
        with open(os.path.join(a.out, "character.json"), "w", encoding="utf-8") as fh:
            json.dump(pack, fh, separators=(",", ":"))
        print(f"wrote {a.out} ({len(files)} meshes)")
    finally:
        if a.keep_work:
            print(f"work folder kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)  # our own temporary folder


if __name__ == "__main__":
    main()

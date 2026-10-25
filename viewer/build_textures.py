#!/usr/bin/env python3
"""
Add the game's textures to a viewer pack you built with build_character.py, from YOUR game install, using the WolvenKit CLI.

    python build_textures.py --wolvenkit "C:\\tools\\wolvenkit\\WolvenKit.CLI.exe" --game "C:\\...\\Cyberpunk 2077" --pack packs\\kerry

It reads each mesh's material (the pack's character.json says which meshes it has): the head's skin albedo, normal and roughness
maps, the eyebrows' strand texture, the teeth's albedo (the teeth, gums and tongue share one) and the game's plain eye albedo. They
are uncooked to PNG into <pack>\\textures\\ and listed under "textures" in character.json. The viewer then uses them. Packs hold game data (now textures too): keep them on your PC, don't share them.

What it handles: heads whose skin material is the game's plain skin (every named character; the player's layered heads are not
covered, and keep the flat colour). Hair and beards are not in a pack.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_character as bc  # noqa: E402

EYE_ALBEDO = r"base\characters\common\eyes\textures\he_000_base_d01.xbm"        # the game's plain eyeball: sclera, iris, pupil in one map


def pick_skin(material_json):
    """The first skin material's Albedo / Normal / Roughness depot paths."""
    for m in material_json["Materials"]:
        if m.get("MaterialTemplate", "").lower().endswith("skin.mt"):
            d = m["Data"]
            return {k: d[k] for k in ("Albedo", "Normal", "Roughness") if isinstance(d.get(k), str) and d[k].endswith(".xbm")}
    return {}


def pick_brows(material_json):
    """The eyebrow strand texture: the DiffuseTexture of the material named "default" (else the first with one)."""
    found = [m for m in material_json["Materials"] if isinstance(m.get("Data", {}).get("DiffuseTexture"), str)
             and m["Data"]["DiffuseTexture"].endswith(".xbm") and "eyebrow" in m["Data"]["DiffuseTexture"].lower()]
    found.sort(key=lambda m: m.get("Name") != "default")
    return {"Albedo": found[0]["Data"]["DiffuseTexture"]} if found else {}


def materials_of(g, depot, work):
    """The Material.json WolvenKit writes next to a mesh export (it lists the materials' textures)."""
    local = g.extract(depot)
    out = os.path.join(work, "mats", re.sub(r"\W", "_", depot))
    os.makedirs(out, exist_ok=True)
    bc.run([g.wk, "export", local, "-o", out, "-gp", g.game], g.env)
    mj = next((os.path.join(out, f) for f in os.listdir(out) if f.endswith(".Material.json")), None)
    if not mj:
        return None
    with open(mj, encoding="utf-8") as fh:
        return json.load(fh)


def uncook(g, depot, out_dir, name):
    """Extract one .xbm by depot path and write it as <out_dir>/<name>.png. Returns the file name, or None if it isn't there."""
    try:
        local = g.extract(depot)
    except FileNotFoundError:
        return None
    tmp = tempfile.mkdtemp(prefix="lipscan-tex-")
    try:
        bc.run([g.wk, "export", local, "-o", tmp, "-gp", g.game, "--uext", "png"], g.env)
        found = [os.path.join(r, f) for r, _, fs in os.walk(tmp) for f in fs if f.lower().endswith(".png")]
        if not found:
            return None
        os.makedirs(out_dir, exist_ok=True)
        shutil.copy(found[0], os.path.join(out_dir, name + ".png"))
        return name + ".png"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Add the game's skin and eye textures to a LipScan viewer pack.")
    ap.add_argument("--wolvenkit", required=True, help="path to WolvenKit.CLI.exe")
    ap.add_argument("--game", required=True, help="Cyberpunk 2077 install folder")
    ap.add_argument("--pack", required=True, help="a pack folder made by build_character.py (has character.json)")
    ap.add_argument("--keep-work", action="store_true", help="keep the temporary extraction folder")
    a = ap.parse_args()

    cj = os.path.join(a.pack, "character.json")
    with open(cj, encoding="utf-8") as fh:
        pack = json.load(fh)
    sources = {m["role"]: m["source"] for m in pack["meshes"]}
    work = tempfile.mkdtemp(prefix="lipscan-pack-")
    g = bc.Game(a.wolvenkit, a.game, work)
    g.env["MeshExportArgs__withMaterials"] = "true"          # the materials file is what lists the textures
    out_dir = os.path.join(a.pack, "textures")
    textures = []
    try:
        for role, picker in (("head", pick_skin), ("eyebrows", pick_brows), ("teeth", pick_skin)):
            if role not in sources:
                continue
            mj = materials_of(g, sources[role], work)
            tex = picker(mj) if mj else {}
            if not tex:
                print(f"{role}: no plain material to take textures from; its flat colour is kept.")
            for slot, key in (("map", "Albedo"), ("normalMap", "Normal"), ("roughnessMap", "Roughness")):
                if key in tex and (role == "head" or key == "Albedo"):
                    f = uncook(g, tex[key], out_dir, f"{role}_{key.lower()}")
                    print(f"{role} {key}: {tex[key].split(chr(92))[-1]} -> {f or 'not found'}")
                    if f:
                        textures.append({"role": role, "slot": slot, "file": f"textures/{f}"})
        f = uncook(g, EYE_ALBEDO, out_dir, "eyes_albedo")
        print(f"eyes albedo -> {f or 'not found'}")
        if f:
            textures.append({"role": "eyes", "slot": "map", "file": f"textures/{f}"})
    finally:
        if not a.keep_work:
            shutil.rmtree(work, ignore_errors=True)
    pack["textures"] = textures
    with open(cj, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, separators=(",", ":"))
    print(f"{len(textures)} textures added to {a.pack}")


if __name__ == "__main__":
    main()

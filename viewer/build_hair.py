#!/usr/bin/env python3
"""
Add the character's hair to a viewer pack you built with build_character.py, from YOUR game install, using the WolvenKit CLI.

    python build_hair.py --wolvenkit "C:\\tools\\wolvenkit\\WolvenKit.CLI.exe" --game "C:\\...\\Cyberpunk 2077" --pack packs\\kerry
    python build_hair.py ... --pack packs\\kerry --hair "base\\characters\\common\\hair\\hh_053_ma__kerry_eurodyne\\hh_053_ma__kerry_eurodyne.mesh"

Finds the character's hair mesh (the game's hair is a set of textured cards skinned to the head), exports it as hair.glb into the pack,
takes the strand alpha texture into textures\\, and reads an average colour from the game's hair profile. The viewer draws it and moves
it with a small spring simulation of the head's motion (see "Hair" in viewer/README.md). Packs hold game data: keep them on your PC.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_character as bc  # noqa: E402
import build_textures as bt  # noqa: E402

SKIP = re.compile(r"young|shadow|cyberware|_common|common_|bald|wig|npc|cutscene|photo|hat", re.I)


def find_hair(g, head_depot):
    """The best hair mesh for the head's character, or None: a hh_<n>_<body>__<name> mesh next to the head or in common\\hair."""
    parts = head_depot.lower().split("\\")
    name = parts[parts.index("main_npc") + 1] if "main_npc" in parts else None
    body = (re.search(r"_(p?[mw][a-z])_", parts[-1]) or [None, "ma"])[1]
    if not name:
        return None
    # hh_050_ma__johnny_silverhand (a first name before the folder's), hh_001_mb_c__jackie_welles (a _c before the __)
    found = [p for _, p in g.list(rf"hh_\d+_p?{body[-2:]}(?:_c)?__(?:[a-z]+_)?{re.escape(name)}[^\\]*\.mesh$")]
    found = [p for p in found if "shadow_meshes" not in p.lower()]
    found = [p for p in found if not SKIP.search(os.path.basename(p))] or [p for p in found if "young" not in p.lower()]
    return sorted(found, key=lambda p: (len(os.path.basename(p)), p))[0] if found else None


def character_profile(g, head_depot):
    """A hair profile named for the character (Kerry has kerry_eurodyne_old_brown_salt_n_pepper.hp), or None."""
    parts = head_depot.lower().split(chr(92))
    name = parts[parts.index("main_npc") + 1] if "main_npc" in parts else None
    bs = chr(92) * 2                                       # a regex backslash
    found = [p for _, p in g.list(rf"{bs}{re.escape(name)}[^{bs}]*\.hp$")] if name else []
    return sorted(found, key=lambda p: ("young" in p.lower(), len(p)))[0] if found else None


NATURAL = ("default", "black_carbon", "black", "dark_brown", "brown", "carbon")


def natural_profile(mats):
    """The hair mesh holds a material for every dye colour. Without a profile named for the character, take a natural dark one."""
    cards = [m for m in mats["Materials"] if isinstance(m.get("Data", {}).get("HairProfile"), str)]
    for want in NATURAL:
        for m in cards:
            if want in m["Name"].lower() or want in m["Data"]["HairProfile"].lower():
                return m["Data"]["HairProfile"]
    return cards[0]["Data"]["HairProfile"] if cards else None


def gradient_mean(entries):
    """The mean colour of a gradient over 0..1 (piecewise linear between its entries, held flat past the ends), per channel 0-255."""
    pts = sorted((e["value"], [e["color"][c] for c in ("Red", "Green", "Blue")]) for e in entries)
    pts = [(0.0, pts[0][1])] + pts + [(1.0, pts[-1][1])]
    total = [0.0, 0.0, 0.0]
    for (v0, c0), (v1, c1) in zip(pts, pts[1:]):
        for k in range(3):
            total[k] += (v1 - v0) * (c0[k] + c1[k]) / 2
    return total


def profile_color(g, hp_depot):
    """An average hair colour (#rrggbb) from a hair profile: the game colours a strand by its position along it (root to tip) and by
    its own random id, so the average colour is the product of the two gradients' means."""
    try:
        d = g.to_json(g.extract(hp_depot))
    except (FileNotFoundError, OSError, KeyError):
        return None
    rt, ids = d.get("gradientEntriesRootToTip") or [], d.get("gradientEntriesID") or []
    if not rt:
        return None
    a = gradient_mean(rt)
    b = [x / 255 for x in gradient_mean(ids)] if ids else [1.0, 1.0, 1.0]
    return "#%02x%02x%02x" % tuple(int(round(min(255, x * y))) for x, y in zip(a, b))


def main():
    ap = argparse.ArgumentParser(description="Add a character's hair to a LipScan viewer pack.")
    ap.add_argument("--wolvenkit", required=True)
    ap.add_argument("--game", required=True, help="Cyberpunk 2077 install folder")
    ap.add_argument("--pack", required=True, help="a pack folder made by build_character.py")
    ap.add_argument("--hair", help="depot path of the hair .mesh (found from the head's name if omitted)")
    ap.add_argument("--hp", help="depot path of a hair profile .hp to take the colour from (the material's own if omitted)")
    ap.add_argument("--color", help="hair colour #rrggbb, instead of the profile's")
    a = ap.parse_args()

    cj = os.path.join(a.pack, "character.json")
    with open(cj, encoding="utf-8") as fh:
        pack = json.load(fh)
    head = next(m["source"] for m in pack["meshes"] if m["role"] == "head")
    work = tempfile.mkdtemp(prefix="lipscan-pack-")
    g = bc.Game(a.wolvenkit, a.game, work)
    try:
        depot = a.hair or find_hair(g, head)
        if not depot:
            sys.exit("No hair mesh found for this head. Give one with --hair (a depot path to a hh_... .mesh).")
        print("hair mesh:", depot)
        g.mesh_glb(g.extract(depot), os.path.join(a.pack, "hair.glb"))
        g.env["MeshExportArgs__withMaterials"] = "true"
        mats = bt.materials_of(g, depot, work) or {"Materials": []}
        card = next((m for m in mats["Materials"] if isinstance(m.get("Data", {}).get("Strand_Alpha"), str)), None)
        textures = [t for t in pack.get("textures", []) if t["role"] != "hair"]
        if card:
            f = bt.uncook(g, card["Data"]["Strand_Alpha"], os.path.join(a.pack, "textures"), "hair_alpha")
            print("strand alpha ->", f or "not found")
            if f:
                textures.append({"role": "hair", "slot": "alphaMap", "file": f"textures/{f}"})
        hp = a.hp or character_profile(g, head) or natural_profile(mats)
        color = a.color or (profile_color(g, hp) if hp else None) or "#2b2420"
        print("hair colour", color, "from", (hp or "a default").split(chr(92))[-1])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    pack["meshes"] = [m for m in pack["meshes"] if m["role"] != "hair"] + [{"role": "hair", "file": "hair.glb", "source": depot}]
    pack["textures"] = textures
    pack["hair"] = {"color": color}
    with open(cj, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, separators=(",", ":"))
    print("hair added to", a.pack)


if __name__ == "__main__":
    main()

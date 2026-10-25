"""
Character-creator support for player heads (V): the face options of Cyberpunk 2077's character creator.

How the game stores them (found with WolvenKit, for player_man_average / player_female_average):
  - <player folder>\\h0_000_<body>__morphs.morphtarget: the base head plus 100 morph targets named h<PP><R>, one per
    head preset PP (01..20) and face region R (1 eyes, 2 nose, 3 mouth, 4 jaw, 5 ear). Picking "jaw 7" in the creator
    means target h074 at full weight.
  - he_ / heb_ / ht_000_<body>__morphs.morphtarget: the same for the eyes (eye targets only), eyebrows and teeth
    (mouth targets only).
  - Each target also carries boneRigMatrices: the face joints' bind pose for that head preset. They're the same for
    all five regions of a preset, so the game must choose per joint which region's preset to use. That rule isn't
    in the data; here each joint follows the region whose morphs move the skin it drives most (an approximation).

This module exports those morph-target files as the pack's meshes (head, eyes, eyebrows, teeth with all their
targets) and writes, per preset, how far each joint moves from the base head's bind pose. The viewer applies the
morphs and moves the joints, so the face rig's poses work on the chosen face.
"""

import json
import os
import re
import shutil
import struct

import numpy as np

REGIONS = ["eyes", "nose", "mouth", "jaw", "ear"]
ROLES = {"head": "h0", "eyes": "he", "eyebrows": "heb", "teeth": "ht"}
COMPONENTS = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path):
    b = open(path, "rb").read()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    rest = 20 + n
    bin_len = struct.unpack("<I", b[rest:rest + 4])[0]
    return j, b[rest + 8:rest + 8 + bin_len]


def accessor(j, bin_, i):
    """An accessor's data as a numpy array (sparse accessors included)."""
    a = j["accessors"][i]
    k, w = COMPONENTS[a["componentType"]], WIDTH[a["type"]]
    if "bufferView" in a:
        v = j["bufferViews"][a["bufferView"]]
        off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = v.get("byteStride") or np.dtype(k).itemsize * w
        raw = np.frombuffer(bin_, dtype=np.uint8, count=stride * (a["count"] - 1) + np.dtype(k).itemsize * w, offset=off)
        out = np.lib.stride_tricks.as_strided(raw, shape=(a["count"], w * np.dtype(k).itemsize), strides=(stride, 1)).copy()
        out = out.view(k).reshape(a["count"], w).astype(np.float64)
    else:
        out = np.zeros((a["count"], w))
    if "sparse" in a:
        s = a["sparse"]
        iv, vv = j["bufferViews"][s["indices"]["bufferView"]], j["bufferViews"][s["values"]["bufferView"]]
        idx = np.frombuffer(bin_, dtype=COMPONENTS[s["indices"]["componentType"]], count=s["count"],
                            offset=iv.get("byteOffset", 0) + s["indices"].get("byteOffset", 0))
        val = np.frombuffer(bin_, dtype=k, count=s["count"] * w,
                            offset=vv.get("byteOffset", 0) + s["values"].get("byteOffset", 0)).reshape(s["count"], w)
        out[idx.astype(int)] = val
    return out


def bone_regions(glb_path):
    """For each joint: the face region whose morph targets move the vertices it drives the most."""
    j, bin_ = read_glb(glb_path)
    mesh = j["meshes"][0]
    names = mesh.get("extras", {}).get("targetNames", [])
    joints = [j["nodes"][n]["name"] for n in j["skins"][0]["joints"]]
    score = np.zeros((len(joints), len(REGIONS)))
    weight = np.zeros(len(joints))
    for prim in mesh["primitives"]:
        at = prim["attributes"]
        sets = [(accessor(j, bin_, at[f"JOINTS_{s}"]).astype(int), accessor(j, bin_, at[f"WEIGHTS_{s}"]))
                for s in range(4) if f"JOINTS_{s}" in at]
        disp = np.zeros((len(sets[0][0]), len(REGIONS)))
        for t, target in enumerate(prim.get("targets", [])):
            if t >= len(names) or "POSITION" not in target:
                continue
            r = REGIONS.index(names[t].split("_")[-1]) if names[t].split("_")[-1] in REGIONS else int(names[t][3]) - 1
            disp[:, r] += np.linalg.norm(accessor(j, bin_, target["POSITION"]), axis=1)
        for js, ws in sets:
            for c in range(js.shape[1]):
                np.add.at(score, js[:, c], ws[:, c:c + 1] * disp)
                np.add.at(weight, js[:, c], ws[:, c])
    out = {}
    for b, name in enumerate(joints):
        if weight[b] > 0 and score[b].max() / weight[b] > 1e-4:
            out[name] = REGIONS[int(np.argmax(score[b]))]
    return out


def bind_worlds(names, matrices):
    """boneRigMatrices (inverse bind, REDengine row-vector layout) -> {bone: world bind matrix (column-vector)}."""
    def mat(m):
        return np.array([[m[a]["X"], m[a]["Y"], m[a]["Z"], m[a]["W"]] for a in "XYZW"])
    return {n["$value"]: np.linalg.inv(mat(m).T) for n, m in zip(names, matrices)}


def quat(m):
    u, _, vt = np.linalg.svd(m[:3, :3])
    r = u @ vt
    w = np.sqrt(max(0.0, 1 + r[0, 0] + r[1, 1] + r[2, 2])) / 2
    if w < 1e-6:
        return [0.0, 0.0, 0.0, 1.0]
    return [(r[2, 1] - r[1, 2]) / (4 * w), (r[0, 2] - r[2, 0]) / (4 * w), (r[1, 0] - r[0, 1]) / (4 * w), w]


def add_creator(g, run, head, out_dir, files):
    """If `head` is a player base head with creator morphs, swap the pack's meshes for the morph-target versions and
    return the pack's "creator" section; else None."""
    folder = os.path.dirname(head)
    player = os.path.dirname(folder)
    m = re.search(r"h0_\d+_(p[mw]a)_", os.path.basename(head))
    if not m:
        return None
    body = m.group(1)
    morphs = {role: f"{player}\\{pre}_000_{body}__morphs.morphtarget" for role, pre in ROLES.items()}
    try:
        local = {"head": g.extract(morphs["head"])}
    except FileNotFoundError:
        return None
    print(f"  character creator: {morphs['head']}")
    for role in ("eyes", "eyebrows", "teeth"):
        try:
            local[role] = g.extract(morphs[role])
        except FileNotFoundError:
            print(f"    no {role} morphs")

    # the meshes, with their morph targets
    env = dict(g.env, MorphTargetExportArgs__IsBinary="true")
    glb_dir = os.path.join(g.work, "morph-glb")
    os.makedirs(glb_dir, exist_ok=True)
    for role, path in local.items():
        run([g.wk, "export", path, "-o", glb_dir, "-gp", g.game], env)
        src = os.path.join(glb_dir, os.path.basename(path) + ".glb")
        if not os.path.exists(src):
            src = os.path.join(glb_dir, os.path.splitext(os.path.basename(path))[0] + ".glb")
        shutil.copy(src, os.path.join(out_dir, f"{role}.glb"))
        entry = next((f for f in files if f["role"] == role), None)
        if entry is None:
            files.append({"role": role, "file": f"{role}.glb", "source": morphs[role]})
        else:
            entry["source"] = morphs[role]
        print(f"    mesh {role}: {morphs[role]} (with creator morphs)")

    # joint moves per preset, relative to each morph file's own base mesh
    regions = bone_regions(os.path.join(out_dir, "head.glb"))
    deltas, region_of = {}, {}
    for role, path in local.items():
        mt = g.to_json(path)
        base = g.to_json(g.extract(mt["baseMesh"]["DepotPath"]["$value"]))
        base_w = bind_worlds(base["boneNames"], base["boneRigMatrices"])
        for t in mt["targets"]:
            name = t["name"]["$value"]                          # h<PP><R>
            preset, reg = name[1:3], REGIONS[int(name[3]) - 1]
            new_w = bind_worlds(t["boneNames"], t["boneRigMatrices"])
            for bone, w in new_w.items():
                if bone not in base_w or (bone in region_of and region_of[bone][0] != role):
                    continue
                region_of.setdefault(bone, (role, regions.get(bone) if role == "head" else reg))
                d = w @ np.linalg.inv(base_w[bone])
                if np.abs(d[:3, 3]).max() > 1e-5 or np.abs(d[:3, :3] - np.eye(3)).max() > 1e-5:
                    deltas.setdefault(preset, {})[bone] = [round(float(x), 6) for x in list(d[:3, 3]) + quat(d)]
    bone_region = {b: r for b, (_, r) in region_of.items() if r}
    print(f"    {len(deltas)} presets, {len(bone_region)} joints assigned to a region")
    return {
        "about": "Cyberpunk 2077 character-creator face options. Morph targets h<PP><R> (preset PP 01-20, region R) are in the "
                 "meshes; boneDeltas[PP][bone] = [tx, ty, tz, qx, qy, qz, qw], how far that preset moves a face joint from the "
                 "base bind pose (REDengine axes, world space). Joints follow the preset chosen for their region (boneRegion).",
        "regions": REGIONS,
        "presets": sorted(deltas),
        "boneRegion": bone_region,
        "boneDeltas": deltas,
        "regionRule": "approximation: each joint follows the region whose morphs move its skin most",
    }

"""Exporters: rename (and where needed combine) the model's tracks for a target.

Each exporter takes the model's result {"fps", "profile", "duration", "tracks"} and returns a new one.
Add a target by writing a function here and listing it in EXPORTERS.
"""


def raw(result):
    """The model's own names (REDengine face-rig pose names)."""
    return result


def cyberpunk(result):
    """Cyberpunk 2077 dialogue lipsync layer: the rig's pose names plus "LipsyncPoseOutput"."""
    return {**result, "target": "cyberpunk-dialogue",
            "tracks": {k + "LipsyncPoseOutput": v for k, v in result["tracks"].items()}}


# ARKit name -> how to build it from the model's tracks: ("max" | "avg", [source tracks]).
# The two rigs don't line up one to one; these are the closest matches. ARKit has no tongue shapes except tongueOut,
# so the model's tongue tracks are dropped.
ARKIT_FROM_RIG = {
    "jawOpen": ("max", ["jaw_mid_open"]),
    "jawLeft": ("max", ["jaw_mid_shift_l"]),
    "mouthClose": ("max", ["lips_together_up", "lips_together_dn"]),  # lips pressed shut over an open jaw
    "mouthPucker": ("avg", ["lips_l_purse", "lips_r_purse"]),
    "mouthFunnel": ("avg", ["lips_l_funnel", "lips_r_funnel"]),
    "mouthRollLower": ("max", ["lips_suck_dn"]),
    "mouthShrugLower": ("avg", ["lips_l_lower_raise", "lips_r_lower_raise"]),
    "mouthUpperUpLeft": ("max", ["lips_l_upper_raise"]),
    "mouthUpperUpRight": ("max", ["lips_r_upper_raise"]),
    "mouthLowerDownLeft": ("max", ["lips_apart_dn"]),
    "mouthLowerDownRight": ("max", ["lips_apart_dn"]),
    "mouthSmileLeft": ("max", ["lips_l_corner_up"]),
    "mouthSmileRight": ("max", ["lips_r_corner_up"]),
    "mouthStretchLeft": ("max", ["lips_l_stretch", "lips_l_corner_stretch", "lips_l_pull"]),
    "mouthStretchRight": ("max", ["lips_r_stretch", "lips_r_corner_stretch", "lips_r_pull"]),
    "noseSneerLeft": ("max", ["nose_l_snear"]),
    "noseSneerRight": ("max", ["nose_r_snear"]),
    "eyeBlinkLeft": ("max", ["eye_l_blink"]),
    "eyeBlinkRight": ("max", ["eye_r_blink"]),
    # upper face (0.2.0). Sides: ARKit's Left and the rig's l are both the character's own left.
    "browInnerUp": ("avg", ["eye_l_brows_raise_in", "eye_r_brows_raise_in"]),
    "browOuterUpLeft": ("max", ["eye_l_brows_raise_out"]),
    "browOuterUpRight": ("max", ["eye_r_brows_raise_out"]),
    "browDownLeft": ("max", ["eye_l_brows_lower"]),
    "browDownRight": ("max", ["eye_r_brows_lower"]),
    "eyeSquintLeft": ("max", ["eye_l_oculi_squint_inner", "eye_l_oculi_squint_outer_upper"]),
    "eyeSquintRight": ("max", ["eye_r_oculi_squint_inner", "eye_r_oculi_squint_outer_upper"]),
    "cheekSquintLeft": ("max", ["eye_l_oculi_squint_outer_lower", "lips_l_nasolabialDeepener"]),
    "cheekSquintRight": ("max", ["eye_r_oculi_squint_outer_lower", "lips_r_nasolabialDeepener"]),
    "eyeWideLeft": ("max", ["eye_l_widen"]),
    "eyeWideRight": ("max", ["eye_r_widen"]),
    "eyeLookDownLeft": ("max", ["eye_l_dir_dn"]),
    "eyeLookDownRight": ("max", ["eye_r_dir_dn"]),
    "eyeLookUpLeft": ("max", ["eye_l_dir_up"]),
    "eyeLookUpRight": ("max", ["eye_r_dir_up"]),
    "eyeLookInLeft": ("max", ["eye_l_dir_in"]),
    "eyeLookInRight": ("max", ["eye_r_dir_in"]),
    "eyeLookOutLeft": ("max", ["eye_l_dir_out"]),
    "eyeLookOutRight": ("max", ["eye_r_dir_out"]),
}


def arkit52(result):
    """The 52 ARKit blendshape names (used by Apple face tracking, Unreal Live Link, Unity, Blender add-ons,
    VRChat and VTuber rigs). Only the shapes the model drives are written; the rest stay at rest."""
    t = result["tracks"]
    n = len(t.get("jaw_mid_open", []))
    out = {}
    for name, (how, sources) in ARKIT_FROM_RIG.items():
        cols = [t[s] for s in sources if s in t]
        if not cols:
            continue
        if how == "max":
            out[name] = [round(max(vals), 4) for vals in zip(*cols)]
        else:
            out[name] = [round(sum(vals) / len(vals), 4) for vals in zip(*cols)]
    return {**result, "target": "arkit52", "frames": n, "tracks": out}


EXPORTERS = {"raw": raw, "cyberpunk": cyberpunk, "arkit52": arkit52}

// Face solver: track values -> bone deformations, rebuilt from the character's facial setup.
//
// Per part (face, tongue, eyes):
//   main pose with in-betweens at positions p0 < p1 < ... (e.g. 0.5, 1): the track value v cross-fades from rest to
//   slot 0 up to p0, then from slot k-1 to slot k up to pk.
//   corrective pose: weight = product of its drivers (a track's value, or one in-between slot's weight).
// Every pose is a list of per-bone offsets (rotation, translation) added on top of the rig's rest pose.
// Bones are then chained through the rig hierarchy, and each bone's change from rest is converted to glTF axes:
//   gltf = (x, z, -y).
// Head motion (optional, degrees): yaw > 0 turns toward the character's left, pitch > 0 lifts the chin, roll > 0
// tilts toward the left shoulder. In the rig the character faces +Y with +Z up and its left at -X; the turn is shared
// out over Neck, Neck1 and Head (the face rig's own neck poses don't turn the head; in the game the body does).
import * as THREE from "three";

const C = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1); // RED -> glTF
const Cinv = C.clone().invert();
const IDENTITY = new THREE.Quaternion();

export class FaceSolver {
  constructor(pack) {
    this.tracks = pack.tracks;
    this.trackIndex = new Map(pack.tracks.map((n, i) => [n, i]));
    this.reference = pack.referenceTracks || [];
    // The dialogue lipsync layer ("<pose>LipsyncPoseOutput") adds onto the base pose track.
    this.layer = [];
    pack.tracks.forEach((n, i) => {
      if (n.endsWith("LipsyncPoseOutput")) {
        const base = this.trackIndex.get(n.slice(0, -"LipsyncPoseOutput".length));
        if (base !== undefined) this.layer.push([i, base]);
      }
    });
    const b = pack.bones;
    this.boneNames = b.names;
    this.boneIndex = new Map(b.names.map((n, i) => [n, i]));
    this.parents = b.parents;
    this.restT = b.t.map((t) => new THREE.Vector3(...t));
    this.restR = b.r.map((r) => new THREE.Quaternion(...r));
    const n = b.names.length;
    this.restWorld = [];
    this.restWorldInv = [];
    for (let i = 0; i < n; i++) {
      const L = new THREE.Matrix4().compose(this.restT[i], this.restR[i], new THREE.Vector3(1, 1, 1));
      const W = this.parents[i] >= 0 ? this.restWorld[this.parents[i]].clone().multiply(L) : L;
      this.restWorld.push(W);
      this.restWorldInv.push(W.clone().invert());
    }
    this.parts = Object.values(pack.parts).map((p) => ({
      main: p.main,
      poses: p.poses.map((list) => list.map((t) => ({ bone: t[0], q: new THREE.Quaternion(t[1], t[2], t[3], t[4]), t: new THREE.Vector3(t[5], t[6], t[7]) }))),
      correctives: p.correctives.map((c) => ({
        drivers: c.drivers,
        pose: c.pose.map((t) => ({ bone: t[0], q: new THREE.Quaternion(t[1], t[2], t[3], t[4]), t: new THREE.Vector3(t[5], t[6], t[7]) })),
      })),
    }));
    this.dT = Array.from({ length: n }, () => new THREE.Vector3());
    this.dR = Array.from({ length: n }, () => new THREE.Quaternion());
    this.world = Array.from({ length: n }, () => new THREE.Matrix4());
    this.deform = Array.from({ length: n }, () => new THREE.Matrix4());
    this.bindWorld = this.restWorld.map((W) => W.clone()); // the rig as built; meshes are bound to this
    this.baseT = this.restT.map((t) => t.clone());
    this.baseR = this.restR.map((r) => r.clone());
    this.restWorldQ = this.restWorld.map((W) => new THREE.Quaternion().setFromRotationMatrix(W));
    this.headBones = [["Neck", 0.3], ["Neck1", 0.3], ["Head", 0.4]]
      .map(([name, share]) => [this.boneIndex.get(name), share]).filter(([i]) => i !== undefined);
    this.v = new Float32Array(pack.tracks.length);
    this.slotW = new Map();
    this._q = new THREE.Quaternion();
    this._m = new THREE.Matrix4();
    this._s = new THREE.Vector3(1, 1, 1);
  }

  apply(pose, w) {
    for (const x of pose) {
      this._q.slerpQuaternions(IDENTITY, x.q, w);
      this.dR[x.bone].multiply(this._q);
      this.dT[x.bone].addScaledVector(x.t, w);
    }
  }

  // Character-creator face options move face joints: offsets = Map(boneIndex -> [tx, ty, tz, qx, qy, qz, qw]), a
  // world-space change from the bind pose (REDengine axes). Rebuilds the rest pose, so every face pose works around
  // the joints' new places. An empty map restores the rig as built.
  setRestOffsets(offsets) {
    const n = this.boneNames.length;
    const world = [];
    const m = new THREE.Matrix4();
    for (let i = 0; i < n; i++) {
      const o = offsets.get(i);
      world.push(o ? m.compose(new THREE.Vector3(o[0], o[1], o[2]), new THREE.Quaternion(o[3], o[4], o[5], o[6]), this._s).clone().multiply(this.bindWorld[i])
                   : this.bindWorld[i].clone());
    }
    for (let i = 0; i < n; i++) {
      if (!offsets.size) { this.restT[i].copy(this.baseT[i]); this.restR[i].copy(this.baseR[i]); }
      else {
        const p = this.parents[i];
        const local = p >= 0 ? world[p].clone().invert().multiply(world[i]) : world[i].clone();
        local.decompose(this.restT[i], this.restR[i], new THREE.Vector3());
      }
      this.restWorld[i].copy(world[i]);
      this.restWorldInv[i].copy(world[i]).invert();
      this.restWorldQ[i].setFromRotationMatrix(world[i]);
    }
  }

  // Turn the neck and head by {yaw, pitch, roll} degrees, shared out over the neck bones (split: {Neck: 0.3, ...}).
  turnHead(head, split) {
    const d = THREE.MathUtils.DEG2RAD;
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler((head.pitch || 0) * d, -(head.roll || 0) * d, (head.yaw || 0) * d, "ZXY"));
    const bones = split ? Object.entries(split).map(([n, s]) => [this.boneIndex.get(n), s]).filter(([i]) => i !== undefined) : this.headBones;
    for (const [i, share] of bones) {
      const part = new THREE.Quaternion().slerpQuaternions(IDENTITY, q, share);
      // a turn about the bone's own pivot, in its rest frame: Wrest^-1 * q * Wrest
      const local = this.restWorldQ[i].clone().invert().multiply(part).multiply(this.restWorldQ[i]);
      this.dR[i].multiply(local);
    }
  }

  // values: Float32Array of track values (absolute); head: optional {yaw, pitch, roll} in degrees.
  // Returns per-bone deformation matrices in glTF space.
  solve(values, head, split) {
    const v = this.v;
    v.set(values);
    for (const [layer, base] of this.layer) v[base] = v[base] + v[layer];
    for (let i = 0; i < v.length; i++) v[i] = Math.min(1, Math.max(0, v[i]));
    for (let i = 0; i < this.dT.length; i++) { this.dT[i].set(0, 0, 0); this.dR[i].identity(); }
    this.slotW.clear();
    this.active = [];

    for (const part of this.parts) {
      for (const m of part.main) {
        const val = v[m.track];
        const ws = new Array(m.at.length).fill(0);
        if (val > 1e-5) {
          let prev = 0;
          for (let k = 0; k < m.at.length; k++) {
            const p = m.at[k];
            if (val <= p || k === m.at.length - 1) {
              const f = Math.min(1, (val - prev) / (p - prev || 1));
              ws[k] = f;
              if (k > 0) ws[k - 1] = 1 - f;
              break;
            }
            prev = p;
          }
          for (let k = 0; k < ws.length; k++) if (ws[k] > 1e-5) this.apply(part.poses[m.poses[k]], ws[k]);
          this.active.push([m.track, val]);
        }
        this.slotW.set(m.track, ws);
      }
      for (const c of part.correctives) {
        let w = 1;
        for (const d of c.drivers) {
          w *= d.slot === undefined ? v[d.track] : ((this.slotW.get(d.track) || [])[d.slot] || 0);
          if (w < 1e-5) break;
        }
        if (w >= 1e-5) this.apply(c.pose, w);
      }
    }
    if (head) this.turnHead(head, split);

    for (let i = 0; i < this.dT.length; i++) {
      const t = this.dT[i].add(this.restT[i]);
      const r = this.dR[i].premultiply(this.restR[i]);
      this._m.compose(t, r, this._s);
      const p = this.parents[i];
      if (p >= 0) this.world[i].multiplyMatrices(this.world[p], this._m);
      else this.world[i].copy(this._m);
      // change from rest, in glTF axes: C * W * Wrest^-1 * C^-1
      this.deform[i].multiplyMatrices(C, this.world[i]).multiply(this.restWorldInv[i]).multiply(Cinv);
    }
    return this.deform;
  }
}

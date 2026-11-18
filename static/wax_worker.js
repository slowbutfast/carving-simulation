/**
 * Web Worker: off-thread volumetric wax subtraction + dirty-chunk meshing.
 *
 * Protocol
 *   -> { type: 'init', config }
 *   -> { type: 'path', poses: Float32Array(6N), rapid: Uint8Array(N), count }
 *   -> { type: 'seek', index }
 *   -> { type: 'reset' }
 *   <- { type: 'ready' | 'meshes' | 'status' | 'collision' }
 */

import { WaxSDFCore, DEFAULT_TOOL } from './wax_sdf_core.js';

let core = null;
let poses = null;
let rapid = null;
let count = 0;
let current = 0;
let snapshots = [];
let snapshotEvery = 1000;
let faulted = false;
let lastCheckShank = -1;

function post(message, transfer = []) {
  self.postMessage(message, transfer);
}

function poseAt(index) {
  const offset = index * 6;
  const axis = [
    poses[offset + 3],
    poses[offset + 4],
    poses[offset + 5],
  ];
  const length = Math.hypot(axis[0], axis[1], axis[2]) || 1;
  return {
    tip: [poses[offset], poses[offset + 1], poses[offset + 2]],
    axis: [axis[0] / length, axis[1] / length, axis[2] / length],
  };
}

function meshPayload() {
  const meshes = core.meshDirtyChunks();
  core.clearDirty();
  const transfer = [];
  for (const mesh of meshes) {
    transfer.push(mesh.positions.buffer, mesh.normals.buffer, mesh.indices.buffer);
  }
  return { meshes, transfer };
}

function snapshotAt(index) {
  snapshots.push({ index, data: core.snapshot() });
  snapshots.sort((a, b) => a.index - b.index);
  // Keep at most five snapshots (~40 MiB at 128^3).
  while (snapshots.length > 5) snapshots.splice(1, 1);
}

function restoreNearest(index) {
  let best = null;
  for (const snapshot of snapshots) {
    if (snapshot.index <= index && (!best || snapshot.index > best.index)) best = snapshot;
  }
  if (!best) return 0;
  core.restore(best.data);
  snapshots = snapshots.filter((snapshot) => snapshot.index <= best.index);
  current = best.index;
  faulted = false;
  return best.index;
}

function carveForward(target) {
  const limit = Math.min(target, count - 1);
  const threshold = -0.5 * core.voxelSize;
  for (let index = current + 1; index <= limit; index++) {
    const pose = poseAt(index);
    const previous = poseAt(index - 1);
    if (rapid && rapid[index]) {
      const result = core.checkRapid(previous, pose, DEFAULT_TOOL);
      if (result.collision) {
        core.lastCollision = result;
        post({ type: 'collision', code: 'RAPID_COLLISION', index, sdf: result.sdf });
        faulted = true;
        current = index;
        return index;
      }
    } else {
      // The unheated shank is checked on tilted finishing poses; vertical
      // roughing plunges sit inside the roughing allowance shell by design.
      const tilted = Math.abs(pose.axis[2]) < 0.98;
      if (tilted && index - lastCheckShank >= 4) {
        lastCheckShank = index;
        const shank = core.checkShank(pose, DEFAULT_TOOL);
        if (shank.collision) {
          post({ type: 'collision', code: 'SHANK_COLLISION', index, sdf: shank.sdf });
          faulted = true;
          current = index;
          return index;
        }
      }
      core.subtractTool(pose, DEFAULT_TOOL, { includeShank: false });
      if (index % snapshotEvery === 0) snapshotAt(index);
    }
    current = index;
    if (index % 5000 === 0) {
      const { meshes, transfer } = meshPayload();
      post(
        { type: 'meshes', index, frames: count, meshes, reason: 'progress', faulted },
        transfer
      );
    }
  }
  return current;
}

function flush(index, reason = 'seek') {
  const { meshes, transfer } = meshPayload();
  post(
    {
      type: 'meshes',
      index,
      frames: count,
      meshes,
      reason,
      faulted,
    },
    transfer
  );
}

self.onmessage = (event) => {
  const data = event.data || {};
  if (data.type === 'init') {
    const stock = data.config.stock || {};
    core = new WaxSDFCore({
      R_stock: stock.R_stock_mm ?? 40,
      H_stock: stock.H_stock_mm ?? 120,
      gridN: data.gridN ?? 128,
      chunkSize: data.chunkSize ?? 16,
    });
    const { meshes, transfer } = meshPayload();
    post(
      {
        type: 'ready',
        voxelSize: core.voxelSize,
        chunksPerAxis: core.chunksPerAxis,
        meshes,
        gridN: core.N,
      },
      transfer
    );
    return;
  }

  if (data.type === 'path') {
    poses = data.poses;
    rapid = data.rapid;
    count = data.count;
    current = 0;
    snapshots = [];
    faulted = false;
    lastCheckShank = -1;
    snapshotEvery = Math.max(500, Math.ceil(count / 12));
    if (core) {
      core._initialize();
      core.modified = false;
      snapshotAt(0);
      const { meshes, transfer } = meshPayload();
      post({ type: 'status', index: 0, frames: count, voxelSize: core.voxelSize });
      post({ type: 'meshes', index: 0, frames: count, meshes, reason: 'reset' }, transfer);
    }
    return;
  }

  if (!core || !poses) return;

  if (data.type === 'seek') {
    const target = Math.max(0, Math.min(count - 1, Math.floor(data.index)));
    if (target < current) {
      restoreNearest(target);
    }
    if (!faulted) {
      const carved = carveForward(target);
      flush(carved, data.reason || 'seek');
      post({ type: 'status', index: carved, frames: count });
    }
    return;
  }

  if (data.type === 'reset') {
    core._initialize();
    core.modified = false;
    current = 0;
    snapshots = [];
    faulted = false;
    lastCheckShank = -1;
    if (count > 0) snapshotAt(0);
    flush(0, 'reset');
    return;
  }
};

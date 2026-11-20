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

/** Map backend blade config (mm) onto the SDF core's tool units. */
function toolFromConfig(configTool) {
  const source = configTool || {};
  const positive = (configKey, fallback) => {
    const value = Number(source[configKey]);
    return Number.isFinite(value) && value > 0 ? value : fallback;
  };
  const span = (configKey, fallback) => {
    const value = source[configKey];
    if (Array.isArray(value) && value.length === 2) {
      const lo = Number(value[0]);
      const hi = Number(value[1]);
      if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) return [lo, hi];
    }
    return fallback;
  };
  const bladeLength = positive('blade_length_mm', DEFAULT_TOOL.bladeLength);
  const heated = positive('heated_length_mm', bladeLength);
  const kerf = Number(source.melt_kerf_mm);
  const envelope = source.head_envelope || {};
  const center = Array.isArray(envelope.center_mm) ? envelope.center_mm : null;
  const half = Array.isArray(envelope.half_extents_mm) ? envelope.half_extents_mm : null;
  return {
    bladeThickness: positive('blade_thickness_mm', DEFAULT_TOOL.bladeThickness),
    bladeWidth: positive('blade_width_mm', DEFAULT_TOOL.bladeWidth),
    bladeLength,
    heatedLength: Math.min(heated, bladeLength),
    meltKerf: Number.isFinite(kerf) && kerf >= 0 ? kerf : DEFAULT_TOOL.meltKerf,
    shaftRadius: positive('shaft_radius_mm', DEFAULT_TOOL.shaftRadius),
    shaftSpan: span('shaft_span_mm', DEFAULT_TOOL.shaftSpan),
    bodyRadius: positive('body_radius_mm', DEFAULT_TOOL.bodyRadius),
    bodySpan: span('body_span_mm', DEFAULT_TOOL.bodySpan),
    headClearance: positive('head_clearance_mm', DEFAULT_TOOL.headClearance),
    headEnvelope:
      center && half
        ? { shape: envelope.shape || 'box', center: [...center], halfExtents: [...half] }
        : DEFAULT_TOOL.headEnvelope,
  };
}

let core = null;
let workerTool = { ...DEFAULT_TOOL };
let poses = null;
let rapid = null;
let count = 0;
let poseStride = 6;
let current = 0;
let snapshots = [];
let snapshotEvery = 1000;
let faulted = false;
const MAX_SNAPSHOTS = 5;

function post(message, transfer = []) {
  self.postMessage(message, transfer);
}

function poseAt(index) {
  const offset = index * poseStride;
  const axis = [
    poses[offset + 3],
    poses[offset + 4],
    poses[offset + 5],
  ];
  const length = Math.hypot(axis[0], axis[1], axis[2]) || 1;
  return {
    tip: [poses[offset], poses[offset + 1], poses[offset + 2]],
    axis: [axis[0] / length, axis[1] / length, axis[2] / length],
    theta: poseStride >= 7 ? poses[offset + 6] : 0,
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
  if (snapshots.length > MAX_SNAPSHOTS) {
    // Even thinning: keep the oldest and newest and drop every other interior
    // snapshot so scrub coverage stays spread over the whole timeline instead
    // of bunching near the end.
    snapshots = snapshots.filter(
      (snapshot, position) =>
        position === 0 ||
        position === snapshots.length - 1 ||
        position % 2 === 0
    );
  }
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
      const result = core.checkRapid(previous, pose, workerTool);
      if (result.collision) {
        core.lastCollision = result;
        post({
          type: 'collision',
          code: 'RAPID_COLLISION',
          index,
          body: result.body,
          sdf: result.sdf,
        });
        faulted = true;
        current = index;
        return index;
      }
    } else {
      // The unheated shaft, cartridge body and tilt-head envelope are checked
      // on every cutting frame: a vertical plunge can bury them in uncarved
      // stock just as a tilted pass can.
      const shank = core.checkShank(pose, workerTool);
      if (shank.collision) {
        post({
          type: 'collision',
          code: 'SHANK_COLLISION',
          index,
          body: shank.body,
          sdf: shank.sdf,
        });
        faulted = true;
        current = index;
        return index;
      }
      core.subtractTool(pose, workerTool, { includeShank: false });
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
    workerTool = toolFromConfig(data.config.tool);
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
        tool: workerTool,
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
    poseStride = Number(data.stride) === 7 ? 7 : 6;
    current = 0;
    snapshots = [];
    faulted = false;
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
    if (count > 0) snapshotAt(0);
    flush(0, 'reset');
    return;
  }
};

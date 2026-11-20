/**
 * Web Worker: off-thread volumetric wax subtraction + dirty-chunk meshing.
 *
 * Protocol
 *   -> { type: 'init', config, gridN, chunkSize }
 *   -> { type: 'path', poses: Float32Array(7N), rapid: Uint8Array(N), count, stride, auditAll }
 *   -> { type: 'seek', index, reason }
 *   -> { type: 'audit', enabled }
 *   -> { type: 'reset' }
 *   <- { type: 'ready' | 'meshes' | 'status' | 'collision' | 'collisions' }
 *
 * The carve itself lives in `carveRange` (`wax_sdf_core.js`) so the headless
 * `scripts/audit_collisions.mjs` audits exactly the loop the viewer runs.
 */

import { WaxSDFCore, DEFAULT_TOOL, carveRange, truncateRuns, toolFromConfig } from './wax_sdf_core.js';

let core = null;
let workerTool = { ...DEFAULT_TOOL };
let poses = null;
let rapid = null;
let count = 0;
let poseStride = 6;
let poseCache = [];
let current = 0;
let snapshots = [];
let snapshotEvery = 1000;
let faulted = false;
let auditAll = false;
let collisionRuns = [];
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

/** Materialise the flat pose columns once; `carveRange` reads objects. */
function buildPoseCache() {
  poseCache = new Array(count);
  for (let index = 0; index < count; index += 1) poseCache[index] = poseAt(index);
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
  // The wax is rewound, so a run that straddles the snapshot did not happen in
  // full any more; runs past it will be re-carved (and re-logged).
  collisionRuns = truncateRuns(collisionRuns, best.index);
  current = best.index;
  faulted = false;
  return best.index;
}

/**
 * Append a run to the log, joining it to the previous one when the chunked
 * carve split a single contiguous collision across two `carveRange` calls.
 */
function mergeRun(run) {
  const previous = collisionRuns[collisionRuns.length - 1];
  if (
    previous &&
    previous.code === run.code &&
    previous.body === run.body &&
    previous.post_fault === run.post_fault &&
    previous.frame_range[1] === run.frame_range[0] - 1
  ) {
    previous.frame_range = [previous.frame_range[0], run.frame_range[1]];
    previous.frames += run.frames;
    if (run.worst_sdf_mm < previous.worst_sdf_mm) {
      previous.worst_sdf_mm = run.worst_sdf_mm;
      previous.worst_frame = run.worst_frame;
      previous.pose = run.pose;
    }
    return previous;
  }
  collisionRuns.push(run);
  return run;
}

/** A snapshot, not the live array: later merges must not rewrite old messages. */
function runsSnapshot() {
  return collisionRuns.map((run) => ({ ...run }));
}

function postCollisions() {
  if (!auditAll) return;
  post({ type: 'collisions', runs: runsSnapshot(), auditAll: true });
}

function carveForward(target) {
  const limit = Math.min(target, count - 1);
  while (current < limit) {
    // Hand `carveRange` at most one snapshot interval so the snapshot cadence
    // and the progress meshes stay where the viewer expects them.  The boundary
    // calculation keeps those intervals aligned with `index % snapshotEvery`.
    let step = Math.min(limit, current + snapshotEvery);
    const boundary = Math.floor(current / snapshotEvery + 1) * snapshotEvery;
    if (boundary > current && boundary < step) step = boundary;

    const result = carveRange(core, poseCache, rapid, workerTool, {
      from: current,
      to: step,
      auditAll,
    });

    for (const run of result.runs) {
      const stored = mergeRun(run);
      post({
        type: 'collision',
        code: stored.code,
        index: stored.worst_frame,
        body: stored.body,
        sdf: stored.worst_sdf_mm,
        pose: stored.pose,
        frame_range: stored.frame_range,
        post_fault: stored.post_fault,
      });
    }

    current = result.current;
    faulted = faulted || result.faulted;
    if (current === step && step > 0 && step % snapshotEvery === 0) snapshotAt(step);
    if (current === step && step > 0 && step % 5000 === 0) {
      const { meshes, transfer } = meshPayload();
      post(
        {
          type: 'meshes',
          index: step,
          frames: count,
          meshes,
          reason: 'progress',
          faulted: faulted && !auditAll,
          auditAll,
        },
        transfer
      );
    }
    if (!auditAll && result.faulted) break;
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
      faulted: faulted && !auditAll,
      auditAll,
      runs: auditAll ? runsSnapshot() : [],
    },
    transfer
  );
}

/** Back to an uncarved stock at frame 0 (path reset, reset, audit toggle). */
function resetCarve() {
  if (core) {
    core._initialize();
    core.modified = false;
  }
  current = 0;
  snapshots = [];
  collisionRuns = [];
  faulted = false;
  if (count > 0) snapshotAt(0);
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
        auditAll,
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
    if (typeof data.auditAll === 'boolean') auditAll = data.auditAll;
    buildPoseCache();
    snapshotEvery = Math.max(500, Math.ceil(count / 12));
    resetCarve();
    if (core) {
      const { meshes, transfer } = meshPayload();
      post({ type: 'status', index: 0, frames: count, voxelSize: core.voxelSize, auditAll });
      post(
        {
          type: 'meshes',
          index: 0,
          frames: count,
          meshes,
          reason: 'reset',
          faulted: faulted && !auditAll,
          auditAll,
          runs: [],
        },
        transfer
      );
    }
    return;
  }

  if (!core || !poses) return;

  if (data.type === 'audit') {
    const enabled = Boolean(data.enabled);
    if (enabled === auditAll) {
      postCollisions();
      return;
    }
    auditAll = enabled;
    // Toggling mid-playback changes what was carved (audit mode keeps going
    // through collisions), so the only honest state is an uncarved frame 0.
    resetCarve();
    flush(0, 'reset');
    postCollisions();
    post({ type: 'status', index: 0, frames: count, voxelSize: core.voxelSize, auditAll });
    return;
  }

  if (data.type === 'seek') {
    const target = Math.max(0, Math.min(count - 1, Math.floor(data.index)));
    if (target < current) {
      restoreNearest(target);
      // Expose the truncated run list at once: everything past the snapshot did
      // not happen any more, so the viewer must stop showing it.
      postCollisions();
    }
    if (!faulted || auditAll) {
      const carved = carveForward(target);
      flush(carved, data.reason || 'seek');
      post({ type: 'status', index: carved, frames: count, auditAll });
      postCollisions();
    }
    return;
  }

  if (data.type === 'reset') {
    resetCarve();
    flush(0, 'reset');
    postCollisions();
    return;
  }
};

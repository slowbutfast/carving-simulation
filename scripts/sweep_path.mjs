/**
 * Integrated 128^3 path-safety sweep (PATCH-10c, handoff §5 step 6).
 *
 * Replays a generated Python trajectory through the production SDF core:
 *   - every rapid segment is checked with `checkRapid`,
 *   - every cutting frame is checked with `checkShank` (no `tilted` gate),
 *   - every cutting frame is subtracted into the current stock.
 *
 * Usage:
 *   .venv/bin/python scripts/sweep_path.py --preset demo --out /tmp/path.json
 *   node scripts/sweep_path.mjs /tmp/path.json
 */

import fs from 'node:fs';
import assert from 'node:assert/strict';

import { WaxSDFCore, DEFAULT_TOOL } from '../static/wax_sdf_core.js';

function poseAt(poses, index) {
  const offset = index * 6;
  const axis = [poses[offset + 3], poses[offset + 4], poses[offset + 5]];
  const length = Math.hypot(axis[0], axis[1], axis[2]) || 1;
  return {
    tip: [poses[offset], poses[offset + 1], poses[offset + 2]],
    axis: [axis[0] / length, axis[1] / length, axis[2] / length],
  };
}

const file = process.argv[2];
assert.ok(file, 'usage: node scripts/sweep_path.mjs <path.json>');
const payload = JSON.parse(fs.readFileSync(file, 'utf8'));
const poses = new Float32Array(payload.poses);
const rapid = new Uint8Array(payload.rapid);
const count = payload.count;
assert.equal(poses.length, count * 6, 'pose buffer length');
assert.equal(rapid.length, count, 'rapid buffer length');

const configTool = payload.tool || {};
const tool = {
  ...DEFAULT_TOOL,
  tipRadius: configTool.tip_radius_mm ?? DEFAULT_TOOL.tipRadius,
  coneHalfAngleDeg: configTool.cone_half_angle_deg ?? DEFAULT_TOOL.coneHalfAngleDeg,
  engagedLength: configTool.engaged_length_mm ?? DEFAULT_TOOL.engagedLength,
  meltKerf: configTool.melt_kerf_mm ?? DEFAULT_TOOL.meltKerf,
  shankRadius: configTool.shank_radius_mm ?? DEFAULT_TOOL.shankRadius,
  shankLength: configTool.shank_length_mm ?? DEFAULT_TOOL.shankLength,
};
const started = Date.now();
const core = new WaxSDFCore({
  R_stock: payload.stock.R_stock_mm,
  H_stock: payload.stock.H_stock_mm,
  gridN: payload.gridN ?? 128,
  chunkSize: 16,
});

let rapidHits = 0;
let shankHits = 0;
let cuttingChecked = 0;
let first = null;
for (let index = 1; index < count; index += 1) {
  const pose = poseAt(poses, index);
  const previous = poseAt(poses, index - 1);
  if (rapid[index]) {
    const result = core.checkRapid(previous, pose, tool);
    if (result.collision) {
      rapidHits += 1;
      first = first ?? { stage: 'rapid', index, sdf: result.sdf, point: pose.tip };
    }
    continue;
  }
  // Every cutting frame, regardless of tilt.
  const shank = core.checkShank(pose, tool);
  cuttingChecked += 1;
  if (shank.collision) {
    shankHits += 1;
    first = first ?? { stage: 'shank', index, sdf: shank.sdf, point: pose.tip };
  }
  core.subtractTool(pose, tool, { includeShank: false });
}

const report = {
  preset: payload.preset,
  grid: `${core.N}^3`,
  frames: count,
  cuttingChecked,
  rapidHits,
  shankHits,
  first,
  ms: Date.now() - started,
};
console.log(JSON.stringify(report));
if (rapidHits !== 0 || shankHits !== 0) process.exitCode = 1;

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

function poseAt(poses, index, stride) {
  const offset = index * stride;
  const axis = [poses[offset + 3], poses[offset + 4], poses[offset + 5]];
  const length = Math.hypot(axis[0], axis[1], axis[2]) || 1;
  return {
    tip: [poses[offset], poses[offset + 1], poses[offset + 2]],
    axis: [axis[0] / length, axis[1] / length, axis[2] / length],
    theta: stride >= 7 ? poses[offset + 6] : 0,
  };
}

const file = process.argv[2];
assert.ok(file, 'usage: node scripts/sweep_path.mjs <path.json>');
const payload = JSON.parse(fs.readFileSync(file, 'utf8'));
const poses = new Float32Array(payload.poses);
const rapid = new Uint8Array(payload.rapid);
const count = payload.count;
const stride = Number(payload.stride) === 7 ? 7 : 6;
assert.equal(poses.length, count * stride, 'pose buffer length');
assert.equal(rapid.length, count, 'rapid buffer length');

const configTool = payload.tool || {};
const positive = (key, fallback) => {
  const value = Number(configTool[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
};
const span = (key, fallback) => {
  const value = configTool[key];
  if (Array.isArray(value) && value.length === 2) return [Number(value[0]), Number(value[1])];
  return fallback;
};
const bladeLength = positive('blade_length_mm', DEFAULT_TOOL.bladeLength);
const tool = {
  ...DEFAULT_TOOL,
  bladeThickness: positive('blade_thickness_mm', DEFAULT_TOOL.bladeThickness),
  bladeWidth: positive('blade_width_mm', DEFAULT_TOOL.bladeWidth),
  bladeLength,
  heatedLength: Math.min(positive('heated_length_mm', bladeLength), bladeLength),
  meltKerf: Number.isFinite(Number(configTool.melt_kerf_mm))
    ? Number(configTool.melt_kerf_mm)
    : DEFAULT_TOOL.meltKerf,
  shaftRadius: positive('shaft_radius_mm', DEFAULT_TOOL.shaftRadius),
  shaftSpan: span('shaft_span_mm', DEFAULT_TOOL.shaftSpan),
  bodyRadius: positive('body_radius_mm', DEFAULT_TOOL.bodyRadius),
  bodySpan: span('body_span_mm', DEFAULT_TOOL.bodySpan),
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
  const pose = poseAt(poses, index, stride);
  const previous = poseAt(poses, index - 1, stride);
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

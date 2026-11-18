import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  WaxSDFCore,
  DEFAULT_TOOL,
  cylinderSDF,
  maxEngagedDisplacement,
} from '../static/wax_sdf_core.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function core48(overrides = {}) {
  return new WaxSDFCore({
    R_stock: 20,
    H_stock: 40,
    gridN: 48,
    chunkSize: 16,
    ...overrides,
  });
}

function pose(tip, axis) {
  return { tip, axis };
}

function edgeCounts(mesh) {
  const counts = new Map();
  const idx = mesh.indices;
  for (let f = 0; f < idx.length; f += 3) {
    const tri = [idx[f], idx[f + 1], idx[f + 2]];
    for (let e = 0; e < 3; e++) {
      const a = tri[e];
      const b = tri[(e + 1) % 3];
      const key = a < b ? `${a}:${b}` : `${b}:${a}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}

test('exact Euclidean cylinder SDF is initialized with exterior padding', () => {
  const core = core48();
  assert.ok(core.voxelSize > 0);
  assert.ok(core.origin.x < -20);
  assert.ok(core.origin.y < -20);
  assert.ok(core.origin.z < 0);
  const eps = 1e-4;
  assert.ok(Math.abs(core.query(0, 0, 20) + 20) < eps);
  assert.ok(Math.abs(core.query(25, 0, 20) - 5) < eps);
  // far outside the cylinder: radial distance dominates
  assert.ok(Math.abs(core.query(25, 0, 55) - Math.hypot(5, 15)) < 0.05);
  // analytic helper agrees with the stored field away from the tool
  const analytic = cylinderSDF(0, 0, 20, 20, 40);
  assert.ok(Math.abs(analytic + 20) < eps);
});

test('undercut subtraction crosses chunk boundaries, dirties neighbors, preserves overhang, and meshes watertight', () => {
  const core = core48();
  const v = core.voxelSize;
  const boundaryX = core.origin.x + 16 * v;
  const tool = {
    ...DEFAULT_TOOL,
    tipRadius: 0.6,
    coneHalfAngleDeg: 30,
    engagedLength: 8,
    meltKerf: 0.3,
    shankRadius: 2.0,
    shankLength: 20,
  };
  // Horizontal tool: tip just right of the chunk boundary, body pointing -X.
  core.subtractTool(pose([boundaryX + 3, 0, 20], [1, 0, 0]), tool, { includeShank: true });

  const left = boundaryX - 3;
  const right = boundaryX + 2;
  assert.ok(core.query(left, 0, 20) > 0, 'cavity carved on the left of the boundary');
  assert.ok(core.query(right, 0, 20) > 0, 'cavity carved on the right of the boundary');
  assert.ok(core.query(left, 0, 31) < 0, 'material above the undercut is preserved');

  const dirty = new Set(core.dirtyChunkIndices());
  const chunkAt = (x) => {
    const ci = Math.floor((x - core.origin.x) / v / core.chunkSize);
    const cj = Math.floor((0 - core.origin.y) / v / core.chunkSize);
    const ck = Math.floor((20 - core.origin.z) / v / core.chunkSize);
    return (ck * core.chunksPerAxis + cj) * core.chunksPerAxis + ci;
  };
  assert.ok(dirty.has(chunkAt(boundaryX - 2)), 'left chunk dirty');
  assert.ok(dirty.has(chunkAt(boundaryX + 2)), 'right chunk dirty');

  const mesh = core.meshAll();
  assert.ok(mesh.indices.length > 0);
  const counts = edgeCounts(mesh);
  let boundaryEdges = 0;
  for (const count of counts.values()) {
    if (count !== 2) boundaryEdges += 1;
  }
  assert.equal(boundaryEdges, 0, 'marching cubes output is a closed 2-manifold (no seams)');
});

test('rapid through a carved pocket succeeds while uncarved rapid raises RAPID_COLLISION', () => {
  const core = core48();
  const tool = {
    ...DEFAULT_TOOL,
    tipRadius: 1.0,
    coneHalfAngleDeg: 20,
    engagedLength: 4,
    meltKerf: 0,
    shankRadius: 3,
    shankLength: 32,
  };
  // Clear a vertical pocket through the top of the stock.  Carve with a
  // slightly oversized shank so the clearance check is not fooled by the
  // half-voxel SDF interpolation band at the cavity wall.
  core.subtractTool(pose([0, 0, 10], [0, 0, -1]), { ...tool, shankRadius: 4 }, { includeShank: true });

  const clean = core.checkRapid(
    pose([0, 0, 16], [0, 0, -1]),
    pose([0, 0, 18], [0, 0, -1]),
    tool
  );
  assert.equal(clean.collision, false, JSON.stringify(clean));

  const crash = core.checkRapid(
    pose([10, 0, 16], [0, 0, -1]),
    pose([10, 0, 20], [0, 0, -1]),
    tool
  );
  assert.equal(crash.collision, true);
  assert.equal(crash.code, 'RAPID_COLLISION');
});

test('unheated shank entering uncarved stock raises SHANK_COLLISION', () => {
  const core = core48();
  const tool = { ...DEFAULT_TOOL, engagedLength: 4, shankRadius: 3, shankLength: 20 };
  const unsafe = core.checkShank(pose([0, 0, 35], [0.9, 0, -0.435]), tool);
  assert.equal(unsafe.collision, true);
  assert.equal(unsafe.code, 'SHANK_COLLISION');

  const safe = core.checkShank(pose([0, 0, 45], [0, 0, -1]), tool);
  assert.equal(safe.collision, false);
});

test('snapshot restore and replay match sequential subtraction exactly', () => {
  const core = core48();
  const tool = { ...DEFAULT_TOOL, engagedLength: 4, shankRadius: 2, shankLength: 10 };
  const first = [
    pose([0, 0, 25], [0, 0, -1]),
    pose([3, 0, 24], [0, 0, -1]),
    pose([6, 0, 23], [0.2, 0, -1]),
  ];
  const second = [
    pose([9, 0, 22], [0.3, 0, -1]),
    pose([12, 0, 21], [0, 0, -1]),
  ];
  for (const p of first) core.subtractTool(p, tool);
  const snapshot = core.snapshot();
  assert.ok(snapshot instanceof Float32Array);
  const atSnapshot = core.data.slice();

  for (const p of second) core.subtractTool(p, tool);
  const afterAll = core.data.slice();
  assert.notDeepEqual(Array.from(core.data), Array.from(atSnapshot));

  core.restore(snapshot);
  assert.deepEqual(Array.from(core.data), Array.from(atSnapshot));
  for (const p of second) core.subtractTool(p, tool);
  assert.deepEqual(Array.from(core.data), Array.from(afterAll));
});

test('carved SDF surface stays within 2 voxels of the reachable target floor', () => {
  const core = new WaxSDFCore({
    R_stock: 20,
    H_stock: 40,
    gridN: 56,
    chunkSize: 16,
  });
  const tool = {
    ...DEFAULT_TOOL,
    tipRadius: 1.2,
    coneHalfAngleDeg: 15,
    engagedLength: 5,
    meltKerf: 0.2,
    shankRadius: 2,
    shankLength: 10,
  };
  const floorZ = 20;
  for (let r = 8; r <= 12.001; r += 0.8) {
    for (let t = 0; t < Math.PI * 2; t += (Math.PI * 2) / 48) {
      core.subtractTool(pose([r * Math.cos(t), r * Math.sin(t), floorZ], [0, 0, -1]), tool);
    }
  }
  const samples = [
    [9.4, 0.3],
    [10.1, 1.2],
    [10.8, 2.4],
    [11.3, 3.9],
    [9.0, 5.1],
  ];
  for (const [r, theta] of samples) {
    const x = r * Math.cos(theta);
    const y = r * Math.sin(theta);
    const above = core.query(x, y, floorZ + core.voxelSize);
    const below = core.query(x, y, floorZ - core.voxelSize);
    assert.ok(above > 0, `voxel above carved floor is empty (sdf=${above})`);
    assert.ok(below < 0, `voxel below carved floor is material (sdf=${below})`);
    // The zero crossing lies between the two probes, inside the 2-voxel band.
    const crossing =
      floorZ - core.voxelSize +
      (2 * core.voxelSize * -below) / (above - below);
    assert.ok(
      Math.abs(crossing - floorZ) <= 2 * core.voxelSize,
      `floor crossing ${crossing} is outside the 2-voxel band`
    );
  }
});

test('engaged-cone displacement helper bounds the swept tool', () => {
  const a = {
    tip_xyz_wax: [0, 0, 20],
    tool_axis_wax: [0, 0, -1],
  };
  const b = {
    tip_xyz_wax: [2, 0, 20],
    tool_axis_wax: [0.1, 0, -0.995],
  };
  const d = maxEngagedDisplacement(a, b, 8);
  assert.ok(d >= 2);
  assert.ok(d < 5);
});

test('machine rig and app contain no kinematic trig', () => {
  for (const rel of ['static/machine_rig.js', 'static/app.js']) {
    const source = fs.readFileSync(path.join(ROOT, rel), 'utf8');
    assert.equal(/Math\.(sin|cos)\s*\(/.test(source), false, `${rel} must not call Math.sin/Math.cos`);
  }
});

test('wax_sdf_core stays a pure JS module with no DOM or Three.js imports', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/wax_sdf_core.js'), 'utf8');
  assert.equal(/from\s+['"]three/.test(source), false);
  assert.equal(/\bdocument\./.test(source), false);
  assert.equal(/\bwindow\./.test(source), false);
});

test(
  'SDF performance benchmark (128^3 init, conical-bevel subtraction, dirty-chunk remesh)',
  { skip: !process.env.BENCH },
  () => {
    const core = new WaxSDFCore({ R_stock: 40, H_stock: 120, gridN: 128, chunkSize: 16 });
    const tool = { ...DEFAULT_TOOL };
    const carveTimes = [];
    let meshTimes = [];
    for (let i = 0; i < 20; i++) {
      const a = (i / 20) * Math.PI * 2;
      const p = pose([20 * Math.cos(a), 20 * Math.sin(a), 60 - i], [0, 0, -1]);
      const t0 = performance.now();
      core.subtractTool(p, tool);
      carveTimes.push(performance.now() - t0);
      const t1 = performance.now();
      const meshes = core.meshDirtyChunks();
      meshTimes.push(performance.now() - t1);
      assert.ok(meshes.length >= 0);
      core.clearDirty();
    }
    const avg = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
    console.log(
      JSON.stringify({
        grid: '128^3',
        voxelSize: core.voxelSize,
        carveAvgMs: avg(carveTimes),
        meshAvgMs: avg(meshTimes),
        combinedAvgMs: avg(carveTimes) + avg(meshTimes),
        projectedFps: 1000 / (avg(carveTimes) + avg(meshTimes)),
      })
    );
    assert.ok(core.voxelSize > 0.5);
  }
);

/**
 * Volumetric wax SDF core regression tests.
 *
 * Sign convention: the wax SDF is **negative inside** the remaining material
 * and positive inside a carved cavity, matching `tool_model.heated_sdf` and the
 * opposite of `trimesh.proximity.signed_distance`.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  WaxSDFCore,
  DEFAULT_TOOL,
  cylinderSDF,
  heatedSDF,
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

function pose(tip, axis, theta = 0) {
  return { tip, axis, theta };
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

/** Width of the positive (carved) interval along a straight scan line. */
function carvedSpan(core, from, to) {
  const step = core.voxelSize / 24;
  let count = 0;
  const length = Math.hypot(to[0] - from[0], to[1] - from[1], to[2] - from[2]);
  const samples = Math.ceil(length / step);
  for (let index = 0; index <= samples; index++) {
    const u = index / samples;
    const x = from[0] + (to[0] - from[0]) * u;
    const y = from[1] + (to[1] - from[1]) * u;
    const z = from[2] + (to[2] - from[2]) * u;
    if (core.query(x, y, z) > 0) count += 1;
  }
  return (count / (samples + 1)) * length;
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

test('default tool is the CAD blade prism, not the retired cone', () => {
  assert.equal(DEFAULT_TOOL.bladeThickness, 1.2);
  assert.equal(DEFAULT_TOOL.bladeWidth, 6.0);
  assert.equal(DEFAULT_TOOL.bladeLength, 14.0);
  assert.equal(DEFAULT_TOOL.heatedLength, 14.0);
  assert.equal(DEFAULT_TOOL.meltKerf, 0.4);
  assert.equal(DEFAULT_TOOL.shaftRadius, 2.5);
  assert.deepEqual([...DEFAULT_TOOL.shaftSpan], [14.0, 75.0]);
  assert.equal(DEFAULT_TOOL.bodyRadius, 3.5);
  assert.deepEqual([...DEFAULT_TOOL.bodySpan], [75.0, 140.0]);
  assert.deepEqual([...DEFAULT_TOOL.headEnvelope.center], [9.0, -3.375, 111.0]);
  assert.deepEqual([...DEFAULT_TOOL.headEnvelope.halfExtents], [20.0, 11.125, 61.0]);
  assert.equal('tipRadius' in DEFAULT_TOOL, false);
  assert.equal('coneHalfAngleDeg' in DEFAULT_TOOL, false);
});

test('heated blade SDF matches the analytic probes (negative inside)', () => {
  const kerf = DEFAULT_TOOL.meltKerf;
  // Reference point at the origin, phi = 0 so u = -Z and s runs along +Z.
  const p = pose([0, 0, 0], [0, 0, -1], 0);
  assert.ok(Math.abs(heatedSDF([0, 0, 0], p) + kerf) < 1e-9);
  assert.ok(Math.abs(heatedSDF([0.6 + kerf, 0, 7.0], p)) < 1e-9);
  assert.ok(Math.abs(heatedSDF([0, 3.0 + kerf + 1.0, 7.0], p) - 1.0) < 1e-9);
  assert.ok(Math.abs(heatedSDF([0, 0, -kerf - 2.0], p) - 2.0) < 1e-9);
  // The convention is explicit: the reference point is inside the inflated box.
  assert.ok(heatedSDF([0, 0, 0], p) < 0);
});

test('Python and JS heated SDF agree on the seeded 1000 x 20 fixture', () => {
  const fixturePath = path.join(ROOT, 'tests/fixtures/heated_sdf_parity.json');
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const tool = {
    bladeThickness: fixture.tool.blade_thickness_mm,
    bladeWidth: fixture.tool.blade_width_mm,
    heatedLength: fixture.tool.heated_length_mm,
    meltKerf: fixture.tool.melt_kerf_mm,
  };
  assert.equal(fixture.sign_convention, 'negative inside');
  let maxDiff = 0;
  for (let pi = 0; pi < fixture.poses.length; pi++) {
    const stored = fixture.poses[pi];
    const jsPose = { tip: stored.tip, axis: stored.u, theta: stored.theta };
    const expected = fixture.distances[pi];
    for (let qi = 0; qi < fixture.points.length; qi++) {
      const diff = Math.abs(heatedSDF(fixture.points[qi], jsPose, tool) - expected[qi]);
      if (diff > maxDiff) maxDiff = diff;
    }
  }
  assert.ok(
    maxDiff <= fixture.tolerance_mm,
    `max |Python - JS| = ${maxDiff} mm exceeds ${fixture.tolerance_mm} mm`
  );
});

test('undercut subtraction crosses chunk boundaries, dirties neighbors, preserves overhang, and meshes watertight', () => {
  const core = core48();
  const v = core.voxelSize;
  const boundaryX = core.origin.x + 16 * v;
  const tool = {
    ...DEFAULT_TOOL,
    bladeThickness: 1.2,
    bladeWidth: 6.0,
    heatedLength: 8.0,
    meltKerf: 0.3,
    shaftRadius: 2.0,
    shaftSpan: [8, 28],
    bodyRadius: 2.5,
    bodySpan: [28, 48],
  };
  // Horizontal tool: u = +X, so the blade extends from the tip toward -X and
  // straddles the chunk boundary.  Include the unheated bodies as in the old
  // undercut fixture.
  core.subtractTool(pose([boundaryX + 3, 0, 20], [1, 0, 0], 0), tool, {
    includeShank: true,
  });

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

test('blade kerf is direction-dependent: theta move carves thickness, r move carves width', () => {
  const core = new WaxSDFCore({ R_stock: 20, H_stock: 40, gridN: 64, chunkSize: 16 });
  const v = core.voxelSize;
  const kerf = DEFAULT_TOOL.meltKerf;
  const thetaWidth = DEFAULT_TOOL.bladeThickness + 2 * kerf; // 2.0 mm
  const radialWidth = DEFAULT_TOOL.bladeWidth + 2 * kerf; // 6.8 mm

  // theta move: u = -Z (phi = 0), a_w = +Y, motion along +e_theta = +Y.
  core.subtractSegment(
    pose([10, -10, 20], [0, 0, -1], 0),
    pose([10, 10, 20], [0, 0, -1], 0)
  );
  const acrossThickness = carvedSpan(core, [6, 0, 27], [14, 0, 27]);
  assert.ok(
    Math.abs(acrossThickness - thetaWidth) <= v,
    `theta slot ${acrossThickness.toFixed(3)} mm vs ${thetaWidth} ± ${v.toFixed(3)} mm`
  );

  // r move: same frame, motion along +e_r = +X.  The perpendicular scan is Y.
  const radialCore = new WaxSDFCore({ R_stock: 20, H_stock: 40, gridN: 64, chunkSize: 16 });
  radialCore.subtractSegment(
    pose([0, 0, 20], [0, 0, -1], 0),
    pose([20, 0, 20], [0, 0, -1], 0)
  );
  const acrossWidth = carvedSpan(radialCore, [10, -10, 27], [10, 10, 27]);
  assert.ok(
    Math.abs(acrossWidth - radialWidth) <= v,
    `r slot ${acrossWidth.toFixed(3)} mm vs ${radialWidth} ± ${v.toFixed(3)} mm`
  );
});

test('rapid through a carved pocket succeeds while uncarved rapid raises RAPID_COLLISION', () => {
  const core = core48();
  const tool = {
    ...DEFAULT_TOOL,
    bladeThickness: 1.2,
    bladeWidth: 6.0,
    heatedLength: 8.0,
    meltKerf: 0,
    shaftRadius: 3,
    shaftSpan: [8, 40],
    bodyRadius: 3.5,
    bodySpan: [40, 72],
  };
  // Clear a vertical pocket through the top of the stock with an oversized
  // blade and shank so the half-voxel interpolation band and the sampled
  // heated-region corners cannot fool the clearance check.
  core.subtractTool(
    pose([0, 0, 10], [0, 0, -1], 0),
    { ...tool, bladeThickness: 4, bladeWidth: 10, shaftRadius: 5 },
    { includeShank: true }
  );

  const clean = core.checkRapid(
    pose([0, 0, 16], [0, 0, -1], 0),
    pose([0, 0, 18], [0, 0, -1], 0),
    tool
  );
  assert.equal(clean.collision, false, JSON.stringify(clean));

  const crash = core.checkRapid(
    pose([10, 0, 16], [0, 0, -1], 0),
    pose([10, 0, 20], [0, 0, -1], 0),
    tool
  );
  assert.equal(crash.collision, true);
  assert.equal(crash.code, 'RAPID_COLLISION');
});

test('per-body shank diagnostics report shaft and head by name', () => {
  const shaftCore = new WaxSDFCore({ R_stock: 20, H_stock: 120, gridN: 48, chunkSize: 16 });
  const shaftCollision = shaftCore.checkShank(
    pose([0, 0, 10], [0, 0, -1], 0),
    DEFAULT_TOOL
  );
  assert.equal(shaftCollision.collision, true);
  assert.equal(shaftCollision.code, 'SHANK_COLLISION');
  assert.equal(shaftCollision.body, 'shaft');

  // Isolate the explicit head envelope: disabling the two cylinders leaves only
  // the box hull from machine_geometry.json, whose span starts 50 mm from the tip.
  const headTool = { ...DEFAULT_TOOL, shaftSpan: [0, 0], bodySpan: [0, 0] };
  const headCore = new WaxSDFCore({ R_stock: 20, H_stock: 120, gridN: 48, chunkSize: 16 });
  const headCollision = headCore.checkShank(
    pose([0, 0, 0], [0, 0, -1], 0),
    headTool
  );
  assert.equal(headCollision.collision, true);
  assert.equal(headCollision.code, 'SHANK_COLLISION');
  assert.equal(headCollision.body, 'head');
});

test('snapshot restore and replay match sequential subtraction exactly', () => {
  const core = core48();
  const tool = {
    ...DEFAULT_TOOL,
    heatedLength: 8,
    shaftRadius: 2,
    shaftSpan: [8, 18],
    bodyRadius: 2.4,
    bodySpan: [18, 28],
  };
  const first = [
    pose([0, 0, 25], [0, 0, -1], 0),
    pose([3, 0, 24], [0, 0, -1], 0.2),
    pose([6, 0, 23], [0.2, 0, -1], 0.4),
  ];
  const second = [
    pose([9, 0, 22], [0.3, 0, -1], 0.6),
    pose([12, 0, 21], [0, 0, -1], 0.8),
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
    bladeThickness: 2.0,
    bladeWidth: 2.0,
    heatedLength: 5,
    meltKerf: 0.2,
  };
  const floorZ = 20;
  for (let r = 8; r <= 12.001; r += 0.8) {
    for (let t = 0; t < Math.PI * 2; t += (Math.PI * 2) / 48) {
      core.subtractTool(
        pose([r * Math.cos(t), r * Math.sin(t), floorZ], [0, 0, -1], t),
        tool
      );
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

test('engaged-region displacement helper bounds the swept tool', () => {
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

test('CAD rig and app contain no kinematic trig', () => {
  for (const rel of ['static/cad_rig.js', 'static/app.js']) {
    const source = fs.readFileSync(path.join(ROOT, rel), 'utf8');
    assert.equal(
      /Math\.(sin|cos)\s*\(/.test(source),
      false,
      `${rel} must not call Math.sin/Math.cos`
    );
  }
});

test('wax_sdf_core stays a pure JS module with no DOM or Three.js imports', () => {
  const source = fs.readFileSync(path.join(ROOT, 'static/wax_sdf_core.js'), 'utf8');
  assert.equal(/from\s+['"]three/.test(source), false);
  assert.equal(/\bdocument\./.test(source), false);
  assert.equal(/\bwindow\./.test(source), false);
});

test(
  'SDF performance benchmark (128^3 init, blade subtraction, dirty-chunk remesh)',
  { skip: !process.env.BENCH },
  () => {
    const core = new WaxSDFCore({ R_stock: 40, H_stock: 120, gridN: 128, chunkSize: 16 });
    const tool = { ...DEFAULT_TOOL };
    const carveTimes = [];
    const meshTimes = [];
    for (let i = 0; i < 20; i++) {
      const a = (i / 20) * Math.PI * 2;
      const p = pose([20 * Math.cos(a), 20 * Math.sin(a), 60 - i], [0, 0, -1], a);
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

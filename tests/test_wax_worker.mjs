/**
 * Worker-level regression tests for the wax SDF Web Worker.
 *
 * The worker module talks to `self`; a small vm harness stubs that global scope
 * so its message protocol can be exercised directly in Node.  The wax SDF is
 * **negative inside** material and positive inside a carved cavity.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

// vm.SourceTextModule requires --experimental-vm-modules; skip cleanly instead
// of failing the whole file when the flag is absent.
const hasSourceTextModule = typeof vm.SourceTextModule === 'function';
import { fileURLToPath } from 'node:url';

import * as coreModule from '../static/wax_sdf_core.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

async function bootWorker() {
  const source = fs
    .readFileSync(path.join(ROOT, 'static/wax_worker.js'), 'utf8')
    .replace(/import \{([^}]+)\} from '\.\/wax_sdf_core\.js';/, 'const {$1} = __core;');
  const messages = [];
  const sandbox = {
    self: {
      onmessage: null,
      postMessage(message) {
        messages.push(message);
      },
    },
    console,
    __core: coreModule,
  };
  vm.createContext(sandbox);
  const module = new vm.SourceTextModule(source, { context: sandbox });
  await module.link(() => Promise.reject(new Error('unexpected import')));
  await module.evaluate();

  const api = {
    messages,
    send: (data) => sandbox.self.onmessage({ data }),
    ofType: (type) => messages.filter((message) => message.type === type),
    /** Carve forward incrementally until the requested index completes. */
    carveTo(index) {
      api.send({ type: 'seek', index });
    },
    triangles() {
      const meshes = api.ofType('meshes').at(-1)?.meshes ?? [];
      return meshes.reduce((sum, mesh) => sum + mesh.indices.length / 3, 0);
    },
  };
  return api;
}

function verticalPath(count, { x = 0, y = 0, z = 36, step = 0.01 } = {}) {
  const poses = new Float32Array(count * 7);
  const rapid = new Uint8Array(count);
  for (let index = 0; index < count; index += 1) {
    poses[index * 7] = x;
    poses[index * 7 + 1] = y;
    poses[index * 7 + 2] = z - index * step;
    poses[index * 7 + 5] = -1;
    // theta_s stays 0: u = -Z, a_w = +Y, a_n = -X.
  }
  return { poses, rapid, count, stride: 7 };
}

const WIDE_TOOL = {
  blade_thickness_mm: 6.0,
  blade_width_mm: 6.0,
  blade_length_mm: 14.0,
  heated_length_mm: 14.0,
  melt_kerf_mm: 0.4,
  shaft_radius_mm: 2.5,
  shaft_span_mm: [14.0, 75.0],
  body_radius_mm: 3.5,
  body_span_mm: [75.0, 140.0],
  head_clearance_mm: 46.5934,
  head_envelope: {
    shape: 'box',
    center_mm: [9.0, -3.375, 111.0],
    half_extents_mm: [20.0, 11.125, 61.0],
  },
};

function initConfig(tool = {}, stock = {}) {
  return {
    stock: { R_stock_mm: 20, H_stock_mm: 40, ...stock },
    tool: { ...WIDE_TOOL, ...tool },
  };
}

test('worker maps config.tool blade constants on init', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  worker.send({ type: 'init', config: initConfig(), gridN: 48, chunkSize: 16 });
  assert.equal(worker.ofType('ready').length, 1, 'worker announced ready');
  const readyTool = worker.ofType('ready')[0].tool;
  assert.equal(readyTool.bladeThickness, 6.0);
  assert.deepEqual([...readyTool.shaftSpan], [14.0, 75.0]);
  assert.deepEqual([...readyTool.bodySpan], [75.0, 140.0]);

  const wide = verticalPath(40, { x: 18.6, y: 0.0, z: 30 });
  worker.send({ type: 'path', ...wide });
  worker.carveTo(wide.count - 1);
  const wideTriangles = worker.triangles();
  assert.ok(wideTriangles > 0, 'wide blade carved the wall');

  // A 1.2 mm blade only reaches 19.6 mm from the axis (half-thickness + kerf),
  // so it leaves the 20 mm stock wall intact and produces less carved geometry.
  const narrow = await bootWorker();
  narrow.send({
    type: 'init',
    config: initConfig({ blade_thickness_mm: 1.2 }),
    gridN: 48,
    chunkSize: 16,
  });
  const thin = verticalPath(40, { x: 18.6, y: 0.0, z: 30 });
  narrow.send({ type: 'path', ...thin });
  narrow.carveTo(thin.count - 1);
  const narrowTriangles = narrow.triangles();

  assert.notEqual(
    wideTriangles,
    narrowTriangles,
    `carved geometry differs with blade thickness (wide ${wideTriangles}, narrow ${narrowTriangles})`
  );
});

test('shaft intrusion reports SHANK_COLLISION with body "shaft"', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  // Stock reaches z = 120; a vertical tip at z = 10 puts the shaft span
  // [14, 75] well inside the uncarved column.
  worker.send({
    type: 'init',
    config: initConfig({}, { H_stock_mm: 120 }),
    gridN: 48,
    chunkSize: 16,
  });

  const pathData = verticalPath(6, { x: 0, y: 0, z: 10 });
  worker.send({ type: 'path', ...pathData });
  worker.send({ type: 'seek', index: pathData.count - 1 });

  const collision = worker.ofType('collision')[0];
  assert.ok(collision, 'shaft collision reported');
  assert.equal(collision.code, 'SHANK_COLLISION');
  assert.equal(collision.body, 'shaft');
});

test('tilt-head envelope intrusion reports SHANK_COLLISION with body "head"', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  // Move both cylinders far outside the stock so the explicit head box from the
  // config is the only unheated body in range.  Its span starts 50 mm above the
  // reference point.
  worker.send({
    type: 'init',
    config: initConfig(
      { shaft_span_mm: [2000, 2001], body_span_mm: [3000, 3001] },
      { H_stock_mm: 120 }
    ),
    gridN: 48,
    chunkSize: 16,
  });

  const pathData = verticalPath(6, { x: 0, y: 0, z: 0 });
  worker.send({ type: 'path', ...pathData });
  worker.send({ type: 'seek', index: pathData.count - 1 });

  const collision = worker.ofType('collision')[0];
  assert.ok(collision, 'head collision reported');
  assert.equal(collision.code, 'SHANK_COLLISION');
  assert.equal(collision.body, 'head');
});

test('vertical cutting pose with the shaft buried in uncarved stock posts SHANK_COLLISION', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  // The shaft spans 14..75 mm behind the tip; with a tip at mid-height it sits
  // inside the uncarved column above the tip.
  worker.send({
    type: 'init',
    config: initConfig({}, { R_stock_mm: 20, H_stock_mm: 40 }),
    gridN: 48,
    chunkSize: 16,
  });

  const count = 6;
  const { poses, rapid } = verticalPath(count, { x: 0, y: 0, z: 20, step: 0.01 });
  worker.send({ type: 'path', poses: Float32Array.from(poses), rapid: Uint8Array.from(rapid), count, stride: 7 });
  worker.send({ type: 'seek', index: count - 1 });

  const collision = worker.ofType('collision')[0];
  assert.ok(collision, 'vertical shank collision reported');
  assert.equal(collision.code, 'SHANK_COLLISION');
  assert.equal(collision.body, 'shaft');
});

// ---------------------------------------------------------------------------
// Audit mode: enriched collision poses, run grouping, restore truncation
// ---------------------------------------------------------------------------

/** Tool whose unheated bodies sit far outside the stock: a clean cutting path. */
const CLEAN_TOOL = {
  ...WIDE_TOOL,
  blade_thickness_mm: 1.2,
  shaft_span_mm: [2000, 2001],
  body_span_mm: [3000, 3001],
};

test('worker collision messages carry the tool pose', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  worker.send({
    type: 'init',
    config: initConfig({}, { R_stock_mm: 20, H_stock_mm: 120 }),
    gridN: 48,
    chunkSize: 16,
  });
  const pathData = verticalPath(6, { x: 0, y: 0, z: 10 });
  worker.send({ type: 'path', ...pathData });
  worker.send({ type: 'seek', index: pathData.count - 1 });

  const collision = worker.ofType('collision')[0];
  assert.ok(collision, 'shaft collision reported');
  assert.ok(collision.pose, 'the collision carries the tool pose');
  assert.equal(collision.pose.tip.length, 3);
  assert.equal(collision.pose.axis.length, 3);
  assert.equal(typeof collision.pose.theta, 'number');
  // The pose is the faulting frame's pose, not the previous one's.
  assert.ok(Math.abs(collision.pose.tip[2] - (10 - collision.index * 0.01)) < 1e-4);
  assert.ok(Math.abs(collision.pose.axis[2] + 1) < 1e-6);
});

test('worker audit mode reports the run list and never halts', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  worker.send({
    type: 'init',
    config: initConfig({}, { R_stock_mm: 20, H_stock_mm: 120 }),
    gridN: 48,
    chunkSize: 16,
  });
  const pathData = verticalPath(20, { x: 0, y: 0, z: 10 });
  worker.send({ type: 'path', ...pathData, auditAll: true });
  worker.send({ type: 'seek', index: pathData.count - 1 });

  const runs = worker.ofType('collisions').at(-1)?.runs ?? [];
  assert.equal(runs.length, 1, 'contiguous collisions are one run');
  assert.deepEqual(runs[0].frame_range, [1, pathData.count - 1]);
  assert.equal(runs[0].post_fault, false);
  assert.ok(runs[0].pose, 'runs carry a pose');
});

test('toggling audit all mid-playback resets the carve to frame 0', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  worker.send({
    type: 'init',
    config: initConfig(CLEAN_TOOL, { R_stock_mm: 20, H_stock_mm: 40 }),
    gridN: 48,
    chunkSize: 16,
  });
  const pathData = verticalPath(12, { x: 10, y: 0, z: 30 });
  worker.send({ type: 'path', ...pathData });
  worker.send({ type: 'seek', index: 8 });
  assert.equal(worker.ofType('collisions').length, 0, 'no audit run list yet');

  worker.send({ type: 'audit', enabled: true });
  const reset = worker.ofType('meshes').at(-1);
  assert.equal(reset.reason, 'reset');
  assert.equal(reset.index, 0);
  assert.equal(reset.auditAll, true);
  assert.equal(worker.ofType('status').at(-1).auditAll, true);
  assert.equal(worker.ofType('collisions').at(-1).runs.length, 0);

  // The carve can be driven forward again from 0 under the new mode.
  worker.send({ type: 'seek', index: 8 });
  assert.equal(worker.ofType('meshes').at(-1).index, 8);
});

test('restoreNearest truncates a run straddling the restored snapshot', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  worker.send({
    type: 'init',
    config: initConfig({}, { R_stock_mm: 20, H_stock_mm: 40 }),
    gridN: 48,
    chunkSize: 16,
  });
  // 600 frames gives snapshotEvery = 500, so a snapshot at 500 sits inside the
  // continuous collision run and the seek back to 550 must cut the run at 500.
  const pathData = verticalPath(600, { x: 0, y: 0, z: 20, step: 0.001 });
  worker.send({ type: 'path', ...pathData, auditAll: true });
  worker.send({ type: 'seek', index: 599 });

  const carved = worker.ofType('collisions').at(-1).runs;
  assert.equal(carved.length, 1);
  assert.equal(carved[0].frame_range[0], 1);
  assert.equal(carved[0].frame_range[1], 599);

  worker.send({ type: 'seek', index: 550 });
  const updates = worker.ofType('collisions');
  const truncated = updates[updates.length - 2];
  assert.equal(
    truncated.runs[0].frame_range[1],
    500,
    'restoring posts the straddling run cut at the snapshot'
  );
  const runs = updates.at(-1).runs;
  assert.ok(runs.length >= 1);
  assert.ok(
    runs.every((run) => run.frame_range[1] <= 550),
    `a run still reaches past the restore index: ${JSON.stringify(runs)}`
  );
  assert.equal(runs[0].frame_range[0], 1, 'the run is re-carved from its start');
});

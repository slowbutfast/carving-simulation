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

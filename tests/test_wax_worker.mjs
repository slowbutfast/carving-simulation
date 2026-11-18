/**
 * Worker-level regression tests for the wax SDF Web Worker (PATCH-10).
 *
 * The worker module talks to `self`; a small vm harness stubs that global scope
 * so its message protocol can be exercised directly in Node.
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

  let lastSeek = 0;
  const api = {
    messages,
    send: (data) => sandbox.self.onmessage({ data }),
    ofType: (type) => messages.filter((message) => message.type === type),
    /** Carve forward incrementally until the requested index completes. */
    carveTo(index) {
      api.send({ type: 'seek', index });
      lastSeek = index;
    },
    triangles() {
      const meshes = api.ofType('meshes').at(-1)?.meshes ?? [];
      return meshes.reduce((sum, mesh) => sum + mesh.indices.length / 3, 0);
    },
    get lastSeek() {
      return lastSeek;
    },
  };
  return api;
}

function verticalPath(count, { x = 0, y = 0, z = 36, step = 0.01 } = {}) {
  const poses = new Float32Array(count * 6);
  const rapid = new Uint8Array(count);
  for (let index = 0; index < count; index += 1) {
    poses[index * 6] = x;
    poses[index * 6 + 1] = y;
    poses[index * 6 + 2] = z - index * step;
    poses[index * 6 + 5] = -1;
  }
  return { poses, rapid, count };
}

const WIDE_TOOL = {
  tip_radius_mm: 2.5,
  cone_half_angle_deg: 30,
  engaged_length_mm: 8,
  melt_kerf_mm: 0.4,
  shank_radius_mm: 3,
  shank_length_mm: 20,
};

function initConfig(tool = {}) {
  return {
    stock: { R_stock_mm: 20, H_stock_mm: 40 },
    tool: { ...WIDE_TOOL, ...tool },
  };
}

test('worker maps data.config.tool on init (wide tip reaches the stock wall)', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  worker.send({ type: 'init', config: initConfig(), gridN: 48, chunkSize: 16 });
  assert.ok(worker.ofType('ready').length === 1, 'worker announced ready');

  const { poses, rapid, count } = verticalPath(40, { x: 18.6, y: 0.0, z: 36 });
  worker.send({ type: 'path', poses, rapid, count });
  worker.carveTo(count - 1);
  const wideTriangles = worker.triangles();
  assert.ok(wideTriangles > 0, 'wide tip carved the wall');

  // Same pose with a hairline default-like tip (0.5 mm) cannot reach x = 18.6
  // through the 20 mm stock wall: the cavity is narrower, so fewer triangles.
  const narrow = await bootWorker();
  narrow.send({
    type: 'init',
    config: initConfig({ tip_radius_mm: 0.5 }),
    gridN: 48,
    chunkSize: 16,
  });
  const path2 = verticalPath(40, { x: 18.6, y: 0.0, z: 36 });
  narrow.send({ type: 'path', poses: path2.poses, rapid: path2.rapid, count });
  narrow.carveTo(count - 1);
  const narrowTriangles = narrow.triangles();

  assert.notEqual(
    wideTriangles,
    narrowTriangles,
    `carved geometry differs with tool radius (wide ${wideTriangles}, narrow ${narrowTriangles})`
  );
});

test('worker checks the shank on every cutting frame (no skipping)', { skip: !hasSourceTextModule && 'requires --experimental-vm-modules' }, async () => {
  const worker = await bootWorker();
  // 5 mm shank so the tilted body reaches the wall at frame 3 only.
  worker.send({ type: 'init', config: initConfig({ shank_radius_mm: 5 }), gridN: 48, chunkSize: 16 });

  const count = 10;
  const tilt = Math.hypot(0.9, 0.435);
  const poses = new Float32Array(count * 6);
  const rapid = new Uint8Array(count);
  const setFrame = (index, tipX) => {
    poses[index * 6] = tipX;
    poses[index * 6 + 1] = 0;
    poses[index * 6 + 2] = 34;
    poses[index * 6 + 3] = 0.9 / tilt;
    poses[index * 6 + 4] = 0;
    poses[index * 6 + 5] = -0.435 / tilt;
  };
  for (let index = 0; index < count; index += 1) setFrame(index, 34);

  // Frame 3 alone tips the 5 mm unheated shank to within a millimetre of the
  // stock wall; neighbouring frames stay clear by more than a voxel.
  setFrame(3, 33);
  // Send copies: structured-clone transfer detaches the scratch buffers.
  worker.send({
    type: 'path',
    poses: Float32Array.from(poses),
    rapid: Uint8Array.from(rapid),
    count,
  });
  worker.send({ type: 'seek', index: count - 1 });

  const collision = worker.ofType('collision')[0];
  assert.ok(collision, 'shank collision reported');
  assert.equal(collision.code, 'SHANK_COLLISION');
  assert.equal(collision.index, 3, 'the single offending frame is not skipped');
});

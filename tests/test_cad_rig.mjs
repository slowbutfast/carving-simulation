/**
 * Headless Three.js scene-graph tests for `CadCarverRig` (no WebGL renderer).
 *
 * The backend frame columns are the source of truth: the rig only applies
 * transforms.  Wax-frame -> Three world is the root group's -90 deg X rotation,
 * so machine (x, y, z) maps to world (x, z, -y).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import * as THREE from 'three';
import { CadCarverRig } from '../static/cad_rig.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MODELS = ['static', 'orbit', 'z', 'radial', 'tilt', 'unassigned'];

function mergedConfig() {
  const geometry = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'machine_geometry.json'), 'utf8')
  );
  const machine = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'machine_config.json'), 'utf8')
  );
  return {
    ...machine,
    tool: { ...machine.tool, ...geometry.tool },
    geometry,
    geometry_provenance: {
      step_sha256: geometry.step_sha256,
      home_pose: geometry.home_pose,
      unassigned_parts: geometry.unassigned_parts,
    },
    cad_reference_pose: geometry.cad_reference_pose,
    pivot_to_tip_mm: geometry.pivot_to_tip_mm,
  };
}

function modelBuffers() {
  const buffers = {};
  for (const name of MODELS) {
    const buffer = fs.readFileSync(path.join(ROOT, 'static/models', `${name}.glb`));
    buffers[name] = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  }
  return buffers;
}

function makeRig(options = {}) {
  return new CadCarverRig(mergedConfig(), {
    modelBuffers: modelBuffers(),
    ...options,
  });
}

function frameAt(fixture, index) {
  const frame = fixture.frames[index];
  return {
    r: frame.r,
    theta: frame.theta,
    theta_s: frame.theta_s,
    h: frame.h,
    phi: frame.phi,
    r_s: frame.r_s,
    z_s: frame.z_s,
    tip_xyz_wax: frame.tip_xyz_wax,
    tool_axis_wax: frame.tool_axis_wax,
  };
}

test('rig tip tracks 20 committed demo frames within 0.1 mm', async () => {
  const fixture = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'tests/fixtures/cad_rig_frames.json'), 'utf8')
  );
  assert.equal(fixture.frames.length, 22);
  assert.ok(
    fixture.frames.some((frame) => Math.abs(frame.phi) > 1e-3),
    'fixture includes a tilted frame'
  );
  assert.ok(
    fixture.frames.some((frame) => frame.r < 0),
    'fixture includes a negative-r frame'
  );
  assert.ok(
    fixture.frames.some((frame) => Math.abs(frame.phi + Math.PI / 3) < 1e-6),
    'fixture includes the -60 degree wrist stop'
  );
  assert.ok(
    fixture.frames.some((frame) => Math.abs(frame.phi - Math.PI * 75 / 180) < 1e-6),
    'fixture includes the +75 degree wrist stop'
  );

  const rig = makeRig();
  assert.equal(await rig.ready, true);
  assert.equal(rig.machineFailed, false);

  let worst = 0;
  for (let index = 0; index < fixture.frames.length; index++) {
    rig.update(frameAt(fixture, index));
    const world = rig.getTipWorld();
    const [x, y, z] = fixture.frames[index].tip_xyz_wax;
    const expected = new THREE.Vector3(x, z, -y);
    const error = world.distanceTo(expected);
    worst = Math.max(worst, error);
    assert.ok(
      error <= 0.1,
      `frame ${fixture.frames[index].index}: tip error ${error.toFixed(6)} mm`
    );
  }
  assert.ok(worst <= 0.1, `worst tip error ${worst.toFixed(6)} mm`);
});

test('imported CAD tilt link rotates about the pivot with phi', async () => {
  const rig = makeRig();
  assert.equal(await rig.ready, true);
  assert.ok(
    Array.isArray(rig.cartridgeMeshes) && rig.cartridgeMeshes.length > 0,
    'tilt GLB exposes the cartridge mesh'
  );
  const cartridge = rig.cartridgeMeshes.find((mesh) =>
    mesh.name.startsWith('T12_K_Cartridge')
  );
  assert.ok(cartridge, 'T12_K_Cartridge mesh is present');

  // The tilt GLB vertices are authored in the machine frame; the blade's
  // lowest point is the reference point at (0, 0, 91).
  const reference = new THREE.Vector3(0, 0, 91);
  for (const phi of [0, -Math.PI / 3, (Math.PI * 75) / 180]) {
    rig.update({ r: 0, theta: 0, theta_s: 0, h: 151, phi });
    rig.root.updateMatrixWorld(true);
    const tipWorld = rig.getTipWorld();
    const cartridgeTip = cartridge.localToWorld(reference.clone());
    const error = cartridgeTip.distanceTo(tipWorld);
    assert.ok(
      error <= 0.1,
      `phi=${phi}: CAD cartridge tip is ${error.toFixed(6)} mm from the tip marker`
    );
  }

  rig.update({ r: 0, theta: 0, theta_s: 0, h: 151, phi: -Math.PI / 3 });
  rig.root.updateMatrixWorld(true);
  const atMinus = cartridge.getWorldPosition(new THREE.Vector3());
  rig.update({ r: 0, theta: 0, theta_s: 0, h: 151, phi: (Math.PI * 75) / 180 });
  rig.root.updateMatrixWorld(true);
  const atPlus = cartridge.getWorldPosition(new THREE.Vector3());
  assert.ok(
    atMinus.distanceTo(atPlus) > 10,
    `CAD tilt geometry did not rotate with phi (moved ${atMinus
      .distanceTo(atPlus)
      .toFixed(3)} mm)`
  );
});

test('wax is static while the orbit link advances 90 degrees', async () => {  const rig = makeRig();
  assert.equal(await rig.ready, true);

  // The app parents the wax to the static link; add a stand-in mesh here.
  const wax = new THREE.Mesh(
    new THREE.BoxGeometry(4, 4, 4),
    new THREE.MeshBasicMaterial()
  );
  wax.name = 'test-wax';
  wax.position.set(5, 0, 10);
  rig.links.static.add(wax);

  rig.update({ r: 0, theta_s: 0, h: 151, phi: 0 });
  rig.root.updateMatrixWorld(true);
  const before = wax.matrixWorld.clone();
  const probe = new THREE.Vector3(10, 0, 0);
  const orbitBefore = rig.links.orbit.localToWorld(probe.clone());

  rig.update({ r: 0, theta_s: Math.PI / 2, h: 151, phi: 0 });
  rig.root.updateMatrixWorld(true);

  for (let index = 0; index < 16; index++) {
    assert.ok(
      Math.abs(wax.matrixWorld.elements[index] - before.elements[index]) < 1e-12,
      `wax world matrix element ${index} changed`
    );
  }

  const orbitAfter = rig.links.orbit.localToWorld(probe.clone());
  const cosine =
    orbitBefore.dot(orbitAfter) /
    (orbitBefore.length() * orbitAfter.length());
  assert.ok(
    Math.abs(cosine) < 1e-9,
    `orbit link did not advance 90 deg (cos=${cosine})`
  );
  assert.ok(
    Math.abs(orbitBefore.length() - 10) < 1e-9 &&
      Math.abs(orbitAfter.length() - 10) < 1e-9,
    'orbit probe radius is preserved'
  );
});

test('tool-only detail hides static/orbit/z but keeps radial and tilt', async () => {
  const rig = makeRig({ machineDetail: 'full' });
  assert.equal(await rig.ready, true);
  rig.setMachineDetail('tool');
  assert.equal(rig.modelGroups.static.visible, false);
  assert.equal(rig.modelGroups.orbit.visible, false);
  assert.equal(rig.modelGroups.z.visible, false);
  assert.equal(rig.modelGroups.radial.visible, true);
  assert.equal(rig.modelGroups.tilt.visible, true);
  rig.setMachineDetail('full');
  assert.equal(rig.modelGroups.static.visible, true);
});

test('GLB load failure falls back to a tool-plus-wax scene and emits an error', async () => {
  const events = [];
  const rig = new CadCarverRig(mergedConfig(), {
    // Deliberately missing paths: every load must fail.
    modelUrls: Object.fromEntries(
      MODELS.map((name) => [name, `file://${ROOT}/does-not-exist/${name}.glb`])
    ),
    onEvent: (event) => events.push(event),
  });

  const ok = await rig.ready;
  assert.equal(ok, false);
  assert.equal(rig.loaded, false);
  assert.equal(rig.machineFailed, true);

  for (const group of Object.values(rig.modelGroups)) {
    assert.equal(group.visible, false, 'machine link geometry hidden');
  }
  assert.ok(rig.fallbackTool, 'fallback tool built');
  assert.equal(rig.fallbackTool.visible, true);
  assert.ok(rig.fallbackTool.children.length >= 3, 'blade, shaft and body present');

  const error = events.find((event) => event.type === 'error');
  assert.ok(error, 'load failure emitted an event');
  assert.equal(error.code, 'GLB_LOAD_FAILED');
  assert.ok(/Machine model failed to load/.test(error.message));

  // The scene still contains the tool and the (app-parented) wax; no throw.
  const wax = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2));
  wax.name = 'test-wax';
  rig.links.static.add(wax);
  assert.ok(rig.root.getObjectByName('fallback-tool'));
  assert.ok(rig.root.getObjectByName('test-wax'));
});

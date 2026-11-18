/**
 * Carving Studio front-end.
 *
 * All kinematics arrive pre-sampled from Python; this file only interpolates
 * backend frame indices and forwards poses.  It contains no Math.sin/Math.cos.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { PrimitiveCarverRig } from './machine_rig.js';
import { VolumetricWaxGrid } from './wax_sdf.js';

const DEFAULT_CONFIG = {
  arm_radial_offset_mm: 45,
  arm_to_pivot_z_mm: 25,
  pivot_to_tip_mm: 30,
  stock: {
    R_stock_mm: 40,
    H_stock_mm: 120,
    z_plinth_mm: 10,
    finish_allowance_mm: 1.5,
    retract_clearance_mm: 6,
  },
  tool: {
    tip_radius_mm: 0.5,
    cone_half_angle_deg: 30,
    engaged_length_mm: 8,
    tip_width_mm: 1.6,
    melt_kerf_mm: 0.4,
    shank_radius_mm: 3,
    shank_length_mm: 40,
  },
};

const RAD_TO_DEG = 180 / Math.PI;
const BASE_FRAMES_PER_SECOND = 90;
const FATAL_CODES = new Set(['RAPID_COLLISION', 'SHANK_COLLISION', 'SOFT_LIMIT_EXCEEDED']);
const WARNING_CODES = new Set([
  'SINGULARITY_HIGH_THETA_DOT',
  'UNREACHABLE_UNDERCUT_AREA',
  'PHI_POLICY_CLAMPED',
]);

const state = {
  data: null,
  frames: null,
  frameCount: 0,
  index: 0,
  playing: false,
  speed: 20,
  accumulator: 0,
  lastSeekAt: 0,
  faultFrame: null,
  faultCode: null,
  totalTime: 0,
  diagnostics: [],
  carvingToEnd: false,
};

const dom = {};
for (const id of [
  'viewport', 'canvas-host', 'statusBadge', 'faultBadge', 'faultText',
  'frameBadge', 'hud-t', 'hud-v', 'hud-r', 'hud-z', 'hud-mode', 'progressFill',
  'playBtn', 'endBtn', 'resetBtn', 'scrub', 'timecode', 'speed', 'toolpathInfo',
  'meshInfo', 'diagnostics', 'diagCount', 'tele-r', 'tele-theta', 'tele-h',
  'tele-phi', 'tele-rs', 'tele-zs', 'tele-vtip', 'tele-stage', 'sculptBtn',
  'preset', 'showGhost', 'showStock', 'headerBadge', 'sculptHint',
  'telemetryGrid',
]) {
  dom[id] = document.getElementById(id);
}

const sliderIds = ['nose', 'brow', 'cheeks', 'jaw', 'chin'];
for (const id of sliderIds) {
  const input = document.getElementById(id);
  const output = document.getElementById(`${id}-value`);
  if (input && output) {
    const sync = () => {
      output.textContent = Number(input.value).toFixed(2);
    };
    input.addEventListener('input', sync);
    sync();
  }
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------

let renderer;
let scene;
let camera;
let controls;
let rig;
let wax;
const clock = new THREE.Clock();

function initScene() {
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  dom['canvas-host'].appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b1220);
  scene.fog = new THREE.Fog(0x0b1220, 420, 900);

  camera = new THREE.PerspectiveCamera(38, 1, 0.5, 3000);
  camera.position.set(230, 190, 255);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(6, 66, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 60;
  controls.maxDistance = 620;
  controls.maxPolarAngle = Math.PI * 0.495;
  controls.update();

  scene.add(new THREE.HemisphereLight(0xbfdbfe, 0x1e293b, 1.15));
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(140, 230, 120);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x93c5fd, 0.85);
  fill.position.set(-140, 90, -120);
  scene.add(fill);
  const rim = new THREE.PointLight(0x38bdf8, 1.2, 520, 2);
  rim.position.set(-90, 140, 110);
  scene.add(rim);

  const grid = new THREE.GridHelper(420, 42, 0x1d3350, 0x142238);
  grid.position.y = -0.2;
  grid.material.opacity = 0.55;
  grid.material.transparent = true;
  scene.add(grid);

  rig = new PrimitiveCarverRig(DEFAULT_CONFIG);
  scene.add(rig.root);

  wax = new VolumetricWaxGrid({
    rigRoot: rig.root,
    config: DEFAULT_CONFIG,
    gridN: 128,
    chunkSize: 16,
    onCollision: handleCollision,
    onStatus: handleWaxStatus,
  });

  window.addEventListener('resize', resize);
  resize();
  renderer.setAnimationLoop(tick);
}

function resize() {
  if (!renderer || !camera) return;
  const width = dom.viewport.clientWidth || window.innerWidth;
  const height = dom.viewport.clientHeight || window.innerHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / Math.max(height, 1);
  camera.updateProjectionMatrix();
}

// ---------------------------------------------------------------------------
// Decoding helpers
// ---------------------------------------------------------------------------

function decodeBase64(text, Type) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Type(bytes.buffer);
}

function decodeColumns(trajectory) {
  const columns = trajectory.columns;
  return {
    t: decodeBase64(columns.t.b64, Float32Array),
    r: decodeBase64(columns.r.b64, Float32Array),
    theta: decodeBase64(columns.theta.b64, Float32Array),
    h: decodeBase64(columns.h.b64, Float32Array),
    phi: decodeBase64(columns.phi.b64, Float32Array),
    r_s: decodeBase64(columns.r_s.b64, Float32Array),
    theta_s: decodeBase64(columns.theta_s.b64, Float32Array),
    z_s: decodeBase64(columns.z_s.b64, Float32Array),
    v_tip: decodeBase64(columns.v_tip.b64, Float32Array),
    is_rapid: decodeBase64(columns.is_rapid.b64, Uint8Array),
    tip_xyz_wax: decodeBase64(columns.tip_xyz_wax.b64, Float32Array),
    tool_axis_wax: decodeBase64(columns.tool_axis_wax.b64, Float32Array),
  };
}

function frameAt(index) {
  const c = state.frames;
  if (!c) return null;
  const i = Math.max(0, Math.min(index, state.frameCount - 1));
  return {
    t: c.t[i],
    r: c.r[i],
    theta: c.theta[i],
    h: c.h[i],
    phi: c.phi[i],
    r_s: c.r_s[i],
    theta_s: c.theta_s[i],
    z_s: c.z_s[i],
    v_tip: c.v_tip[i],
    is_rapid: Boolean(c.is_rapid[i]),
    tip_xyz_wax: [c.tip_xyz_wax[i * 3], c.tip_xyz_wax[i * 3 + 1], c.tip_xyz_wax[i * 3 + 2]],
    tool_axis_wax: [
      c.tool_axis_wax[i * 3],
      c.tool_axis_wax[i * 3 + 1],
      c.tool_axis_wax[i * 3 + 2],
    ],
  };
}

// ---------------------------------------------------------------------------
// Simulation data
// ---------------------------------------------------------------------------

async function sculptAndSimulate() {
  if (!state) return;
  setStatus('CARVING', 'playing');
  dom.sculptBtn.disabled = true;
  dom.sculptHint.textContent = 'generating…';
  try {
    const sliders = {};
    for (const id of sliderIds) {
      const input = document.getElementById(id);
      sliders[id] = Number(input ? input.value : 0);
    }
    const response = await fetch('/api/sculpt-and-sim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sliders, preset: dom.preset.value }),
    });
    const body = await response.json();
    if (!response.ok) {
      const detail = body.detail || body;
      throw new Error(detail.diagnostics?.[0]?.message || 'Simulation request failed');
    }
    loadSimulation(body);
  } catch (error) {
    dom.sculptHint.textContent = 'error';
    setStatus('ERROR', 'error');
    appendDiagnostic({
      code: 'API_ERROR',
      severity: 'error',
      message: String(error.message || error),
      count: 1,
    });
  } finally {
    dom.sculptBtn.disabled = false;
  }
}

function loadSimulation(body) {
  state.data = body;
  state.diagnostics = body.diagnostics || [];
  state.faultFrame = null;
  state.faultCode = null;

  const columns = decodeColumns(body.trajectory);
  state.frames = columns;
  state.frameCount = body.trajectory.frame_count;
  state.index = 0;
  state.playing = false;
  state.accumulator = 0;
  state.carvingToEnd = false;
  state.totalTime = columns.t[state.frameCount - 1] || 0;

  const mesh = body.target_mesh;
  const vertices = decodeBase64(mesh.vertices_b64, Float32Array);
  const faces = decodeBase64(mesh.faces_b64, Uint32Array);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
  geometry.setIndex(new THREE.BufferAttribute(faces, 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  rig.setTargetMesh(geometry);
  rig.setTargetVisible(dom.showGhost.checked);

  wax.setPath(columns, state.frameCount);
  wax.seek(0);

  dom.scrub.max = '1000';
  dom.scrub.value = '0';
  dom.toolpathInfo.textContent =
    `${state.frameCount.toLocaleString()} frames · ${body.preset} · ` +
    `${Number(body.summary?.generation_ms || 0).toFixed(0)} ms backend`;
  dom.sculptHint.textContent = `${mesh.face_count.toLocaleString()} faces`;
  dom.playBtn.disabled = false;
  dom.endBtn.disabled = false;
  dom.resetBtn.disabled = false;
  renderDiagnostics();

  const fatal = state.diagnostics.find(
    (diagnostic) => FATAL_CODES.has(diagnostic.code) && diagnostic.severity === 'error'
  );
  if (fatal) {
    state.faultCode = fatal.code;
    state.faultFrame = typeof fatal.frame === 'number' ? fatal.frame : 0;
    showFault(fatal.code);
  } else {
    dom.faultBadge.classList.add('hidden');
    setStatus('READY', 'ready');
  }

  updateRigAt(0);
  updateTelemetry();
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

function updateRigAt(index) {
  const frame = frameAt(index);
  if (!frame) return;
  rig.update(frame);
  const ratio = state.frameCount > 1 ? index / (state.frameCount - 1) : 0;
  dom.scrub.value = String(Math.round(ratio * 1000));
  dom.progressFill.style.width = `${(ratio * 100).toFixed(2)}%`;
  dom.frameBadge.textContent = `FRAME ${index + 1} / ${state.frameCount}`;
  dom.timecode.textContent = `${frame.t.toFixed(2)} / ${state.totalTime.toFixed(2)} s`;
  dom['hud-t'].textContent = `${frame.t.toFixed(2)} s`;
  dom['hud-v'].textContent = `${frame.v_tip.toFixed(1)} mm/s`;
  dom['hud-r'].textContent = frame.r_s.toFixed(2);
  dom['hud-z'].textContent = frame.z_s.toFixed(2);
  dom['hud-mode'].textContent = frame.is_rapid ? 'RAPID' : 'CUT';
}

let lastTelemetry = 0;
function updateTelemetry(force = false) {
  const now = performance.now();
  if (!force && now - lastTelemetry < 90) return;
  lastTelemetry = now;
  const frame = frameAt(state.index);
  if (!frame) return;
  dom['tele-r'].textContent = `${frame.r.toFixed(2)} mm`;
  dom['tele-theta'].textContent = `${(frame.theta_s * RAD_TO_DEG).toFixed(1)}°`;
  dom['tele-h'].textContent = `${frame.h.toFixed(2)} mm`;
  dom['tele-phi'].textContent = `${(frame.phi * RAD_TO_DEG).toFixed(1)}°`;
  dom['tele-rs'].textContent = `${frame.r_s.toFixed(2)} mm`;
  dom['tele-zs'].textContent = `${frame.z_s.toFixed(2)} mm`;
  dom['tele-vtip'].textContent = `${frame.v_tip.toFixed(2)} mm/s`;
  const stage = state.data?.trajectory ? (frame.is_rapid ? 'rapid' : 'cut') : '—';
  dom['tele-stage'].textContent = `${stage} · ${frame.t.toFixed(2)} s`;
}

function play() {
  if (!state.frames) {
    sculptAndSimulate();
    return;
  }
  if (state.index >= state.frameCount - 1) {
    state.index = 0;
    wax.seek(0);
  }
  state.playing = true;
  state.accumulator = 0;
  state.carvingToEnd = false;
  dom.playBtn.textContent = '❚❚ Pause';
  setStatus('PLAYING', 'playing');
}

function pause() {
  state.playing = false;
  dom.playBtn.textContent = '▶ Play';
  if (state.faultCode) return;
  setStatus('PAUSED', 'warning');
}

function togglePlay() {
  if (state.playing) pause();
  else play();
}

function scrubTo(index) {
  if (!state.frames) return;
  const target = Math.max(0, Math.min(state.frameCount - 1, index));
  state.index = target;
  updateRigAt(target);
  updateTelemetry(true);
  wax.seek(target, 'scrub');
  if (!state.playing && !state.faultCode) setStatus('SCRUBBING', 'playing');
}

function tick() {
  const delta = Math.min(clock.getDelta(), 0.1);
  if (state.playing && state.frames) {
    state.accumulator += delta * state.speed * BASE_FRAMES_PER_SECOND;
    const advance = Math.floor(state.accumulator);
    if (advance > 0) {
      state.accumulator -= advance;
      const next = Math.min(state.index + advance, state.frameCount - 1);
      if (state.faultFrame !== null && next >= state.faultFrame) {
        state.index = state.faultFrame;
        updateRigAt(state.index);
        pause();
        showFault(state.faultCode);
      } else {
        state.index = next;
        updateRigAt(state.index);
        updateTelemetry();
        const now = performance.now();
        if (now - state.lastSeekAt > 90) {
          state.lastSeekAt = now;
          wax.seek(state.index, 'play');
        }
        if (state.index >= state.frameCount - 1) {
          pause();
          setStatus('COMPLETE', 'ready');
        }
      }
    }
  }
  controls.update();
  renderer.render(scene, camera);
}

// ---------------------------------------------------------------------------
// Diagnostics and status
// ---------------------------------------------------------------------------

function setStatus(label, tone) {
  dom.statusBadge.className = `badge ${tone}`;
  dom.statusBadge.innerHTML = `<span class="dot"></span>${label}`;
  dom.headerBadge.className = `badge ${tone}`;
  dom.headerBadge.innerHTML = `<span class="dot"></span>${label}`;
}

function showFault(code) {
  state.faultCode = code;
  dom.faultBadge.classList.remove('hidden');
  dom.faultBadge.className = `badge ${WARNING_CODES.has(code) ? 'warning' : 'error'}`;
  dom.faultText.textContent = code;
  rig.setFault(code);
  setStatus(WARNING_CODES.has(code) ? 'WARNING' : 'FAULT', WARNING_CODES.has(code) ? 'warning' : 'error');
  dom['hud-mode'].textContent = code;
}

function handleCollision(message) {
  pause();
  state.faultFrame = message.index;
  showFault(message.code);
  appendDiagnostic({
    code: message.code,
    severity: 'error',
    message: `Worker SDF collision at frame ${message.index}`,
    count: 1,
    frame: message.index,
  });
}

function handleWaxStatus(message) {
  if (message.type === 'ready') {
    dom.meshInfo.textContent = `${message.gridN}³ · ${message.voxelSize.toFixed(2)} mm voxel`;
  }
  if (message.type === 'progress' && state.carvingToEnd) {
    state.index = Math.max(state.index, message.index);
    updateRigAt(state.index);
    updateTelemetry();
  }
  if (message.type === 'meshes' && message.reason === 'progress' && state.carvingToEnd) {
    state.index = Math.max(state.index, message.index);
    updateRigAt(state.index);
    updateTelemetry();
  }
  if (message.type === 'meshes' && message.reason === 'end') {
    state.carvingToEnd = false;
    state.index = state.frameCount - 1;
    updateRigAt(state.index);
    updateTelemetry(true);
    setStatus('COMPLETE', 'ready');
  }
  if (message.type === 'meshes' && message.reason === 'scrub' && !state.playing) {
    setStatus('PAUSED', 'warning');
  }
  if (message.faulted) {
    pause();
  }
}

function renderDiagnostics() {
  dom.diagnostics.innerHTML = '';
  const diagnostics = state.diagnostics;
  dom.diagCount.textContent = `${diagnostics.length}`;
  if (!diagnostics.length) {
    appendDiagnostic({
      code: 'CLEAN',
      severity: 'info',
      message: 'No diagnostics reported for this toolpath.',
      count: 1,
    });
    return;
  }
  for (const diagnostic of diagnostics) {
    appendDiagnostic(diagnostic);
  }
}

function appendDiagnostic(diagnostic) {
  const div = document.createElement('div');
  div.className = `diag ${diagnostic.severity || 'info'}`;
  const count = diagnostic.count && diagnostic.count > 1 ? ` ×${diagnostic.count}` : '';
  const value = typeof diagnostic.value === 'number' ? ` · ${diagnostic.value.toFixed(2)}` : '';
  div.innerHTML = `<code>${diagnostic.code}${count}</code><br>${diagnostic.message || ''}${value}`;
  dom.diagnostics.appendChild(div);
  dom.diagCount.textContent = String(dom.diagnostics.children.length);
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

dom.playBtn.addEventListener('click', togglePlay);
dom.sculptBtn.addEventListener('click', sculptAndSimulate);
dom.endBtn.addEventListener('click', () => {
  if (!state.frames) return;
  pause();
  setStatus('CARVING', 'playing');
  state.carvingToEnd = true;
  wax.seek(state.frameCount - 1, 'end');
});
dom.resetBtn.addEventListener('click', () => {
  if (!state.frames) return;
  pause();
  state.index = 0;
  state.faultCode = null;
  state.faultFrame = null;
  state.carvingToEnd = false;
  dom.faultBadge.classList.add('hidden');
  rig.setFault(null);
  wax.reset();
  updateRigAt(0);
  updateTelemetry(true);
  setStatus('READY', 'ready');
});
dom.scrub.addEventListener('input', () => {
  if (!state.frames) return;
  if (state.playing) pause();
  const ratio = Number(dom.scrub.value) / 1000;
  scrubTo(Math.round(ratio * (state.frameCount - 1)));
});
dom.speed.addEventListener('change', () => {
  state.speed = Number(dom.speed.value) || 1;
});
dom.showGhost.addEventListener('change', () => {
  if (rig) rig.setTargetVisible(dom.showGhost.checked);
});
dom.showStock.addEventListener('change', () => {
  if (wax) wax.setVisible(dom.showStock.checked);
});

dom.playBtn.disabled = true;
dom.endBtn.disabled = true;
dom.resetBtn.disabled = true;

try {
  initScene();
  sculptAndSimulate();
} catch (error) {
  setStatus('WEBGL ERROR', 'error');
  dom['canvas-host'].innerHTML =
    `<div style="padding:24px;color:#ef4444;font-family:monospace">WebGL unavailable: ${error.message}</div>`;
}

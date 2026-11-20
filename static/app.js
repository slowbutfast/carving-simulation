/**
 * Carving Studio front-end.
 *
 * All kinematics arrive pre-sampled from Python; this file only interpolates
 * backend frame indices and forwards poses.  It contains no Math.sin/Math.cos.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CadCarverRig } from './cad_rig.js';
import { VolumetricWaxGrid } from './wax_sdf.js';

const DEFAULT_CONFIG = {
  arm_radial_offset_mm: 0,
  arm_to_pivot_z_mm: 0,
  pivot_to_tip_mm: 60,
  stock: {
    R_stock_mm: 40,
    H_stock_mm: 120,
    z_plinth_mm: 12,
    finish_allowance_mm: 1.5,
    retract_clearance_mm: 6,
  },
  tool: {
    blade_thickness_mm: 1.2,
    blade_width_mm: 6.0,
    blade_length_mm: 14.0,
    heated_length_mm: 14.0,
    melt_kerf_mm: 0.4,
    shaft_radius_mm: 2.5,
    shaft_span_mm: [14.0, 75.0],
    body_radius_mm: 3.5,
    body_span_mm: [75.0, 140.0],
    head_clearance_mm: 46.5934,
  },
  geometry: {
    cad_reference_pose: { h: 151.0, r: 0.0, theta_deg: 0.0, phi_deg: 0.0 },
    pivot_point_mm: [0.0, 0.0, 151.0],
    pivot_axis_mm: [0.0, -1.0, 0.0],
    tool_reference_point_mm: [0.0, 0.0, 91.0],
    unassigned_parts: [],
    home_pose: null,
  },
  geometry_provenance: { step_sha256: null, home_pose: null, unassigned_parts: [] },
};

const RAD_TO_DEG = 180 / Math.PI;
const BASE_FRAMES_PER_SECOND = 90;
const FATAL_CODES = new Set(['RAPID_COLLISION', 'SHANK_COLLISION', 'SOFT_LIMIT_EXCEEDED']);
const WARNING_CODES = new Set([
  'SINGULARITY_HIGH_THETA_DOT',
  'UNREACHABLE_UNDERCUT_AREA',
  'PHI_POLICY_CLAMPED',
  'BLADE_BROADSIDE_FEED',
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
  machineDetail: window.matchMedia('(min-width: 900px)').matches ? 'full' : 'tool',
  slidersEnabled: true,
  auditAll: false,
  collisionLog: { backend: null, worker: [] },
};

const dom = {};
for (const id of [
  'viewport', 'canvas-host', 'statusBadge', 'faultBadge', 'faultText',
  'frameBadge', 'hud-t', 'hud-v', 'hud-r', 'hud-z', 'hud-mode', 'progressFill',
  'playBtn', 'endBtn', 'resetBtn', 'scrub', 'timecode', 'speed', 'toolpathInfo',
  'meshInfo', 'diagnostics', 'diagCount', 'tele-r', 'tele-theta', 'tele-h',
  'tele-phi', 'tele-rs', 'tele-zs', 'tele-vtip', 'tele-stage', 'sculptBtn',
  'preset', 'showGhost', 'showStock', 'headerBadge', 'sculptHint',
  'telemetryGrid', 'machineDetailBtn', 'unassignedNote', 'provenanceStep',
  'provenanceHome', 'sliderNote', 'auditAll', 'copyJson', 'downloadJson',
  'collisionCount',
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
  scene.fog = new THREE.Fog(0x0b1220, 1200, 2600);

  camera = new THREE.PerspectiveCamera(38, 1, 0.5, 4000);
  camera.position.set(620, 430, 700);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 60, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 120;
  controls.maxDistance = 1800;
  controls.maxPolarAngle = Math.PI * 0.495;
  controls.update();

  scene.add(new THREE.HemisphereLight(0xbfdbfe, 0x1e293b, 1.15));
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(240, 360, 220);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x93c5fd, 0.85);
  fill.position.set(-240, 160, -220);
  scene.add(fill);
  const rim = new THREE.PointLight(0x38bdf8, 1.2, 900, 2);
  rim.position.set(-160, 240, 180);
  scene.add(rim);

  const grid = new THREE.GridHelper(1600, 80, 0x1d3350, 0x142238);
  grid.position.y = -141;
  grid.material.opacity = 0.55;
  grid.material.transparent = true;
  scene.add(grid);

  rig = new CadCarverRig(DEFAULT_CONFIG, {
    machineDetail: state.machineDetail,
    onEvent: handleRigEvent,
  });
  scene.add(rig.root);

  wax = new VolumetricWaxGrid({
    rigRoot: rig.links.static,
    config: DEFAULT_CONFIG,
    gridN: 128,
    chunkSize: 16,
    onCollision: handleCollision,
    onStatus: handleWaxStatus,
  });

  if (dom.machineDetailBtn) dom.machineDetailBtn.disabled = true;
  rig.ready.then(() => {
    if (dom.machineDetailBtn) dom.machineDetailBtn.disabled = false;
    applyMachineDetail();
    updateUnassignedNote();
    updateProvenance();
  });
  applyMachineDetail();

  window.addEventListener('resize', resize);
  resize();
  renderer.setAnimationLoop(tick);
}

function handleRigEvent(event) {
  if (!event) return;
  if (event.type === 'error') {
    appendDiagnostic({
      code: event.code || 'GLB_LOAD_FAILED',
      severity: event.severity || 'warning',
      message: event.message || 'Machine model failed to load — showing tool only',
      count: 1,
    });
    setStatus('WARNING', 'warning');
    if (dom.machineDetailBtn) dom.machineDetailBtn.disabled = false;
  }
  if (event.type === 'loaded') {
    if (dom.machineDetailBtn) dom.machineDetailBtn.disabled = false;
    updateUnassignedNote();
    updateProvenance();
  }
}

function applyMachineDetail() {
  if (!rig) return;
  const mode = state.machineDetail === 'tool' ? 'tool' : 'full';
  rig.setMachineDetail(mode);
  if (dom.machineDetailBtn) {
    dom.machineDetailBtn.textContent =
      mode === 'full' ? 'Machine detail: Full' : 'Machine detail: Tool only';
    dom.machineDetailBtn.setAttribute('aria-pressed', String(mode === 'tool'));
  }
}

function updateUnassignedNote() {
  if (!rig || !dom.unassignedNote) return;
  const parts = rig.getProvenance().unassignedParts || [];
  if (!parts.length) {
    dom.unassignedNote.classList.add('hidden');
    dom.unassignedNote.textContent = '';
    return;
  }
  dom.unassignedNote.classList.remove('hidden');
  const names = [...new Set(parts.map((part) => String(part).replace(/:\d+$/, '')))];
  dom.unassignedNote.textContent =
    `${parts.length} CAD parts not simulated: ${names.join(', ')}`;
  dom.unassignedNote.setAttribute('aria-pressed', String(!rig.ghostsVisible));
}

function updateProvenance() {
  if (!rig) return;
  const provenance = rig.getProvenance();
  const sha = provenance.stepSha256 ? String(provenance.stepSha256).slice(0, 8) : '—';
  if (dom.provenanceStep) dom.provenanceStep.textContent = `STEP ${sha}`;
  if (dom.provenanceHome) {
    dom.provenanceHome.textContent = ` · home: ${
      provenance.homePose == null ? 'unset' : 'set'
    }`;
  }
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
  state.slidersEnabled = body.sliders_enabled !== false;
  state.collisionLog = { backend: body.collision_log ?? null, worker: [] };
  applySlidersEnabled();
  renderCollisionLog();

  if (body.config) {
    rig.configure(body.config);
    updateUnassignedNote();
    updateProvenance();
  }

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
  wax.setAuditAll(state.auditAll);
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
    const warning = state.diagnostics.find((diagnostic) => WARNING_CODES.has(diagnostic.code));
    if (warning) {
      // Reuse the existing amber warning badge path; broadside feeds are not
      // fatal, so playback is not auto-paused.
      dom.faultBadge.classList.remove('hidden');
      dom.faultBadge.className = 'badge warning';
      dom.faultText.textContent = warning.code;
      setStatus('WARNING', 'warning');
      rig.setFault(warning.code);
    } else {
      dom.faultBadge.classList.add('hidden');
      setStatus('READY', 'ready');
    }
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

function showFault(code, body = null) {
  state.faultCode = code;
  dom.faultBadge.classList.remove('hidden');
  dom.faultBadge.className = `badge ${WARNING_CODES.has(code) ? 'warning' : 'error'}`;
  dom.faultText.textContent = body ? `${code} · ${body}` : code;
  rig.setFault(code, body);
  setStatus(WARNING_CODES.has(code) ? 'WARNING' : 'FAULT', WARNING_CODES.has(code) ? 'warning' : 'error');
  dom['hud-mode'].textContent = body ? `${code} · ${body}` : code;
}

function applySlidersEnabled() {
  const enabled = state.slidersEnabled;
  for (const id of sliderIds) {
    const input = document.getElementById(id);
    const output = document.getElementById(`${id}-value`);
    const row = input ? input.closest('.slider-row') : null;
    if (input) {
      input.disabled = !enabled;
      input.title = enabled
        ? ''
        : 'This target mesh has no landmark sidecar, so facial sliders are ignored.';
    }
    if (output) output.classList.toggle('disabled', !enabled);
    if (row) row.classList.toggle('disabled', !enabled);
  }
  if (dom.sliderNote) dom.sliderNote.classList.toggle('hidden', enabled);
}

// ---------------------------------------------------------------------------
// Collision log (backend `collision_log` + worker SDF runs)
// ---------------------------------------------------------------------------

/** Worker run -> the log shape the backend uses, plus the frame's joints. */
function enrichCollisionRun(message) {
  const range = message.frame_range || [message.index ?? 0, message.index ?? 0];
  const frame = frameAt(message.worst_frame ?? range[0]);
  return {
    code: message.code,
    body: message.body ?? null,
    frame_range: [range[0], range[1]],
    worst_frame: message.worst_frame ?? range[0],
    worst_sdf_mm: typeof message.sdf === 'number' ? message.sdf : null,
    post_fault: Boolean(message.post_fault),
    pose: message.pose ?? null,
    r: frame ? frame.r : null,
    theta_deg: frame ? frame.theta_s * RAD_TO_DEG : null,
    h: frame ? frame.h : null,
    phi_deg: frame ? frame.phi * RAD_TO_DEG : null,
    stage: frame ? (frame.is_rapid ? 'rapid' : 'cut') : null,
    is_rapid: frame ? frame.is_rapid : null,
  };
}

function renderCollisionLog() {
  if (!dom.collisionCount) return;
  const runs = state.collisionLog.worker.length;
  const backend = state.collisionLog.backend?.events?.length ?? 0;
  dom.collisionCount.textContent =
    `${runs} worker run${runs === 1 ? '' : 's'} · ${backend} backend event${
      backend === 1 ? '' : 's'
    }`;
}

function collisionReport() {
  return {
    service: state.data?.service ?? null,
    preset: state.data?.preset ?? null,
    frames: state.frameCount,
    sliders_enabled: state.slidersEnabled,
    audit_all: state.auditAll,
    backend: state.collisionLog.backend,
    worker: { audit_all: state.auditAll, runs: state.collisionLog.worker },
  };
}

async function copyCollisionJson() {
  const text = JSON.stringify(collisionReport(), null, 2);
  try {
    await navigator.clipboard.writeText(text);
    dom.copyJson.textContent = 'Copied';
    window.setTimeout(() => {
      dom.copyJson.textContent = 'Copy JSON';
    }, 1200);
  } catch (error) {
    appendDiagnostic({
      code: 'CLIPBOARD_UNAVAILABLE',
      severity: 'warning',
      message: `Could not copy the collision log: ${error.message || error}`,
      count: 1,
    });
  }
}

function downloadCollisionJson() {
  const blob = new Blob([JSON.stringify(collisionReport(), null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `collision_report_frame_${state.index}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function handleCollision(message) {
  if (state.auditAll) {
    // Audit mode never halts: the run list is the artefact, not a fault badge.
    return;
  }
  pause();
  state.faultFrame = message.index;
  showFault(message.code, message.body || null);
  appendDiagnostic({
    code: message.code,
    severity: 'error',
    message: `Worker SDF collision at frame ${message.index}${
      message.body ? ` (${message.body})` : ''
    }`,
    count: 1,
    frame: message.index,
  });
}

function handleWaxStatus(message) {
  if (message.type === 'ready') {
    dom.meshInfo.textContent = `${message.gridN}³ · ${message.voxelSize.toFixed(2)} mm voxel`;
  }
  if (message.type === 'collisions') {
    state.collisionLog.worker = (message.runs || []).map(enrichCollisionRun);
    renderCollisionLog();
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
dom.machineDetailBtn.addEventListener('click', () => {
  if (dom.machineDetailBtn.disabled) return;
  state.machineDetail = state.machineDetail === 'full' ? 'tool' : 'full';
  applyMachineDetail();
});
dom.unassignedNote.addEventListener('click', () => {
  if (!rig) return;
  rig.setGhostVisible(!rig.ghostsVisible);
  updateUnassignedNote();
});
dom.auditAll.addEventListener('change', () => {
  state.auditAll = dom.auditAll.checked;
  state.faultCode = null;
  state.faultFrame = null;
  dom.faultBadge.classList.add('hidden');
  if (rig) rig.setFault(null);
  // The worker re-carves from frame 0: audit mode leaves collisions uncarved, so
  // the wax state before the toggle cannot be reused.
  state.collisionLog.worker = [];
  renderCollisionLog();
  if (wax) wax.setAuditAll(state.auditAll);
  state.index = 0;
  updateRigAt(0);
  updateTelemetry(true);
  if (state.frames) setStatus(state.auditAll ? 'AUDITING' : 'READY', state.auditAll ? 'playing' : 'ready');
});
dom.copyJson.addEventListener('click', copyCollisionJson);
dom.downloadJson.addEventListener('click', downloadCollisionJson);

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

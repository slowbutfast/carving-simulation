/**
 * 4-DOF Wax Carver Studio 2001 front-end.
 *
 * Windows XP Luna shell (ported from wax-robot) wrapped around the existing
 * simulation client.  All kinematics arrive pre-sampled from Python; this file
 * only interpolates backend frame indices and forwards poses.  It contains no
 * kinematic trigonometry and never flips the camera to a Z-up convention.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import * as fflate from 'three/addons/libs/fflate.module.js';
import { CadCarverRig } from './cad_rig.js';
import { VolumetricWaxGrid } from './wax_sdf.js';
import { read3mf } from './threemf.js';
import {
  DEFAULT_LIMITS,
  checkUploadAllowed,
  limitsFromHealth,
  listFormats,
  uploadSubtitle,
} from './upload.js';

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
const FATAL_CODES = new Set([
  'RAPID_COLLISION',
  'SHANK_COLLISION',
  'SOFT_LIMIT_EXCEEDED',
  'STOCK_BOUNDS_EXCEEDED',
]);
const WARNING_CODES = new Set([
  'SINGULARITY_HIGH_THETA_DOT',
  'UNREACHABLE_UNDERCUT_AREA',
  'BLADE_BROADSIDE_FEED',
  'GLB_LOAD_FAILED',
  'PHI_POLICY_CLAMPED',
]);

const SLIDER_IDS = ['nose', 'brow', 'cheeks', 'jaw', 'chin'];
const MOBILE_TABS = ['model', 'sculpt', 'sim'];

/** Async toolpath job polling: 500 ms ticks, 3 transient failures tolerated. */
const JOB_POLL_INTERVAL_MS = 500;
const JOB_MAX_TRANSIENT_FAILURES = 3;
const JOB_STOPPING_MESSAGE = 'Previous generation is stopping — try again in a moment';

/** Backend phase keys -> the label announced once per phase transition. */
const JOB_PHASE_LABELS = new Map([
  ['sculpt', 'Sculpting'],
  ['roughing', 'Roughing'],
  ['finishing', 'Finishing'],
  ['resample', 'Resampling'],
  ['resampling', 'Resampling'],
  ['trajectory', 'Trajectory'],
  ['gouges', 'Gouge check'],
  ['feed_class', 'Feed check'],
  ['encode', 'Encoding'],
  ['encoding', 'Encoding'],
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
  generating: false,
  machineDetail: window.matchMedia('(min-width: 900px)').matches ? 'full' : 'tool',
  slidersEnabled: true,
  auditAll: false,
  collisionLog: { backend: null, worker: [] },
  limits: { ...DEFAULT_LIMITS, acceptedFormats: [...DEFAULT_LIMITS.acceptedFormats] },
  presets: [],
  customFile: null,
};

const dom = {};
for (const id of [
  'viewport',
  'simulate-button',
  'sculpt-hint',
  'preset-select',
  'upload-zone',
  'upload-subtitle',
  'file-input',
  'model-note',
  'sliderNote',
  'auditAll',
  'collisionCount',
  'showGhost',
  'showStock',
  'R_stock',
  'H_stock',
  'machineDetailBtn',
  'unassigned-note',
  'provenance-step',
  'provenance-home',
  'prevBtn',
  'playBtn',
  'nextBtn',
  'endBtn',
  'sim-scrubber',
  'sim-time',
  'sim-speed',
  'status-text',
  'status-joints',
  'status-tip',
  'status-feed',
  'status-state',
  'diagnostics',
  'diag-count',
  'processing-overlay',
  'progress-label',
  'progress-bar',
  'progress-fill',
  'progress-pct',
  'progress-elapsed',
  'help-dialog',
  'help-dialog-close',
  'help-dialog-ok',
  'menu-upload',
  'menu-sculpt',
  'menu-play',
  'menu-prev',
  'menu-next',
  'menu-end',
  'menu-about',
  'menu-presets',
  'mobile-tabs',
  'studio-window',
  'btn-minimize',
  'btn-maximize',
  'btn-close',
]) {
  dom[id] = document.getElementById(id);
}

const menuEntries = document.querySelectorAll('.menu-entry');
const menuTriggers = document.querySelectorAll('.menu-item[data-menu]');
const mobileTabButtons = document.querySelectorAll('.mobile-tab');
const tabPanels = document.querySelectorAll('[data-tab-panel]');

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------

let renderer;
let scene;
let camera;
let controls;
let rig;
let wax;
let previewGroup;
const clock = new THREE.Clock();
const previewMaterial = new THREE.MeshStandardMaterial({
  color: 0xe8d595,
  roughness: 0.6,
  metalness: 0.05,
});

function initScene() {
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  dom.viewport.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf0ede0);

  camera = new THREE.PerspectiveCamera(38, 1, 0.5, 6000);
  camera.position.set(620, 430, 700);
  camera.up.set(0, 1, 0);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 60, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;
  controls.minDistance = 120;
  controls.maxDistance = 2200;
  controls.update();

  // Three-point gallery lighting on a warm cream studio background.
  scene.add(new THREE.HemisphereLight(0xffffff, 0xdcd8cc, 1.15));
  const key = new THREE.DirectionalLight(0xfff4df, 2.1);
  key.position.set(240, 360, 220);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x9fc6ff, 0.9);
  fill.position.set(-240, 160, -220);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xffd700, 0.8);
  rim.position.set(-160, 240, 180);
  scene.add(rim);

  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();

  const grid = new THREE.GridHelper(1600, 80, 0xb8b4a6, 0xd0ccc0);
  grid.position.y = -141;
  grid.material.opacity = 0.4;
  grid.material.transparent = true;
  scene.add(grid);

  previewGroup = new THREE.Group();
  previewGroup.name = 'preview-group';
  scene.add(previewGroup);

  rig = new CadCarverRig(DEFAULT_CONFIG, {
    machineDetail: state.machineDetail,
    onEvent: handleRigEvent,
  });
  // CadCarverRig owns its own -90 deg X-rotated root; add it directly.
  scene.add(rig.root);

  wax = new VolumetricWaxGrid({
    rigRoot: rig.links.static,
    config: DEFAULT_CONFIG,
    gridN: 128,
    chunkSize: 16,
    onCollision: handleCollision,
    onStatus: handleWaxStatus,
  });
  wax.setVisible(Boolean(dom.showStock ? dom.showStock.checked : true));

  if (dom.machineDetailBtn) dom.machineDetailBtn.disabled = true;
  rig.ready.then(() => {
    if (dom.machineDetailBtn) dom.machineDetailBtn.disabled = false;
    applyMachineDetail();
    updateUnassignedNote();
    updateProvenance();
  });
  applyMachineDetail();

  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(() => resize()).observe(dom.viewport);
  }
  window.addEventListener('resize', resize);
  resize();
  renderer.setAnimationLoop(tick);
}

function handleRigEvent(event) {
  if (!event) return;
  if (event.type === 'error') {
    // GLB_LOAD_FAILED must never crash the studio: fall back to the tool only.
    appendDiagnostic({
      code: event.code || 'GLB_LOAD_FAILED',
      severity: event.severity || 'warning',
      message: event.message || 'Machine model failed to load - showing tool only',
      count: 1,
    });
    setStatusState('WARNING', 'warning');
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
      mode === 'full' ? 'Machine Detail: Full' : 'Machine Detail: Tool Only';
    dom.machineDetailBtn.setAttribute('aria-pressed', String(mode === 'tool'));
  }
}

function updateUnassignedNote() {
  const note = dom['unassigned-note'];
  if (!rig || !note) return;
  const parts = rig.getProvenance().unassignedParts || [];
  if (!parts.length) {
    note.hidden = true;
    note.textContent = '';
    return;
  }
  note.hidden = false;
  const names = [...new Set(parts.map((part) => String(part).replace(/:\d+$/, '')))];
  note.textContent = `${parts.length} Unassigned parts not simulated: ${names.join(', ')}`;
  note.setAttribute('aria-pressed', String(!rig.ghostsVisible));
}

function updateProvenance() {
  if (!rig) return;
  const provenance = rig.getProvenance();
  const sha = provenance.stepSha256 ? String(provenance.stepSha256).slice(0, 8) : '-';
  if (dom['provenance-step']) dom['provenance-step'].textContent = `STEP ${sha}`;
  if (dom['provenance-home']) {
    dom['provenance-home'].textContent = ` · home: ${
      provenance.homePose == null ? 'unset' : 'set'
    }`;
  }
}

function resize() {
  if (!renderer || !camera || !dom.viewport) return;
  const width = Math.max(dom.viewport.clientWidth, 1);
  const height = Math.max(dom.viewport.clientHeight, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
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
// API helpers
// ---------------------------------------------------------------------------

async function requestJson(label, url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error(`${label}: no response from server (${error.message})`);
  }
  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      throw new Error(`${label}: non-JSON response (HTTP ${response.status})`);
    }
  }
  if (!response.ok) {
    const detail =
      body && body.detail !== undefined
        ? typeof body.detail === 'string'
          ? body.detail
          : JSON.stringify(body.detail)
        : `HTTP ${response.status}`;
    throw new Error(`${label}: ${detail}`);
  }
  return body;
}

async function loadLimits() {
  try {
    const body = await requestJson('Load limits', '/api/health');
    state.limits = limitsFromHealth(body);
  } catch (error) {
    console.warn('[carver] could not read /api/health; using default upload limits', error);
  }
  applyUploadLimits();
}

function applyUploadLimits() {
  const formats = state.limits.acceptedFormats;
  if (dom['file-input']) dom['file-input'].accept = formats.join(',');
  if (dom['upload-subtitle']) dom['upload-subtitle'].textContent = uploadSubtitle(state.limits);
  if (dom['upload-zone']) {
    const names = formats.map((suffix) => suffix.slice(1).toUpperCase());
    dom['upload-zone'].setAttribute('aria-label', `Upload a custom ${listFormats(names)}`);
  }
}

function populatePresetMenu() {
  const menu = dom['menu-presets'];
  if (!menu) return;
  menu.innerHTML = '<div class="menu-section-label">Bundled Presets</div>';
  for (const preset of state.presets) {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = 'menu-option';
    option.dataset.preset = preset.id;
    option.setAttribute('role', 'menuitemradio');
    option.setAttribute('aria-checked', 'false');

    const check = document.createElement('span');
    check.className = 'menu-check';
    check.setAttribute('aria-hidden', 'true');

    const label = document.createElement('span');
    label.textContent = preset.label || preset.name || preset.id;

    option.append(check, label);
    menu.appendChild(option);
  }
}

async function loadPresets() {
  try {
    const body = await requestJson('Load presets', '/api/presets');
    state.presets = (body && body.presets) || [];
    if (dom['preset-select']) {
      dom['preset-select'].innerHTML = '';
      for (const preset of state.presets) {
        const option = document.createElement('option');
        option.value = preset.id;
        option.textContent = preset.label || preset.name || preset.id;
        dom['preset-select'].appendChild(option);
      }
      if (state.presets.length) dom['preset-select'].value = state.presets[0].id;
    }
    populatePresetMenu();
  } catch (error) {
    if (dom['preset-select']) {
      dom['preset-select'].innerHTML = '<option value="base_head">Base Head</option>';
    }
    if (dom['menu-presets']) {
      dom['menu-presets'].innerHTML = '<div class="menu-section-label">Presets Unavailable</div>';
    }
    setStatusText(`Preset API error: ${error.message}`);
  }
}

function selectPreset(presetId) {
  const preset = state.presets.find((item) => item.id === presetId);
  if (!preset) return;
  state.customFile = null;
  if (dom['preset-select']) dom['preset-select'].value = presetId;
  if (dom['model-note']) {
    dom['model-note'].textContent = `Preset: ${preset.label || preset.name || preset.id}`;
  }
}

// ---------------------------------------------------------------------------
// Upload / preview
// ---------------------------------------------------------------------------

function clearPreview() {
  if (!previewGroup) return;
  for (const child of [...previewGroup.children]) {
    child.geometry?.dispose();
  }
  previewGroup.clear();
}

function addPreviewGeometry(geometry, name) {
  if (!previewGroup) return;
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  const mesh = new THREE.Mesh(geometry, previewMaterial);
  mesh.name = name;
  previewGroup.add(mesh);
  framePreview();
}

function framePreview() {
  if (!previewGroup || !previewGroup.children.length) return;
  const box = new THREE.Box3().setFromObject(previewGroup);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 1);
  controls.target.copy(center);
  camera.position
    .copy(center)
    .add(new THREE.Vector3(1.15, 0.95, 1.35).normalize().multiplyScalar(maxDim * 1.9));
  controls.update();
}

async function previewThreeMf(file) {
  const buffer = await file.arrayBuffer();
  const { positions } = read3mf(buffer, { inflateSync: fflate.inflateSync });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  clearPreview();
  addPreviewGeometry(geometry, file.name);
}

async function handleCustomFile(file) {
  if (!file) return;

  // Refuse before sending anything: the server never sees a bad upload.
  const refusal = checkUploadAllowed(file, state.limits);
  if (refusal) {
    if (dom['model-note']) dom['model-note'].textContent = refusal;
    setStatusText(refusal);
    if (dom['file-input']) dom['file-input'].value = '';
    return;
  }

  state.customFile = file;
  if (dom['model-note']) dom['model-note'].textContent = `Custom: ${file.name}`;
  setStatusText(`Loading ${file.name}...`);

  try {
    const normalized = file.name.toLowerCase();
    if (normalized.endsWith('.stl')) {
      const buffer = await file.arrayBuffer();
      const geometry = new STLLoader().parse(buffer);
      clearPreview();
      addPreviewGeometry(geometry, file.name);
    } else if (normalized.endsWith('.3mf')) {
      await previewThreeMf(file);
    } else {
      const text = await file.text();
      const group = new OBJLoader().parse(text);
      clearPreview();
      group.traverse((child) => {
        if (!child.isMesh) return;
        const geometry = child.geometry;
        geometry.computeVertexNormals();
        const mesh = new THREE.Mesh(geometry, previewMaterial);
        mesh.name = file.name;
        previewGroup.add(mesh);
      });
      framePreview();
    }
    setStatusText(`Preview ready: ${file.name}`);
  } catch (error) {
    console.error(`[carver] could not read local model ${file.name}`, error);
    setStatusText(`Could not read ${file.name}: ${error.message}`);
  }
}

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------

function stockPresetValue() {
  const checked = document.querySelector('input[name="stock-preset"]:checked');
  return checked ? checked.value : 'demo';
}

// ---------------------------------------------------------------------------
// Async toolpath jobs (poll / result / delete-ack)
// ---------------------------------------------------------------------------

/** The job the current poll loop owns; `null` when nothing is generating. */
let activeJob = null;

function phaseLabel(phase) {
  if (!phase) return 'Generating';
  return JOB_PHASE_LABELS.get(phase) || String(phase);
}

/**
 * `aria-live="polite"` announces every text change, so the label is written
 * only when the phase really changed (once per phase, not once per tick).
 */
function setProgressLabel(text) {
  const label = dom['progress-label'];
  if (label && label.textContent !== text) label.textContent = text;
}

function resetProgress() {
  if (dom['progress-fill']) dom['progress-fill'].style.width = '0%';
  if (dom['progress-bar']) dom['progress-bar'].setAttribute('aria-valuenow', '0');
  if (dom['progress-pct']) dom['progress-pct'].textContent = '0%';
  if (dom['progress-elapsed']) dom['progress-elapsed'].textContent = '0 s';
  setProgressLabel('Sculpting');
}

function showProcessingOverlay() {
  resetProgress();
  if (dom['processing-overlay']) dom['processing-overlay'].hidden = false;
}

function hideProcessingOverlay() {
  if (dom['processing-overlay']) dom['processing-overlay'].hidden = true;
}

function updateProgressElapsed() {
  if (!activeJob || !dom['progress-elapsed']) return;
  const seconds = Math.max(0, (Date.now() - activeJob.startedAt) / 1000);
  dom['progress-elapsed'].textContent = `${seconds.toFixed(1)} s`;
}

/** One poll tick: bar width, aria value, percentage, elapsed and phase label. */
function updateProgress(status) {
  const raw = Number(status && status.progress);
  const fraction = Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : 0;
  const percent = Math.round(fraction * 100);
  if (dom['progress-fill']) dom['progress-fill'].style.width = `${fraction * 100}%`;
  if (dom['progress-bar']) dom['progress-bar'].setAttribute('aria-valuenow', String(percent));
  if (dom['progress-pct']) dom['progress-pct'].textContent = `${percent}%`;
  setProgressLabel(phaseLabel(status && status.phase));
  updateProgressElapsed();
}

/**
 * One job-API round trip.  Unlike `requestJson` this keeps the HTTP status and
 * the parsed body, so 202/404/422/429/5xx each take their own path, and it
 * flags transient failures (network, 5xx) so the poller can retry them.
 */
async function jobRequest(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    return { status: 0, ok: false, body: null, transient: true, failure: error.message };
  }
  let text = '';
  try {
    text = await response.text();
  } catch (error) {
    return {
      status: response.status,
      ok: false,
      body: null,
      transient: response.status >= 500,
      failure: error.message,
    };
  }
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  return {
    status: response.status,
    ok: response.ok,
    body,
    transient: response.status >= 500,
    failure: null,
  };
}

/** First human-readable message out of an error body (`detail` or `message`). */
function jobErrorText(body) {
  if (!body || typeof body !== 'object') return null;
  const detail = body.detail;
  const diagnostics = detail && typeof detail === 'object' ? detail.diagnostics : null;
  if (Array.isArray(diagnostics) && diagnostics.length) {
    const first = diagnostics[0] || {};
    const message = String(first.message || first.code || '').trim();
    if (message) return message;
  }
  if (Array.isArray(detail) && detail.length) {
    // FastAPI's own request-validation shape: [{ loc, msg, type }].
    const first = detail[0] || {};
    return String(first.msg || first.message || JSON.stringify(first));
  }
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (typeof body.message === 'string' && body.message.trim()) return body.message;
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return null;
}

function jobFailureMessage(result) {
  if (result.status === 0) return 'Lost contact with the server while generating the toolpath.';
  if (result.status >= 500) return 'The server could not generate the toolpath. Try again.';
  return jobErrorText(result.body) || `Toolpath generation failed (HTTP ${result.status}).`;
}

function reportJobFailure(message) {
  if (dom['sculpt-hint']) dom['sculpt-hint'].textContent = 'error';
  setStatusState('ERROR', 'collision');
  setStatusText(message);
  appendDiagnostic({
    code: 'API_ERROR',
    severity: 'error',
    message,
    count: 1,
  });
}

/** Chain the next tick with `setTimeout`; `visibilitychange` can resolve it early. */
function waitForNextPoll(job) {
  return new Promise((resolve) => {
    job.wake = resolve;
    job.timer = window.setTimeout(() => {
      job.timer = null;
      job.wake = null;
      resolve();
    }, JOB_POLL_INTERVAL_MS);
  });
}

/** Returning to a visible tab polls at once instead of waiting out the tick. */
function wakeActiveJob() {
  if (!activeJob) return;
  if (activeJob.timer) {
    window.clearTimeout(activeJob.timer);
    activeJob.timer = null;
  }
  const wake = activeJob.wake;
  activeJob.wake = null;
  if (wake) wake();
}

function attachPageHide(job) {
  if (job.onPageHide) return;
  job.onPageHide = () => {
    // Best effort: the server cancels the worker and frees its semaphore.
    fetch(`/api/sculpt-and-sim/jobs/${encodeURIComponent(job.id)}`, {
      method: 'DELETE',
      keepalive: true,
    }).catch(() => {});
  };
  window.addEventListener('pagehide', job.onPageHide);
}

function detachPageHide(job) {
  if (!job || !job.onPageHide) return;
  window.removeEventListener('pagehide', job.onPageHide);
  job.onPageHide = null;
}

/** The result is retained until this ack, so a late fetch can still succeed. */
function acknowledgeJob(jobId) {
  fetch(`/api/sculpt-and-sim/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' }).catch(
    () => {}
  );
}

async function fetchJobResult(job) {
  const url = `/api/sculpt-and-sim/jobs/${encodeURIComponent(job.id)}/result`;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const result = await jobRequest(url);
    if (result.ok) {
      if (result.body) return result.body;
      reportJobFailure('The toolpath result arrived empty. Try again.');
      return null;
    }
    if (!result.transient || attempt > 0) {
      reportJobFailure(jobFailureMessage(result));
      return null;
    }
  }
  return null;
}

async function pollJob(job) {
  const url = `/api/sculpt-and-sim/jobs/${encodeURIComponent(job.id)}`;
  for (;;) {
    const result = await jobRequest(url);
    if (!result.ok) {
      if (result.status === 404) {
        reportJobFailure('The toolpath job expired. Press SCULPT & SIMULATE to try again.');
        return null;
      }
      if (result.transient) {
        // Tolerate three consecutive dropped ticks, then give up cleanly.
        job.transientFailures += 1;
        if (job.transientFailures <= JOB_MAX_TRANSIENT_FAILURES) {
          await waitForNextPoll(job);
          continue;
        }
        reportJobFailure('Lost contact with the toolpath job. Try again.');
        return null;
      }
      reportJobFailure(jobFailureMessage(result));
      return null;
    }
    job.transientFailures = 0;
    const status = result.body || {};
    updateProgress(status);
    if (status.status === 'done') return fetchJobResult(job);
    if (status.status === 'error') {
      reportJobFailure(jobFailureMessage(result));
      return null;
    }
    if (status.status === 'cancelled' || status.status === 'cancelling') {
      if (dom['sculpt-hint']) dom['sculpt-hint'].textContent = 'cancelled';
      setStatusState('PAUSED', '');
      setStatusText(status.message || 'Toolpath generation cancelled.');
      return null;
    }
    await waitForNextPoll(job);
  }
}

async function sculptAndSimulate() {
  if (state.generating) return;
  state.generating = true;
  setStatusState('CARVING', '');
  setStatusText('Generating toolpath...');
  if (dom['simulate-button']) dom['simulate-button'].disabled = true;
  if (dom['sculpt-hint']) dom['sculpt-hint'].textContent = 'generating...';
  showProcessingOverlay();

  let job = null;
  try {
    const sliders = {};
    for (const id of SLIDER_IDS) {
      const input = document.getElementById(id);
      sliders[id] = Number(input ? input.value : 0);
    }
    const stockConfig = {
      R_stock_mm: Number(dom['R_stock']?.value) || DEFAULT_CONFIG.stock.R_stock_mm,
      H_stock_mm: Number(dom['H_stock']?.value) || DEFAULT_CONFIG.stock.H_stock_mm,
    };
    const started = await jobRequest('/api/sculpt-and-sim/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sliders,
        preset: stockPresetValue(),
        stock_cfg: stockConfig,
      }),
    });

    if (started.status === 429) {
      reportJobFailure(JOB_STOPPING_MESSAGE);
      return;
    }
    if (!started.ok) {
      reportJobFailure(
        started.status === 422
          ? jobErrorText(started.body) || 'The sculpt request is not valid.'
          : jobFailureMessage(started)
      );
      return;
    }
    if (!started.body || !started.body.job_id) {
      reportJobFailure('The server did not return a toolpath job id.');
      return;
    }

    job = {
      id: started.body.job_id,
      startedAt: Date.now(),
      timer: null,
      wake: null,
      transientFailures: 0,
      onPageHide: null,
    };
    activeJob = job;
    attachPageHide(job);

    const payload = await pollJob(job);
    if (!payload) return;
    loadSimulation(payload);
    acknowledgeJob(job.id);
  } catch (error) {
    reportJobFailure(String(error.message || error));
  } finally {
    if (job) {
      if (job.timer) window.clearTimeout(job.timer);
      job.timer = null;
      job.wake = null;
      detachPageHide(job);
    }
    activeJob = null;
    hideProcessingOverlay();
    state.generating = false;
    if (dom['simulate-button']) dom['simulate-button'].disabled = false;
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
  rig.setTargetVisible(Boolean(dom.showGhost ? dom.showGhost.checked : true));

  wax.setPath(columns, state.frameCount);
  wax.setAuditAll(state.auditAll);
  wax.seek(0);

  if (dom['sim-scrubber']) {
    dom['sim-scrubber'].max = '1000';
    dom['sim-scrubber'].value = '0';
  }
  if (dom['sculpt-hint']) {
    dom['sculpt-hint'].textContent =
      `${state.frameCount.toLocaleString()} frames · ${body.preset} · ` +
      `${Number(body.summary?.generation_ms || 0).toFixed(0)} ms backend`;
  }
  for (const button of ['playBtn', 'nextBtn', 'prevBtn', 'endBtn']) {
    if (dom[button]) dom[button].disabled = false;
  }
  if (dom['sim-scrubber']) dom['sim-scrubber'].disabled = false;
  setStatusText(`Ready · ${state.frameCount.toLocaleString()} frames`);
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
      setStatusState('WARNING', 'warning');
      setStatusText(warning.code);
      rig.setFault(warning.code);
    } else {
      rig.setFault(null);
      setStatusState('READY', '');
    }
  }

  updateRigAt(0);
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

function updateRigAt(index) {
  const frame = frameAt(index);
  if (!frame) return;
  rig.update(frame);
  const ratio = state.frameCount > 1 ? index / (state.frameCount - 1) : 0;
  if (dom['sim-scrubber']) dom['sim-scrubber'].value = String(Math.round(ratio * 1000));
  updateStatusCells(frame);
}

let lastTelemetry = 0;
function updateStatusCells(frame, force = false) {
  if (!frame) return;
  const now = performance.now();
  if (!force && now - lastTelemetry < 90) return;
  lastTelemetry = now;
  if (dom['status-joints']) {
    dom['status-joints'].textContent =
      `r ${frame.r.toFixed(1)} / theta ${(frame.theta_s * RAD_TO_DEG).toFixed(0)} / ` +
      `h ${frame.h.toFixed(1)} / phi ${(frame.phi * RAD_TO_DEG).toFixed(0)}`;
  }
  if (dom['status-tip']) {
    dom['status-tip'].textContent =
      `tip ${frame.tip_xyz_wax.map((value) => value.toFixed(1)).join(', ')}`;
  }
  if (dom['status-feed']) dom['status-feed'].textContent = `v_tip ${frame.v_tip.toFixed(1)} mm/s`;
  if (dom['sim-time']) {
    dom['sim-time'].textContent = `${frame.t.toFixed(2)} / ${state.totalTime.toFixed(2)} s`;
  }
}

function play() {
  if (!state.frames) {
    if (!state.generating) sculptAndSimulate();
    return;
  }
  if (state.index >= state.frameCount - 1) {
    state.index = 0;
    wax.seek(0);
  }
  state.playing = true;
  state.accumulator = 0;
  state.carvingToEnd = false;
  if (dom.playBtn) dom.playBtn.textContent = 'Pause';
  setStatusState('PLAYING', '');
}

function pause() {
  state.playing = false;
  if (dom.playBtn) dom.playBtn.textContent = 'Play';
  if (state.faultCode) return;
  setStatusState('PAUSED', '');
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
  updateStatusCells(frameAt(target), true);
  wax.seek(target, 'scrub');
  if (!state.playing && !state.faultCode) setStatusState('SCRUBBING', '');
}

function stepBy(delta) {
  if (!state.frames) return;
  if (state.playing) pause();
  scrubTo(state.index + delta);
}

function carveToEnd() {
  if (!state.frames) return;
  pause();
  setStatusState('CARVING', '');
  state.carvingToEnd = true;
  wax.seek(state.frameCount - 1, 'end');
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
        updateStatusCells(frameAt(state.index));
        const now = performance.now();
        if (now - state.lastSeekAt > 90) {
          state.lastSeekAt = now;
          wax.seek(state.index, 'play');
        }
        if (state.index >= state.frameCount - 1) {
          pause();
          setStatusState('COMPLETE', '');
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

function setStatusText(text) {
  if (!dom['status-text']) return;
  dom['status-text'].textContent = text;
  dom['status-text'].title = text;
}

function setStatusState(label, tone) {
  const cell = dom['status-state'];
  if (!cell) return;
  cell.className = 'status-cell';
  if (tone === 'collision') cell.classList.add('status-badge-collision');
  else if (tone === 'warning') cell.classList.add('status-badge-warning');
  cell.textContent = label;
}

function showFault(code, body = null) {
  state.faultCode = code;
  const warning = WARNING_CODES.has(code);
  setStatusState(warning ? 'WARNING' : 'FAULT', warning ? 'warning' : 'collision');
  setStatusText(body ? `${code}: ${body}` : code);
  rig.setFault(code, body);
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
    if (dom['sculpt-hint']) {
      dom['sculpt-hint'].textContent =
        `Wax grid ${message.gridN}^3 · ${message.voxelSize.toFixed(2)} mm voxel`;
    }
  }
  if (message.type === 'collisions') {
    state.collisionLog.worker = (message.runs || []).map(enrichCollisionRun);
    renderCollisionLog();
  }
  if (message.type === 'progress' && state.carvingToEnd) {
    state.index = Math.max(state.index, message.index);
    updateRigAt(state.index);
    updateStatusCells(frameAt(state.index));
  }
  if (message.type === 'meshes' && message.reason === 'progress' && state.carvingToEnd) {
    state.index = Math.max(state.index, message.index);
    updateRigAt(state.index);
    updateStatusCells(frameAt(state.index));
  }
  if (message.type === 'meshes' && message.reason === 'end') {
    state.carvingToEnd = false;
    state.index = state.frameCount - 1;
    updateRigAt(state.index);
    updateStatusCells(frameAt(state.index), true);
    setStatusState('COMPLETE', '');
  }
  if (message.type === 'meshes' && message.reason === 'scrub' && !state.playing) {
    setStatusState('PAUSED', '');
  }
  if (message.faulted) pause();
}

function renderDiagnostics() {
  if (!dom.diagnostics) return;
  dom.diagnostics.innerHTML = '';
  const diagnostics = state.diagnostics;
  if (dom['diag-count']) dom['diag-count'].textContent = `${diagnostics.length}`;
  if (!diagnostics.length) {
    appendDiagnostic({
      code: 'CLEAN',
      severity: 'info',
      message: 'No diagnostics reported for this toolpath.',
      count: 1,
    });
    return;
  }
  for (const diagnostic of diagnostics) appendDiagnostic(diagnostic);
}

function appendDiagnostic(diagnostic) {
  if (!dom.diagnostics) return;
  const div = document.createElement('div');
  div.className = `diag ${diagnostic.severity || 'info'}`;
  const count = diagnostic.count && diagnostic.count > 1 ? ` x${diagnostic.count}` : '';
  const value = typeof diagnostic.value === 'number' ? ` · ${diagnostic.value.toFixed(2)}` : '';
  div.innerHTML = `<code>${diagnostic.code}${count}</code><br>${diagnostic.message || ''}${value}`;
  dom.diagnostics.appendChild(div);
  if (dom['diag-count']) dom['diag-count'].textContent = String(dom.diagnostics.children.length);
}

// ---------------------------------------------------------------------------
// XP shell wiring
// ---------------------------------------------------------------------------

if (dom.auditAll) {
  dom.auditAll.addEventListener('change', () => {
    state.auditAll = dom.auditAll.checked;
    state.faultCode = null;
    state.faultFrame = null;
    if (rig) rig.setFault(null);
    state.collisionLog.worker = [];
    if (wax && wax.setAuditAll) wax.setAuditAll(state.auditAll);
    state.index = 0;
    updateRigAt(0);
    updateTelemetry(true);
    if (state.frames) setStatusState(state.auditAll ? 'AUDITING' : 'READY', '');
  });
}

function closeMenus() {
  for (const entry of menuEntries) {
    entry.querySelector('.menu-item')?.setAttribute('aria-expanded', 'false');
    const dropdown = entry.querySelector('.menu-dropdown');
    if (dropdown) dropdown.hidden = true;
  }
}

function openMenu(name) {
  for (const entry of menuEntries) {
    const trigger = entry.querySelector('.menu-item');
    const dropdown = entry.querySelector('.menu-dropdown');
    const shouldOpen = Boolean(trigger && trigger.dataset.menu === name && dropdown);
    trigger?.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    if (dropdown) dropdown.hidden = !shouldOpen;
  }
}

function anyMenuOpen() {
  return Boolean(document.querySelector('.menu-dropdown:not([hidden])'));
}

function switchMobileTab(tabName) {
  const target = MOBILE_TABS.includes(tabName) ? tabName : 'model';
  for (const button of mobileTabButtons) {
    const active = button.dataset.tab === target;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  }
  for (const panel of tabPanels) {
    panel.classList.toggle('mobile-panel-active', panel.dataset.tabPanel === target);
  }
  requestAnimationFrame(resize);
}

function openHelpDialog() {
  closeMenus();
  if (!dom['help-dialog']) return;
  dom['help-dialog'].hidden = false;
  dom['help-dialog-close']?.focus();
}

function closeHelpDialog() {
  if (dom['help-dialog']) dom['help-dialog'].hidden = true;
}

function syncSliderOutputs() {
  for (const id of SLIDER_IDS) {
    const input = document.getElementById(id);
    const output = document.getElementById(`${id}-value`);
    if (!input || !output) continue;
    const sync = () => {
      output.textContent = Number(input.value).toFixed(2);
    };
    input.addEventListener('input', sync);
    sync();
  }
}

function wireEvents() {
  if (dom['simulate-button']) dom['simulate-button'].addEventListener('click', sculptAndSimulate);

  if (dom['upload-zone'] && dom['file-input']) {
    dom['upload-zone'].addEventListener('click', () => dom['file-input'].click());
    dom['upload-zone'].addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        dom['file-input'].click();
      }
    });
    dom['file-input'].addEventListener('change', () => handleCustomFile(dom['file-input'].files[0]));
    for (const eventName of ['dragenter', 'dragover']) {
      dom['upload-zone'].addEventListener(eventName, (event) => {
        event.preventDefault();
        dom['upload-zone'].classList.add('dragover');
      });
    }
    for (const eventName of ['dragleave', 'drop']) {
      dom['upload-zone'].addEventListener(eventName, (event) => {
        event.preventDefault();
        dom['upload-zone'].classList.remove('dragover');
      });
    }
    dom['upload-zone'].addEventListener('drop', (event) => {
      const file = event.dataTransfer?.files?.[0];
      if (file) handleCustomFile(file);
    });
  }

  dom['preset-select']?.addEventListener('change', () => selectPreset(dom['preset-select'].value));

  dom.playBtn?.addEventListener('click', togglePlay);
  dom.prevBtn?.addEventListener('click', () => stepBy(-1));
  dom.nextBtn?.addEventListener('click', () => stepBy(1));
  dom.endBtn?.addEventListener('click', carveToEnd);

  dom['sim-scrubber']?.addEventListener('input', () => {
    if (!state.frames) return;
    if (state.playing) pause();
    const ratio = Number(dom['sim-scrubber'].value) / 1000;
    scrubTo(Math.round(ratio * (state.frameCount - 1)));
  });
  dom['sim-speed']?.addEventListener('change', () => {
    state.speed = Number(dom['sim-speed'].value) || 1;
  });

  dom.showGhost?.addEventListener('change', () => {
    if (rig) rig.setTargetVisible(dom.showGhost.checked);
  });
  dom.showStock?.addEventListener('change', () => {
    if (wax) wax.setVisible(dom.showStock.checked);
  });
  dom.machineDetailBtn?.addEventListener('click', () => {
    if (dom.machineDetailBtn.disabled) return;
    state.machineDetail = state.machineDetail === 'full' ? 'tool' : 'full';
    applyMachineDetail();
  });
  dom['unassigned-note']?.addEventListener('click', () => {
    if (!rig) return;
    rig.setGhostVisible(!rig.ghostsVisible);
    updateUnassignedNote();
  });

  for (const trigger of menuTriggers) {
    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      const name = trigger.dataset.menu;
      const dropdown = document.getElementById(`menu-${name}`);
      const wasOpen = dropdown ? !dropdown.hidden : false;
      closeMenus();
      if (!wasOpen) openMenu(name);
    });
    trigger.addEventListener('pointerenter', () => {
      if (window.matchMedia?.('(hover: hover)').matches && anyMenuOpen()) {
        openMenu(trigger.dataset.menu);
      }
    });
  }

  document.addEventListener('pointerdown', (event) => {
    if (!event.target.closest('.menu-entry')) closeMenus();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeMenus();
      closeHelpDialog();
    }
  });

  // A background tab throttles timers and the server abandons silent jobs, so
  // the first thing a returning tab does is poll.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') wakeActiveJob();
  });

  dom['menu-upload']?.addEventListener('click', () => {
    closeMenus();
    dom['file-input']?.click();
  });
  dom['menu-sculpt']?.addEventListener('click', () => {
    closeMenus();
    sculptAndSimulate();
  });
  dom['menu-play']?.addEventListener('click', () => {
    closeMenus();
    togglePlay();
  });
  dom['menu-prev']?.addEventListener('click', () => {
    closeMenus();
    stepBy(-1);
  });
  dom['menu-next']?.addEventListener('click', () => {
    closeMenus();
    stepBy(1);
  });
  dom['menu-end']?.addEventListener('click', () => {
    closeMenus();
    carveToEnd();
  });
  dom['menu-about']?.addEventListener('click', openHelpDialog);
  dom['menu-presets']?.addEventListener('click', (event) => {
    const option = event.target.closest('[data-preset]');
    if (!option) return;
    selectPreset(option.dataset.preset);
    closeMenus();
  });

  for (const button of mobileTabButtons) {
    button.addEventListener('click', () => switchMobileTab(button.dataset.tab));
  }

  dom['help-dialog']?.addEventListener('click', (event) => {
    if (event.target === dom['help-dialog']) closeHelpDialog();
  });
  dom['help-dialog-close']?.addEventListener('click', closeHelpDialog);
  dom['help-dialog-ok']?.addEventListener('click', closeHelpDialog);

  dom['btn-minimize']?.addEventListener('click', () => {
    dom['studio-window']?.classList.toggle('minimized');
    setTimeout(resize, 30);
  });
  dom['btn-maximize']?.addEventListener('click', () => {
    dom['studio-window']?.classList.toggle('maximized');
    setTimeout(resize, 30);
  });
  dom['btn-close']?.addEventListener('click', () => {
    if (window.confirm('Close 4-DOF Wax Carver Studio 2001?')) {
      if (dom['studio-window']) dom['studio-window'].style.display = 'none';
    }
  });
}

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

function start() {
  initScene();
  wireEvents();
  syncSliderOutputs();
  applyMachineDetail();
  switchMobileTab('model');
  updateUnassignedNote();
  updateProvenance();
  loadLimits();
  loadPresets();
  sculptAndSimulate();
}

try {
  start();
} catch (error) {
  setStatusState('WEBGL ERROR', 'collision');
  setStatusText(`WebGL unavailable: ${error.message}`);
  if (dom.viewport) {
    dom.viewport.innerHTML =
      `<div style="padding:24px;color:#e81123;font-family:monospace">WebGL unavailable: ${error.message}</div>`;
  }
}

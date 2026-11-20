/**
 * CAD-derived 4-DOF carver rig.
 *
 * Loads the per-link GLBs exported by `scripts/extract_machine.py` and nests
 * them `static ⊃ orbit ⊃ z ⊃ radial ⊃ tilt` inside the existing -90 deg
 * X-rotated root group.  Per frame this file sets ONLY:
 *
 *   - orbit rotation about machine Z by `+theta`
 *   - z translation by `h - cad_reference_pose.h` along local +Z
 *   - radial translation by `r - cad_reference_pose.r` along local +X
 *   - tilt rotation about the pivot line by `phi`
 *
 * There is no kinematic trigonometry here: backend frames carry every joint
 * value and `tip_xyz_wax`.  The `scene.*` colour tokens live in one material
 * factory so every link uses exactly one colour.
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const ROOT_ROTATION_X = -Math.PI / 2;

const MODEL_LINKS = ['static', 'orbit', 'z', 'radial', 'tilt', 'unassigned'];

export const SCENE_COLORS = Object.freeze({
  wax: '#b91c1c',
  static: '#4b5563',
  orbit: '#64748b',
  z: '#7c8796',
  radial: '#94a3b8',
  tilt: '#cbd5e1',
  bladeHeated: '#f97316',
  unassignedGhost: '#a78bfa',
  //: High-contrast cyan: the tool collision highlight reads at a glance against
  //: the deep red wax, including for red-green colour-blind viewers.
  collision: '#22d3ee',
  warning: '#f59e0b',
});

const METALNESS = 0.3;
const ROUGHNESS = 0.6;

/**
 * One material factory for the whole rig.  Link greys get lighter from the
 * base to the tool, which is the only colour coding used.
 */
export function createSceneMaterials() {
  const cache = new Map();
  const standard = (key, options) => {
    if (!cache.has(key)) {
      cache.set(
        key,
        new THREE.MeshStandardMaterial({
          metalness: METALNESS,
          roughness: ROUGHNESS,
          ...options,
        })
      );
    }
    return cache.get(key);
  };

  const links = {};
  for (const link of ['static', 'orbit', 'z', 'radial', 'tilt']) {
    links[link] = standard(`link:${link}`, { color: new THREE.Color(SCENE_COLORS[link]) });
  }

  return {
    links,
    wax: standard('wax', {
      color: new THREE.Color(SCENE_COLORS.wax),
      metalness: 0.05,
      roughness: 0.58,
    }),
    heated: standard('heated', {
      color: new THREE.Color(SCENE_COLORS.bladeHeated),
      emissive: new THREE.Color(SCENE_COLORS.bladeHeated),
      emissiveIntensity: 0.25,
    }),
    fault: standard('fault', {
      color: new THREE.Color(SCENE_COLORS.collision),
      emissive: new THREE.Color(SCENE_COLORS.collision),
      emissiveIntensity: 0.6,
    }),
    warning: standard('warning', {
      color: new THREE.Color(SCENE_COLORS.warning),
      emissive: new THREE.Color(SCENE_COLORS.warning),
      emissiveIntensity: 0.5,
    }),
    ghost: standard('ghost', {
      color: new THREE.Color(SCENE_COLORS.unassignedGhost),
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
    }),
    target: standard('target', {
      color: new THREE.Color('#60a5fa'),
      transparent: true,
      opacity: 0.16,
      wireframe: true,
      depthWrite: false,
      emissive: new THREE.Color('#1d4ed8'),
      emissiveIntensity: 0.25,
    }),
  };
}

function numberOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function vectorOr(value, fallback) {
  if (Array.isArray(value) && value.length === 3) {
    const parsed = value.map((item) => Number(item));
    if (parsed.every((item) => Number.isFinite(item))) return parsed;
  }
  return fallback;
}

export class CadCarverRig {
  constructor(config = {}, options = {}) {
    this.config = config || {};
    this.options = options;
    this.onEvent = options.onEvent || (() => {});

    this.materials = createSceneMaterials();
    this.machineDetail = options.machineDetail === 'tool' ? 'tool' : 'full';
    this.ghostsVisible = true;
    this.machineFailed = false;
    this.loaded = false;
    this.loadError = null;
    this.lastPose = null;
    this.unassignedParts = [];
    this._originalMaterials = new Map();

    this.root = new THREE.Group();
    this.root.name = 'machine-root';
    this.root.rotation.x = ROOT_ROTATION_X;

    // Transform-only hierarchy.  Model geometry is parented into the per-link
    // `modelGroups` so the machine-detail toggle can hide links without hiding
    // their descendants (notably the wax, which is parented to `static`).
    this.links = {
      static: new THREE.Group(),
      orbit: new THREE.Group(),
      z: new THREE.Group(),
      radial: new THREE.Group(),
      tilt: new THREE.Group(),
    };
    this.links.static.name = 'static-link';
    this.links.orbit.name = 'orbit-link';
    this.links.z.name = 'z-link';
    this.links.radial.name = 'radial-link';
    this.links.tilt.name = 'tilt-link';

    this.root.add(this.links.static);
    this.links.static.add(this.links.orbit);
    this.links.orbit.add(this.links.z);
    this.links.z.add(this.links.radial);
    this.links.radial.add(this.links.tilt);

    this.modelGroups = {};
    for (const link of ['static', 'orbit', 'z', 'radial', 'tilt']) {
      const group = new THREE.Group();
      group.name = `model-${link}`;
      this.modelGroups[link] = group;
      if (link !== 'tilt') this.links[link].add(group);
    }

    this.unassignedGroup = new THREE.Group();
    this.unassignedGroup.name = 'model-unassigned';
    this.links.static.add(this.unassignedGroup);

    // Pre-baked tilt pivot: translate to the pivot, rotate, translate back.
    this.tiltPivot = new THREE.Group();
    this.tiltPivot.name = 'tilt-pivot';
    this.links.tilt.add(this.tiltPivot);

    this.tiltOffset = new THREE.Group();
    this.tiltOffset.name = 'tilt-pivot-offset';
    this.tiltPivot.add(this.tiltOffset);

    // The imported tilt GLB must live inside the pre-baked pivot group, not as
    // a sibling of it in `links.tilt`, or `update()` would rotate only the tip
    // marker and leave the CAD cartridge, holder and horn stationary.
    this.tiltOffset.add(this.modelGroups.tilt);

    this.tipMarker = new THREE.Mesh(
      new THREE.SphereGeometry(1.25, 16, 12),
      this.materials.heated
    );
    this.tipMarker.name = 'tip-marker';
    this.tiltOffset.add(this.tipMarker);

    this.targetGhost = new THREE.Group();
    this.targetGhost.name = 'target-ghost';
    this.root.add(this.targetGhost);

    this._applyConfig(this.config);
    this._buildHeatedOverlay();
    this._buildFallbackTool();
    this._refreshVisibility();

    this.ready = this._loadModels();
  }

  // -------------------------------------------------------------------------
  // Configuration
  // -------------------------------------------------------------------------

  configure(config = {}) {
    this.config = config || {};
    this._applyConfig(this.config);
    this._refreshVisibility();
    return this;
  }

  _applyConfig(config) {
    const geometry = config.geometry || {};
    const reference = geometry.cad_reference_pose || config.cad_reference_pose || {};
    this.cadReference = {
      h: numberOr(reference.h, 151.0),
      r: numberOr(reference.r, 0.0),
      theta: numberOr(reference.theta_deg, 0.0),
      phi: numberOr(reference.phi_deg, 0.0),
    };

    this.pivotPoint = vectorOr(geometry.pivot_point_mm, [0.0, 0.0, this.cadReference.h]);
    this.pivotAxis = new THREE.Vector3(
      ...vectorOr(geometry.pivot_axis_mm, [0.0, -1.0, 0.0])
    ).normalize();
    // The recorded axis is an unoriented line (currently -Y, the servo-horn
    // direction).  Positive phi is about the local +e_theta direction, which is
    // machine +Y at theta = 0, so the Euler Y angle is +phi.
    this.tiltSign = 1;
    this.pivotToTip = numberOr(config.pivot_to_tip_mm, numberOr(geometry.pivot_to_tip_mm, 60.0));
    this.toolReference = vectorOr(
      geometry.tool_reference_point_mm,
      [0.0, 0.0, this.pivotPoint[2] - this.pivotToTip]
    );

    const provenance = config.geometry_provenance || {};
    this.stepSha256 = provenance.step_sha256 || geometry.step_sha256 || null;
    this.homePose = provenance.home_pose ?? geometry.home_pose ?? null;
    this.unassignedParts =
      geometry.unassigned_parts || provenance.unassigned_parts || [];

    this.tiltPivot.position.set(
      this.pivotPoint[0],
      this.pivotPoint[1],
      this.pivotPoint[2]
    );
    this.tiltOffset.position.set(
      -this.pivotPoint[0],
      -this.pivotPoint[1],
      -this.pivotPoint[2]
    );
    this.tipMarker.position.set(
      this.toolReference[0],
      this.toolReference[1],
      this.toolReference[2]
    );
    if (this.heatedOverlay) {
      const tool = this.config.tool || {};
      const length = numberOr(
        tool.heated_length_mm,
        numberOr(tool.blade_length_mm, 14.0)
      );
      this.heatedOverlay.position.set(
        this.toolReference[0],
        this.toolReference[1],
        this.toolReference[2] + length / 2
      );
    }
  }

  getProvenance() {
    return {
      stepSha256: this.stepSha256,
      homePose: this.homePose,
      unassignedParts: [...this.unassignedParts],
    };
  }

  // -------------------------------------------------------------------------
  // Scene construction
  // -------------------------------------------------------------------------

  _buildHeatedOverlay() {
    const tool = this.config.tool || {};
    const thickness = numberOr(tool.blade_thickness_mm, 1.2);
    const width = numberOr(tool.blade_width_mm, 6.0);
    const length = numberOr(
      tool.heated_length_mm,
      numberOr(tool.blade_length_mm, 14.0)
    );
    // At the CAD reference pose the heated box spans s in [0, heated_length]
    // along -u = +Z from the tool reference point.
    const geometry = new THREE.BoxGeometry(thickness, width, length);
    this.heatedOverlay = new THREE.Mesh(geometry, this.materials.heated);
    this.heatedOverlay.name = 'blade-heated';
    this.heatedOverlay.position.set(
      this.toolReference[0],
      this.toolReference[1],
      this.toolReference[2] + length / 2
    );
    this.tiltOffset.add(this.heatedOverlay);
  }

  _buildFallbackTool() {
    const tool = this.config.tool || {};
    const thickness = numberOr(tool.blade_thickness_mm, 1.2);
    const width = numberOr(tool.blade_width_mm, 6.0);
    const bladeLength = numberOr(tool.blade_length_mm, 14.0);
    const heatedLength = Math.min(
      numberOr(tool.heated_length_mm, bladeLength),
      bladeLength
    );
    const shaftRadius = numberOr(tool.shaft_radius_mm, 2.5);
    const bodyRadius = numberOr(tool.body_radius_mm, 3.5);
    const shaftSpan = Array.isArray(tool.shaft_span_mm)
      ? tool.shaft_span_mm.map(Number)
      : [14.0, 75.0];
    const bodySpan = Array.isArray(tool.body_span_mm)
      ? tool.body_span_mm.map(Number)
      : [75.0, 140.0];

    this.fallbackTool = new THREE.Group();
    this.fallbackTool.name = 'fallback-tool';
    this.fallbackTool.visible = false;
    this.tiltOffset.add(this.fallbackTool);

    const tip = this.toolReference;
    const blade = new THREE.Mesh(
      new THREE.BoxGeometry(thickness, width, heatedLength),
      this.materials.heated
    );
    blade.position.set(tip[0], tip[1], tip[2] + heatedLength / 2);
    this.fallbackTool.add(blade);

    const addCylinder = (radius, span, material) => {
      const height = Math.max(span[1] - span[0], 0.001);
      const mesh = new THREE.Mesh(
        new THREE.CylinderGeometry(radius, radius, height, 20, 1, false),
        material
      );
      // Cylinders are Y-up; rotate into the machine Z-up local frame and centre
      // the axial span measured from the tool reference point along -u = +Z.
      mesh.rotation.x = Math.PI / 2;
      mesh.position.set(tip[0], tip[1], tip[2] + (span[0] + span[1]) / 2);
      this.fallbackTool.add(mesh);
      return mesh;
    };
    this.fallbackShaft = addCylinder(shaftRadius, shaftSpan, this.materials.links.tilt);
    this.fallbackBody = addCylinder(bodyRadius, bodySpan, this.materials.links.tilt);
  }

  // -------------------------------------------------------------------------
  // GLB loading
  // -------------------------------------------------------------------------

  _modelUrl(name) {
    if (this.options.modelUrls && this.options.modelUrls[name]) {
      return this.options.modelUrls[name];
    }
    return new URL(`./models/${name}.glb`, import.meta.url).href;
  }

  _loadOne(loader, name) {
    const buffers = this.options.modelBuffers;
    if (buffers && buffers[name]) {
      return new Promise((resolve, reject) => {
        try {
          loader.parse(buffers[name], '', resolve, reject);
        } catch (error) {
          reject(error);
        }
      });
    }
    return new Promise((resolve, reject) => {
      loader.load(this._modelUrl(name), resolve, undefined, reject);
    });
  }

  async _loadModels() {
    const loader = new GLTFLoader();
    try {
      const loaded = {};
      for (const name of MODEL_LINKS) {
        // The rectangular CAD wax block is a `stock_placeholder` and must never
        // be rendered (there is no exported mesh for it).
        loaded[name] = await this._loadOne(loader, name);
      }
      for (const name of MODEL_LINKS) {
        const target =
          name === 'unassigned' ? this.unassignedGroup : this.modelGroups[name];
        this._attachModel(name, loaded[name], target);
      }
      this.loaded = true;
      this._refreshVisibility();
      this.onEvent({ type: 'loaded', links: MODEL_LINKS.slice() });
      return true;
    } catch (error) {
      this._enterFallback(error);
      return false;
    }
  }

  _attachModel(name, gltf, target) {
    const material =
      name === 'unassigned' ? this.materials.ghost : this.materials.links[name];
    const scene = gltf.scene || gltf.scenes?.[0];
    if (!scene) return;
    scene.traverse((child) => {
      if (!child.isMesh) return;
      child.material = material;
      child.castShadow = false;
      child.receiveShadow = false;
      this._originalMaterials.set(child, material);
      if (name === 'tilt') {
        const nodeName = String(child.name || '');
        if (nodeName.startsWith('T12_K_Cartridge')) {
          this.cartridgeMeshes = this.cartridgeMeshes || [];
          this.cartridgeMeshes.push(child);
        } else {
          this.headMeshes = this.headMeshes || [];
          this.headMeshes.push(child);
        }
      }
    });
    scene.name = name === 'unassigned' ? 'unassigned-model' : `${name}-model`;
    target.add(scene);
    target.visible = !this.machineFailed;
  }

  _enterFallback(error) {
    this.machineFailed = true;
    this.loaded = false;
    this.loadError = error;
    for (const group of Object.values(this.modelGroups)) group.visible = false;
    for (const group of [this.unassignedGroup, this.targetGhost]) group.visible = false;
    if (this.fallbackTool) this.fallbackTool.visible = true;
    this.onEvent({
      type: 'error',
      code: 'GLB_LOAD_FAILED',
      severity: 'warning',
      message: 'Machine model failed to load — showing tool only',
      error: String(error?.message || error),
    });
  }

  // -------------------------------------------------------------------------
  // Frame update
  // -------------------------------------------------------------------------

  /**
   * Apply one backend frame.  Only transforms are set here.
   *
   * `frame` carries `r`, `theta_s`, `h`, `phi` and `tip_xyz_wax`; the GLBs are
   * already in machine coordinates at `cad_reference_pose`, so each joint is a
   * delta from that pose.
   */
  update(frame) {
    if (!frame) return;
    this.lastPose = frame;
    const theta = numberOr(frame.theta_s ?? frame.theta, 0);
    const phi = numberOr(frame.phi, 0);
    const h = numberOr(frame.h, this.cadReference.h);
    const r = numberOr(frame.r, this.cadReference.r);

    this.links.orbit.rotation.set(0, 0, theta);
    this.links.z.position.set(0, 0, h - this.cadReference.h);
    this.links.radial.position.set(r - this.cadReference.r, 0, 0);
    // Pre-baked translate-rotate-translate pivot: the pivot group sits at
    // `pivot_point_mm` and the geometry group sits at its negative offset.
    // +phi is about +e_theta (machine +Y at theta = 0); the extracted
    // pivot_axis_mm is the same tangential line, so only its sign is used.
    this.tiltPivot.rotation.set(0, this.tiltSign * phi, 0);
  }

  /** World position of the cartridge's lowest point (for tests and HUD). */
  getTipWorld(target = new THREE.Vector3()) {
    this.root.updateMatrixWorld(true);
    return this.tipMarker.getWorldPosition(target);
  }

  setMachineDetail(mode) {
    this.machineDetail = mode === 'tool' ? 'tool' : 'full';
    this._refreshVisibility();
  }

  setGhostVisible(visible) {
    this.ghostsVisible = Boolean(visible);
    this._refreshVisibility();
  }

  setFault(code, body = null) {
    this._restoreMaterials();
    if (!code) return;
    const material =
      code === 'SINGULARITY_HIGH_THETA_DOT' ||
      code === 'UNREACHABLE_UNDERCUT_AREA' ||
      code === 'BLADE_BROADSIDE_FEED'
        ? this.materials.warning
        : this.materials.fault;

    let targets = [];
    if (body === 'shaft' || body === 'body') {
      targets = [...(this.cartridgeMeshes || [])];
    } else if (body === 'head') {
      targets = [...(this.headMeshes || [])];
    } else {
      targets = [
        ...(this.heatedOverlay ? [this.heatedOverlay] : []),
        ...(this.cartridgeMeshes || []),
      ];
    }
    for (const mesh of targets) mesh.material = material;
  }

  _restoreMaterials() {
    for (const [mesh, material] of this._originalMaterials) {
      mesh.material = material;
    }
    if (this.heatedOverlay) this.heatedOverlay.material = this.materials.heated;
  }

  _refreshVisibility() {
    const full = this.machineDetail === 'full';
    const failed = this.machineFailed;
    this.modelGroups.static.visible = !failed && full;
    this.modelGroups.orbit.visible = !failed && full;
    this.modelGroups.z.visible = !failed && full;
    this.modelGroups.radial.visible = !failed;
    this.modelGroups.tilt.visible = !failed;
    this.unassignedGroup.visible =
      !failed && full && this.ghostsVisible && this.unassignedParts.length > 0;
    if (this.fallbackTool) this.fallbackTool.visible = failed;
    if (this.heatedOverlay) this.heatedOverlay.visible = !failed;
  }

  // -------------------------------------------------------------------------
  // App compatibility helpers
  // -------------------------------------------------------------------------

  setTargetMesh(geometry) {
    this.targetGhost.clear();
    const mesh = new THREE.Mesh(geometry, this.materials.target);
    mesh.name = 'target-ghost-mesh';
    this.targetGhost.add(mesh);
  }

  setTargetVisible(visible) {
    this.targetGhost.visible = Boolean(visible) && !this.machineFailed;
  }
}

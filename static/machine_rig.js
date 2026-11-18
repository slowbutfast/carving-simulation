/**
 * Primitive 4-DOF carver rig.
 *
 * The whole machine lives inside a root group rotated -90 deg about +X so the
 * machine frame (+Z up) maps to the Three.js world (+Y up).  Every joint
 * transform comes from backend-sampled poses; this file performs no kinematic
 * trigonometry (no Math.sin / Math.cos calls).
 */

import * as THREE from 'three';

const ROOT_ROTATION_X = -Math.PI / 2;
const Z_AXIS = new THREE.Vector3(0, 0, 1);
const PLATTER_TICKS = [
  [1, 0], [0.7071, 0.7071], [0, 1], [-0.7071, 0.7071],
  [-1, 0], [-0.7071, -0.7071], [0, -1], [0.7071, -0.7071],
];

function steelMaterial(color = 0x94a3b8, roughness = 0.42, metalness = 0.85) {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness });
}

export class PrimitiveCarverRig {
  constructor(config = {}) {
    this.config = config;
    const stock = config.stock || {};
    this.R_stock = stock.R_stock_mm ?? 40;
    this.z_plinth = stock.z_plinth_mm ?? 10;
    this.columnX = (config.arm_radial_offset_mm ?? 45) + 60;
    this.pivotDrop = config.arm_to_pivot_z_mm ?? 25;
    this.pivotToTip = config.pivot_to_tip_mm ?? 30;
    this.tool = config.tool || {};

    this.root = new THREE.Group();
    this.root.name = 'machine-root';
    this.root.rotation.x = ROOT_ROTATION_X;

    this.materials = {
      steel: steelMaterial(),
      darkSteel: steelMaterial(0x475569, 0.55, 0.7),
      platter: steelMaterial(0x64748b, 0.35, 0.9),
      wax: new THREE.MeshStandardMaterial({ color: 0xe8d595, roughness: 0.62, metalness: 0.05 }),
      heated: new THREE.MeshStandardMaterial({
        color: 0xf59e0b,
        emissive: 0xb45309,
        emissiveIntensity: 0.55,
        roughness: 0.35,
        metalness: 0.55,
      }),
      shank: steelMaterial(0xcbd5e1, 0.3, 0.95),
      fault: new THREE.MeshStandardMaterial({
        color: 0xef4444,
        emissive: 0x991b1b,
        emissiveIntensity: 0.7,
        roughness: 0.4,
        metalness: 0.3,
      }),
      warning: new THREE.MeshStandardMaterial({
        color: 0xf59e0b,
        emissive: 0x92400e,
        emissiveIntensity: 0.6,
        roughness: 0.4,
        metalness: 0.3,
      }),
    };

    this.platterGroup = new THREE.Group();
    this.root.add(this.platterGroup);
    this._buildPlatter();

    this.column = new THREE.Mesh(new THREE.BoxGeometry(9, 9, 1), this.materials.darkSteel);
    this.column.position.set(this.columnX, 0, 1);
    this.root.add(this.column);

    this.arm = new THREE.Mesh(new THREE.BoxGeometry(1, 6, 6), this.materials.steel);
    this.root.add(this.arm);

    this.carriage = new THREE.Mesh(new THREE.BoxGeometry(12, 11, 11), this.materials.darkSteel);
    this.root.add(this.carriage);

    this.wristMount = new THREE.Mesh(new THREE.BoxGeometry(5, 5, 1), this.materials.darkSteel);
    this.root.add(this.wristMount);

    this.wrist = new THREE.Group();
    this.root.add(this.wrist);
    const wristJoint = new THREE.Mesh(
      new THREE.SphereGeometry(3.4, 20, 14),
      this.materials.steel
    );
    this.wrist.add(wristJoint);

    this.toolGroup = new THREE.Group();
    this.root.add(this.toolGroup);
    this._buildTool();

    this.targetGhost = new THREE.Group();
    this.root.add(this.targetGhost);

    this.lastPose = null;
    this.faultCode = null;
  }

  _buildPlatter() {
    const platter = new THREE.Mesh(
      new THREE.CylinderGeometry(this.R_stock, this.R_stock * 1.06, this.z_plinth, 72, 1, false),
      this.materials.platter
    );
    platter.rotation.x = Math.PI / 2;
    platter.position.z = this.z_plinth / 2;
    this.platterGroup.add(platter);

    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(this.R_stock * 1.03, 0.8, 10, 72),
      this.materials.darkSteel
    );
    rim.rotation.x = Math.PI / 2;
    rim.position.z = this.z_plinth;
    this.platterGroup.add(rim);

    const tickGeometry = new THREE.BoxGeometry(1.4, 4, 1.2);
    for (const [ux, uy] of PLATTER_TICKS) {
      const tick = new THREE.Mesh(tickGeometry, this.materials.heated);
      tick.position.set(ux * this.R_stock * 0.86, uy * this.R_stock * 0.86, this.z_plinth + 0.6);
      this.platterGroup.add(tick);
    }
  }

  _buildTool() {
    const engaged = this.tool.engaged_length_mm ?? 8;
    const tipRadius = this.tool.tip_radius_mm ?? 0.5;
    const shankLength = this.tool.shank_length_mm ?? 40;
    const shankRadius = this.tool.shank_radius_mm ?? 3;
    const halfAngle = ((this.tool.cone_half_angle_deg ?? 30) * Math.PI) / 180;
    const baseRadius = Math.min(tipRadius + engaged * Math.tan(halfAngle), 8);

    const cone = new THREE.Mesh(
      new THREE.CylinderGeometry(0.05, baseRadius, engaged, 24, 1, true),
      this.materials.heated
    );
    cone.geometry.translate(0, -engaged / 2, 0);
    cone.geometry.rotateX(Math.PI / 2);
    this.toolGroup.add(cone);

    const shank = new THREE.Mesh(
      new THREE.CylinderGeometry(shankRadius, shankRadius, shankLength, 20, 1, false),
      this.materials.shank
    );
    shank.geometry.translate(0, -(engaged + shankLength / 2), 0);
    shank.geometry.rotateX(Math.PI / 2);
    this.toolGroup.add(shank);

    this.heatGlow = new THREE.PointLight(0xf59e0b, 0.9, 26, 2);
    this.toolGroup.add(this.heatGlow);
  }

  /** Show a translucent target face mesh (wax-frame geometry). */
  setTargetMesh(geometry) {
    this.targetGhost.clear();
    const material = new THREE.MeshStandardMaterial({
      color: 0x60a5fa,
      transparent: true,
      opacity: 0.16,
      wireframe: true,
      depthWrite: false,
      emissive: 0x1d4ed8,
      emissiveIntensity: 0.25,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = 'target-ghost';
    this.targetGhost.add(mesh);
  }

  setTargetVisible(visible) {
    this.targetGhost.visible = Boolean(visible);
  }

  setFault(code) {
    this.faultCode = code;
    const severe = code === 'RAPID_COLLISION' || code === 'SHANK_COLLISION';
    const warning = code === 'SINGULARITY_HIGH_THETA_DOT' || code === 'UNREACHABLE_UNDERCUT_AREA';
    const material = severe
      ? this.materials.fault
      : warning
        ? this.materials.warning
        : this.materials.heated;
    for (const child of this.toolGroup.children) {
      if (child.isMesh) child.material = material;
    }
  }

  /**
   * Apply one backend frame. All values are pre-sampled by Python:
   * r, theta, h, phi, tip_xyz_wax[3], tool_axis_wax[3].
   */
  update(frame) {
    if (!frame) return;
    this.lastPose = frame;

    this.platterGroup.rotation.z = -frame.theta;
    this.column.scale.z = Math.max(frame.h, 0.001);
    this.column.position.z = frame.h / 2;

    const armStart = this.columnX;
    const armEnd = frame.r;
    this.arm.scale.x = Math.max(Math.abs(armEnd - armStart), 0.001);
    this.arm.position.set((armEnd + armStart) / 2, 0, frame.h);
    this.carriage.position.set(frame.r, 0, frame.h);
    const pivotZ = frame.h - this.pivotDrop;
    this.wrist.position.set(frame.r, 0, pivotZ);
    this.wristMount.scale.z = Math.max(this.pivotDrop, 0.001);
    this.wristMount.position.set(frame.r, 0, pivotZ + this.pivotDrop / 2);

    if (frame.tip_xyz_wax && frame.tool_axis_wax) {
      const tip = frame.tip_xyz_wax;
      const axis = NEW_VECTOR.set(
        frame.tool_axis_wax[0],
        frame.tool_axis_wax[1],
        frame.tool_axis_wax[2]
      ).normalize();
      this.toolGroup.position.set(tip[0], tip[1], tip[2]);
      this.toolGroup.quaternion.setFromUnitVectors(Z_AXIS, axis);
      if (this.heatGlow) {
        this.heatGlow.position.set(0, 0, 1.5);
      }
    }
  }
}

const NEW_VECTOR = new THREE.Vector3();

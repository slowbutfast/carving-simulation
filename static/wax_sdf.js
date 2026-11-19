/**
 * Three.js adapter around the wax SDF Web Worker.
 *
 * Keeps one BufferGeometry per 16^3 chunk, applies transferable mesh buffers,
 * and forwards back-end trajectory frames as compact pose arrays.
 */

import * as THREE from 'three';

export class VolumetricWaxGrid {
  constructor({ rigRoot, config, gridN = 128, chunkSize = 16, onCollision, onStatus }) {
    this.config = config;
    this.onCollision = onCollision || (() => {});
    this.onStatus = onStatus || (() => {});
    this.group = new THREE.Group();
    this.group.name = 'volumetric-wax';
    rigRoot.add(this.group);

    this.material = new THREE.MeshStandardMaterial({
      color: 0xe8d595,
      roughness: 0.58,
      metalness: 0.04,
      flatShading: false,
    });
    this.chunkMeshes = new Map();
    this.ready = false;
    this.voxelSize = null;
    this.currentIndex = 0;
    this.frameCount = 0;

    this.worker = new Worker(new URL('./wax_worker.js', import.meta.url), {
      type: 'module',
    });
    this.worker.onmessage = (event) => this._handleMessage(event.data);
    this.worker.onerror = (error) => {
      // eslint-disable-next-line no-console
      console.error('[wax-worker]', error.message || error);
      this.onStatus({ type: 'worker-error', message: String(error.message || error) });
    };
    this.worker.postMessage({
      type: 'init',
      config: {
        stock: config.stock,
        tool: config.tool,
      },
      gridN,
      chunkSize,
    });
  }

  _handleMessage(message) {
    if (message.type === 'ready') {
      this.ready = true;
      this.voxelSize = message.voxelSize;
      this.gridN = message.gridN;
      this._applyMeshes(message.meshes);
      this.onStatus(message);
      return;
    }
    if (message.type === 'meshes') {
      this.currentIndex = message.index;
      this.frameCount = message.frames ?? this.frameCount;
      this._applyMeshes(message.meshes);
      this.onStatus(message);
      return;
    }
    if (message.type === 'status') {
      this.currentIndex = message.index;
      this.frameCount = message.frames ?? this.frameCount;
      this.onStatus(message);
      return;
    }
    if (message.type === 'collision') {
      this.onCollision(message);
      return;
    }
    if (message.type === 'progress') {
      this.onStatus(message);
    }
  }

  _applyMeshes(meshes) {
    if (!meshes) return;
    for (const mesh of meshes) {
      let entry = this.chunkMeshes.get(mesh.chunkIndex);
      if (!entry) {
        const geometry = new THREE.BufferGeometry();
        const material = this.material;
        const object = new THREE.Mesh(geometry, material);
        object.frustumCulled = true;
        this.group.add(object);
        entry = { object, geometry };
        this.chunkMeshes.set(mesh.chunkIndex, entry);
      }
      const { geometry } = entry;
      geometry.setAttribute('position', new THREE.BufferAttribute(mesh.positions, 3));
      geometry.setAttribute('normal', new THREE.BufferAttribute(mesh.normals, 3));
      geometry.setIndex(new THREE.BufferAttribute(mesh.indices, 1));
      geometry.computeBoundingSphere();
      geometry.computeBoundingBox();
      geometry.attributes.position.needsUpdate = true;
      geometry.attributes.normal.needsUpdate = true;
      geometry.index.needsUpdate = true;
    }
  }

  /** Compact backend columns -> transferable pose array for the worker. */
  setPath(columns, frameCount) {
    const tip = columns.tip_xyz_wax;
    const axis = columns.tool_axis_wax;
    const theta = columns.theta_s;
    const rapid = columns.is_rapid;
    const poses = new Float32Array(frameCount * 7);
    for (let index = 0; index < frameCount; index++) {
      poses[index * 7] = tip[index * 3];
      poses[index * 7 + 1] = tip[index * 3 + 1];
      poses[index * 7 + 2] = tip[index * 3 + 2];
      poses[index * 7 + 3] = axis[index * 3];
      poses[index * 7 + 4] = axis[index * 3 + 1];
      poses[index * 7 + 5] = axis[index * 3 + 2];
      poses[index * 7 + 6] = theta ? theta[index] : 0;
    }
    const rapidCopy = Uint8Array.from(rapid);
    this.frameCount = frameCount;
    this.currentIndex = 0;
    this.worker.postMessage(
      {
        type: 'path',
        poses,
        rapid: rapidCopy,
        count: frameCount,
        stride: 7,
      },
      [poses.buffer]
    );
  }

  seek(index, reason = 'seek') {
    this.worker.postMessage({ type: 'seek', index, reason });
  }

  reset() {
    this.worker.postMessage({ type: 'reset' });
  }

  setVisible(visible) {
    this.group.visible = Boolean(visible);
  }

  dispose() {
    this.worker.terminate();
    for (const { object, geometry } of this.chunkMeshes.values()) {
      this.group.remove(object);
      geometry.dispose();
    }
    this.chunkMeshes.clear();
    this.material.dispose();
  }
}

/**
 * Pure-JS volumetric wax SDF core.
 *
 * Zero DOM / Three.js imports so it runs natively under `node --test`.
 *
 * Stock is a solid cylinder z in [0, H_stock] with radius R_stock, stored as a
 * single float32 128^3 (or configurable) grid initialized with the exact
 * Euclidean cylinder SDF and padded by at least 2 voxels on every side.
 *
 * The heated conical-bevel + melt-kerf frustum is subtracted with
 * `max(sdf, -d_tool)`; the unheated shank is a cylinder over
 * [L_tip, L_tip + L_shank] of radius shankRadius.
 *
 * Chunks are `chunkSize^3` (default 16^3).  Meshing reads a 1-voxel apron from
 * the global grid, marks boundary-neighbour chunks dirty, and uses global
 * central-difference gradients for normals.  Isosurface extraction uses
 * marching cubes with a 6-tetrahedron Kuhn decomposition of every cell (all
 * 256 cases, no lookup-table ambiguities); vertices are keyed by global grid
 * edge, so shared chunk faces produce identical vertices and no seams.
 */

export const DEFAULT_TOOL = Object.freeze({
  tipRadius: 0.5,
  coneHalfAngleDeg: 30,
  engagedLength: 8,
  meltKerf: 0.4,
  shankRadius: 3,
  shankLength: 40,
});

/** Exact Euclidean signed distance to a capped cylinder (negative inside). */
export function cylinderSDF(x, y, z, R, H) {
  const dr = Math.hypot(x, y) - R;
  const dz = Math.abs(z - H / 2) - H / 2;
  return Math.min(Math.max(dr, dz), 0) + Math.hypot(Math.max(dr, 0), Math.max(dz, 0));
}

/** Exact maximum displacement of any point on a cone `[0, L]` between poses. */
export function maxEngagedDisplacement(first, second, engagedLength) {
  const a = first.tip_xyz_wax;
  const b = second.tip_xyz_wax;
  const ua = first.tool_axis_wax;
  const ub = second.tool_axis_wax;
  let atTip = 0;
  let atBase = 0;
  for (let i = 0; i < 3; i++) {
    const dtip = b[i] - a[i];
    const daxis = ub[i] - ua[i];
    atTip += dtip * dtip;
    const base = dtip - engagedLength * daxis;
    atBase += base * base;
  }
  return Math.max(Math.sqrt(atTip), Math.sqrt(atBase));
}

const TETS = [
  [0, 1, 2, 6],
  [0, 2, 3, 6],
  [0, 3, 7, 6],
  [0, 7, 4, 6],
  [0, 4, 5, 6],
  [0, 5, 1, 6],
];
const CORNERS = [
  [0, 0, 0],
  [1, 0, 0],
  [1, 1, 0],
  [0, 1, 0],
  [0, 0, 1],
  [1, 0, 1],
  [1, 1, 1],
  [0, 1, 1],
];
const RING_DIRECTIONS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
  [0.70710678, 0.70710678],
  [-0.70710678, 0.70710678],
  [0.70710678, -0.70710678],
  [-0.70710678, -0.70710678],
];

function normalize(vector) {
  const length = Math.hypot(vector[0], vector[1], vector[2]) || 1;
  return [vector[0] / length, vector[1] / length, vector[2] / length];
}

function cross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function perpendicularBasis(axis) {
  const helper = Math.abs(axis[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
  const b = normalize(cross(axis, helper));
  const c = cross(axis, b);
  return [b, c];
}

export class WaxSDFCore {
  constructor({
    R_stock = 40,
    H_stock = 120,
    gridN = 64,
    chunkSize = 16,
    paddingVoxels = 2,
  } = {}) {
    this.R_stock = Number(R_stock);
    this.H_stock = Number(H_stock);
    this.N = Number(gridN);
    this.chunkSize = Number(chunkSize);
    this.paddingVoxels = Math.max(2, Number(paddingVoxels) || 2);
    this.voxelSize =
      Math.max(2 * this.R_stock, this.H_stock) / Math.max(4, this.N - 4);
    const span = this.N * this.voxelSize;
    this.origin = {
      x: -span / 2,
      y: -span / 2,
      z: (this.H_stock - span) / 2,
    };
    this.chunksPerAxis = Math.ceil(this.N / this.chunkSize);
    this.strideY = this.N;
    this.strideZ = this.N * this.N;
    this.data = new Float32Array(this.N * this.N * this.N);
    this.modified = false;
    this._dirty = new Set();
    this._allDirty = true;
    this._initialize();
  }

  _initialize() {
    const { N, voxelSize: v, origin, R_stock: R, H_stock: H } = this;
    let index = 0;
    for (let k = 0; k < N; k++) {
      const z = origin.z + k * v;
      for (let j = 0; j < N; j++) {
        const y = origin.y + j * v;
        for (let i = 0; i < N; i++) {
          const x = origin.x + i * v;
          this.data[index++] = cylinderSDF(x, y, z, R, H) + 1e-3;
        }
      }
    }
    this._dirty.clear();
    this._allDirty = true;
  }

  idx(i, j, k) {
    return k * this.strideZ + j * this.strideY + i;
  }

  inBounds(i, j, k) {
    const N = this.N;
    return i >= 0 && j >= 0 && k >= 0 && i < N && j < N && k < N;
  }

  voxel(i, j, k) {
    if (!this.inBounds(i, j, k)) return 1e6;
    return this.data[this.idx(i, j, k)];
  }

  /** Trilinear SDF query (exact analytic cylinder before any subtraction). */
  query(x, y, z) {
    if (!this.modified) return cylinderSDF(x, y, z, this.R_stock, this.H_stock);
    const { N, voxelSize: v, origin } = this;
    const gx = (x - origin.x) / v;
    const gy = (y - origin.y) / v;
    const gz = (z - origin.z) / v;
    if (gx < 0 || gy < 0 || gz < 0 || gx > N - 1 || gy > N - 1 || gz > N - 1) {
      return cylinderSDF(x, y, z, this.R_stock, this.H_stock);
    }
    const i0 = Math.min(N - 2, Math.floor(gx));
    const j0 = Math.min(N - 2, Math.floor(gy));
    const k0 = Math.min(N - 2, Math.floor(gz));
    const fx = gx - i0;
    const fy = gy - j0;
    const fz = gz - k0;
    const c000 = this.voxel(i0, j0, k0);
    const c100 = this.voxel(i0 + 1, j0, k0);
    const c010 = this.voxel(i0, j0 + 1, k0);
    const c110 = this.voxel(i0 + 1, j0 + 1, k0);
    const c001 = this.voxel(i0, j0, k0 + 1);
    const c101 = this.voxel(i0 + 1, j0, k0 + 1);
    const c011 = this.voxel(i0, j0 + 1, k0 + 1);
    const c111 = this.voxel(i0 + 1, j0 + 1, k0 + 1);
    const c00 = c000 + (c100 - c000) * fx;
    const c10 = c010 + (c110 - c010) * fx;
    const c01 = c001 + (c101 - c001) * fx;
    const c11 = c011 + (c111 - c011) * fx;
    const c0 = c00 + (c10 - c00) * fy;
    const c1 = c01 + (c11 - c01) * fy;
    return c0 + (c1 - c0) * fz;
  }

  _gradient(x, y, z) {
    const h = this.voxelSize * 0.5;
    const gx = this.query(x + h, y, z) - this.query(x - h, y, z);
    const gy = this.query(x, y + h, z) - this.query(x, y - h, z);
    const gz = this.query(x, y, z + h) - this.query(x, y, z - h);
    const length = Math.hypot(gx, gy, gz) || 1;
    return [gx / length, gy / length, gz / length];
  }

  _toolSDF(x, y, z, apex, axis, tool, includeShank) {
    const dx = x - apex[0];
    const dy = y - apex[1];
    const dz = z - apex[2];
    const t = -(dx * axis[0] + dy * axis[1] + dz * axis[2]);
    const px = dx + axis[0] * t;
    const py = dy + axis[1] * t;
    const pz = dz + axis[2] * t;
    const radial = Math.hypot(px, py, pz);
    const alpha = (tool.coneHalfAngleDeg * Math.PI) / 180;
    const tipRadius = tool.tipRadius + tool.meltKerf;
    const coneRadius = tipRadius + t * Math.tan(alpha);
    let distance = Math.max(radial - coneRadius, -t, t - tool.engagedLength);
    if (includeShank) {
      const shankDistance = Math.max(
        radial - tool.shankRadius,
        tool.engagedLength - t,
        t - (tool.engagedLength + tool.shankLength)
      );
      distance = Math.min(distance, shankDistance);
    }
    return distance;
  }

  _boundingBox(apex, axis, tool, includeShank) {
    const reach = includeShank
      ? tool.engagedLength + tool.shankLength
      : tool.engagedLength;
    const maxRadius =
      Math.max(
        tool.tipRadius + tool.meltKerf + reach * Math.tan((tool.coneHalfAngleDeg * Math.PI) / 180),
        includeShank ? tool.shankRadius : 0
      ) + this.voxelSize;
    const center = [
      apex[0] - axis[0] * (reach / 2),
      apex[1] - axis[1] * (reach / 2),
      apex[2] - axis[2] * (reach / 2),
    ];
    const extent = reach / 2 + maxRadius;
    const { voxelSize: v, origin } = this;
    return {
      i0: Math.max(0, Math.floor((center[0] - extent - origin.x) / v)),
      i1: Math.min(this.N - 1, Math.ceil((center[0] + extent - origin.x) / v)),
      j0: Math.max(0, Math.floor((center[1] - extent - origin.y) / v)),
      j1: Math.min(this.N - 1, Math.ceil((center[1] + extent - origin.y) / v)),
      k0: Math.max(0, Math.floor((center[2] - extent - origin.z) / v)),
      k1: Math.min(this.N - 1, Math.ceil((center[2] + extent - origin.z) / v)),
    };
  }

  _chunkCoords(i, j, k) {
    const cs = this.chunkSize;
    return [Math.floor(i / cs), Math.floor(j / cs), Math.floor(k / cs)];
  }

  _chunkIndex(cx, cy, cz) {
    return (cz * this.chunksPerAxis + cy) * this.chunksPerAxis + cx;
  }

  _markDirty(i, j, k) {
    const cs = this.chunkSize;
    const [cx, cy, cz] = this._chunkCoords(i, j, k);
    const li = i % cs;
    const lj = j % cs;
    const lk = k % cs;
    const maxChunk = this.chunksPerAxis - 1;
    for (let dx = -1; dx <= 1; dx++) {
      if (dx < 0 && li !== 0) continue;
      if (dx > 0 && li !== cs - 1) continue;
      for (let dy = -1; dy <= 1; dy++) {
        if (dy < 0 && lj !== 0) continue;
        if (dy > 0 && lj !== cs - 1) continue;
        for (let dz = -1; dz <= 1; dz++) {
          if (dz < 0 && lk !== 0) continue;
          if (dz > 0 && lk !== cs - 1) continue;
          const nx = cx + dx;
          const ny = cy + dy;
          const nz = cz + dz;
          if (nx < 0 || ny < 0 || nz < 0 || nx > maxChunk || ny > maxChunk || nz > maxChunk) {
            continue;
          }
          this._dirty.add(this._chunkIndex(nx, ny, nz));
          this._allDirty = false;
        }
      }
    }
  }

  /**
   * Subtract the heated conical-bevel frustum (and optionally the shank) at one
   * pose. `pose = { tip: [x,y,z], axis: [x,y,z] }`, axis points pivot -> tip.
   */
  subtractTool(pose, tool = DEFAULT_TOOL, { includeShank = false } = {}) {
    const apex = pose.tip;
    const axis = normalize(pose.axis);
    const box = this._boundingBox(apex, axis, tool, includeShank);
    let touched = 0;
    for (let k = box.k0; k <= box.k1; k++) {
      const z = this.origin.z + k * this.voxelSize;
      for (let j = box.j0; j <= box.j1; j++) {
        const y = this.origin.y + j * this.voxelSize;
        for (let i = box.i0; i <= box.i1; i++) {
          const x = this.origin.x + i * this.voxelSize;
          const distance = this._toolSDF(x, y, z, apex, axis, tool, includeShank);
          if (distance >= 0) continue;
          const index = this.idx(i, j, k);
          const next = Math.max(this.data[index], -distance);
          if (next > this.data[index] + 1e-9) {
            this.data[index] = next;
            touched += 1;
            this._markDirty(i, j, k);
          }
        }
      }
    }
    if (touched > 0) this.modified = true;
    return touched;
  }

  /** Sweep the tool along a pose segment, sub-stepping at half-voxel spacing. */
  subtractSegment(first, second, tool = DEFAULT_TOOL, options = {}) {
    const a = first.tip;
    const b = second.tip;
    const distance = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    const steps = Math.max(1, Math.min(512, Math.ceil(distance / (0.5 * this.voxelSize))));
    let touched = 0;
    for (let step = 0; step <= steps; step++) {
      const u = step / steps;
      const tip = [
        a[0] + (b[0] - a[0]) * u,
        a[1] + (b[1] - a[1]) * u,
        a[2] + (b[2] - a[2]) * u,
      ];
      const axis = normalize([
        first.axis[0] + (second.axis[0] - first.axis[0]) * u,
        first.axis[1] + (second.axis[1] - first.axis[1]) * u,
        first.axis[2] + (second.axis[2] - first.axis[2]) * u,
      ]);
      touched += this.subtractTool({ tip, axis }, tool, options);
    }
    return touched;
  }

  dirtyChunkIndices() {
    if (this._allDirty) {
      const all = [];
      for (let index = 0; index < this.chunksPerAxis ** 3; index++) all.push(index);
      return all;
    }
    return [...this._dirty].sort((a, b) => a - b);
  }

  clearDirty() {
    this._dirty.clear();
    this._allDirty = false;
  }

  snapshot() {
    return this.data.slice();
  }

  restore(snapshot) {
    if (snapshot.length !== this.data.length) {
      throw new Error('snapshot size mismatch');
    }
    this.data.set(snapshot);
    this.modified = true;
    this._dirty.clear();
    this._allDirty = true;
  }

  _sampleBody(pose, tool, { includeShank = true, shankOnly = false }) {
    const apex = pose.tip;
    const axis = normalize(pose.axis);
    const [basisB, basisC] = perpendicularBasis(axis);
    const stations = [];
    const tipRadius = tool.tipRadius + tool.meltKerf;
    const alpha = (tool.coneHalfAngleDeg * Math.PI) / 180;
    if (!shankOnly) {
      stations.push({ t: 0, radius: 0 });
      for (const fraction of [0.5, 1]) {
        const t = tool.engagedLength * fraction;
        stations.push({ t, radius: tipRadius + t * Math.tan(alpha) });
      }
    }
    if (includeShank) {
      // The shank extends from the apex back toward the wrist pivot, i.e. along
      // -axis: points are `apex - axis * t` for t in [L_tip, L_tip + L_shank].
      for (const fraction of [0.25, 0.75, 1]) {
        stations.push({
          t: tool.engagedLength + tool.shankLength * fraction,
          radius: tool.shankRadius,
        });
      }
    }
    const points = [];
    for (const station of stations) {
      // `axis` points pivot -> tip, so body points lie behind the apex.
      const base = [
        apex[0] - axis[0] * station.t,
        apex[1] - axis[1] * station.t,
        apex[2] - axis[2] * station.t,
      ];
      points.push(base);
      if (station.radius <= 0) continue;
      for (const [du, dv] of RING_DIRECTIONS) {
        const r = station.radius * 0.9;
        points.push([
          base[0] + (basisB[0] * du + basisC[0] * dv) * r,
          base[1] + (basisB[1] * du + basisC[1] * dv) * r,
          base[2] + (basisB[2] * du + basisC[2] * dv) * r,
        ]);
      }
    }
    return points;
  }

  checkRapid(first, second, tool = DEFAULT_TOOL) {
    const a = first.tip;
    const b = second.tip;
    const distance = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    const steps = Math.max(1, Math.min(128, Math.ceil(distance / (0.5 * this.voxelSize))));
    const threshold = -0.5 * this.voxelSize;
    for (let step = 0; step <= steps; step++) {
      const u = step / steps;
      const pose = {
        tip: [
          a[0] + (b[0] - a[0]) * u,
          a[1] + (b[1] - a[1]) * u,
          a[2] + (b[2] - a[2]) * u,
        ],
        axis: normalize([
          first.axis[0] + (second.axis[0] - first.axis[0]) * u,
          first.axis[1] + (second.axis[1] - first.axis[1]) * u,
          first.axis[2] + (second.axis[2] - first.axis[2]) * u,
        ]),
      };
      for (const point of this._sampleBody(pose, tool, { includeShank: true })) {
        const sdf = this.query(point[0], point[1], point[2]);
        if (sdf < threshold) {
          return { collision: true, code: 'RAPID_COLLISION', sdf, point, step };
        }
      }
    }
    return { collision: false, code: null };
  }

  checkShank(pose, tool = DEFAULT_TOOL) {
    const threshold = -0.5 * this.voxelSize;
    for (const point of this._sampleBody(pose, tool, { includeShank: true, shankOnly: true })) {
      const sdf = this.query(point[0], point[1], point[2]);
      if (sdf < threshold) {
        return { collision: true, code: 'SHANK_COLLISION', sdf, point };
      }
    }
    return { collision: false, code: null };
  }

  _edgeVertex(cornerA, cornerB, valueA, valueB, originI, originJ, originK, collector, map) {
    const aIndex = this.idx(originI + cornerA[0], originJ + cornerA[1], originK + cornerA[2]);
    const bIndex = this.idx(originI + cornerB[0], originJ + cornerB[1], originK + cornerB[2]);
    const low = Math.min(aIndex, bIndex);
    const high = Math.max(aIndex, bIndex);
    const key = low * (this.N ** 3) + high;
    const cached = map.get(key);
    if (cached !== undefined) return cached;

    const denominator = valueA - valueB;
    let t = Math.abs(denominator) < 1e-12 ? 0.5 : valueA / denominator;
    t = Math.min(1, Math.max(0, t));
    const v = this.voxelSize;
    const x = this.origin.x + (originI + cornerA[0] + t * (cornerB[0] - cornerA[0])) * v;
    const y = this.origin.y + (originJ + cornerA[1] + t * (cornerB[1] - cornerA[1])) * v;
    const z = this.origin.z + (originK + cornerA[2] + t * (cornerB[2] - cornerA[2])) * v;
    const normal = this._gradient(x, y, z);
    const index = collector.positions.length / 3;
    collector.positions.push(x, y, z);
    collector.normals.push(normal[0], normal[1], normal[2]);
    map.set(key, index);
    return index;
  }

  _emitTriangle(collector, indices) {
    const { positions } = collector;
    const i0 = indices[0] * 3;
    const i1 = indices[1] * 3;
    const i2 = indices[2] * 3;
    const ax = positions[i1] - positions[i0];
    const ay = positions[i1 + 1] - positions[i0 + 1];
    const az = positions[i1 + 2] - positions[i0 + 2];
    const bx = positions[i2] - positions[i0];
    const by = positions[i2 + 1] - positions[i0 + 1];
    const bz = positions[i2 + 2] - positions[i0 + 2];
    const nx = ay * bz - az * by;
    const ny = az * bx - ax * bz;
    const nz = ax * by - ay * bx;
    if (nx * nx + ny * ny + nz * nz < 1e-16) return;
    const cx = (positions[i0] + positions[i1] + positions[i2]) / 3;
    const cy = (positions[i0 + 1] + positions[i1 + 1] + positions[i2 + 1]) / 3;
    const cz = (positions[i0 + 2] + positions[i1 + 2] + positions[i2 + 2]) / 3;
    const gradient = this._gradient(cx, cy, cz);
    if (nx * gradient[0] + ny * gradient[1] + nz * gradient[2] < 0) {
      collector.indices.push(indices[0], indices[2], indices[1]);
    } else {
      collector.indices.push(indices[0], indices[1], indices[2]);
    }
  }

  _processTet(tet, values, originI, originJ, originK, collector, map) {
    const inside = [];
    const outside = [];
    for (const corner of tet) {
      if (values[corner] < 0) inside.push(corner);
      else outside.push(corner);
    }
    if (inside.length === 0 || inside.length === 4) return;

    const vertexFor = (cornerA, cornerB) =>
      this._edgeVertex(
        CORNERS[cornerA],
        CORNERS[cornerB],
        values[cornerA],
        values[cornerB],
        originI,
        originJ,
        originK,
        collector,
        map
      );

    if (inside.length === 1 || inside.length === 3) {
      const crossing = [];
      for (const inner of inside) {
        for (const outer of outside) {
          // Every pair of vertices in a tetrahedron is one of its six edges.
          crossing.push(vertexFor(inner, outer));
        }
      }
      if (crossing.length === 3) this._emitTriangle(collector, crossing);
      return;
    }

    const [i0, i1] = inside;
    const [o0, o1] = outside;
    const e00 = vertexFor(i0, o0);
    const e01 = vertexFor(i0, o1);
    const e11 = vertexFor(i1, o1);
    const e10 = vertexFor(i1, o0);
    this._emitTriangle(collector, [e00, e01, e11]);
    this._emitTriangle(collector, [e00, e11, e10]);
  }

  _meshChunkInto(chunkIndex, collector) {
    this._meshChunkWithMap(chunkIndex, collector, new Map());
  }

  _emptyCollector() {
    return { positions: [], normals: [], indices: [] };
  }

  _finalizeCollector(collector) {
    return {
      positions: Float32Array.from(collector.positions),
      normals: Float32Array.from(collector.normals),
      indices: Uint32Array.from(collector.indices),
    };
  }

  meshAll() {
    const collector = this._emptyCollector();
    const total = this.chunksPerAxis ** 3;
    const sharedMap = new Map();
    for (let chunk = 0; chunk < total; chunk++) {
      this._meshChunkWithMap(chunk, collector, sharedMap);
    }
    return this._finalizeCollector(collector);
  }

  _meshChunkWithMap(chunkIndex, collector, map) {
    const cs = this.chunkSize;
    const nc = this.chunksPerAxis;
    const cx = chunkIndex % nc;
    const cy = Math.floor(chunkIndex / nc) % nc;
    const cz = Math.floor(chunkIndex / (nc * nc));
    const baseI = cx * cs;
    const baseJ = cy * cs;
    const baseK = cz * cs;
    for (let lk = 0; lk < cs; lk++) {
      const k = baseK + lk;
      if (k + 1 >= this.N) continue;
      for (let lj = 0; lj < cs; lj++) {
        const j = baseJ + lj;
        if (j + 1 >= this.N) continue;
        for (let li = 0; li < cs; li++) {
          const i = baseI + li;
          if (i + 1 >= this.N) continue;
          const values = new Array(8);
          let negative = 0;
          for (let c = 0; c < 8; c++) {
            const corner = CORNERS[c];
            const value = this.voxel(i + corner[0], j + corner[1], k + corner[2]);
            values[c] = value;
            if (value < 0) negative += 1;
          }
          if (negative === 0 || negative === 8) continue;
          for (const tet of TETS) {
            this._processTet(tet, values, i, j, k, collector, map);
          }
        }
      }
    }
  }

  /** Meshes only the dirty chunks; each chunk is a separate BufferGeometry payload. */
  meshDirtyChunks() {
    const dirty = this.dirtyChunkIndices();
    const meshes = [];
    for (const chunkIndex of dirty) {
      const collector = this._emptyCollector();
      this._meshChunkInto(chunkIndex, collector);
      if (collector.indices.length === 0) continue;
      const finalized = this._finalizeCollector(collector);
      meshes.push({ chunkIndex, ...finalized });
    }
    return meshes;
  }
}

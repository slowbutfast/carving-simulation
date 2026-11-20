/**
 * Pure-JS volumetric wax SDF core.
 *
 * Zero DOM / Three.js imports so it runs natively under `node --test`.
 *
 * Stock is a solid cylinder z in [0, H_stock] with radius R_stock, stored as a
 * single float32 128^3 (or configurable) grid initialized with the exact
 * Euclidean cylinder SDF and padded by at least 2 voxels on every side.
 *
 * The heated blade prism (blade_thickness x blade_width x heated_length in the
 * tool frame (a_n, a_w, u)) inflated by melt_kerf is subtracted with
 * `max(sdf, -d_heated)`.  **The wax SDF convention is negative inside** (the
 * same convention as `tool_model.heated_sdf`; trimesh is the opposite).
 *
 * The unheated bodies are checked for collisions but are never subtracted by a
 * cutting move: the ⌀2*shaft_radius shaft, the ⌀2*body_radius cartridge body,
 * and the explicit tilt-head box envelope.  All axial spans are measured from
 * the tool reference point along `-u` (i.e. from the tip back toward the pivot).
 *
 * Chunks are `chunkSize^3` (default 16^3).  Meshing reads a 1-voxel apron from
 * the global grid, marks boundary-neighbour chunks dirty, and uses global
 * central-difference gradients for normals.  Isosurface extraction uses
 * marching cubes with a 6-tetrahedron Kuhn decomposition of every cell (all
 * 256 cases, no lookup-table ambiguities); vertices are keyed by global grid
 * edge, so shared chunk faces produce identical vertices and no seams.
 */

export const DEFAULT_TOOL = Object.freeze({
  bladeThickness: 1.2,
  bladeWidth: 6.0,
  bladeLength: 14.0,
  heatedLength: 14.0,
  meltKerf: 0.4,
  shaftRadius: 2.5,
  shaftSpan: Object.freeze([14.0, 75.0]),
  bodyRadius: 3.5,
  bodySpan: Object.freeze([75.0, 140.0]),
  headClearance: 46.5934,
  headEnvelope: Object.freeze({
    shape: 'box',
    center: Object.freeze([9.0, -3.375, 111.0]),
    halfExtents: Object.freeze([20.0, 11.125, 61.0]),
  }),
});

/** Exact Euclidean signed distance to a capped cylinder (negative inside). */
export function cylinderSDF(x, y, z, R, H) {
  const dr = Math.hypot(x, y) - R;
  const dz = Math.abs(z - H / 2) - H / 2;
  return Math.min(Math.max(dr, dz), 0) + Math.hypot(Math.max(dr, 0), Math.max(dz, 0));
}

/**
 * Conservative maximum displacement of the heated blade's reference point and
 * its `engagedLength`-distant base between two poses.  A swept-stamp bound.
 */
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
const BODY_RING_DIRECTIONS = [
  [1, 0],
  [0.8660254, 0.5],
  [0.5, 0.8660254],
  [0, 1],
  [-0.5, 0.8660254],
  [-0.8660254, 0.5],
  [-1, 0],
  [-0.8660254, -0.5],
  [-0.5, -0.8660254],
  [0, -1],
  [0.5, -0.8660254],
  [0.8660254, -0.5],
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

function toolFrame(pose) {
  const u = normalize(pose.axis);
  const theta = Number.isFinite(pose.theta) ? Number(pose.theta) : 0;
  // a_w = e_theta(theta); a_n = a_w x u.  The ordered (a_n, a_w, u) frame is
  // right-handed with a_n x a_w = u and a_n = -e_r at phi = 0.
  const aW = [-Math.sin(theta), Math.cos(theta), 0];
  const aN = normalize(cross(aW, u));
  return { tip: pose.tip, u, aW, aN };
}

/** Rounded-box SDF in the local (a_n, a_w, s) frame; negative inside. */
function boxSDF(ln, lw, ls, center, half) {
  const qn = Math.abs(ln - center[0]) - half[0];
  const qw = Math.abs(lw - center[1]) - half[1];
  const qs = Math.abs(ls - center[2]) - half[2];
  const outside = Math.hypot(Math.max(qn, 0), Math.max(qw, 0), Math.max(qs, 0));
  const inside = Math.min(Math.max(qn, qw, qs), 0);
  return outside + inside;
}

/**
 * Exact signed distance to the kerf-inflated blade prism, mirroring
 * `tool_model.heated_sdf`.  Negative inside.
 */
export function heatedSDF(point, pose, tool = DEFAULT_TOOL) {
  const frame = toolFrame(pose);
  const dx = point[0] - frame.tip[0];
  const dy = point[1] - frame.tip[1];
  const dz = point[2] - frame.tip[2];
  const ln = dx * frame.aN[0] + dy * frame.aN[1] + dz * frame.aN[2];
  const lw = dx * frame.aW[0] + dy * frame.aW[1] + dz * frame.aW[2];
  // s runs along -u from the reference point; the box centre is heated/2 above.
  const ls = -(dx * frame.u[0] + dy * frame.u[1] + dz * frame.u[2]);
  const ht = (tool.bladeThickness ?? DEFAULT_TOOL.bladeThickness) / 2;
  const hw = (tool.bladeWidth ?? DEFAULT_TOOL.bladeWidth) / 2;
  const hl = (tool.heatedLength ?? tool.bladeLength ?? DEFAULT_TOOL.heatedLength) / 2;
  const kerf = tool.meltKerf ?? DEFAULT_TOOL.meltKerf;
  return boxSDF(ln, lw, ls, [0, 0, hl], [ht, hw, hl]) - kerf;
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

  _toolFrame(pose) {
    return toolFrame(pose);
  }

  _local(frame, x, y, z) {
    const dx = x - frame.tip[0];
    const dy = y - frame.tip[1];
    const dz = z - frame.tip[2];
    return [
      dx * frame.aN[0] + dy * frame.aN[1] + dz * frame.aN[2],
      dx * frame.aW[0] + dy * frame.aW[1] + dz * frame.aW[2],
      -(dx * frame.u[0] + dy * frame.u[1] + dz * frame.u[2]),
    ];
  }

  _worldPoint(frame, n, w, s) {
    return [
      frame.tip[0] + frame.aN[0] * n + frame.aW[0] * w - frame.u[0] * s,
      frame.tip[1] + frame.aN[1] * n + frame.aW[1] * w - frame.u[1] * s,
      frame.tip[2] + frame.aN[2] * n + frame.aW[2] * w - frame.u[2] * s,
    ];
  }

  /** A rounded-box SDF in the local (a_n, a_w, s) frame; negative inside. */
  _boxSDF(ln, lw, ls, center, half) {
    const qn = Math.abs(ln - center[0]) - half[0];
    const qw = Math.abs(lw - center[1]) - half[1];
    const qs = Math.abs(ls - center[2]) - half[2];
    const outside = Math.hypot(Math.max(qn, 0), Math.max(qw, 0), Math.max(qs, 0));
    const inside = Math.min(Math.max(qn, qw, qs), 0);
    return outside + inside;
  }

  /** Capped-cylinder SDF along s in [s0, s1]; negative inside. */
  _cylinderSDF(ln, lw, ls, radius, s0, s1) {
    const radial = Math.hypot(ln, lw) - radius;
    const axial = Math.max(s0 - ls, ls - s1);
    return Math.min(Math.max(radial, axial), 0) + Math.hypot(Math.max(radial, 0), Math.max(axial, 0));
  }

  _headEnvelope(tool) {
    const envelope = tool.headEnvelope || tool.head_envelope || DEFAULT_TOOL.headEnvelope;
    const center = envelope.center || envelope.center_mm || DEFAULT_TOOL.headEnvelope.center;
    const half = envelope.halfExtents || envelope.half_extents_mm || DEFAULT_TOOL.headEnvelope.halfExtents;
    return { center, half };
  }

  /**
   * Signed distance to the tool at one local point.  The heated blade is always
   * included; `includeShank` adds the unheated shaft, body and head bodies for
   * the carve-with-body path used by tests and the sweep CLI.
   */
  _toolSDF(ln, lw, ls, tool, includeShank) {
    const ht = (tool.bladeThickness ?? DEFAULT_TOOL.bladeThickness) / 2;
    const hw = (tool.bladeWidth ?? DEFAULT_TOOL.bladeWidth) / 2;
    const hl = (tool.heatedLength ?? tool.bladeLength ?? DEFAULT_TOOL.heatedLength) / 2;
    const kerf = tool.meltKerf ?? DEFAULT_TOOL.meltKerf;
    // Blade box centre is heated_length/2 above the reference point along -u,
    // so it spans s in [0, heated_length].  Inflated by the melt kerf.
    let distance = this._boxSDF(ln, lw, ls, [0, 0, hl], [ht, hw, hl]) - kerf;
    if (!includeShank) return distance;

    const shaftSpan = tool.shaftSpan || tool.shaft_span_mm || DEFAULT_TOOL.shaftSpan;
    const bodySpan = tool.bodySpan || tool.body_span_mm || DEFAULT_TOOL.bodySpan;
    const shaftRadius = tool.shaftRadius ?? DEFAULT_TOOL.shaftRadius;
    const bodyRadius = tool.bodyRadius ?? DEFAULT_TOOL.bodyRadius;
    if (shaftSpan[1] > shaftSpan[0]) {
      distance = Math.min(
        distance,
        this._cylinderSDF(ln, lw, ls, shaftRadius, shaftSpan[0], shaftSpan[1])
      );
    }
    if (bodySpan[1] > bodySpan[0]) {
      distance = Math.min(
        distance,
        this._cylinderSDF(ln, lw, ls, bodyRadius, bodySpan[0], bodySpan[1])
      );
    }
    const envelope = this._headEnvelope(tool);
    distance = Math.min(
      distance,
      this._boxSDF(ln, lw, ls, envelope.center, envelope.half)
    );
    return distance;
  }

  _boundingBox(frame, tool, includeShank) {
    const heatedLength = tool.heatedLength ?? tool.bladeLength ?? DEFAULT_TOOL.heatedLength;
    const kerf = tool.meltKerf ?? DEFAULT_TOOL.meltKerf;
    let sMax = heatedLength;
    let radial = Math.hypot(
      (tool.bladeThickness ?? DEFAULT_TOOL.bladeThickness) / 2,
      (tool.bladeWidth ?? DEFAULT_TOOL.bladeWidth) / 2
    ) + kerf;
    if (includeShank) {
      const shaftSpan = tool.shaftSpan || tool.shaft_span_mm || DEFAULT_TOOL.shaftSpan;
      const bodySpan = tool.bodySpan || tool.body_span_mm || DEFAULT_TOOL.bodySpan;
      const envelope = this._headEnvelope(tool);
      sMax = Math.max(sMax, shaftSpan[1], bodySpan[1], envelope.center[2] + envelope.half[2]);
      radial = Math.max(
        radial,
        tool.shaftRadius ?? DEFAULT_TOOL.shaftRadius,
        tool.bodyRadius ?? DEFAULT_TOOL.bodyRadius,
        Math.hypot(
          Math.abs(envelope.center[0]) + envelope.half[0],
          Math.abs(envelope.center[1]) + envelope.half[1]
        )
      );
    }
    const center = [
      frame.tip[0] - frame.u[0] * (sMax / 2),
      frame.tip[1] - frame.u[1] * (sMax / 2),
      frame.tip[2] - frame.u[2] * (sMax / 2),
    ];
    const extent = sMax / 2 + radial + this.voxelSize;
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
   * Subtract the kerf-inflated blade prism (and optionally the unheated bodies)
   * at one pose.  `pose = { tip: [x,y,z], axis: u, theta }` where `u` points
   * from the pivot toward the tool reference point and `theta` is the orbit
   * angle used to build `a_w = e_theta(theta)`.
   */
  subtractTool(pose, tool = DEFAULT_TOOL, { includeShank = false } = {}) {
    const frame = this._toolFrame(pose);
    const box = this._boundingBox(frame, tool, includeShank);
    let touched = 0;
    for (let k = box.k0; k <= box.k1; k++) {
      const z = this.origin.z + k * this.voxelSize;
      for (let j = box.j0; j <= box.j1; j++) {
        const y = this.origin.y + j * this.voxelSize;
        for (let i = box.i0; i <= box.i1; i++) {
          const x = this.origin.x + i * this.voxelSize;
          const [ln, lw, ls] = this._local(frame, x, y, z);
          const distance = this._toolSDF(ln, lw, ls, tool, includeShank);
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
    const thetaA = Number.isFinite(first.theta) ? first.theta : 0;
    const thetaB = Number.isFinite(second.theta) ? second.theta : 0;
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
      touched += this.subtractTool(
        { tip, axis, theta: thetaA + (thetaB - thetaA) * u },
        tool,
        options
      );
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

  _sampleCylinderBody(frame, body, radius, span, samples) {
    if (!(span[1] > span[0]) || !(radius > 0)) return;
    const count = 4;
    for (let station = 0; station < count; station++) {
      const s = span[0] + ((span[1] - span[0]) * station) / (count - 1);
      samples.push({ body, point: this._worldPoint(frame, 0, 0, s) });
      for (const [dn, dw] of BODY_RING_DIRECTIONS) {
        samples.push({
          body,
          point: this._worldPoint(frame, dn * radius, dw * radius, s),
        });
      }
    }
  }

  _sampleHeadBody(frame, tool, samples) {
    const envelope = this._headEnvelope(tool);
    const s0 = envelope.center[2] - envelope.half[2];
    const s1 = envelope.center[2] + envelope.half[2];
    for (const fraction of [0, 0.5, 1]) {
      const s = s0 + (s1 - s0) * fraction;
      for (const fn of [-1, 0, 1]) {
        for (const fw of [-1, 0, 1]) {
          samples.push({
            body: 'head',
            point: this._worldPoint(
              frame,
              envelope.center[0] + fn * envelope.half[0],
              envelope.center[1] + fw * envelope.half[1],
              s
            ),
          });
        }
      }
    }
  }

  _sampleBodies(frame, tool, { parts = ['shaft', 'body', 'head'] } = {}) {
    const samples = [];
    if (parts.includes('shaft')) {
      this._sampleCylinderBody(
        frame,
        'shaft',
        tool.shaftRadius ?? DEFAULT_TOOL.shaftRadius,
        tool.shaftSpan || tool.shaft_span_mm || DEFAULT_TOOL.shaftSpan,
        samples
      );
    }
    if (parts.includes('body')) {
      this._sampleCylinderBody(
        frame,
        'body',
        tool.bodyRadius ?? DEFAULT_TOOL.bodyRadius,
        tool.bodySpan || tool.body_span_mm || DEFAULT_TOOL.bodySpan,
        samples
      );
    }
    if (parts.includes('head')) this._sampleHeadBody(frame, tool, samples);
    return samples;
  }

  _sampleHeatedRegion(frame, tool) {
    const kerf = tool.meltKerf ?? DEFAULT_TOOL.meltKerf;
    const hn = (tool.bladeThickness ?? DEFAULT_TOOL.bladeThickness) / 2 + kerf;
    const hw = (tool.bladeWidth ?? DEFAULT_TOOL.bladeWidth) / 2 + kerf;
    const hl = (tool.heatedLength ?? tool.bladeLength ?? DEFAULT_TOOL.heatedLength) / 2 + kerf;
    const points = [this._worldPoint(frame, 0, 0, 0)];
    for (const sn of [-1, 1]) {
      for (const sw of [-1, 1]) {
        for (const ss of [-1, 1]) {
          points.push(this._worldPoint(frame, sn * hn, sw * hw, hl + ss * hl));
        }
      }
    }
    return points;
  }

  checkRapid(first, second, tool = DEFAULT_TOOL) {
    const a = first.tip;
    const b = second.tip;
    const thetaA = Number.isFinite(first.theta) ? first.theta : 0;
    const thetaB = Number.isFinite(second.theta) ? second.theta : 0;
    const distance = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    const steps = Math.max(1, Math.min(128, Math.ceil(distance / (0.5 * this.voxelSize))));
    const threshold = -0.5 * this.voxelSize;
    for (let step = 0; step <= steps; step++) {
      const u = step / steps;
      const frame = this._toolFrame({
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
        theta: thetaA + (thetaB - thetaA) * u,
      });
      for (const point of this._sampleHeatedRegion(frame, tool)) {
        const sdf = this.query(point[0], point[1], point[2]);
        if (sdf < threshold) {
          return { collision: true, code: 'RAPID_COLLISION', body: 'blade', sdf, point, step };
        }
      }
      for (const sample of this._sampleBodies(frame, tool)) {
        const sdf = this.query(sample.point[0], sample.point[1], sample.point[2]);
        if (sdf < threshold) {
          return {
            collision: true,
            code: 'RAPID_COLLISION',
            body: sample.body,
            sdf,
            point: sample.point,
            step,
          };
        }
      }
    }
    return { collision: false, code: null };
  }

  /**
   * Check the unheated tool bodies at one cutting pose.  Reports the first
   * offending body name (`shaft`, `body` or `head`) in the diagnostic.
   */
  checkShank(pose, tool = DEFAULT_TOOL) {
    const frame = this._toolFrame(pose);
    const threshold = -0.5 * this.voxelSize;
    for (const sample of this._sampleBodies(frame, tool)) {
      const sdf = this.query(sample.point[0], sample.point[1], sample.point[2]);
      if (sdf < threshold) {
        return {
          collision: true,
          code: 'SHANK_COLLISION',
          body: sample.body,
          sdf,
          point: sample.point,
        };
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

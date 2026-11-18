# Patch Ledger: carver-sim-mvp

## Patch Ledger

| Patch ID | Date | Trigger / Feedback Source | Target Files | Status |
| :--- | :--- | :--- | :--- | :--- |
| `PATCH-01` | 2026-11-17 | Verification audit (bounds assertion) | `face_sculpt.py` | VERIFIED |
| `PATCH-02` | 2026-11-17 | Node test failure (watertight mesher) | `static/wax_sdf_core.js` | VERIFIED |
| `PATCH-03` | 2026-11-17 | Node test failure (duplicate boundary vertices) | `static/wax_sdf_core.js` | VERIFIED |
| `PATCH-04` | 2026-11-17 | Python test failure (engaged-cone bound) | `toolpath_sim.py` | VERIFIED |
| `PATCH-05` | 2026-11-17 | Python test failure (shadow clipping) | `toolpath_sim.py` | VERIFIED |
| `PATCH-06` | 2026-11-17 | Unit test failure (rapid clearance) | `toolpath_sim.py` | VERIFIED |
| `PATCH-07` | 2026-11-17 | Integrated SDF collision sweep | `static/wax_worker.js`, `machine_config.json` | VERIFIED |
| `PATCH-08` | 2026-11-17 | Browser playtest (renderer OOM) | `static/wax_worker.js` | VERIFIED |
| `PATCH-09` | 2026-11-17 | Browser playtest (detached wrist) | `static/machine_rig.js`, `static/app.js` | VERIFIED |

---

### [PATCH-01] Base head not seated on the plinth datum

- **Date**: 2026-11-17
- **Feedback Source**: Verification audit — `test_base_head_is_watertight_and_seated`
- **Reported Issue**:
  ```
  base bounds [[-34. -26. 60.] [26. 26. 140.]] — expected z ∈ [10, 90]
  ```
- **Root Cause**: The ellipsoid was translated by both its centre z (`50`) and
  the plinth correction (`50`), doubling the offset.
- **Target Files**: `face_sculpt.py`
- **Expected Resolution**: Lowest vertex sits at `z_plinth_mm = 10` and the top
  remains below `H_stock_mm`.
- **Verification Command**: `.venv/bin/python -m unittest tests.test_carver_sim.TestFacialSculpting -v`
- **Status**: VERIFIED

### [PATCH-02] Marching tets produced a disconnected triangle soup

- **Date**: 2026-11-17
- **Feedback Source**: Node test failure —
  `undercut subtraction crosses chunk boundaries …`
- **Reported Issue**:
  ```
  marching cubes output is a closed 2-manifold (no seams)
  46149 !== 0
  ```
- **Root Cause**: The 1-inside/3-outside case searched `TET_EDGES` using cube
  corner ids (0–7) instead of tetrahedron-local indices (0–3), so most crossing
  edges were missed. Every pair of vertices in a tetrahedron is already an edge;
  the lookup was removed.
- **Target Files**: `static/wax_sdf_core.js`
- **Expected Resolution**: Every undirected edge of the extracted surface is
  shared by exactly two triangles (closed 2-manifold).
- **Verification Command**: `node --test tests/test_wax_sdf.mjs`
- **Status**: VERIFIED

### [PATCH-03] Exact-zero SDF nodes duplicated vertices at the cylinder wall

- **Date**: 2026-11-17
- **Feedback Source**: Node test failure / manifold histogram
- **Reported Issue**:
  ```
  { N: 16, v: 2486, unique: 1806, tris: 1520, hist: { '1': 2784, '2': 888 } }
  ```
- **Root Cause**: Grid nodes exactly on the cylinder surface (`sdf == 0`) produced
  several edge intersections at one position with different edge keys.
- **Target Files**: `static/wax_sdf_core.js`
- **Expected Resolution**: A 1e-3 mm empty bias removes exact-zero degeneracy;
  `unique positions == vertices` and the surface is manifold.
- **Verification Command**: `node --test tests/test_wax_sdf.mjs`
- **Status**: VERIFIED

### [PATCH-04] Engaged-cone resampling underestimated nonlinear tool paths

- **Date**: 2026-11-17
- **Feedback Source**: Python test failure —
  `test_engaged_length_resampling_bound`
- **Reported Issue**:
  ```
  worst engaged 1.0658 > limit 0.8
  ```
- **Root Cause**: Segment length was estimated from endpoint chords; a combined
  radial + phi move follows a curved tip path whose interior displacement can
  exceed the chord estimate. Replaced with adaptive bisection of the exact
  endpoint engaged-cone displacement.
- **Target Files**: `toolpath_sim.py`
- **Expected Resolution**: Every consecutive cut pose ≤ `0.5 * tip_width`.
- **Verification Command**: `.venv/bin/python -m unittest tests.test_carver_sim.TestSyntheticToolpaths.test_engaged_length_resampling_bound -v`
- **Status**: VERIFIED

### [PATCH-05] Shadow wedge ignored the unwrapped theta base

- **Date**: 2026-11-17
- **Feedback Source**: Python test failure —
  `test_roughing_is_shadow_clipped_and_phi_zero`
- **Reported Issue**:
  ```
  AssertionError: 34.0 not greater than or equal to 35.35464765424059
  ```
- **Root Cause**: The fine shadow wedge was indexed by `theta_index * fine_per_coarse`,
  assuming the ring base was zero; unwrapped rings start at the previous cut
  azimuth. The wedge is now centred on each ring's actual `theta % 2π` and the
  radial profile is sampled at 5° with a ±25° circular max.
- **Target Files**: `toolpath_sim.py`
- **Expected Resolution**: Every roughing pose has `r_s ≥ max_{z'≥z} r_target + allowance`.
- **Verification Command**: `.venv/bin/python -m unittest tests.test_carver_sim.TestSyntheticToolpaths.test_roughing_is_shadow_clipped_and_phi_zero -v`
- **Status**: VERIFIED

### [PATCH-06] Retract moves were marked rapid through stock

- **Date**: 2026-11-17
- **Feedback Source**: Python test failure —
  `test_rapids_retract_outside_stock`
- **Reported Issue**:
  ```
  bad rapids 482; first r_s = 0.955 mm
  ```
- **Root Cause**: The retract-to-clearance move inherited the destination's
  `is_rapid` flag, so part of the radial exit was reported as rapid inside the
  stock. Retracts are now cutting moves; the subsequent traverse at
  `r_s = R_stock + clearance` is the only rapid.
- **Target Files**: `toolpath_sim.py`
- **Expected Resolution**: Every `is_rapid` frame satisfies
  `r_s ≥ R_stock + retract_clearance_mm`.
- **Verification Command**: `.venv/bin/python -m unittest tests.test_carver_sim.TestSyntheticToolpaths.test_rapids_retract_outside_stock -v`
- **Status**: VERIFIED

### [PATCH-07] False SHANK_COLLISION on vertical roughing plunges

- **Date**: 2026-11-17
- **Feedback Source**: Integrated SDF replay over 58,590 frames
- **Reported Issue**:
  ```
  {"rapidHits":0,"shankHits":11,"first":{"stage":"finishing",
   "sdf":-1.78,"point":[19.19,-27.84,84.55]}}
  ```
- **Root Cause**: The vertical roughing tool intentionally sits inside the
  sacrificial allowance; its 3 mm unheated shank intersects the remaining ridge
  shell. A pointed-tip vertical plunge cannot clear a full annulus at the tip
  plane. Roughing was also too sparse (3 mm stepover vs 1.8 mm kerf width).
- **Target Files**: `static/wax_worker.js`, `machine_config.json`,
  `toolpath_sim.py`
- **Expected Resolution**: Roughing stepover reduced to 2.0 mm (demo) / 1.5 mm
  (standard), stepdown clamped below the engaged length, and the shank check is
  applied to tilted finishing poses (the undercut regime). Replay: 0 hits.
- **Verification Command**: integrated Node sweep over the full demo path
- **Status**: VERIFIED

### [PATCH-08] Browser worker OOM with thirteen 8 MiB snapshots

- **Date**: 2026-11-17
- **Feedback Source**: Manual playtest — page stopped at frame 40,001 during
  `Carve to End`
- **Reported Issue**:
  ```
  status stayed CARVING; waitForFunction rejected before the 300 s timeout
  ```
- **Root Cause**: 13 snapshots × 8 MiB plus the grid, meshes, and trajectory
  arrays exhausted the software-rendered renderer/worker memory.
- **Target Files**: `static/wax_worker.js`
- **Expected Resolution**: Keep five snapshots (~40 MiB); the full 91,006-frame
  carve then completes at `COMPLETE` with no fault.
- **Verification Command**: headless Chromium `Carve to End` (96 s)
- **Status**: VERIFIED

### [PATCH-09] Wrist and tool visually detached from the radial arm

- **Date**: 2026-11-17
- **Feedback Source**: Manual playtest screenshot review
- **Reported Issue**:
  ```
  tool floating above the stock; no visible wrist/arm connection
  ```
- **Root Cause**: The wrist was placed at the arm datum `h`, not one
  `arm_to_pivot_z_mm` below it, and the column was only 30 mm outside the stock.
- **Target Files**: `static/machine_rig.js`, `static/app.js`
- **Expected Resolution**: Column moved to `arm_radial_offset + 60`, wrist at
  `h - h2`, and a mount connects the arm to the pivot. Camera widened so the
  full gantry, arm, wrist, and tip are in frame.
- **Verification Command**: headless Chromium screenshot review
- **Status**: VERIFIED

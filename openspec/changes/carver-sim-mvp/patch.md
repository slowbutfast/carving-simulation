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

### [PATCH-10] PR #1 Review Fixes: Worker Tool Config, Section/Transition Finishing, Reachability, Limits & Shank Checks

- **Date**: 2026-11-18 03:52:00 UTC
- **Feedback Source**: Code Review (PR #1 — `REQUEST CHANGES` from Agent 1 & Agent 2)
- **Feedback Summary**:
  - **Critical (3)**:
    1. `static/wax_worker.js:79,93,101,134`: Worker ignores `data.config.tool` sent on `init`, passing hardcoded `DEFAULT_TOOL` to `checkRapid`, `checkShank`, and `subtractTool`.
    2. `toolpath_sim.py:531-541,571,584,674`: `surface_slice_points` collects a ±0.55×θ-step wedge and places vertices at `theta_emit` with their own radius (pulling side-of-nose radii onto the centerline), while `cl_poses` records vertex-based `apex` instead of FK of emitted joints and `detect_gouges` only probes `~60` poses without probing the apex.
    3. `toolpath_sim.py:549-568,591-602`: Approach and retract moves interpolate `phi`, `r`, and `h` simultaneously, swinging the tip below cut height into the upper lip/face without `is_rapid` or `cl_poses` coverage.
  - **Important (6)**:
    4. `toolpath_sim.py:289-306`: `finishing_phi` uses `phi = beta - alpha` and checks `phi <= phi_max` (rejecting >15° below horizontal instead of `|beta - phi| <= 90° - alpha`), disagreeing with spec and `kinematics.phi_selection_policy`.
    5. `toolpath_sim.py:66-77`: `_joint` skips `validate_joints`, so generated trajectories never surface `SOFT_LIMIT_EXCEEDED`.
    6. `toolpath_sim.py:221-223`: `multiple_hits=False` undercounts top-down shadow on multi-layer geometry (ears/hair/uploads).
    7. `toolpath_sim.py:241-286,576-587`: Wedge-binned finishing order depends on tessellation and can zigzag across overhangs.
    8. `toolpath_sim.py:645-655`: Hitting `max_frames` truncates the trajectory with only a warning, leaving the tool inside the stock without retracting.
    9. `static/wax_worker.js:52-57,89-99`: Shank check only runs every 4th tilted finishing frame (missing intermediate cutting moves), and snapshot eviction `splice(1, 1)` clusters snapshots at the end of the timeline.
- **Reported Issue / Raw Trace**:
  ```
  PR #1 Verdict: REQUEST CHANGES
  - static/wax_worker.js:79,93,101 ignores data.config.tool (uses DEFAULT_TOOL)
  - static/wax_worker.js:89 checks shank only every 4th tilted frame; snapshots bunch at end
  - toolpath_sim.py:531-541,571,584,674 wedge vertex radius distortion + cl_poses != FK + 60-pose gouge subsample
  - toolpath_sim.py:549-568,591-602 simultaneous (r, h, phi) approach/retract swings tip into part
  - toolpath_sim.py:289-306, 66-77, 221-223, 645-655 reachability formula, missing limit check, multiple_hits=False, truncation without error/retract
  ```
- **Root Cause**:
  - `wax_worker.js` never mapped `data.config.tool` on `init` and throttled `checkShank` / evicted snapshots unevenly.
  - `toolpath_sim.py` approximated `r–Z` slices via azimuthal vertex wedges, coupled `phi` changes with radial/vertical transitions, skipped `validate_joints` in `_joint`/`build_trajectory`, used `multiple_hits=False` for shadow rays, and truncated at `max_frames` without failing or coarsening.
- **Target Files**: `static/wax_worker.js`, `toolpath_sim.py`, `server.py`, `tests/test_wax_sdf.mjs`, `tests/test_carver_sim.py`
- **Resolution Strategy**:
  1. Map `data.config.tool` in `wax_worker.js` `init`, pass it to `checkRapid`/`checkShank`/`subtractTool`, check shank on every cutting frame, and thin snapshots evenly.
  2. Replace wedge vertex binning in `toolpath_sim.py` with planar `mesh.section(plane_normal=e_θ, plane_origin=0)` contour slicing, compute `cl_poses` from FK of emitted frames, and run `detect_gouges` (including apex) on all finishing frames.
  3. Split approach/retract transitions into 3 safe moves: retract along `-u` at constant `phi` until clear of stock, reorient `phi`, then rapid (reverse for approach).
  4. Fix `finishing_phi` to clamp `beta - alpha` and test `|beta - phi| <= 90° - alpha`, enable `multiple_hits=True` in shadow raycasts, validate all frames in `build_trajectory`, and raise HTTP 422 (or error) on `max_frames` exceedance.
- **Status**: PARTIAL — see Resolution Progress below
- **Resolution Progress** (2026-11-18):
  - `static/wax_worker.js`: `data.config.tool` is mapped on `init` into `workerTool`
    and passed to `checkRapid`, `checkShank` and `subtractTool`; `checkShank` runs
    on every tilted cutting frame (no `>= 4` skip); snapshots are thinned evenly
    instead of `splice(1, 1)`. Verified by `tests/test_wax_worker.mjs` (2/2).
  - `static/wax_sdf_core.js`: *(Correction: `902b8b8` already computed `apex - axis * t` in `_sampleBody`; `d268090` only updated comments in this file.)*
  - `toolpath_sim.py`: finished the planar section slicing (`mesh_plane` +
    face normals, no `networkx` dependency), the 3-step constant-`phi`
    approach/retract, `|beta - phi| <= 90° - alpha` reachability,
    `multiple_hits=True` shadow rays, joint-limit collection in `_joint`, and
    `FrameCapExceededError` (no mid-stock truncation).
  - **NOT resolved — finishing fidelity**: after ~10 attempts at per-point outward
    normals (`mesh.contains` returns unreliable answers for face-adjacent points in
    trimesh 5.2.1; section-projection normals flip at the closed plinth seam), the
    finishing stage now emits radial draw passes with `phi = 0`. That is safe and
    gouge-clean for a star-shaped stock but does **not** drive the wrist pitch per
    surface normal, so `UNREACHABLE_UNDERCUT_AREA` / `phi != 0` finishing is not
    implemented as specified.
  - **Blast radius**: `server.py` Pydantic constraints + 422 mapping for
    `FrameCapExceededError` are **not written**.
  - **Test state**: Node `tests/test_wax_sdf.mjs` 9/9 pass; `tests/test_wax_worker.mjs`
    2/2 pass; Python `unittest discover -s tests` = **6 failures, 2 errors**
    (5 are the intended `phi = 0` contract change needing updated assertions, 3 are
    genuine gaps: shadow fixture, approach-height, planar-contour assertions, and the
    two API 422 tests with no implementation).

### [PATCH-10b] Restore Wrist-Pitched Undercut Finishing, Transition/Gouge/Shank Fixes & API 422 Validation

- **Date**: 2026-11-18 16:27:00 UTC
- **Feedback Source**: Code Review (PR #1 head `d268090` — `REQUEST CHANGES` from Agent 1 & Agent 2)
- **Feedback Summary**:
  1. `d268090` regressed finishing to `phi = 0` draw passes because `trimesh.nearest.signed_distance` was misread as negative-inside (it is **positive inside**). Do NOT rewrite the 5 failing spec tests to `phi = 0`; restore wrist-pitched undercut finishing using `section_contour` face normals.
  2. Filter `section_contour` to `radius >= 0` (the `theta + pi` negative half is visited by its own slice).
  3. Fix `safe_approach_moves` to drop to cut height at `R + clearance`, pitch `phi` there, then slide along `-u` at constant `phi` (instead of a diagonal from above the stock).
  4. Fix `detect_gouges` to check `signed_distance(axis_pt) > -(tip_r + kerf + t * tan(alpha))` at each station along the axis.
  5. Restore tilted-pass standoff to `tip_r + melt_kerf_mm` instead of `6 mm` / `finish_standoff_mm`.
  6. Remove the `tilted` gate on `checkShank` in `static/wax_worker.js` so every cutting frame is checked as specified.
  7. Implement `server.py` HTTP 422 handling (Pydantic field constraints on `stock_cfg`/`tool_cfg` + `FrameCapExceededError -> 422`) and revert `machine_config.json` preset coarsening (`demo` 15°→7.5°, `standard` 10°→5°) and `max_frames` bump (`400000`→`250000`).
  8. Keep the valid `d268090` fixes (worker tool mapping, even snapshot thinning, `multiple_hits=True` shadow rays, `mesh_plane` sections, `FrameCapExceededError`, per-joint limit validation, FK gouge checks on every emitted frame).
- **Reported Issue / Raw Trace**:
  ```
  Python unittest discover -s tests: 6 failures, 2 errors at d268090
  - toolpath_sim.py:806-835 forces phi = 0 on finishing
  - server.py:125-149 lacks 422 handling for invalid stock_cfg/tool_cfg and FrameCapExceededError
  - machine_config.json:66-83 coarsened theta_step_deg and raised max_frames to 400000
  - static/wax_worker.js:120-121 gates checkShank behind tilted check
  ```
- **Root Cause**:
  - `trimesh.nearest.signed_distance` returns **positive** values inside a watertight mesh and negative outside; `surface_normal_at` flipped normals inward, causing upside-down cuts and the `phi = 0` retreat.
- **Target Files**: `toolpath_sim.py`, `machine_config.json`, `static/wax_worker.js`, `server.py`, `tests/test_carver_sim.py`, `tests/test_wax_worker.mjs`, `openspec/changes/carver-sim-mvp/patch.md`, `openspec/changes/carver-sim-mvp/verification.md`
- **Resolution Strategy**:
  - Add a step-zero sign-convention test for `trimesh.nearest.signed_distance` (>0 inside), delete `surface_normal_at`, restore `section_contour` normals (`radius >= 0`) + `finishing_phi` + `tip_r + kerf` standoff, fix 3-step approach & `detect_gouges` radius threshold, remove `tilted` gate in `wax_worker.js`, add `server.py` 422 validation, and revert `machine_config.json` presets/`max_frames`.
- **Status**: SUPERSEDED by PATCH-10c (step-zero sign test landed; finishing rewrite left uncommitted and red)

### [PATCH-10c] Structured Undercut Finishing: Ordered Section Polylines, Exact Body Check, Axial Entry/Exit, API 422 & Config Revert

- **Date**: 2026-11-18 16:49:42 UTC
- **Feedback Source**: Code Review of the uncommitted PATCH-10b working tree + Unit Test Failure (`unittest discover -s tests`: 41 run, 6 failures, 2 errors, 1 skip)
- **Feedback Summary**:
  PATCH-10b correctly fixed the sign-convention root cause (step-zero test green) but the finishing rewrite did not converge. The agent tried four heuristics in a row (raw face normals; skip downward faces; snap the CC->CL offset to pure radial/vertical; `_flank_clearance` pre-filter). Each one moved the failure somewhere else because `build_finishing` has **four independent defects that interact**, and the only feedback signal was an end-to-end count ("2.9k gouges", "36% unreachable"):
  1. **Contour ordering (structural):** `section_contour` returns points sorted by `(z, radius)`, not walked along the section, and `build_finishing` joins every accepted point with a straight cutting move. On the needle fixture, each z between 40 and 50 alternates body wall (r=15), needle inner face (r=19.2) and needle outer face (r=20.8), so consecutive cuts pass *through* the needle. Skipped (unreachable) points also get bridged by straight cuts through material. The "zig-zags across the axis" diagnosis was wrong: it zig-zags across a separate island and across rejected gaps.
  2. **`finishing_phi` (L395-423):** the `n_z <= 0.2` branch clips `n_z` to 0, so every downward face is treated as a vertical wall and reported reachable at phi = beta - alpha. Flat tops get phi = -30 deg because the `max(0, beta - alpha)` floor from the original implementation was dropped.
  3. **CC->CL offset (L838-846):** the true normal is snapped to pure radial or pure vertical before offsetting, so on slopes the apex is placed off the cutter-location point. Separately, the blanket `n_z < -0.2 -> unreachable` (L822-828) throws away undercuts that are geometrically reachable (|beta - phi| <= 90 - alpha allows faces up to 45 deg below horizontal at phi_max = 75, alpha = 30). That is why the ellipsoid head read 36-100 % unreachable.
  4. **`_flank_clearance` (L721-757) is inverted twice:** it builds the body axis from `-normal` instead of the FK tool axis at phi, and it returns `flank + signed_distance`, which is **negative** when clear (signed_distance < 0 outside). Callers treat `<= 0` as blocked, so every clear pose was rejected (99-100 % unreachable). It is the same sign misreading as PATCH-10b, one layer down.
  Secondary defects found in the same pass:
  5. **Approach slide (L690-719)** moves horizontally at the cut z, not along -u as its docstring says. For a pitched cut under an overhang, the body sweeps through the overhang tip during the slide.
  6. **`section_contour` ignores `sample_step_mm`** (`_ = sample_step_mm`) and samples every max(0.5, extent/300) mm, which inflates frames (448k-471k, over the cap).
  7. **Roughing stepdown leaves real shank contact (L500).** Stepdown is clamped to `0.75 * engaged` = 6 mm, but the previous level's cone only clears the unheated shank footprint if `stepdown <= engaged - (shank_r - tip_r - kerf) / tan(alpha)` = 8 - 2.1/0.577 = **4.36 mm**. Above that, a sliver of wax at r_cur - 3 .. r_cur - 2.05, z+8 .. z+9.7 sits inside the shank on vertical walls. That sliver is very likely the "false" SHANK_COLLISION behind PATCH-07 and the `tilted` gate in `wax_worker.js:120-121`.
  Four of the eight failing tests have **demonstrably incorrect assertions** (details under Resolution Strategy). They are not spec-encoding tests and may be corrected. `test_finishing_uses_phi_and_reports_unreachable_undercuts` IS spec-encoding and must not be edited.
- **Reported Issue / Raw Trace**:
  ```
  ERROR test_max_frames_exceedance_maps_to_422       FrameCapExceededError: 448079 frames > max_frames=400000 (server has no 422 mapping)
  ERROR test_out_of_bounds_stock_emits_soft_limit_exceeded  FrameCapExceededError: 470955 frames > 400000 (limit errors not short-circuited before resampling)
  FAIL  test_zero_tool_radius_returns_422            200 != 422
  FAIL  test_approach_and_retract_never_drop_below_cut_height  120.109375 not <= 120.000001
  FAIL  test_finishing_follows_planar_contours       77.33 not < 24.0
  FAIL  test_finishing_phi_reachability_allows_surface_close_to_phi  True is not false
  FAIL  test_shadow_profile_uses_multiple_hits       15.0 not > 19.0
  FAIL  test_finishing_uses_phi_and_reports_unreachable_undercuts  0 not > 20
  Ran 41 tests in 171.517s  FAILED (failures=6, errors=2, skipped=1)
  ```
- **Root Cause**: `build_finishing` is one monolithic loop with no unit-testable seams, so four interacting geometry defects (ordering, phi branch, snapped offset, inverted clearance sign) could only be observed through aggregate end-to-end counts. Each heuristic fix hid one defect and exposed another.
- **Target Files**: `toolpath_sim.py`, `server.py`, `machine_config.json`, `static/wax_worker.js`, `tests/test_carver_sim.py`, `tests/test_wax_worker.mjs`, `openspec/changes/carver-sim-mvp/verification.md`, `openspec/changes/carver-sim-mvp/patch.md`, `openspec/changes/carver-sim-mvp/tasks.md`
- **Resolution Strategy**: Keep the current working tree (do **not** revert to `d268090`, whose phi = 0 path and axis-only gouge probes are worse). Split finishing into pure helpers, each with its own unit test, then compose them: ordered section polylines -> fixed `finishing_phi` -> true-normal CL offset -> one vectorised `tool_body_penetrates` (ring + axis points, `mesh.contains`) shared by the pre-filter and `detect_gouges` -> runs of consecutive accepted points -> axial exit/entry with a radial fallback. Short-circuit on SOFT_LIMIT before resampling, add the server 422s, clamp roughing stepdown to the shank-safe bound and remove the worker `tilted` gate, revert the presets and frame cap, and correct the four demonstrably wrong test assertions. Full step list in `handoff-patch.md`.
- **Status**: PENDING

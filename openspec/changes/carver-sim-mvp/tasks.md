## 1. Test Scaffolding (TDD)

- [x] 1.1 Scaffold failing tests in `tests/test_carver_sim.py` for 4-DOF FK algebraic/sign verification ($\phi = 0^\circ, 90^\circ$, `tip_xyz_wax`, `tool_axis_wax`), IK round-trip + `PHI_POLICY_CLAMPED` + tangential-normal fallback, `SOFT_LIMIT_EXCEEDED`, and a pending-hardware `±1.0 mm` calibration fixture
- [x] 1.2 Scaffold failing tests for relative tip speed (`v_tip` on pure $\theta$ rotation and combined $(r, \theta, h, \phi)$ motion with $\phi \ne 0^\circ$ and unwrapped $\theta$), timing model, and `SINGULARITY_HIGH_THETA_DOT`
- [x] 1.3 Scaffold failing tests for watertight, non-self-intersecting parametric facial deformation (`apply_facial_modifications`) bounded inside $(R_{\text{stock}} - \text{finish\_allowance\_mm}, H_{\text{stock}})$ and `STOCK_BOUNDS_EXCEEDED`
- [x] 1.4 Scaffold failing tests for shadow-clipped roughing, $r$–$Z$ undercut finishing (`UNREACHABLE_UNDERCUT_AREA`, `GOUGE`), engaged-length resampling ($\Delta s_{\max} \le 0.5 \cdot \text{tip\_width}$), and `POST /api/sculpt-and-sim` columnar base64 payload contract
- [x] 1.5 Scaffold failing Node tests in `tests/test_wax_sdf.mjs` for `wax_sdf_core.js`: undercut subtraction across `16³` chunk boundaries + dirty neighbors, `RAPID_COLLISION`, `SHANK_COLLISION`, snapshot scrub replay, surface fidelity, and zero-trig JS lint

## 2. Backend Kinematics, Sculpting & Synthetic Toolpaths

- [x] 2.1 Create `machine_config.json` (datums, `pivot_to_tip_mm`, conical-bevel + shank profile, `melt_kerf_mm`, stock/plinth defaults, feeds, per-axis `v_max`, singularity thresholds, soft limits) and `package.json` (pinning Node `>=20` and Three.js)
- [x] 2.2 Implement `kinematics.py` with Python-only FK/IK (`tip_xyz_wax`, `tool_axis_wax`, $r$–$Z$ normal projection, `PHI_POLICY_CLAMPED`, `SOFT_LIMIT_EXCEEDED`), segment timing, relative $v_{\text{tip}}$, and `SINGULARITY_HIGH_THETA_DOT`
- [x] 2.3 Procedurally generate watertight `presets/base_head.stl` + `presets/base_head_landmarks.json` and implement `face_sculpt.py` (`cKDTree` RBF/Gaussian normal deformations, non-self-intersection guard, `STOCK_BOUNDS_EXCEEDED`)
- [x] 2.4 Implement `toolpath_sim.py` Stage 1: shadow-aware cylindrical roughing ($\phi = 0^\circ$) with safe-by-construction `is_rapid` retracts
- [x] 2.5 Implement `toolpath_sim.py` Stage 2: 2D $r$–$Z$ slice undercut finishing, $\phi$ selection, CC$\to$CL offset, `UNREACHABLE_UNDERCUT_AREA` / `GOUGE` diagnostics, engaged-length resampling, and `demo`/`standard` presets
- [x] 2.6 Implement `server.py` (FastAPI) exposing `GET /api/health`, `POST /api/sculpt-and-sim` (columnar base64 `Float32Array`/`Uint8Array` buffers, `max_frames` cap), and static file serving

## 3. Three.js Primitive Rig & Volumetric SDF Wax Viewer

- [x] 3.1 Run SDF performance benchmark spike measuring `128³` conical-bevel subtraction + `16³` dirty-chunk Marching Cubes remesh time to verify $\ge 30\text{ FPS}$ budget
- [x] 3.2 Implement `static/machine_rig.js` (`PrimitiveCarverRig` inside `-90°` X-rotated root group, driven solely by backend poses with zero JS trig)
- [x] 3.3 Implement `static/wax_sdf_core.js` (pure JS exact cylinder SDF + exterior padding, conical-bevel subtraction, `16³` chunks with 1-voxel apron + neighbor dirtying + global gradient normals, `RAPID_COLLISION`, `SHANK_COLLISION`, and snapshots)
- [x] 3.4 Implement `static/wax_worker.js` and `static/wax_sdf.js` (Web Worker with transferable chunk mesh buffers and Three.js `BufferGeometry` adapter)
- [x] 3.5 Implement `static/index.html` and `static/app.js` with facial sliders, `Demo`/`Standard` preset, `THREE.Clock` loop, transport bar (`Play/Pause`, `Scrub`, `1x–20x`, `Carve to End`), fault auto-pause, and live telemetry

## 4. Verification & Empirical Audit

- [x] 4.1 Run full Python (`python -m unittest discover -s tests -v`) and Node (`node --test tests/test_wax_sdf.mjs`) test suites and verify clean passes
- [x] 4.2 Strictly validate OpenSpec artifacts (`openspec validate carver-sim-mvp --strict`)
- [x] 4.3 Populate `verification.md` with Requirement Adherence Matrix, resolved assumptions, hardware calibration fixture status, and verbatim execution logs

## Patch 10: PR #1 Review Fixes (Worker Tool Config, Finishing Sections/Transitions, Reachability, Limits & Shank Checks)

- [ ] P10.1 Scaffold failing Node & Python tests (Node cases written and passing; Python reproductions written but not yet green) for non-default `config.tool` volume difference, every-cut-frame shank check, even snapshot retention, planar section finishing + FK gouge check, 3-step safe approach/retract, `|beta - phi| <= 90° - alpha` reachability, `multiple_hits=True` shadow, `SOFT_LIMIT_EXCEEDED` on out-of-bounds stock, and `max_frames` 422 error
- [x] P10.2 Fix `static/wax_worker.js` (`init` tool mapping, pass `tool` to `checkRapid`/`checkShank`/`subtractTool`, check shank on every cutting frame, even snapshot thinning)
- [ ] P10.3 Fix `toolpath_sim.py` (`multiple_hits=True` shadow, `mesh.section` planar `r–Z` contour slicing, 3-step constant-`phi` retract/approach, `|beta - phi| <= 90° - alpha` reachability, FK-derived `cl_poses` + full `detect_gouges`, joint limit validation, and `max_frames` error) and `server.py` (422 on frame cap / invalid `stock_cfg`/`tool_cfg`)
- [ ] P10.4 Verify all reproduction tests pass and run full Python + Node regression suites (Node suites green: 9/9 core + 2/2 worker; Python regression suite red — see patch.md PATCH-10 status)
- [ ] P10.5 Update `verification.md` and mark `PATCH-10` as `VERIFIED` in `patch.md` (blocked on P10.4)

## Patch 10b: Restore Undercut Finishing, Approach/Gouge/Shank Fixes & API 422

- [ ] P10b.1 Add step-zero `trimesh.nearest.signed_distance` sign-convention reproduction test (>0 inside watertight sphere/mesh) and verify existing Python failures reproduce without editing the 5 spec-encoding assertions
- [ ] P10b.2 Revert `machine_config.json` presets (`demo` `theta_step_deg: 7.5`, `standard` `theta_step_deg: 5.0`) and `api.max_frames: 250000`; remove `tilted` gate in `static/wax_worker.js` so `checkShank` runs on every cutting frame
- [ ] P10b.3 Fix `toolpath_sim.py`: delete `surface_normal_at`, filter `section_contour` to `radius >= 0`, feed `section_contour` normals into `finishing_phi` + count unreachable points, restore `tip_r + melt_kerf_mm` standoff for tilted passes, fix `safe_approach_moves` (drop to `z` at `R + clearance`, pitch `phi`, slide along `-u`), and fix `detect_gouges` (`signed_distance(axis_pt) > -(tip_r + kerf + t * tan(alpha))`)
- [ ] P10b.4 Implement `server.py` HTTP 422 validation (Pydantic constraints on `stock_cfg`/`tool_cfg` + `FrameCapExceededError -> 422`)
- [ ] P10b.5 Run full Python (`python3 -m unittest discover -s tests -v`) and Node (`node --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs`) suites + `openspec validate carver-sim-mvp --strict`, update `verification.md`, and mark `PATCH-10` & `PATCH-10b` `VERIFIED` in `patch.md`

## Patch 10c: Structured Undercut Finishing, API 422 & Config Revert

- [ ] P10c.1 Add unit tests for the new pure helpers (`section_polylines` ordering, `finishing_phi` table, `cutter_location` offset, `tool_body_penetrates` clear/buried, `exit_moves` direction) and correct the four demonstrably wrong assertions; confirm `test_finishing_uses_phi_and_reports_unreachable_undercuts` still fails unedited
- [ ] P10c.2 Refactor `toolpath_sim.py` finishing into the helpers, fix `finishing_phi`, true-normal CL offset, run splitting, axial entry/exit, `sample_step_mm`, SOFT_LIMIT short-circuit, and roughing shank-safe stepdown
- [ ] P10c.3 `server.py` 422s (Pydantic constraints, error-severity diagnostics, `FrameCapExceededError`); revert `machine_config.json` presets/`max_frames`/unused `finish_standoff_mm`; remove the `tilted` gate in `static/wax_worker.js` + vertical shank worker test
- [ ] P10c.4 Run full Python + Node suites, the integrated 128^3 sweep (0 rapid / 0 shank hits) and `openspec validate carver-sim-mvp --strict`
- [ ] P10c.5 Update `verification.md`, tick P10.*/P10b.*/P10c.*, mark PATCH-10, PATCH-10b, PATCH-10c `VERIFIED` in `patch.md`

## Patch 10d: Helper 1 Ordering Fix + Continue PATCH-10c

- [ ] P10d.1 Reproduce the 2 red section-polyline tests and print the post-clip, pre-split pieces for the box fixture
- [ ] P10d.2 Fix `_clip_band.crossing_parameters` per-axis bounds and reorder `section_polylines` (clip first; split only untouched closed islands; rotate crossing loops to an outside vertex); fix the islands-test comment
- [ ] P10d.3 All 4 section tests green; commit `wip(carver-sim): P10c helper 1 green`; helper 1 frozen
- [ ] P10d.4 Complete P10c.2-P10c.5 (helpers 2-5, `build_finishing`, server 422s, config revert, worker gate, suites, 128^3 sweep, validate, docs)

## Patch 10e: Test Rulings, Helper 5 (`exit_moves`) Radial Pullout & `build_finishing` Composition

- [ ] P10e.1 Apply test rulings in `tests/test_carver_sim.py`: revert `test_exit_moves_are_clear_and_end_outboard` fixture to `fb0c145` (`80×80×20` slab, `apex` at `z=82`), fix `test_tool_body_penetrates_when_tilted_into_wall` L952 (`< 15.0`), and confirm both helper tests fail/pass as expected (helpers 1–4 frozen)
- [ ] P10e.2 Fix `exit_moves` (add horizontal `+e_r` pullout candidate at constant `phi` before re-pitching) and `entry_moves`; compose `build_finishing` from `section_polylines`, `finishing_phi`, `cutter_location`, `tool_body_penetrates`, `entry_moves`, and `exit_moves` (removing all calls to `_flank_clearance`, `safe_approach_moves`, `safe_retract_moves`)
- [ ] P10e.3 Complete remaining PATCH-10c items: `SOFT_LIMIT` short-circuit + roughing shank-safe stepdown in `toolpath_sim.py`, `server.py` 422s, `machine_config.json` revert (`7.5°`/`5.0°`, `max_frames: 250000`), and `static/wax_worker.js` `tilted` gate removal + vertical shank worker test
- [ ] P10e.4 Run full Python (`python3 -m unittest discover -s tests -v`), Node (`node --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs`), `128³` sweep, and `openspec validate carver-sim-mvp --strict --json`
- [ ] P10e.5 Update `verification.md` with fresh logs, tick `P10.*`–`P10e.*` in `tasks.md`, and mark `PATCH-10`..`PATCH-10e` `VERIFIED` in `patch.md`


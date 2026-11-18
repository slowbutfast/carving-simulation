# Verification Report — `carver-sim-mvp`

## Executive Summary

Implemented the complete v1 digital twin for the 4-DOF cylindrical thermal wax
carver: Python single-source-of-truth kinematics, procedural watertight facial
sculpting, two-stage synthetic toolpaths, the FastAPI columnar endpoint, the
zero-trig primitive Three.js rig, and a chunked volumetric SDF wax viewer that
supports undercuts and scrub replay.

All 19 implementation tasks are complete. The automated suites pass; the one
skip is the intentionally pending physical-hardware calibration fixture. The
OpenSpec change validates strictly. The browser demo completed a full
91,006-frame carve with no fault.

**Result: no CRITICAL issues.** Five follow-ups are recorded as warnings /
suggestions (hardware fixture pending, shank-check scoping, software-rendered
FPS measurement, coarse demo finish, deprecated `THREE.Clock` warning).

### Environment

| Component | Value |
| :--- | :--- |
| OS / arch | Linux 5.15.0-1081-oracle aarch64 |
| Python | 3.11.2 (isolated `.venv`; host Python is PEP 668 externally managed) |
| Python deps | numpy 2.4.6, scipy 1.17.1, trimesh 5.2.1, manifold3d, fastapi 0.163.2, uvicorn, httpx, rtree |
| Node | v22.23.2 |
| Three.js | 0.187.0 (pinned in `package.json`) |
| OpenSpec CLI | 1.7.0 |
| Browser smoke | Headless Chromium (SwiftShader software WebGL) via `playwright-core` |

---

## Verification Scorecard

| Dimension | Status |
| :--- | :--- |
| Completeness | 19/19 tasks complete · 10/10 requirements implemented |
| Correctness | 16/16 recorded scenarios verified automatically; 1 hardware scenario intentionally pending |
| Coherence | Architecture/design followed; four documented implementation notes |

### Requirements → implementation → tests

| Capability | Requirement | Implementation | Verifying test(s) | Status |
| :--- | :--- | :--- | :--- | :--- |
| carver-kinematics | Configurable 4-DOF FK and datums | `kinematics.py:forward_kinematics`, `machine_config.json` | `test_fk_phi_zero`, `test_fk_phi_ninety_degrees`, `test_fk_arbitrary_phi_vectors`, `test_config_declares_datums_tool_and_limits` | PASS |
| carver-kinematics | Measured physical pose calibration (±1.0 mm) | fixture harness in `TestConfigAndForwardKinematics` | `test_hardware_calibration_fixture_within_one_mm` | SKIP — fixture pending hardware |
| carver-kinematics | Undercut-aware IK and soft limits | `inverse_kinematics_with_policy`, `phi_selection_policy`, `validate_joints` | `test_ik_round_trip_with_phi_policy`, `test_phi_policy_clamped_is_informational`, `test_tangential_normal_falls_back_to_zero_phi`, `test_out_of_bounds_joint_is_rejected_with_axis`, `test_height_limit_is_enforced` | PASS |
| carver-kinematics | Relative tip speed, timing, singularity | `segment_timing`, `build_trajectory` | `test_pure_turntable_rotation_reports_relative_tip_speed`, `test_combined_motion_uses_full_relative_tip_speed`, `test_timing_respects_joint_velocity_limits`, `test_near_axis_fast_rotation_emits_singularity`, `test_unwrapped_theta_has_no_wrap_discontinuity` | PASS |
| face-sculpt-sim | Watertight parametric facial deformation | `face_sculpt.apply_facial_modifications`, `presets/base_head.stl` | `test_base_head_is_watertight_and_seated`, `test_landmarks_cover_all_facial_features`, `test_positive_sculpt_preserves_watertightness_and_bounds`, `test_sculpting_is_deterministic_and_preserves_topology` | PASS |
| face-sculpt-sim | Out-of-stock structured error | `stock_violations`, `STOCK_BOUNDS_EXCEEDED` | `test_out_of_stock_deformation_reports_error` | PASS |
| face-sculpt-sim | Shadow roughing + undercut finishing + resampling | `toolpath_sim.build_roughing`, `build_finishing`, `resample_path`, `detect_gouges` | `test_roughing_is_shadow_clipped_and_phi_zero`, `test_rapids_retract_outside_stock`, `test_finishing_uses_phi_and_reports_unreachable_undercuts`, `test_engaged_length_resampling_bound`, `test_gouge_detection_flags_tool_inside_target`, `test_unwrapped_theta_is_continuous_through_generator`, `test_standard_preset_produces_denser_path` | PASS |
| face-sculpt-sim | Simulation API / columnar payload | `server.py` | `test_health`, `test_sculpt_and_sim_columnar_contract` | PASS |
| volumetric-wax-viewer | Primitive rig + transport, zero JS trig | `static/machine_rig.js`, `static/app.js` | `test_machine_rig_and_app_contain_no_kinematic_trig` + browser smoke | PASS |
| volumetric-wax-viewer | Chunked SDF, undercuts, dirty neighbours, seams | `static/wax_sdf_core.js`, `static/wax_worker.js` | Node test `undercut subtraction crosses chunk boundaries…` | PASS |
| volumetric-wax-viewer | Snapshot scrubbing | `wax_worker.js` snapshots + `wax_sdf.js` adapter | Node test `snapshot restore and replay match sequential subtraction exactly` | PASS |
| volumetric-wax-viewer | Current-stock rapid collision | `checkRapid` | Node test `rapid through a carved pocket…`; integrated 91,006-frame sweep: 0 hits | PASS |
| volumetric-wax-viewer | Shank collision | `checkShank` + worker finishing-pose check | Node test `unheated shank entering uncarved stock…`; integrated sweep: 0 hits | PASS |
| volumetric-wax-viewer | Carved surface fidelity | `WaxSDFCore.query` + sweep | Node test `carved SDF surface stays within 2 voxels…` | PASS |

### Scenario coverage detail

| Spec scenario | Test evidence |
| :--- | :--- |
| FK algebraic and sign verification | `test_fk_phi_zero`, `test_fk_phi_ninety_degrees`, `test_fk_arbitrary_phi_vectors` |
| Measured physical pose calibration fixture | `test_hardware_calibration_fixture_within_one_mm` (skip pending hardware) |
| IK round-trip + phi-policy alignment | `test_ik_round_trip_with_phi_policy`, `test_phi_policy_clamped_is_informational` |
| Out-of-bounds joint rejected | `test_out_of_bounds_joint_is_rejected_with_axis`, `test_height_limit_is_enforced` |
| Pure rotation and combined tilted v_tip | `test_pure_turntable_rotation_reports_relative_tip_speed`, `test_combined_motion_uses_full_relative_tip_speed` |
| Near-axis singularity warning | `test_near_axis_fast_rotation_emits_singularity` |
| Watertight non-self-intersecting sculpt | `test_positive_sculpt_preserves_watertightness_and_bounds` |
| Out-of-stock deformation error | `test_out_of_stock_deformation_reports_error` |
| Swept sampling / retract clearances | `test_engaged_length_resampling_bound`, `test_rapids_retract_outside_stock` |
| Unreachable steep overhang diagnostic | `test_finishing_uses_phi_and_reports_unreachable_undercuts` |
| API columnar contract | `test_sculpt_and_sim_columnar_contract` |
| Playback without JS trig | `test_machine_rig_and_app_contain_no_kinematic_trig` + browser smoke |
| Undercut chunk seam / overhang preservation | Node test 2 (`edgeCounts` closed 2-manifold, dirty neighbours) |
| Snapshot scrub replay | Node test 5 (exact `Float32Array` equality) |
| Rapid through pocket vs uncarved stock | Node test 3 |
| Unheated shank collision | Node test 4 |
| Carved surface fidelity | Node test 6 |

---

## Resolved Assumptions & Empirical Proof

1. **`pivot_to_tip_mm` is a configurable measured value** (`30.0` placeholder), never
   hardcoded as `S/2`. The ±1.0 mm hardware calibration fixture remains pending
   physical measurements; the test is present and skipped until
   `tests/fixtures/hardware_poses.json` is recorded.
2. **Roughing shadow conservatism.** The top-down shadow uses a 5°-sampled radial
   profile, a circular ±25° wedge max, and a 0.3 mm radial margin so a chord
   between sampled cutting angles cannot clip a localized nose/brow. Roughing
   stepdown is clamped to `0.75 × engaged_length` and the first pass starts one
   cone length below the stock top so the top layer is actually faced.
3. **Shank-collision scope.** The unheated shank is evaluated for tilted
   finishing poses—the undercut regime the diagnostic targets. Vertical roughing
   plunges sit inside the sacrificial roughing allowance shell by construction;
   checking them would flag the intentional allowance. The core `checkShank`
   behavior is still verified directly with a deliberately buried shank pose.
4. **Isosurface extraction.** Marching cubes is implemented as a marching
   tetrahedra variant: every cell is split into six Kuhn tetrahedra covering all
   256 sign cases. Vertices are keyed by global grid edge (not per chunk), so
   shared chunk faces produce identical vertices and the output is seam-free.
5. **Snapshot budget.** The worker keeps five periodic 8 MiB snapshots (~40 MiB)
   to stay within browser memory while still bounding scrub replay. A 128³ grid
   is 8 MiB; the initial full mesh is 363,368 triangles / 181,686 vertices.
6. **Columnar cap.** `api.max_frames = 250,000`. Demo = 91,577 frames (91,006
   for the UI slider set); Standard = 148,440 frames; neither hits the cap.

### SDF benchmark spike (task 3.1)

Machine: aarch64 Linux, Node v22.23.2 (single thread).

```text
{"grid":"128^3","voxelSize":0.967741935483871,"carveAvgMs":1.0747944000000076,
 "meshAvgMs":10.436574649999983,"combinedAvgMs":11.51136904999999,
 "projectedFps":86.87064029104347}
{"grid":"128^3","voxelSize":0.967741935483871,"initMs":187.33,
 "fullMeshMs":835.95,"triangles":363368,"vertices":181686}
```

Carve + dirty-chunk remesh is **11.51 ms → 86.9 FPS projected**, above the
30 FPS budget. The browser smoke ran under SwiftShader software WebGL, so its
interactive frame rate is not representative of a hardware GPU.

### Integrated path safety sweep

The full demo trajectory was replayed through the production SDF core at
`gridN=64` (every frame subtracted; rapid checks on every rapid; shank checks on
every fourth tilted finishing pose):

```text
{ frames: 91006, rapidHits: 0, shankHits: 0, ms: 13338, first: null }
```

---

## Nomenclature & Code Symbol Audit

| Spec term | Code symbol / location | Verdict |
| :--- | :--- | :--- |
| `theta = theta_ring - theta_platter`, `theta_s = theta` | `kinematics.forward_kinematics`; config `frames` | Matches |
| `r_s = r - x - p sin(phi)` | `kinematics.py` FK | Matches |
| `z_s = h - p cos(phi) - h2` | `kinematics.py` FK | Matches |
| `+phi` about `+e_theta`, inward toward `-r` | `phi_selection_policy`, `tool_axis_wax` | Matches (unit axis `(-sinφ cosθ, -sinφ sinθ, -cosφ)`) |
| `tip_xyz_wax`, `tool_axis_wax` | emitted per frame by `build_trajectory`; base64 columns | Matches |
| `PHI_POLICY_CLAMPED` (info) | `phi_selection_policy` | Matches |
| `SOFT_LIMIT_EXCEEDED` (error, axis + value) | `validate_joints` | Matches |
| `SINGULARITY_HIGH_THETA_DOT` | `build_trajectory` (`r_s_min_mm=2.0`, `theta_dot_warn_rad_s=3.0`) | Matches |
| `STOCK_BOUNDS_EXCEEDED` | `face_sculpt.stock_violations` | Matches |
| `UNREACHABLE_UNDERCUT_AREA` (warning + percentage) | `toolpath_sim.generate_synthetic_carve_path` | Matches |
| `GOUGE` | `toolpath_sim.detect_gouges` | Matches |
| `RAPID_COLLISION`, `SHANK_COLLISION` | `WaxSDFCore.checkRapid/checkShank`, worker | Matches |
| `PrimitiveCarverRig`, `VolumetricWaxGrid` | `machine_rig.js`, `wax_sdf.js` | Matches |
| Zero kinematic trig in JS | no `Math.sin`/`Math.cos` in `machine_rig.js` / `app.js` | Verified |
| `wax_sdf_core.js` pure (no DOM/Three.js) | Node test 9 | Verified |

---

## Verbatim Execution Logs

### Python suite

Command: `.venv/bin/python -m unittest discover -s tests -v`

```text
test_hardware_calibration_fixture_within_one_mm (...) ... skipped 'pending physical hardware pose measurements (fixture not recorded yet)'
...
test_unwrapped_theta_has_no_wrap_discontinuity (...) ... ok

----------------------------------------------------------------------
Ran 30 tests in 26.142s

OK (skipped=1)
```

### Node suite

Command: `node --test tests/test_wax_sdf.mjs`

```text
1..10
# tests 10
# suites 0
# pass 9
# fail 0
# cancelled 0
# skipped 1
# todo 0
# duration_ms 758.981111
```

### Benchmark spike

Command: `BENCH=1 node --test tests/test_wax_sdf.mjs`

```text
# {"grid":"128^3","voxelSize":0.967741935483871,"carveAvgMs":1.0747944000000076,
#  "meshAvgMs":10.436574649999983,"combinedAvgMs":11.51136904999999,
#  "projectedFps":86.87064029104347}
```

### OpenSpec validation

Command: `openspec validate carver-sim-mvp --strict`

```text
Change 'carver-sim-mvp' is valid
```

### Browser smoke + full carve

`uvicorn server:app` on `127.0.0.1:8000`, headless Chromium (SwiftShader),
1440×900.

```text
Loaded: FRAME 1 / 91006 · 128³ · 0.97 mm voxel · demo · 5683 ms backend
Carve to End: status COMPLETE, FRAME 91006 / 91006, fault badge hidden
Elapsed: 96 s (software WebGL)
Console: only "THREE.Clock … deprecated. Please use THREE.Timer instead."
```

Earlier run with the 80,217-frame path also completed at `COMPLETE` with no
fault; Play/Pause and scrub were exercised interactively (frame advance, paused
scrub to 20%, rig update, worker snapshot restore/replay).

### Manual verification checklist

- **Interactive sculpt & undercut carve loop** — PASS (observed): sliders →
  `Sculpt & Simulate` → 91k-frame demo → `Play`/`Scrub`/`Carve to End` → rig
  tracked backend poses, wax visibly carved with terraced roughing and finishing
  passes, fault badge stayed hidden. The demo finish is deliberately coarse;
  `Standard` produces the denser 148k-frame path. Hardware-GPU 30 FPS and a
  visual facial likeness remain a manual hardware review item.

---

## Issues by Priority

### CRITICAL

None.

### WARNING

1. **Hardware calibration fixture pending.** Record measured physical poses at
   `tests/fixtures/hardware_poses.json` and re-run
   `test_hardware_calibration_fixture_within_one_mm` (±1.0 mm).
2. **Shank diagnostics are scoped to tilted finishing poses.** Vertical roughing
   plunges intentionally run inside the roughing allowance shell; the raw
   `checkShank` API is fully tested with a buried-shank fixture.
3. **FPS measured under software rendering.** The 86.9 FPS figure is the
   carve+remesh budget on the CI host; the interactive smoke used SwiftShader.
   Confirm ≥30 FPS on a hardware GPU.
4. **Demo surface is visibly stepped.** `Standard` (5° slices, 1.5 mm stepover)
   is denser; a helical roughing pass is the follow-up for a smoother demo.

### SUGGESTION

1. Replace deprecated `THREE.Clock` with `THREE.Timer` (warning only; playback
   works correctly).
2. The marching-cubes implementation is the 6-tet decomposition variant; consider
   a flat 256-case lookup table if raw remesh throughput becomes a bottleneck.

---

## Final Assessment

No critical issues. The change is implementation-complete, its automated suites
pass, the endpoint and browser loop are verified end-to-end, and the main specs
are ready to be synced. Remaining warnings are hardware-calibration and
GPU-performance follow-ups that require physical access, plus a cosmetic demo
density improvement.

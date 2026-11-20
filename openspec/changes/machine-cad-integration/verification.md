# Verification — machine-cad-integration

## Executive summary

The CAD (295 placed leaf occurrences, STEP SHA-256
`00882f0ebeaeaae66b7b8eb28e4d2dc9bbf30d65c2d66705f86deec566fd7bd0`) is the
source of the machine: an offline extractor writes `machine_geometry.json` and
six link GLBs (3.20 MiB total). Runtime kinematics use the corrected datums
(orbit theta, signed r to the pivot, h to the pivot, `p = 60`, `x = 0`), and the
cone tool is fully replaced by the 1.2 x 6.0 x 14.0 mm blade in
`tool_model.py`, the toolpath generator, the API and the web worker. The
`expectedFailure` on `test_finishing_follows_planar_contours` is removed and the
test passes.

Two owner gates stay open by design: task 7.1 (roles + joint-sweep sign-off) and
7.2 (pivot axis and stock dimensions). See
`openspec/changes/machine-cad-integration/owner-questions.md` and
`joint-sweep.json`.

## Environment

| Item | Value |
| :--- | :--- |
| Kernel / arch | Linux 5.15.0-1081-oracle, aarch64 |
| Python | 3.11.2 |
| Node | v22.23.2 |
| Runtime deps | `requirements.txt` + `requirements-dev.txt` in `.venv` |
| CAD deps | `cadquery-ocp==8.0.1.1.0`, `trimesh`, `numpy` in `.venv-cad` |
| Three.js | 0.187.0 (`node_modules`, pinned in `package.json`) |

## Result summary

| Suite | Command | Result |
| :--- | :--- | :--- |
| Python runtime | `.venv/bin/python -m unittest discover -s tests -v` | **101 tests, 0 failures, 5 skipped** (one hardware-pose fixture not recorded; four OCP-gated extractor tests) |
| OCP extractor | `.venv-cad/bin/python -m unittest tests.test_machine_cad_extract -v` | **4 tests, 0 failures** |
| Node | `node --experimental-vm-modules --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs tests/test_cad_rig.mjs` | **23 tests, 22 pass, 0 fail, 1 skipped (BENCH)** |

`npm run test:node` runs all three suites with `--experimental-vm-modules`
(required for the ES-module worker); only the `BENCH` benchmark is skipped.

## Requirement adherence audit matrix

### machine-cad-model

| Requirement / scenario | Verifying test | Result |
| :--- | :--- | :--- |
| Units, frame, orbit axis | `test_source_unit_and_frame_are_recorded`, `test_base_plate_diameter_in_machine_frame`, `test_orbit_axis_is_the_machine_z_axis_through_the_origin`, `test_cad_to_machine_transform_moves_the_seat_plane_to_z_zero` | pass |
| Extraction deterministic and traceable | `test_extraction_is_deterministic`, `test_glb_export_is_deterministic_within_the_budget`, `test_step_sha256_matches_the_committed_step` | pass |
| Runtime never depends on OCP | `test_runtime_modules_do_not_import_ocp`, `test_static_js_does_not_reference_the_step_file` | pass |
| Unknown/placeholder parts reported | `test_unknown_and_placeholder_parts_are_reported_by_name`, `test_link_counts_sum_to_295` | pass |
| New part without a rule surfaces as unassigned | `test_unmatched_part_surfaces_as_unassigned` | pass |
| Constants match verified CAD measurements | `test_constants_match_the_verified_cad_measurements`, `test_cad_reference_pose_matches_the_pivot_height` | pass |
| Home pose never inferred | `test_home_pose_is_never_inferred` | pass |
| Link meshes reassemble the CAD pose / budget | `test_glb_total_stays_within_budget`, `test_mesh_node_names_match_cad_occurrences`, `test_tilt_glb_cartridge_lowest_vertex_is_the_reference_point` | pass |

### blade-tool-model

| Requirement / scenario | Verifying test | Result |
| :--- | :--- | :--- |
| Tool frame matches CAD at theta=0, phi=0 | `test_frame_at_zero_is_the_cad_blade_orientation` | pass |
| Frame orthonormal/right-handed under tilt | `test_frame_is_right_handed_orthonormal_across_the_grid` | pass |
| Analytic heated-SDF probes | `test_analytic_probes_from_the_spec`, `test_inside_is_negative_and_outside_positive` | pass |
| Python and JS SDF agree | Node `Python and JS heated SDF agree on the seeded 1000 x 20 fixture` (max diff 4.26e-14 mm) | pass |
| Support placement tangent for arbitrary normals | `test_placement_is_tangent_for_arbitrary_normals` | pass |
| Flat-top contact offsets by kerf only | `test_flat_top_contact_offsets_by_the_kerf_only` | pass |
| Tangential normal is not a scalar radial offset | `test_tangential_normal_is_not_a_scalar_radial_offset` | pass |
| Shaft collision at 2 mm vs 3 mm | `test_shaft_wall_at_two_mm_penetrates_at_three_does_not` | pass |
| Head envelope comes from the geometry | `test_head_envelope_is_read_from_the_geometry` | pass |
| Broadside / slice / plunge classification | `test_radial_feed_is_broadside_and_tangential_is_slice`, `test_threshold_comes_from_config` | pass |
| Rapid clearance covers the unheated shaft | `test_radial_support_extent_covers_the_unheated_shaft` | pass |

### carver-kinematics

| Requirement / scenario | Verifying test | Result |
| :--- | :--- | :--- |
| FK algebraic and sign verification | `test_fk_phi_zero`, `test_fk_phi_ninety_degrees`, `test_fk_arbitrary_phi_vectors` | pass |
| CAD reference pose -> (0, 0, 91) | `test_cad_reference_pose_reproduces_the_cad_reference_point` | pass |
| Measured physical pose calibration fixture | `test_hardware_calibration_fixture_within_one_mm` | **skipped** (no hardware measurements recorded) |
| IK round-trip and phi-policy clamp | `test_ik_round_trip_with_phi_policy`, `test_phi_policy_clamped_is_informational` | pass |
| Out-of-bounds joint rejected with axis | `test_out_of_bounds_joint_is_rejected_with_axis`, `test_height_limit_is_enforced`, `test_known_cad_travel_rejects_an_out_of_range_target` | pass |
| Signed-r solution avoids a configured stop | `test_signed_r_solution_avoids_a_configured_orbit_stop` | pass |
| Unknown CAD travel requires explicit config | `test_unknown_cad_travel_limit_requires_an_explicit_fallback` | pass |
| Config narrows, never widens CAD travel | `test_configuration_may_narrow_but_never_widen_cad_travel` | pass |
| Relative tip speed (pure orbit and combined) | `test_pure_turntable_rotation_reports_relative_tip_speed`, `test_combined_motion_uses_full_relative_tip_speed` | pass |
| Singularity on both sides of the axis | `test_near_axis_fast_rotation_emits_singularity`, `test_axis_crossing_emits_singularity_on_both_sides` | pass |
| Full 360-degree azimuth coverage behind the orbit stops | `test_every_azimuth_bin_receives_cutting_frames` | pass |
| Branch switches stay above the stock | `test_no_cross_axis_move_below_the_stock_plane` | pass |
| Default v_max_theta <= 1.0 | `test_config_declares_datums_tool_and_limits` | pass |

### face-sculpt-sim

| Requirement / scenario | Verifying test | Result |
| :--- | :--- | :--- |
| Blade sampling bound | `test_heated_blade_resampling_bound` | pass |
| Unreachable undercut reported | `test_finishing_uses_phi_and_reports_unreachable_undercuts` | pass |
| Roughing slices >= 90 % and broadside reported | `test_roughing_passes_slice_and_broadside_is_reported` | pass |
| CL placement uses the support point | `test_cutter_location_is_the_support_function_placement` | pass |
| Finishing follows planar contours (exit criterion) | `test_finishing_follows_planar_contours` (no `expectedFailure`) | pass |
| Rapids clear by the tool's radial extent | `test_rapids_retract_outside_stock_and_tool_extent` | pass |
| API columnar contract + provenance | `test_sculpt_and_sim_columnar_contract`, `test_demo_response_carries_geometry_provenance` | pass |
| Legacy cone keys -> 422 naming the key | `test_removed_cone_key_returns_422_naming_it` | pass |
| `heated_length_mm` <= blade length | `test_heated_length_longer_than_the_blade_returns_422` | pass |
| No cone geometry left in `toolpath_sim.py` | `test_toolpath_module_has_no_cone_geometry` | pass |

### volumetric-wax-viewer

| Requirement / scenario | Verifying test | Result |
| :--- | :--- | :--- |
| Rig tip tracks backend frames | Node `rig tip tracks 20 committed demo frames within 0.1 mm` | pass |
| Imported CAD tilt link rotates with phi | Node `imported CAD tilt link rotates about the pivot with phi` | pass |
| Wax static while the orbit advances | Node `wax is static while the orbit link advances 90 degrees` | pass |
| No kinematic trig in JS | Node `CAD rig and app contain no kinematic trig` | pass |
| Undercut subtraction, dirty neighbors, overhang preserved | Node `undercut subtraction crosses chunk boundaries...` | pass |
| Direction-dependent blade kerf | Node `blade kerf is direction-dependent...` | pass |
| Snapshot scrub restore | Node `snapshot restore and replay match sequential subtraction exactly` | pass |
| Rapid through carved pocket vs uncarved | Node `rapid through a carved pocket succeeds while uncarved rapid raises RAPID_COLLISION` | pass |
| Per-body shank diagnostics with body name | Node `per-body shank diagnostics report shaft and head by name`, worker `shaft`/`head` tests | pass |
| GLB failure fallback | Node `GLB load failure falls back to a tool-plus-wax scene and emits an error` | pass |
| Machine-detail toggle (Tool only hides static/orbit/z) | Node `tool-only detail hides static/orbit/z but keeps radial and tilt` | pass |

## Resolved assumptions and empirical proof

| Assumption | Status | Evidence |
| :--- | :--- | :--- |
| Tool is the 1.2 x 6.0 x 14.0 mm blade | **Verified** | Owner: "the blade in the cad is the real thing"; section study + extraction |
| Pivot is the servo-horn axis, `p = 60` | **Verified by CAD; owner confirmation pending (7.2)** | `pivot_to_tip_mm = 60.0`, reference `(0, 0, 91)`; dowel alternative recorded at 14.03 mm |
| `r` travel `[-51, 135]` | **Verified** | stop faces minus carriage half-length |
| `h` travel `[71.009, 231.5]` | Computed from CAD (Z bearings vs stops) | `machine_geometry.json`, provenance recorded |
| `theta` travel | **Unverified** | `null` + reason; config supplies +/-170 deg labelled `verified: false` |
| Cylinder stock R/H | **Unverified (7.2)** | config `40 / 120` |
| Home pose | **Unverified** | `home_pose: null` |
| `Cold_Tool_6mm_Shank` | **Unverified** | `unassigned_parts` |
| Heated length = blade length | **Unverified (7.2)** | config `14.0`, capped at the blade length |

## Nomenclature and symbol audit

`grep -rn "tip_radius_mm\|cone_half_angle_deg\|engaged_length_mm\|tip_width_mm\|shank_radius_mm\|shank_length_mm\|PrimitiveCarverRig\|machine_rig"` over `*.py`, `*.js`, `*.mjs`, `*.json`:

- Matches only in `tests/test_carver_sim.py` (the assertions that the removed
  keys are absent and that the API returns 422 naming `cone_half_angle_deg`) and
  in `kinematics.REMOVED_TOOL_KEYS` (the rejection guard). These are the guard,
  not a remaining cone implementation.
- `toolpath_sim.py` contains none (enforced by
  `test_toolpath_module_has_no_cone_geometry`).
- `apex` appears nowhere in Python or static JS; the concept is
  `tip`/`tool reference point` (`grep -rn apex --include=*.py --include=*.js` is
  empty outside archived `openspec/changes/carver-sim-mvp/`).
- `static/machine_rig.js` is deleted; `PrimitiveCarverRig` is gone.

## Performance vs the 0.3 baseline

Baseline (`main` at `98ac91d`, cone finishing): `demo` 138,201 frames,
167,278 ms median (best 164,297 ms), sliders
`{nose:1.0, chin:0.6, brow:0.4, cheeks:0.4, jaw:0.3}`, roughing + finishing.

| Preset | Frames (CAD blade) | Wall time | Ratio to baseline |
| :--- | ---: | ---: | ---: |
| `demo` | 84,831 | 194.6 s | 1.16x (guard <= 1.5x) |
| `standard` | 182,626 | suite pass | under the 250k frame cap |

The guard (<= 1.5x baseline for equivalent stages/inputs) passes: 194.6 s vs 250.9 s allowed.
The extra time over the first implementation is the full 360-degree azimuth
coverage; `body_penetrates` culls samples outside the target mesh AABB to keep
the cost inside the guard.

## Committed artifact identity

| Artifact | Value |
| :--- | :--- |
| STEP SHA-256 | `00882f0ebeaeaae66b7b8eb28e4d2dc9bbf30d65c2d66705f86deec566fd7bd0` |
| `machine_geometry.json` SHA-256 | `d846d3e548464126300a7b524a3349b83bf040b7aca5c6f69a882f2da3bc455b` |
| OCP version | 8.0.1.1.0 |
| GLB total | 3.20 MiB (budget 8 MiB) |
| Leaf occurrences | 295 (`static` 100, `orbit` 113, `z` 54, `radial` 17, `tilt` 8, `unassigned` 2, `stock_placeholder` 1) |

## Verbatim execution logs

```
$ .venv/bin/python -m unittest discover -s tests -v
...
test_frame_is_right_handed_orthonormal_across_the_grid (test_tool_model.TestToolFrame...) ... ok
----------------------------------------------------------------------
Ran 101 tests in 1400.340s

OK (skipped=5)
```

```
$ .venv-cad/bin/python -m unittest tests.test_machine_cad_extract -v
test_committed_artifact_is_current ... ok
test_extraction_is_deterministic ... ok
test_glb_export_is_deterministic_within_the_budget ... ok
test_unmatched_part_surfaces_as_unassigned ... ok
----------------------------------------------------------------------
Ran 4 tests in 33.582s

OK
```

```
$ node --experimental-vm-modules --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs tests/test_cad_rig.mjs
# tests 22
# pass 21
# fail 0
# skipped 1
```

```
$ .venv/bin/python scripts/extract_machine.py
wrote machine_geometry.json: 7 links, 295 parts
GLB total: 3.13 MiB
unassigned: ['Cold_Tool_6mm_Shank:1', 'Dowel_3x37:1']
stock_placeholder: ['Wax_Block_Cast_120x100x56:1']
```

## Manual verification (maintainer)

Automated scene-graph tests cover tip tracking, static wax, toggle visibility and
the GLB fallback, but WebGL rendering could not be exercised here: Chromium
fails to launch in this sandbox (`No usable sandbox`). The following remain for
a maintainer/owner with a display:

- Load the studio and confirm the machine at `cad_reference_pose` matches the
  Fusion assembly (T12 pointing down, no rectangular block, cylindrical stock on
  the seat plane, unassigned note listing `Cold_Tool_6mm_Shank` and
  `Dowel_3x37`).
- Play `demo` and scrub: the ring/column/arm orbit while the wax stays still;
  negative-r frames place the carriage across the orbit axis; the blade tip
  stays on the carving front.
- Confirm the roughing groove reads about 2 mm wide and any broadside segment
  shows the `BLADE_BROADSIDE_FEED` badge.
- Below 900 px: the toggle defaults to Tool only with a >= 44 px target.
- Owner sign-off on `cad_part_roles.json` + `joint-sweep.json`, and answers to
  `owner-questions.md`.

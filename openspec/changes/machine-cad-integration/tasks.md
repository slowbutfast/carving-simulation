## 0. Preconditions (gate, no code)

- [x] 0.1 `carver-sim-mvp` merged to `main` on 2026-11-19 as squash commit `98ac91d` (PR #1). It merged **with** cone-based undercut finishing (`build_finishing` composed from PATCH-10c helpers 1–5), not descoped, and `test_finishing_follows_planar_contours` is marked `@unittest.expectedFailure` (PATCH-10f: corner-normal standoff collapse). This change **replaces** that cone geometry in `build_finishing` and its helpers (`finishing_phi`, `cutter_location`, `tool_body_penetrates`, `entry_moves`/`exit_moves`) with `tool_model.py`. Exit criterion: that `expectedFailure` is removed and the test passes, or the test is rewritten against `place_on_contact` with the change recorded in `patch.md`. Branch `feat/machine-cad-integration` from `main` at or after `98ac91d`.
- [x] 0.2 Commit `assets/Wax+Face+Carver+v2.stp`. Add `assets/*.stl` to `.gitignore` with a comment ("derived, nameless; use the STEP").
- [x] 0.3 On `main` at `98ac91d`, record the MVP `demo` toolpath-generation wall-time baseline in `research.md` → Verified facts, including revision, enabled stages, slider values, frame count, and environment. Compare only the same enabled stages in the performance guard. Recorded: 138,201 frames; median 167,278 ms over three runs (best 164,297 ms).

## 1. Test Scaffolding (TDD)

- [x] 1.1 Write failing `tests/test_machine_cad.py` for "Deterministic STEP extraction into derived machine artifacts" (units/frame/orbit axis, provenance/staleness, runtime import guard).
- [x] 1.2 Write failing `tests/test_machine_cad.py` cases for "Explicit CAD part-to-link role mapping with unassigned reporting" (295 coverage, unassigned/placeholder lists).
- [x] 1.3 Write failing `tests/test_machine_cad.py` cases for "CAD-derived kinematic constants and travel evidence with provenance" and "Link meshes in the machine frame within a size budget".
- [x] 1.4 Write `tests/test_machine_cad_extract.py` (OCP-gated `skipUnless`): determinism, committed-artifact-current, unmatched-part surfacing.
- [x] 1.5 Write failing `tests/test_tool_model.py` for all five blade-tool-model requirements (frame, heated SDF probes, support placement, body collision, feed class).
- [x] 1.6 Migrate `tests/test_carver_sim.py` kinematics tests to the new datums (signed r, orbit θ, CAD reference pose, synthetic θ-stop signed-r IK, |r_s| singularity, v_max θ default, and rejection of a null CAD limit without an explicit fallback). List every migrated assertion and its reason in `patch.md`.
- [x] 1.7 Add failing `tests/test_carver_sim.py` cases for the modified face-sculpt-sim requirements (roughing slice fraction, `place_on_contact` CL, collision-search reachability, blade sampling bound, rapid tool-extent clearance, API 422 on cone keys, provenance in response, performance guard).
- [x] 1.8 Add failing `tests/test_wax_sdf.mjs` cases (parity fixture, direction-dependent kerf, per-body `SHANK_COLLISION`, zero-trig guard on `cad_rig.js`). Add failing `tests/test_cad_rig.mjs` (tip tracking, static wax, GLB-failure fallback).
- [x] 1.9 Run the suites and record the expected-red list in `patch.md`. No implementation edits in this group.

## 2. CAD Extraction Pipeline (offline)

- [x] 2.1 Add `requirements-cad.txt` (`cadquery-ocp==8.0.1.1.0`, `trimesh`, `numpy`) and a README note: `python -m venv .venv-cad && .venv-cad/bin/pip install -r requirements-cad.txt`.
- [x] 2.2 Write `cad_part_roles.json` from the architecture draft table (ordered prefix rules, plus `FST_*` handling, plus `unassigned` default).
- [x] 2.3 Implement `scripts/extract_machine.py`:
  - XCAF walk (`TDF_ChildIterator`, `IsComponent_s` / `IsFree_s`, `CornerMin/CornerMax`, `TopoDS.Face`)
  - mm units and recording of `source_length_unit`
  - CAD → machine transform with `seat_y_cad`
  - role assignment
  - `unassigned` / `stock_placeholder` lists
  - SHA-256 and OCP version
  - sorted, rounded JSON output
- [x] 2.4 Compute the constants:
  - Pivot from the servo horn axis. Also record the `Dowel_3x37` axis as `pivot_candidates`.
  - Tool reference point from the cartridge's lowest face centre.
  - `pivot_to_tip_mm`, `pivot_radial_offset_mm`, `tangential_tool_offset_mm`.
  - `r_travel_mm` from the radial stop faces and carriage half-length.
  - `h_travel_mm` from the Z stops and the carriage-to-pivot offset.
  - `theta_travel_deg` from the stop block vs the arm's swept envelope. Use `null` plus `reason` if this can't be computed.
  - `cad_reference_pose`, and `home_pose: null`.
- [x] 2.5 Compute the tool block: blade dims from cartridge sections, shaft/body radii and spans, `head_clearance_mm`, and an explicit head envelope hull (box or capsule) with dimensions and pose relative to the tool reference point, for the tilt link minus the cartridge.
- [x] 2.6 Export per-link GLBs (node names = occurrence names, per-link linear deflection, cartridge ≤ 0.02 mm) within the 8 MiB budget. Commit `machine_geometry.json` and `static/models/*.glb`.
- [x] 2.7 Get 1.1–1.4 green.

## 3. Kinematics and Config

- [x] 3.1 Add a config loader that merges `machine_geometry.json` under `machine_config.json`. Config may narrow CAD travel limits but never widen them; a null CAD limit requires an explicit conservative, provenance-labeled config fallback. Blade dims are not overridable.
- [x] 3.2 Update `machine_config.json`:
  - remove the cone keys
  - add `heated_length_mm`, `broadside_threshold_deg` and `finish_phi_search_step_deg`
  - set `v_max.theta_rad_s` ≤ 1.0
  - stock R/H stay configurable and are marked unverified
- [x] 3.3 Update `kinematics.py`:
  - orbit-θ datum docs
  - signed r
  - h to the pivot (h2 = 0)
  - |r_s| singularity check
  - signed-r IK branch selection with θ-limit feasibility and minimum |Δθ|
  - φ policy projected into the chosen solution's frame
- [x] 3.4 Get the 1.6 kinematics tests green.

## 4. Tool Model

- [x] 4.1 Implement `tool_model.py`: frame, `heated_sdf`, `place_on_contact` (support function with centroid tie-break), `body_penetrates` (shaft/body/head ring sampling, explicit sign handling), and `feed_class`.
- [x] 4.2 Generate `tests/fixtures/heated_sdf_parity.json` from `tool_model.py` (seeded).
- [x] 4.3 Get 1.5 green.

## 5. Toolpath and API

- [x] 5.1 Update `toolpath_sim.py` roughing:
  - CL placement against the shadow via `place_on_contact`
  - θ-direction ring passes with radial stepovers only
  - classify segments with `feed_class` and emit `BLADE_BROADSIDE_FEED`
- [x] 5.2 Update finishing:
  - φ_ideal from the IK policy
  - `place_on_contact`
  - `body_penetrates` search over φ candidates ordered by distance from φ_ideal, with early exit
  - `UNREACHABLE_UNDERCUT_AREA` / `GOUGE`
  - remove the closed-form cone bound and all cone-key reads
  - replace the MVP cone helpers (`finishing_phi`'s α term, `cutter_location`'s `ρ + kerf` offset, `tool_body_penetrates`'s cone stations, `entry_moves`/`exit_moves` clearance) with `tool_model` calls. Migrate `TestFinishingHelpers` fixtures that encode the cone or `p = 30` (each listed in `patch.md`)
  - remove `@unittest.expectedFailure` from `test_finishing_follows_planar_contours` and get it passing (the 0.1 exit criterion)
- [x] 5.3 Update the sampling bound to 0.5·(blade_thickness + 2·kerf) over heated-region corner points, and make rapid retract clearance include the tool's radial support extent.
- [x] 5.4 Update `server.py`:
  - `tool_cfg` whitelist (`melt_kerf_mm`, `heated_length_mm` ≤ blade length)
  - 422 naming removed cone keys
  - `config.geometry_provenance` in the response
- [x] 5.5 Get 1.7 green, including the performance guard.

## 6. Viewer

- [x] 6.1 Update `static/wax_sdf_core.js` and `wax_worker.js`:
  - blade inflated-box SDF stamp, with the tool frame from `theta_s` + `tool_axis_wax`
  - constants from the config payload
  - per-body shank checks (shaft, body, head) reporting the body name
- [x] 6.2 Implement `static/cad_rig.js` `CadCarverRig`:
  - GLTFLoader at the app's pinned Three version
  - `static ⊃ orbit ⊃ z ⊃ radial ⊃ tilt`
  - deltas from `cad_reference_pose`
  - pre-baked tilt pivot
  - ghosted `unassigned`, hidden `stock_placeholder`
  - tip marker
  - load-failure fallback
- [x] 6.3 Wire `static/app.js`:
  - replace `PrimitiveCarverRig` and delete `static/machine_rig.js`
  - wax parented to `static`
  - machine-detail toggle (Tool-only default under 900px)
  - unassigned-parts note
  - provenance readout
  - `BLADE_BROADSIDE_FEED` warning badge

  Use the `scene.*` tokens from `design.md`.
- [x] 6.4 Get 1.8 green.

## 7. Owner Review Gates

- [ ] 7.1 Present `cad_part_roles.json` plus a joint-sweep recording for owner sign-off. Apply corrections by regenerating artifacts, not by hand-editing the JSON.
- [ ] 7.2 Ask the owner about the pivot axis (servo horn vs `Dowel_3x37`) and the cylinder stock R/H. Record the answers in research.md (move from Unverified to Verified facts), and regenerate or retune if needed.
- [x] 7.3 Leave `home_pose`, `Cold_Tool_6mm_Shank` and `heated_length_mm` as recorded open items unless the owner supplies them.

## 8. Verification & Empirical Audit

- [x] 8.1 Run the full regression suite: `.venv/bin/python -m unittest discover -s tests`, `node --test tests/`, and `.venv-cad/bin/python -m unittest tests.test_machine_cad_extract`. Verify clean passes and record pass/skip counts. Check `demo`/`standard` frame counts and toolpath-generation wall time against the 0.3 baseline (`98ac91d`) using equivalent enabled stages and inputs.
- [x] 8.2 Populate `verification.md`:
  - Requirement Adherence Matrix (every requirement and scenario in all five spec files → test name → result)
  - resolved and remaining assumptions (pivot, heated length, stock, home pose, cold tool)
  - `machine_geometry.json` SHA and `step_sha256`
  - verbatim execution logs

## Patch 01: PR #2 Review Fixes (CAD Tilt Parenting, Back-Side Signed-r Coverage, Node Test Flags & Extent)

- [x] P01.1 Scaffold failing tests: `T12_K_Cartridge` world rotation at `phi != 0` in `tests/test_cad_rig.mjs` (plus `-60°`/`+75°` frames in `tests/fixtures/cad_rig_frames.json`), and 10°-azimuth-bin coverage on `demo` in `tests/test_carver_sim.py`
- [x] P01.2 Fix `static/cad_rig.js` (`modelGroups.tilt` parented under `this.tiltOffset` so imported CAD tilt geometry rotates with `phi`)
- [x] P01.3 Fix `toolpath_sim.py` (`_theta_grid` endpoint inclusion + negative-`r_s` sweep for `(theta_hi, theta_lo + 360°)` in roughing/finishing) and `tool_model.py` (`+ kerf` in `radial_support_extent`)
- [x] P01.4 Update `package.json` (`test:node` with `--experimental-vm-modules` and all 3 `.mjs` suites) and `tests.md`
- [x] P01.5 Run full Python + Node suites and `openspec validate machine-cad-integration --strict --json`, update `verification.md`, and mark `PATCH-01` `VERIFIED` in `patch.md` (keeping owner gates 7.1 and 7.2 open)

## Patch 02: Sign-Aware Roughing Links, Shaft Rapid Extent, Gouge Depth & Over-Stock Rapids

- [x] P02.1 Scaffold failing tests in `tests/test_carver_sim.py` and `tests/test_tool_model.py`: (a) zero non-rapid `roughing`/`finishing`/`*_link` segments cross `r_s = 0` below `H_stock`, (b) `detect_gouges` reported depth `>=` test-measured depth and checks `roughing_link`/`finishing_link`, (c) `radial_support_extent(0)` `>=` shaft radius (`2.5 mm`), and (d) `test_rapids_retract_outside_stock_and_tool_extent` accepts `z_s >= H_stock + retract_clearance_mm`
- [x] P02.2 Fix `toolpath_sim.py`: sign-aware `last_sign * clearance_radius` link-out/in + over-stock (`H_stock + clearance`) branch switch in `build_roughing`; expand `detect_gouges` sampling (corners + face centers) and run across `finishing`, `roughing_link`, and `finishing_link`; keep `safe_zs` cross-axis finishing repositions `rapid=True`
- [x] P02.3 Fix `tool_model.py`: include unheated shaft radius in `radial_support_extent`
- [x] P02.4 Run full Python + Node suites + `openspec validate machine-cad-integration --strict --json`, update `verification.md`, and mark `PATCH-02` `VERIFIED` in `patch.md` (keeping owner gates 7.1 and 7.2 open)

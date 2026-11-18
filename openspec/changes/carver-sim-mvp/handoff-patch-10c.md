# Surgical Patch Handoff: OpenSpec Change 'carver-sim-mvp' [PATCH-10c]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `carver-sim-mvp`
- **Patch ID**: `PATCH-10c` (supersedes PATCH-10b; completes PATCH-10 on PR #1, branch `feat/carver-sim-mvp`, head `d268090` + uncommitted working tree)
- **Objective**: Get wrist-pitched undercut finishing working by splitting `build_finishing` into small unit-tested geometry helpers. Fix the four interacting defects (contour ordering, `finishing_phi` branch, snapped CL offset, inverted `_flank_clearance`), then close the API/config/worker items so the Python and Node suites both pass.
- **Start from the CURRENT working tree.** Do NOT `git checkout -- toolpath_sim.py` back to `d268090`: its phi = 0 path and axis-only gouge probes are worse. Keep what is correct in the tree: the step-zero sign test, `radius >= 0` filtering, face normals from `mesh_plane`, `tip_r + kerf` offset, `detect_gouges` sign, `multiple_hits=True`, `FrameCapExceededError`, `_joint` limit validation.
- **Feedback & Diagnostic Trace**:
  ```
  .venv/bin/python -m unittest discover -s tests   (41 run, 6 failures, 2 errors, 1 skipped, 171 s)
  ERROR test_max_frames_exceedance_maps_to_422      FrameCapExceededError: 448079 > 400000 (no 422 mapping)
  ERROR test_out_of_bounds_stock_emits_soft_limit_exceeded  FrameCapExceededError: 470955 > 400000
  FAIL  test_zero_tool_radius_returns_422           200 != 422
  FAIL  test_approach_and_retract_never_drop_below_cut_height  120.109375 not <= 120.000001
  FAIL  test_finishing_follows_planar_contours      77.33 not < 24.0
  FAIL  test_finishing_phi_reachability_allows_surface_close_to_phi  True is not false
  FAIL  test_shadow_profile_uses_multiple_hits      15.0 not > 19.0
  FAIL  test_finishing_uses_phi_and_reports_unreachable_undercuts  0 not > 20
  ```
- **Root Cause Analysis**: `build_finishing` (L759-900) is one loop with no testable seams, and four separate defects interact inside it:
  1. **Ordering.** `section_contour` sorts points by `(z, radius)` and `build_finishing` joins every accepted point with a straight cut. On the needle fixture the tool alternates body wall r=15 / needle inner r=19.2 / needle outer r=20.8 at each z and cuts through the needle. Rejected points also get bridged by straight cuts through material.
  2. **`finishing_phi` (L395-423).** The `n_z <= 0.2` branch clips `n_z` to 0, so downward faces look like vertical walls and are reported reachable. The `max(0, beta - alpha)` floor is gone, so flat tops get phi = -30 deg.
  3. **CL offset (L822-846).** The normal is snapped to pure radial or pure vertical before offsetting. The blanket `n_z < -0.2 -> unreachable` rule discards reachable undercuts.
  4. **`_flank_clearance` (L721-757).** It walks `-normal` instead of the FK tool axis, and returns `flank + signed_distance`, which is NEGATIVE when clear. Callers reject `<= 0`, so every clear pose is rejected (99-100 % unreachable). This is the same sign misreading as PATCH-10b. **trimesh `signed_distance` is POSITIVE INSIDE, and `contains` agrees with it.**

  Secondary: the approach slide is horizontal rather than along -u (L690-719); `sample_step_mm` is ignored (frame blow-up); the roughing stepdown of 6 mm exceeds the shank-safe bound of 4.36 mm (L500), which explains the PATCH-07 shank hits and the worker `tilted` gate.

## 2. Strict Target Context Map
| File Path | Target Lines | Modification Summary |
|---|---|---|
| `toolpath_sim.py` | L306-393 `section_contour` | Becomes `section_polylines(mesh, theta, z_min, z_max, step)`. Chain `mesh_plane` segments by shared endpoints (`_vkey` exists and is unused; plain dict adjacency, NO networkx) into ordered polylines. Clip each to `radius >= 0` and `z in [z_min + 1.5, z_max]`, splitting at the clip boundaries. Resample each polyline at arc-length `step` (honour `sample_step_mm`; caller passes `finish_z_step_mm`). Each point carries `(radius, z, point_xyz, n_r, n_z)`, with the normal = intersected face normal projected to `(e_r, e_z)` and re-normalised (existing tangential fallback kept). Orient polylines bottom-to-top. Keep a thin `section_contour` wrapper that flattens the polylines if other tests import it. |
| `toolpath_sim.py` | L395-423 `finishing_phi` | Delete the `n_z <= 0.2` branch. `beta = atan2(n_r, n_z)`; `phi_pref = max(0, beta - alpha)` if `beta >= 0` else `min(0, beta + alpha)`; `phi = clamp(phi_pref, phi_lo, phi_hi)`; `reachable = abs(beta - phi) <= pi/2 - alpha + EPS`. |
| `toolpath_sim.py` | new, near L425 | `cutter_location(point_xyz, n_r, n_z, theta, config) -> apex_xyz = point + (n_r*e_r + n_z*e_z) * (tip_radius_mm + melt_kerf_mm)`, using the TRUE normal (no snapping). |
| `toolpath_sim.py` | L432-479 `detect_gouges`, L721-757 `_flank_clearance` | Replace both with one vectorised `tool_body_penetrates(mesh, apexes (N,3), axes (N,3), config) -> bool (N,)`. Stations `t in {0.25, 0.5, 0.75, 1.0} * engaged`. At each station, take the axis point `apex - axis*t` plus 8 ring points at radius `tip_radius_mm + t*tan(alpha)` (melt kerf deliberately omitted as tolerance) in the plane perpendicular to `axis`. A pose penetrates if `mesh.contains` is True for any of them. One `contains` call per batch. `detect_gouges` keeps its signature and diagnostic text and calls this. Delete `_flank_clearance`. |
| `toolpath_sim.py` | L636-719 `safe_retract_moves` / `safe_approach_moves` | Replace with `exit_moves(apex, phi, theta, mesh, config, clearance_target, collector)`. Candidate A: pull along -u (`apex - u*s`) with `s` solved so that radius >= clearance_target, i.e. `s = (clear - r_apex)/sin(phi)` when `sin(phi) > 0.05`; otherwise lift to `H_stock + retract_clearance`. Candidate B: radial pull at constant z and phi to `clearance_target`. Sample each candidate every 1 mm and take the first whose samples are all clear under `tool_body_penetrates`. If neither is clear, add an `UNREACHABLE_UNDERCUT_AREA`-counted rejection for that run's end point (drop the point and retry with the previous one). Then reorient phi -> 0 at the clear point, then rise to `safe_zs`. `entry_moves` = the reverse of `exit_moves` for the run's first point: descend phi=0 at `clearance_target` -> pitch -> plunge along the chosen candidate. All of these are non-rapid and tagged stage `"finishing_link"`. |
| `toolpath_sim.py` | L759-900 `build_finishing` | Compose: for each slice -> `section_polylines` -> batch-evaluate `finishing_phi` + `cutter_location` + FK axis (`u = -sin(phi) e_r - cos(phi) e_z`) -> one `tool_body_penetrates` pre-filter -> split each polyline into **runs of consecutive accepted points** (a rejected point ends a run; never bridge runs with a cut) -> per run: `entry_moves`, cut moves (stage `"finishing"`), `exit_moves`, rapid at `safe_zs`. Remove the `n_z < -0.2` rule, the normal snapping and `_melt_kerf_offset` usage beyond `cutter_location`. Count rejected points into `unreachable_points`. |
| `toolpath_sim.py` | L500 roughing stepdown | `stepdown = min(rough_stepdown_mm, engaged - (shank_radius_mm - tip_radius_mm - melt_kerf_mm)/tan(alpha))`, floor 1.0 mm (= 4.36 mm with defaults). Comment the derivation. |
| `toolpath_sim.py` | L903-984 `generate_synthetic_carve_path` | After building raw joints and BEFORE `resample_path`: if `collector.has_error()` (SOFT_LIMIT_EXCEEDED), return `ToolpathResult(frames=[], diagnostics=...)` immediately. Run `detect_gouges` over frames with stage `"finishing"` only (link moves are covered by `exit_moves` sampling). |
| `server.py` | L43-47, L125-169 | Typed Pydantic `StockCfg` / `ToolCfg` models, all fields optional, with `gt=0` (`ge=0` for `melt_kerf_mm`), `extra="forbid"`. Return 422 with `{"status":"error","diagnostics":[...]}` when the toolpath result has any error-severity diagnostic. Catch `FrameCapExceededError` -> 422 with a `FRAME_CAP_EXCEEDED` error diagnostic. |
| `machine_config.json` | presets / api / toolpath | `demo.theta_step_deg 7.5`, `standard.theta_step_deg 5.0`, `api.max_frames 250000`; remove the now-unused `finish_standoff_mm` keys. If demo still exceeds 250k, coarsen `finish_z_step_mm` (the polyline step), never `theta_step_deg`, and record the frame count in verification.md. |
| `static/wax_worker.js` | L117-121 | Remove the `tilted` gate: `checkShank` on every cutting frame. Fix the comment. |
| `tests/test_wax_worker.mjs` | append | A vertical cutting pose whose shank is buried in uncarved stock posts `SHANK_COLLISION`. |
| `tests/test_carver_sim.py` | see §3 | New helper unit tests + four assertion corrections. |

## 3. Blast Radius & Invariant Guardrails
- **STRICT BLAST RADIUS**: Only the files and regions above. Roughing logic apart from the stepdown clamp, kinematics.py, face_sculpt.py, wax_sdf_core.js and the UI are out of scope.
- **FORBIDDEN**:
  - Do NOT revert `toolpath_sim.py` to `d268090`.
  - Do NOT add dependencies (no networkx, no fast_simplification).
  - Do NOT edit `test_finishing_uses_phi_and_reports_unreachable_undercuts` or any other `TestSyntheticToolpaths` / kinematics / spec-scenario test.
  - Do NOT use `signed_distance` for inside/outside in new code; use `mesh.contains`. If you must use it: **> 0 is INSIDE**.
  - Do NOT tune end-to-end counts to make the tests pass. If an end-to-end test fails, find which helper unit test is missing.
  - Do NOT modify `.env` or credential files.
- **Assertion corrections that ARE permitted** (each one is demonstrably wrong; cite the reason in the commit message):
  1. `test_finishing_phi_reachability_allows_surface_close_to_phi`: beta = 89.9 deg is a *vertical wall* (horizontal normal) and is reachable (`|89.9 - 59.9| = 30 <= 60`). Replace with beta = 179 deg (face pointing almost straight down) -> `phi = 75`, `|104| > 60` -> unreachable.
  2. `test_shadow_profile_uses_multiple_hits`: the comment's "r ~= 21.2 at z=20" is the box *corner diagonal* (15 x sqrt 2); along theta = 0 the wall is at r = 15, and the needle spans z 40-56, so z = 56 grazes its top face. Probe `z = [20, 45]`; assert `profile[0,0] ~= 15 (+-0.5)` and `profile[0,1] >= 20.5` (needle outer face at 20.8; a single hit would stop at 15).
  3. `test_finishing_follows_planar_contours`: the body spans z 10-50, so `|z - 48| < 24` is wrong, and the old filter included link moves. Filter `stage == "finishing"`, and assert every sampled tip's unsigned distance to the mesh (`abs(mesh.nearest.signed_distance)`) is within `tip_radius_mm + melt_kerf_mm +- 0.6` mm.
  4. `test_approach_and_retract_never_drop_below_cut_height`: the upper bound `H_stock` contradicts the generator's own safe plane `H_stock + retract_clearance`. Use `H_stock + retract_clearance_mm + pivot_to_tip_mm`. Treat `"finishing_link"` frames the same way the test currently treats transitions.
- **INVARIANTS TO PRESERVE**: every currently passing Python and Node test (33 Python + 9 core + 2 worker); `engaged_length` resampling bound; unwrapped-theta continuity; zero-trig JS lint; step-zero sign test.

## 4. Visual & UI Impact
- Status: Non-visual patch. The new `"finishing_link"` stage tag is backend-only (`app.js` derives its own telemetry label from `is_rapid`). No styling or layout changes.

## 5. Reproduction & Verification Protocol
Work in this order. Each step must be green before starting the next. **Stop and report** if a helper unit test cannot be made green within two attempts, rather than adding heuristics.
1. **Reproduce**: `.venv/bin/python -m unittest discover -s tests -k Patch10 -k test_finishing_uses_phi_and_reports_unreachable_undercuts` -> the 8 failures above.
2. **Helper unit tests first (new, in `tests/test_carver_sim.py`, class `TestFinishingHelpers`)**, using analytic fixtures (`trimesh.creation.box`, `icosphere`), not the head:
   - `section_polylines` on a box at theta = 0: every polyline is continuous (consecutive points <= 1.5 x step apart), radius >= 0, ordered bottom-to-top; the needle fixture gives 2 polylines (body, needle).
   - `finishing_phi` table: beta 0 -> (0, True); 40 -> (10, True); 90 -> (60, True); 120 -> (75, True, |45| <= 60); 179 -> (75, False); -40 -> (-10, True).
   - `cutter_location`: distance from apex to the face = `tip_r + kerf` within 1e-6 on a 45 deg plane (no snapping).
   - `tool_body_penetrates`: a box top face with the apex at the CL and phi from `finishing_phi` -> False; the same pose pushed 1 mm along -n -> True; apex clear but body tilted into a wall -> True.
   - `exit_moves`: from a pitched pose under a box overhang, every sampled exit pose is clear and ends with radius >= clearance_target.
3. **Compose** `build_finishing`, then make the 4 corrected assertions and the unedited spec test green.
4. **API/config/worker**: the 422 tests, config revert, worker gate and the new worker test.
5. **Full regression**: `.venv/bin/python -m unittest discover -s tests -v` and `node --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs`.
6. **Integrated sweep** (same harness as `verification.md`, at 128^3 this time, not 64): demo trajectory through `WaxSDFCore` with rapid + shank checks on EVERY cutting frame -> expect 0 RAPID_COLLISION / 0 SHANK_COLLISION. Record frame counts per preset (must be <= 250000).
7. `openspec validate carver-sim-mvp --strict`.

## 6. Surgical Patch Checklist
- [ ] P10c.1 Run the reproduction command; confirm the 8 failures; add `TestFinishingHelpers` (red) and the four assertion corrections.
- [ ] P10c.2 Implement the helpers + `build_finishing` composition, `finishing_phi` fix, stepdown clamp and SOFT_LIMIT short-circuit in `toolpath_sim.py`; helper tests green, then the corrected and spec tests green.
- [ ] P10c.3 `server.py` 422s, `machine_config.json` revert, `wax_worker.js` gate removal + worker test.
- [ ] P10c.4 Full Python + Node suites, 128^3 integrated sweep, `openspec validate --strict`, all clean.
- [ ] P10c.5 Update `verification.md`, tick P10.*/P10b.*/P10c.* in `tasks.md`, set PATCH-10, PATCH-10b and PATCH-10c to `VERIFIED` in `patch.md`. Commit with message `fix(carver-sim): PATCH-10c structured undercut finishing` and correct the PATCH-10 shank-fix claim (the `wax_sdf_core.js` change in `d268090` was comment-only).

# Surgical Patch Handoff: OpenSpec Change 'carver-sim-mvp' [PATCH-10]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `carver-sim-mvp`
- **Patch ID**: `PATCH-10`
- **Objective**: Resolve all 3 Critical and 6 Important PR #1 review findings across `static/wax_worker.js`, `toolpath_sim.py`, and `server.py` (worker tool config propagation, planar `r–Z` section finishing + full FK gouge probing, 3-step constant-$\phi$ approach/retract transitions, reachability condition, shadow `multiple_hits`, joint limit validation, every-cut shank checking, even snapshot thinning, and 422 on `max_frames` exceedance).
- **Feedback & Diagnostic Trace**:
  ```
  PR #1 Verdict: REQUEST CHANGES
  Critical:
  1. static/wax_worker.js:79,93,101,134: worker ignores data.config.tool on init; passes hardcoded DEFAULT_TOOL to checkRapid, checkShank, subtractTool.
  2. toolpath_sim.py:531-541,571,584,674: wedge vertex binning pulls side-of-nose radii onto centerline; cl_poses uses vertex apex instead of FK of emitted joints; detect_gouges checks only ~60 poses and never probes the apex.
  3. toolpath_sim.py:549-568,591-602: approach/retract interpolates phi simultaneously with r and h, swinging tip below cut height into the upper lip/face without rapid/gouge coverage.

  Important:
  4. toolpath_sim.py:289-306: finishing_phi uses phi = beta - alpha <= phi_max (rejecting >15 deg below horizontal) instead of clamping phi and checking |beta - phi| <= 90 deg - alpha.
  5. toolpath_sim.py:66-77: _joint skips validate_joints, so out-of-bounds stock configs never emit SOFT_LIMIT_EXCEEDED.
  6. toolpath_sim.py:221-223: multiple_hits=False undercounts shadow on multi-layer geometry.
  7. toolpath_sim.py:241-286,576-587: wedge-binned finishing order depends on tessellation and zigzags across overhangs.
  8. toolpath_sim.py:645-655: hitting max_frames truncates mid-stock with only a warning instead of returning an error (422) or coarsening.
  9. static/wax_worker.js:52-57,89-99: checkShank only runs every 4th tilted finishing frame; snapshot eviction splice(1, 1) clusters snapshots at the end.
  ```
- **Root Cause Analysis**:
  - `wax_worker.js` never mapped `data.config.tool` into a `WaxSDFCore` tool object on `init`, throttled `checkShank` to every 4th tilted frame, and evicted the oldest non-zero snapshot.
  - `toolpath_sim.py` approximated `r–Z` slices using azimuthal vertex wedges, coupled `phi` reorientation with radial/vertical travel, omitted `validate_joints` in generated frames, used `multiple_hits=False` for shadow rays, and truncated at `max_frames` without failing cleanly.

## 2. Strict Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `static/wax_worker.js` | `L12-L23, L52-L57, L72-L105, L131-L153` | Map `data.config.tool` (`tip_radius_mm`, `cone_half_angle_deg`, `engaged_length_mm`, `melt_kerf_mm`, `shank_radius_mm`, `shank_length_mm`) on `init` into `workerTool` (falling back to `DEFAULT_TOOL` per field) and pass `workerTool` to `checkRapid`, `checkShank`, and `subtractTool`. Run `checkShank` on **every** cutting frame (`!rapid[index]`) without the `>= 4` skip. Replace `snapshots.splice(1, 1)` with even thinning (drop every other interior snapshot) so scrub coverage spans the full timeline. |
| `toolpath_sim.py` | `L221-L227` | Set `multiple_hits=True` in `mesh.ray.intersects_location(...)` so outer features (ears, hair, uploads) are captured in the top-down shadow profile. |
| `toolpath_sim.py` | `L241-L286, L520-L545` | Replace wedge vertex binning with planar cross-section slicing via `mesh.section(plane_normal=e_theta, plane_origin=[0,0,0])` (ordered along the 2D `r–Z` contour) so radii and normals lie exactly on `theta_geom`. |
| `toolpath_sim.py` | `L289-L306` | Clamp `phi = clamp(beta - alpha, phi_lo, phi_hi)` (signed for inward/outward normals) and compute reachability via `abs(beta - phi) <= (math.pi / 2 - alpha) + EPS`. Align docstring to reflect apex contact + flank clearance. |
| `toolpath_sim.py` | `L309-L350, L547-L606, L674-L676` | Split each approach and retract into 3 safe moves: (retract) move along `-tool_axis` (`-u`) at constant `phi` until clear of `R_stock + clearance`, reorient `phi` to `0`, then `is_rapid` traverse; reverse for approach. Populate `cl_poses` from `kinematics.forward_kinematics` of the **actually emitted** finishing frames, and run `detect_gouges` (including probing the tip apex itself) across all finishing frames. |
| `toolpath_sim.py` | `L645-L662` | Raise a structured error (e.g. `FrameCapExceededError` mapped to HTTP 422 in `server.py`) when `len(joints) > max_frames` instead of truncating mid-stock; ensure `build_trajectory` validates soft limits on every frame and surfaces `SOFT_LIMIT_EXCEEDED`. |
| `server.py` | `L43-L48, L110-L165` | Add Pydantic field constraints (`gt=0`, etc.) on `stock_cfg` and `tool_cfg` so invalid inputs return HTTP 422, and map `FrameCapExceededError` to HTTP 422. |
| `tests/test_wax_sdf.mjs` | `[APPEND]` | Add tests proving: (1) a non-default `config.tool` (`tip_radius_mm`) changes carved SDF volume in `wax_worker.js` / `WaxSDFCore`, (2) `checkShank` catches a single-frame shank collision without skipping frames, and (3) snapshot thinning retains evenly spaced indices across the timeline. |
| `tests/test_carver_sim.py` | `[APPEND]` | Add tests proving: (1) planar `r–Z` section finishing lands FK tip within tolerance without centerline distortion, (2) 3-step constant-`phi` approach/retract avoids swinging below cut height, (3) `finishing_phi` accepts `beta <= phi_max - alpha` (`|beta - phi| <= 90° - alpha`), (4) `multiple_hits=True` captures outer shadow, (5) out-of-bounds `stock_cfg` emits `SOFT_LIMIT_EXCEEDED`, and (6) `max_frames` exceedance / negative `stock_cfg` returns HTTP 422. |

## 3. Blast Radius & Invariant Guardrails
- **STRICT BLAST RADIUS**: Modify ONLY the files and line ranges specified in the Target Context Map.
- **FORBIDDEN**:
  - Do NOT refactor `kinematics.py`, `face_sculpt.py`, `static/machine_rig.js`, `static/wax_sdf_core.js`, or `static/app.js` unless strictly required by a mapped signature.
  - Do NOT modify `.env` or credential files.
  - Do NOT modify existing passing test assertions unless demonstrably incorrect.
  - Do NOT implement `tool-model-upload` (that is a separate future OpenSpec change).
- **INVARIANTS TO PRESERVE**:
  - All existing passing tests in `tests/test_carver_sim.py` and `tests/test_wax_sdf.mjs` MUST continue to pass.
  - Zero kinematic trigonometry in JavaScript (`static/machine_rig.js`, `static/app.js`).

## 4. Visual & UI Impact
- Status: Non-visual patch. No styling, CSS, or HTML layout modifications permitted.

## 5. Reproduction & Verification Protocol
1. **Reproduce First**:
   - Add the failing test cases in `tests/test_wax_sdf.mjs` and `tests/test_carver_sim.py`.
   - Run `node --test tests/test_wax_sdf.mjs` and `.venv/bin/python -m unittest tests.test_carver_sim -v` and confirm the new tests fail.
2. **Apply Minimal Fix**: Make the targeted edits in `static/wax_worker.js`, `toolpath_sim.py`, and `server.py`.
3. **Verify Fix**: Re-run both test suites and confirm all new reproduction tests pass.
4. **Full Regression Suite**:
   - Run `.venv/bin/python -m unittest discover -s tests -v`
   - Run `node --test tests/test_wax_sdf.mjs`
   - Run `openspec validate carver-sim-mvp --strict --json`

## 6. Surgical Patch Checklist
- [ ] P10.1 Add failing reproduction tests in `tests/test_wax_sdf.mjs` and `tests/test_carver_sim.py` and confirm they fail.
- [ ] P10.2 Fix `static/wax_worker.js` (`init` tool config mapping, every-cut-frame `checkShank`, even snapshot thinning).
- [ ] P10.3 Fix `toolpath_sim.py` (`multiple_hits=True`, `mesh.section` planar `r–Z` contour slicing, 3-step constant-`phi` retract/approach, `|beta - phi| <= 90° - alpha` reachability, FK-derived `cl_poses` + full `detect_gouges`, joint limit validation, `max_frames` error) and `server.py` (422 validation).
- [ ] P10.4 Re-run full Python + Node suites and `openspec validate carver-sim-mvp --strict --json` and confirm 100% pass.
- [ ] P10.5 Update `openspec/changes/carver-sim-mvp/tasks.md` checkboxes to `- [x]`, update `verification.md`, and mark `PATCH-10` as `VERIFIED` in `patch.md`.

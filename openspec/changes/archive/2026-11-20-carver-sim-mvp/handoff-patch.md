# Surgical Patch Handoff: OpenSpec Change 'carver-sim-mvp' [PATCH-10e]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `carver-sim-mvp`
- **Patch ID**: `PATCH-10e` (resumes from `fb60eaf`, keeping frozen helpers 1–4)
- **Objective**: Apply the 3 test rulings on `TestFinishingHelpers`, fix helper 5 (`exit_moves` + `entry_moves`) with a horizontal `+e_r` pullout candidate, compose `build_finishing` from helpers 1–5 (eliminating the 8 `_flank_clearance` `NameError`s), finish the remaining PATCH-10c items (`server.py` 422s, `machine_config.json` revert, `wax_worker.js` `tilted` gate removal, roughing shank-safe stepdown), and update `verification.md`.
- **Feedback & Diagnostic Trace**:
  ```
  Head fb60eaf: 43 tests, 2 failures, 8 errors, 1 skipped
  - 8x NameError: name '_flank_clearance' is not defined at toolpath_sim.py:1214
  - FAIL test_tool_body_penetrates_when_tilted_into_wall (L952 checked x - r < 0.0 instead of x - r < 15.0)
  - FAIL test_exit_moves_are_clear_and_end_outboard: 0 not >= 2 : ['UNREACHABLE_UNDERCUT_AREA']
  ```
- **Root Cause Analysis**:
  - `test_tool_body_penetrates_when_tilted_into_wall` L952 checked `x - r < 0.0` instead of the wall face at `x = 15.0`.
  - `exit_moves` only tried `-u` (which rises into a horizontal overhang at `z = 90`) and vertical lift (which rises into the slab), missing a horizontal `+e_r` pullout candidate at constant `phi`.
  - `build_finishing` (`toolpath_sim.py:1191-1274`) still calls deleted `_flank_clearance`, `safe_approach_moves`, and `safe_retract_moves`.

## 2. Strict Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `tests/test_carver_sim.py` | `L906-L1000` | **Test Rulings**: Keep `test_cutter_location_offsets_along_true_normal` (accepted). Fix `test_tool_body_penetrates_when_tilted_into_wall` L952 (`< 15.0` instead of `< 0.0`). Revert `test_exit_moves_are_clear_and_end_outboard` fixture to `fb0c145` (`slab` `80×80×20` at `z=100`, `apex` at `z=82`, `phi=75°`, retaining `H_stock` check). |
| `toolpath_sim.py` | `L1017-L1140` | In `exit_moves`, add a horizontal `+e_r` radial pullout candidate at constant `phi` (to `clearance_target`, then re-pitch `phi -> 0`, then lift to `safe_z`) so wide overhangs (`z=90` above `z=82`) clear without hitting `-u` or vertical lift; mirror in `entry_moves`. |
| `toolpath_sim.py` | `L1185-L1275` | Compose `build_finishing` from frozen helpers 1–4 + helper 5 (`section_polylines`, `finishing_phi`, `cutter_location`, `tool_body_penetrates`, `entry_moves`, `exit_moves`), removing all calls to deleted `_flank_clearance`, `safe_approach_moves`, and `safe_retract_moves`. |
| `toolpath_sim.py` | `L531-L674, L907-L980` | Clamp roughing stepdown to the shank-safe bound (`<= engaged - (shank_r - tip_r - kerf) / tan(alpha)`), short-circuit on `SOFT_LIMIT_EXCEEDED` before resampling, and raise `FrameCapExceededError` when `len(joints) > max_frames`. |
| `server.py` | `L43-L48, L125-L155` | Add Pydantic constraints (`gt=0`, valid ranges) on `stock_cfg` / `tool_cfg` and map `FrameCapExceededError` / error-severity diagnostics to HTTP 422. |
| `machine_config.json` | `L65-L83` | Revert `presets.demo.theta_step_deg` to `7.5`, `presets.standard.theta_step_deg` to `5.0`, and `api.max_frames` to `250000`. |
| `static/wax_worker.js` & `tests/test_wax_worker.mjs` | `wax_worker.js:L118-L132` | Remove the `tilted` gate so `core.checkShank(pose, workerTool)` runs on every cutting frame, and add a vertical (`phi=0`) shank-collision worker test. |
| `openspec/changes/carver-sim-mvp/verification.md`, `patch.md`, `tasks.md` | `[UPDATE]` | Update `verification.md` with fresh passing logs + `128³` sweep results, tick `P10.*`–`P10e.*` in `tasks.md`, and mark `PATCH-10`..`PATCH-10e` `VERIFIED` in `patch.md`. |

## 3. Blast Radius & Invariant Guardrails
- **FROZEN**: Do **NOT** modify helpers 1–4 (`section_polylines`, `finishing_phi`, `cutter_location`, `tool_body_penetrates`) or their unit tests (except L952 `< 15.0` wall-face fix).
- **STRICT BLAST RADIUS**: Modify ONLY the files and line ranges in the Target Context Map.
- **FORBIDDEN**: Do NOT modify `.env`, credential files, `kinematics.py`, `face_sculpt.py`, `static/machine_rig.js`, `static/wax_sdf_core.js`, or `static/app.js`.

## 4. Visual & UI Impact
- Status: Non-visual patch. No styling, CSS, or HTML layout modifications permitted.

## 5. Reproduction & Verification Protocol
1. **Reproduce First**: Run `.venv/bin/python -m unittest tests.test_carver_sim.TestFinishingHelpers -v` after applying the test rulings; confirm `test_tool_body_penetrates_when_tilted_into_wall` passes and `test_exit_moves_are_clear_and_end_outboard` fails.
2. **Apply Fixes**: Update `exit_moves`/`entry_moves`, compose `build_finishing`, and complete `server.py` / `machine_config.json` / `static/wax_worker.js`.
3. **Full Regression Suite**:
   - `.venv/bin/python -m unittest discover -s tests -v` (0 failures, 0 errors, 1 expected hardware skip)
   - `node --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs` (100% pass)
   - `openspec validate carver-sim-mvp --strict --json` (`valid: true`)

## 6. Surgical Patch Checklist
- [ ] P10e.1 Apply test rulings in `tests/test_carver_sim.py` (`test_exit_moves` reverted to `fb0c145`, L952 `< 15.0` fixed).
- [ ] P10e.2 Fix `exit_moves` (`+e_r` horizontal pullout candidate) & `entry_moves`; compose `build_finishing` from frozen helpers 1–4 + helper 5.
- [ ] P10e.3 Complete `toolpath_sim.py` (shank-safe roughing stepdown, `SOFT_LIMIT` short-circuit), `server.py` 422s, `machine_config.json` revert, and `static/wax_worker.js` `tilted` gate removal + test.
- [ ] P10e.4 Run full Python + Node suites, `128³` sweep, and `openspec validate carver-sim-mvp --strict --json`.
- [ ] P10e.5 Update `verification.md`, tick `P10.*`–`P10e.*` in `tasks.md`, and mark `PATCH-10`..`PATCH-10e` `VERIFIED` in `patch.md`.

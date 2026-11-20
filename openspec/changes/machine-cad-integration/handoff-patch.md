# Surgical Patch Handoff: OpenSpec Change 'machine-cad-integration' [PATCH-02]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `machine-cad-integration`
- **Patch ID**: `PATCH-02`
- **Objective**: Fix sign-aware roughing branch switching (`build_roughing`), include unheated shaft radius in `tool_model.radial_support_extent`, align `detect_gouges` sampling/stages (`finishing`, `roughing_link`, `finishing_link`) so reported depth `>=` measured depth, and restore `rapid=True` for over-stock (`z_s >= H_stock + clearance`) finishing repositions.
- **Feedback & Diagnostic Trace**:
  ```
  PR #2 Verdict: REQUEST CHANGES (ec9a521)
  Critical:
  1. toolpath_sim.py:992-1042 (build_roughing): `for run in runs:` always links out/in with
     +clearance_radius. Switching between r_s > 0 and r_s < 0 creates 94 non-rapid moves
     crossing r_s = 0 below H_stock on demo (36 straight through the target head mesh).
  Important:
  2. tool_model.py:321-334 (radial_support_extent): only checks heated blade (~1.0 mm at phi=0),
     omitting the 2.5 mm unheated shaft radius required by rapid-clearance spec.
  3. toolpath_sim.py:822-862 (detect_gouges): reports 1.558 mm vs 3.9 mm actual burial on
     needle fixture, and skips roughing_link / finishing_link stages.
  4. toolpath_sim.py:1376-1380,1523-1570 (build_finishing): safe_zs = H + clearance cross-axis
     move was relabelled non-rapid finishing_link, inflating demo from ~64k to ~98k frames.
  Owner Gates (remain open for owner sign-off):
  - tasks.md:114-115 (7.1 roles + joint sweep, 7.2 pivot axis + cylinder stock R/H).
  ```
- **Root Cause Analysis**:
  - `build_roughing` did not track `last_sign` or lift above `H_stock + clearance` when switching `r_s` branch sign.
  - `radial_support_extent` ignored `shaft_radius_mm`.
  - `detect_gouges` sampled fewer points than the test's corners + face centers and excluded link stages.

## 2. Strict Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `toolpath_sim.py` | `L992-L1043` | Track `last_sign` across runs/levels in `build_roughing`: link out on `last_sign * clearance_radius`; if `new_sign != last_sign`, lift to `safe_zs = H_stock + clearance`, traverse `start_theta` as `rapid=True` above the stock, and descend to `level` on `new_sign * clearance_radius` before linking in. |
| `toolpath_sim.py` | `L822-L863` + caller in `generate_synthetic_carve_path` | Expand `detect_gouges` sampling to match the heated-region corners + face centers/midpoints so reported `GOUGE` depth is `>=` test-measured depth, and run `detect_gouges` across `finishing`, `roughing_link`, and `finishing_link` stages. |
| `toolpath_sim.py` | `L1376-L1380, L1523-L1570` | Keep the `safe_zs = H_stock + clearance` over-stock cross-axis reposition in `build_finishing` as `rapid=True` (avoiding unnecessary cutting-density resampling), while keeping `r_s`-in-level links non-rapid. |
| `tool_model.py` | `L321-L334` | Include the unheated shaft's radial extent (`shaft_radius` / `max(heated_extent, shaft_extent)`) in `radial_support_extent(phi, config)` so `phi = 0` returns `>= 2.5 mm`. |
| `tests/test_tool_model.py` | `[APPEND]` | Assert `radial_support_extent(0.0, config) >= shaft_radius_mm` (i.e. `>= 2.5 mm`). |
| `tests/test_carver_sim.py` | `[APPEND]` | (1) Assert zero non-rapid `roughing`, `finishing`, `roughing_link`, or `finishing_link` segments cross `r_s = 0` below `H_stock`; (2) assert `GOUGE` reported depth `>=` test-measured burial depth on the needle fixture; (3) update `test_rapids_retract_outside_stock_and_tool_extent` to accept `z_s >= H_stock + retract_clearance_mm` as clear. |
| `openspec/changes/machine-cad-integration/patch.md` | `L57` & `PATCH-02` | Verify no stale `z_plinth_mm moved 10 -> 12` bullet exists; mark `PATCH-02` `VERIFIED` once suites pass. |

## 3. Blast Radius & Invariant Guardrails
- **STRICT BLAST RADIUS**: Modify ONLY the files and line ranges specified in the Target Context Map.
- **DEFERRED (Do NOT implement in this patch)**:
  - `I1` (non-tilting radial-link bracket collision envelope) and `I2` (overhang slab fixture) remain deferred to the follow-up change.
  - Do NOT tick owner gates `7.1` or `7.2` in `tasks.md`—those stay unchecked pending owner sign-off.
- **FORBIDDEN**:
  - Do NOT modify `.env`, credential files, `machine_geometry.json`, `scripts/extract_machine.py`, or `static/cad_rig.js`.

## 4. Visual & UI Impact
- Status: Non-visual patch. No CSS, HTML, or `DESIGN.md` token modifications permitted.

## 5. Reproduction & Verification Protocol
1. **Reproduce First**:
   - Add the failing test cases in `tests/test_carver_sim.py` and `tests/test_tool_model.py`.
   - Run `.venv/bin/python -m unittest tests.test_carver_sim tests.test_tool_model -v` and confirm the new tests fail.
2. **Apply Minimal Fixes**: Apply targeted edits in `toolpath_sim.py` and `tool_model.py`.
3. **Full Regression Suite**:
   - Run `.venv/bin/python -m unittest discover -s tests -v` (0 failures).
   - Run `npm run test:node` (0 failures, only BENCH skipped).
   - Run `openspec validate machine-cad-integration --strict --json`.

## 6. Surgical Patch Checklist
- [ ] P02.1 Scaffold failing tests in `tests/test_carver_sim.py` and `tests/test_tool_model.py` and confirm failure.
- [ ] P02.2 Fix `toolpath_sim.py` (sign-aware `build_roughing` links + over-stock switch, `detect_gouges` corners+faces & link stages, over-stock `rapid=True` in `build_finishing`).
- [ ] P02.3 Fix `tool_model.py` (`radial_support_extent` includes shaft radius).
- [ ] P02.4 Run full Python + Node suites + `openspec validate machine-cad-integration --strict --json`, update `tasks.md` (`P02.1–P02.4`), update `verification.md`, and mark `PATCH-02` `VERIFIED` in `patch.md` (keeping `7.1`/`7.2` open).

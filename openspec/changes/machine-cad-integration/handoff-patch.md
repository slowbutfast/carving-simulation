# Surgical Patch Handoff: OpenSpec Change 'machine-cad-integration' [PATCH-01]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `machine-cad-integration`
- **Patch ID**: `PATCH-01`
- **Objective**: Fix the 2 Critical and 1 Important PR #2 review findings (CAD tilt-link parenting in `static/cad_rig.js`, back-side signed-`r` azimuth coverage in `toolpath_sim.py`, and `--experimental-vm-modules` in `package.json`/`tests.md`), plus `+ kerf` in `tool_model.py` and full-travel `phi` frames in `tests/fixtures/cad_rig_frames.json`.
- **Feedback & Diagnostic Trace**:
  ```
  PR #2 Verdict: REQUEST CHANGES (247cdd5)
  Critical:
  1. static/cad_rig.js:161-180,388-392,472: modelGroups.tilt is attached to this.links.tilt
     (sibling of tiltPivot) instead of this.tiltOffset; update() rotates only tiltPivot, so
     imported CAD cartridge, holder, and horn stay fixed while tipMarker moves.
  2. toolpath_sim.py:103-117 + roughing/finishing: _theta_grid uses range(count) (stops at
     162.4 deg instead of 170 deg), and the generator never emits negative-r_s cuts for the
     ~28 deg behind the head (170..180, -180..-170). Zero cutting frames have r_s < 0.
  Important:
  3. package.json:11 & tests.md: npm run test:node omits --experimental-vm-modules and
     test_wax_worker.mjs / test_cad_rig.mjs, silently skipping 4 spec-scenario tests.
  Suggestions:
  4. tool_model.py:311-320: radial_support_extent omits + melt_kerf_mm.
  5. tests/fixtures/cad_rig_frames.json: max |phi| is ~9 deg; add -60 deg and +75 deg frames.
  ```
- **Root Cause Analysis**:
  - `CadCarverRig` attached `modelGroups['tilt']` to `this.links.tilt` instead of `this.tiltOffset`, bypassing `this.tiltPivot.rotation`.
  - `_theta_grid` used `range(count)` (dropping `hi_deg`), and roughing/finishing did not map uncovered back-side azimuths `(theta_hi, theta_lo + 360°)` onto `theta_emit = azimuth - 180°` with `r_s < 0`.

## 2. Strict Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `static/cad_rig.js` | `L161-L168, L388-L393` | Parent `this.modelGroups['tilt']` under `this.tiltOffset` (instead of `this.links['tilt']`) so the imported `tilt` GLB scene rotates about `tiltPivot` with `phi`. |
| `tests/fixtures/cad_rig_frames.json` | `[APPEND]` | Add representative frames at `phi = -60°` and `+75°` (within `20`+ frames) to verify pivot-point accuracy across full wrist travel. |
| `tests/test_cad_rig.mjs` | `L73-L106` | Extend the rig test to assert that a loaded `T12_K_Cartridge` mesh node (from `rig.cartridgeMeshes`) rotates/translates in world space at `phi != 0` and tracks `tipMarker` / `tip_xyz_wax`. |
| `toolpath_sim.py` | `L103-L118` + roughing/finishing azimuth loops | Include `hi_deg` in `_theta_grid` (`range(count + 1)`), and cover azimuths in `(theta_hi, theta_lo + 360°)` using the signed-`r` (`r_s < 0`, `theta = azimuth - pi`) branch in both roughing and finishing. |
| `tests/test_carver_sim.py` | `[APPEND]` | Add a test verifying that every `10°` azimuth bin of the `demo` target receives cutting frames (including `170°–180°` and `-180°–-170°` via `r_s < 0`). |
| `tool_model.py` | `L311-L320` | Add `+ kerf` (`abs(length * math.sin(phi)) + 0.5 * thickness * abs(cos(phi)) + kerf`) in `radial_support_extent`. |
| `package.json` | `L10-L13` | Update `test:node` to `"node --experimental-vm-modules --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs tests/test_cad_rig.mjs"`. |
| `openspec/changes/machine-cad-integration/tests.md` | `L33-L43` | Document `npm run test:node` / `node --experimental-vm-modules --test ...` so the 4 worker/shank tests are not skipped. |

## 3. Blast Radius & Invariant Guardrails
- **STRICT BLAST RADIUS**: Modify ONLY the files and line ranges specified in the Target Context Map.
- **DEFERRED (Do NOT implement in this patch)**:
  - `I1` (non-tilting radial-link bracket collision envelope) and `I2` (`test_exit_moves_are_clear_and_end_outboard` slab fixture) are deferred to the follow-up spec revision/change alongside owner gate answers (`7.1`, `7.2`).
  - Do NOT tick tasks `7.1` or `7.2` in `tasks.md`—those remain open owner gates.
- **FORBIDDEN**:
  - Do NOT modify `.env`, credential files, `machine_geometry.json`, or `scripts/extract_machine.py`.
  - Do NOT modify existing passing test assertions unless explicitly mapped above.

## 4. Visual & UI Impact
- Status: Scene-graph fix only (`CadCarverRig` `tiltOffset` parenting). No CSS, HTML, or `DESIGN.md` token modifications permitted.

## 5. Reproduction & Verification Protocol
1. **Reproduce First**:
   - Add the `T12_K_Cartridge` world-position assertion in `tests/test_cad_rig.mjs` and the `10°`-azimuth-bin coverage assertion in `tests/test_carver_sim.py`.
   - Run `node --experimental-vm-modules --test tests/test_cad_rig.mjs` and `.venv/bin/python -m unittest tests.test_carver_sim -v` and confirm both fail.
2. **Apply Minimal Fixes**: Apply targeted edits in `static/cad_rig.js`, `toolpath_sim.py`, `tool_model.py`, `package.json`, and `tests.md`.
3. **Full Regression Suite**:
   - Run `npm run test:node` (all 3 `.mjs` files with `--experimental-vm-modules`, 0 skipped).
   - Run `.venv/bin/python -m unittest discover -s tests -v`.
   - Run `openspec validate machine-cad-integration --strict --json`.

## 6. Surgical Patch Checklist
- [ ] P01.1 Scaffold failing tests in `tests/test_cad_rig.mjs` (plus `-60°`/`+75°` in `tests/fixtures/cad_rig_frames.json`) and `tests/test_carver_sim.py` (`10°` azimuth bins) and confirm failure.
- [ ] P01.2 Fix `static/cad_rig.js` (`modelGroups.tilt` parented under `this.tiltOffset`).
- [ ] P01.3 Fix `toolpath_sim.py` (`_theta_grid` endpoint + negative-`r_s` back-side sweep) and `tool_model.py` (`+ kerf` in `radial_support_extent`).
- [ ] P01.4 Update `package.json` (`test:node`) and `openspec/changes/machine-cad-integration/tests.md`.
- [ ] P01.5 Run full Node + Python suites + `openspec validate machine-cad-integration --strict --json`, update `tasks.md` (`P01.1–P01.5`), update `verification.md`, and mark `PATCH-01` `VERIFIED` in `patch.md`.

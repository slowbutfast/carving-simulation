# Verification: xp-ui-overhaul

> Status: **complete, with one paused check** — implementation tasks 1.1–3.2 and
> verification tasks 4.1–4.3 are signed off. The targeted suites were re-run
> after the orchestrator's UI-only corrections and pass. The final full-suite
> rerun was paused at the user's request after 54 passing tests (0 failures);
> the completed pre-correction full-suite run is recorded below. The change is
> ready to archive after merge.

## Executive Summary & Environment

- **Change**: `xp-ui-overhaul` (branch `feat/xp-ui-overhaul`, based on `main` @ `d9e2ec5`)
- **Date**: 2026-11-20
- **Runner**: Node `v22.23.2`; Python `3.11` from `./.venv/bin/python`; Chromium via `playwright-core` `1.65.1`
- **Scope delivered**: emoji-free Windows XP Luna shell (`4-DOF Wax Carver Studio 2001`),
  Google `DESIGN.md`, XP transport dock, 5-cell telemetry status bar, client-side
  upload validation + `.3mf` preview, `/api/presets`, upload-limit health fields,
  and root static serving alongside `/vendor` (`three@0.187.0`).
- **Preserved modules untouched**: `kinematics.py`, `face_sculpt.py`,
  `toolpath_sim.py`, `tool_model.py`, `static/cad_rig.js`, `static/wax_sdf*.js`,
  `static/wax_worker.js`, `static/models/*.glb`, all machine/role JSON, and
  `package*.json`.

## Requirement Adherence Audit Matrix

| Spec requirement / scenario | Verifying test | Status |
|---|---|---|
| **R1** Emoji-free XP Luna shell, menu bar, mobile tabs, help dialog, outside-click/Escape dismissal | `tests/test_xp_ui_lint.mjs` — "index.html renders the 6-layer XP window shell"; Playwright menu/help/escape flow | PASS |
| **S1** Menus/dialogs/tabs update and dismiss; zero Unicode emoji | `tests/test_xp_ui_lint.mjs` — "UI sources are free of Unicode emoji"; Playwright `menuOpen/menuClosed/dialogOpen/dialogClosed` | PASS |
| **R2** Preset selection, pre-flight upload validation, `.3mf` preview | `tests/test_upload_js.mjs` (6 tests); Playwright unsupported/oversized upload refusals | PASS |
| **S2** Unsupported or oversized upload is rejected client-side without a network request | `tests/test_upload_js.mjs`; Playwright `.gcode` and 100-byte-limit cases (`#model-note` + `#status-text`) | PASS |
| **R3** Sculpt/CAD controls, emoji-free transport dock, 5-cell telemetry, fault auto-pause + collision/warning badges | `tests/test_xp_ui_lint.mjs` ("status bar exposes exactly five status cells", "xp.css defines XP chrome...", "app.js wires..."); Playwright play/pause/next/prev/scrub/fault flow | PASS |
| **S3** `SCULPT & SIMULATE` drives rig/SDF playback, scrub snapshots, five cells, collision auto-pause | Playwright transport + `RAPID_COLLISION` fixture: `FAULT`, `.status-badge-collision`, `rgb(232, 17, 35)` / `rgb(255, 255, 255)` | PASS |
| **R4** Gallery viewport, `ResizeObserver`, `+Y` up, `-90°` X root, zero JS trig | `tests/test_xp_ui_lint.mjs` ("app.js wires...", "cad_rig.js keeps +Y up..."); Playwright resize to `820×900` | PASS |
| **S4** Viewport resizes and renders rig/stock with zero JS trig | Playwright desktop `866×694` canvas / mobile `804×280` canvas; lint zero `Math.sin`/`Math.cos` | PASS |
| Upload limits fallback + subtitle (`max_upload_bytes`, `accepted_formats`) | `tests/test_upload_js.mjs` (6 tests) | PASS |
| `GET /` serves the XP shell, `GET /xp.css` serves the dock | `tests/test_server_ui.py` — `test_index_serves_xp_studio`, `test_xp_css_served` | PASS |
| `GET /api/health` advertises upload limits; `GET /api/presets` lists bundled `base_head` | `tests/test_server_ui.py` — `test_health_advertises_upload_limits`, `test_presets_lists_bundled_base_head` | PASS |
| Google `DESIGN.md` front matter + ordered 8 sections | `tests/test_xp_ui_lint.mjs` — "DESIGN.md has YAML front matter..." | PASS |
| Existing kinematics/SDF/CAD behaviour unchanged | `tests/test_carver_sim.py`, `test_cad_rig.mjs`, `test_wax_*.mjs` | PASS |

## Resolved Assumptions & Empirical Proof

- **`CadCarverRig` owns the `-90°` X rotation**: `static/cad_rig.js` sets
  `ROOT_ROTATION_X = -Math.PI / 2`; `static/app.js` adds `rig.root` directly and
  only sets `camera.up.set(0, 1, 0)`. Verified by lint and by the rendered
  desktop screenshot (machine upright, not flipped).
- **The model-source preset is not the toolpath preset**: `#preset-select` is
  populated from `GET /api/presets` (`base_head`), while the request's `preset`
  field sends the `Demo`/`Standard` stock radio value accepted by
  `SimulationRequest.preset`.
- **Playwright sandbox limitation**: the bundled MCP browser could not launch
  (`No usable sandbox!`). Resolved by launching the installed Chromium through
  `playwright-core` with `--no-sandbox --enable-unsafe-swiftshader`, which
  produced the desktop, mobile, fault, menu, and help screenshots without
  console errors.
- **Demo toolpath cost**: a real `POST /api/sculpt-and-sim` (`demo`) took
  `401.85 s` and returned `7.1 MB` / `86,040` frames. The browser interaction
  pass therefore mocked that endpoint with the captured, real response, while
  one unmocked load confirmed the static assets, GLB rig, and API wiring.
- **Mobile model appears small at first**: below `900px` the rig defaults to
  `Machine Detail: Tool Only`, so only the tool subset renders; toggling to
  `Full` restores the machine. This is the specified behaviour, not a render
  defect.
- **Pre-existing diagnostics**: `UNREACHABLE_UNDERCUT_AREA` and
  `BLADE_BROADSIDE_FEED` are emitted by the unchanged backend for the demo
  head; the UI correctly renders them in the amber warning state.

## Orchestrator Corrections During Verification

- Sidebar width aligned to the design token: `238px` → `320px`.
- Mobile breakpoint tightened from `max-width: 900px` to `max-width: 899px`
  so `>= 900px` is desktop, exactly as the design states.
- Transport buttons and scrubber start `disabled` and are enabled only when a
  toolpath exists, preventing an accidental duplicate simulation request;
  `sculptAndSimulate()` is also re-entrancy guarded (`state.generating`).
- `Machine Detail`, download buttons, and other mobile actions raised to the
  `>= 44px` touch target (`#machineDetailBtn` measured at `44px`).
- Added a visible `Provenance` caption ahead of the `STEP …`/home readout.

## Nomenclature & Code Symbol Audit

- `CadCarverRig`, `VolumetricWaxGrid`, `read3mf`, `limitsFromHealth`,
  `checkUploadAllowed`, and `uploadSubtitle` match their source modules and the
  spec/design glossary.
- DOM ids match the spec: `studio-window`, `simulate-button`, `sim-scrubber`,
  `sim-time`, `sim-speed`, `preset-select`, `file-input`, `model-note`,
  `machineDetailBtn`, `unassigned-note`, `status-text`, `status-joints`,
  `status-tip`, `status-feed`, `status-state`, `provenance-step`,
  `provenance-home`, `help-dialog`, `diagnostics`, `diag-count`.
- `static/upload.js` and `static/threemf.js` are byte-identical to the
  `wax-robot` sources (`cmp` verified).

## Browser Verification (Playwright)

| Check | Desktop `1400×900` | Mobile `820×900` |
|---|---|---|
| XP shell / title | `4-DOF Wax Carver Studio 2001`, `.desktop` gradient visible | same |
| Sidebar / viewport | `320px` / canvas `866×694` | viewport `804×280` |
| Status cells | exactly `5` | exactly `5` |
| Telemetry | `r 48.5 / theta 0 / h 180.0 / phi 0`, `tip 48.5, 0.0, 120.0`, `v_tip 0.0 mm/s` | same |
| Transport | Play → `PLAYING`, time `0.00 → 6.95 / 2906.28 s`; Next advances; scrub `750` → `2196.03 s` | Play button `44px`; panel hidden until `Sim` tab |
| Machine Detail | `Full` → toggle → `Tool Only` | defaults to `Tool Only`, target `44px` |
| Menus / help | File opens, Escape closes; Help/About opens, Escape closes | tabs `Model`/`Sculpt`/`Sim` switch panels |
| Upload refusal | `.gcode` → "unsupported format. Use .stl, .obj or .3mf." | — |
| Oversized refusal | 2 KiB vs 100-byte limit → "accepts up to 0.0 MB" | — |
| Fault state | `RAPID_COLLISION` → `FAULT`, `.status-badge-collision`, `rgb(232, 17, 35)` on white | — |
| Duplicate requests | `1` POST despite play/next/prev/scrub | — |
| Console errors | `0` | `0` |

## Empirical Execution Logs

```
$ node --test tests/test_upload_js.mjs tests/test_xp_ui_lint.mjs
# tests 13
# pass 13
# fail 0
# skipped 0

$ npm run test:node
# tests 23
# pass 22
# fail 0
# skipped 1

$ ./.venv/bin/python -m unittest tests.test_server_ui -v
test_health_advertises_upload_limits ... ok
test_index_serves_xp_studio ... ok
test_presets_lists_bundled_base_head ... ok
test_xp_css_served ... ok
Ran 4 tests in 0.050s
OK

$ ./.venv/bin/python -m unittest discover -s tests -v
# Completed during implementation (before the orchestrator's UI-only edits):
Ran 105 tests in 1701.020s
OK (skipped=5)

# Final post-correction rerun, paused at the user's request:
# 54 tests logged as "ok", 0 failures, interrupted while running
# test_standard_preset_produces_denser_path (the slow toolpath block).
# The paused run covered every new test and the API/CAD/SDF suites reached up
# to that point; no failure or error had been logged.

$ openspec validate xp-ui-overhaul --strict --json
valid: true
issues: []

$ node --check static/app.js
JS_OK
```

## Quick Re-Verification (60-Second Audit)

```bash
node --test tests/test_upload_js.mjs tests/test_xp_ui_lint.mjs
npm run test:node
./.venv/bin/python -m unittest tests.test_server_ui -v
openspec validate xp-ui-overhaul --strict --json
# Full suite (slow, ~28 min):
./.venv/bin/python -m unittest discover -s tests -v
```

Expected: Node 13/13 pass; `test:node` 22 pass / 1 skip / 0 fail; server UI
4/4; strict validation `valid: true`. The full suite is `OK (skipped=5)` when
allowed to finish (`~28 min`); the final rerun in this session was paused at the
user's request after 54 passing tests.

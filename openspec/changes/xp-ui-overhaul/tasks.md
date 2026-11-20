## 1. Test Scaffolding (TDD)

- [x] 1.1 Scaffold failing Node tests in `tests/test_upload_js.mjs` covering `limitsFromHealth`, `checkUploadAllowed`, and `uploadSubtitle`
- [x] 1.2 Scaffold failing Node lint tests in `tests/test_xp_ui_lint.mjs` asserting 6-layer XP DOM, `.transport-dock`, 5 `.status-cell` panes, `ResizeObserver`, Google `DESIGN.md` 8-section order, absence of `camera.up.set(0, 0, 1)`, zero `Math.sin`/`Math.cos` in `static/app.js`, and zero Unicode emojis in `static/index.html`, `static/xp.css`, and `static/app.js`
- [x] 1.3 Scaffold failing Python tests in `tests/test_server_ui.py` for `GET /`, `GET /xp.css`, `GET /api/health` (`max_upload_bytes`, `accepted_formats`), and `GET /api/presets`

## 2. Google `DESIGN.md` & Migrate XP Luna Assets

- [x] 2.1 Write root `DESIGN.md` following `github.com/google-labs-code/design.md` (via `opensrc`) and validate with `npx @google/design.md lint DESIGN.md` (or schema/contrast check)
- [x] 2.2 Copy `wax-robot/static/upload.js` and `wax-robot/static/threemf.js` to `static/upload.js` and `static/threemf.js`
- [x] 2.3 Migrate `wax-robot/static/xp.css` to `static/xp.css`, swapping material tokens (`--wax-stock`, `--target-face-ghost`, `--rig-metal`, `--cutter-hot`) and adding `.transport-dock`, `.transport-btn`, `.transport-scrubber`, `.transport-time`, `.transport-speed`, and `.status-badge-collision` styles
- [x] 2.4 Migrate `wax-robot/static/index.html` to emoji-free `static/index.html` as `4-DOF Wax Carver Studio 2001` (preserving `/vendor/build/three.module.js` importmap) with facial sculpt sliders, stock/preset & CAD rig controls (`Machine Detail`, `Unassigned Parts`, `Provenance`), `#simulate-button`, `.transport-dock`, 5-cell `.status-bar`, and `#help-dialog`

## 3. Port Viewer & Align Server Routes

- [x] 3.1 Port `wax-robot/static/viewer.js` into `static/app.js` (gallery Three.js scene with `+Y` up, `-90°` X-rotated root, `ResizeObserver`, XP menus/tabs/dialog/window controls, upload/3MF preview, `CadCarverRig` + `< 900px` `Tool Only` default, `POST /api/sculpt-and-sim` columnar decoding, `THREE.Clock` playback, scrub snapshots, 5-cell telemetry, and fault/warning badges including `BLADE_BROADSIDE_FEED` & `GLB_LOAD_FAILED`)
- [x] 3.2 Update `server.py` so `GET /api/health` advertises `max_upload_bytes` and `accepted_formats`, `GET /api/presets` returns bundled presets, and `StaticFiles(html=True)` mounts at `/` after `/api/*` and `/vendor` routes

## 4. Verification & Empirical Audit

- [x] 4.1 Run `node --test tests/test_upload_js.mjs tests/test_xp_ui_lint.mjs`, `npm run test:node`, `.venv/bin/python -m unittest tests.test_server_ui -v`, and `.venv/bin/python -m unittest discover -s tests -v` and verify clean passes
- [x] 4.2 Strictly validate OpenSpec artifacts (`openspec validate xp-ui-overhaul --strict --json`)
- [x] 4.3 Populate `verification.md` with Requirement Adherence Matrix and verbatim execution logs

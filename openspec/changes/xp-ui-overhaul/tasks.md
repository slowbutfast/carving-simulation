## 1. Test Scaffolding (TDD)

- [ ] 1.1 Scaffold failing Node tests in `tests/test_upload_js.mjs` covering `limitsFromHealth`, `checkUploadAllowed`, and `uploadSubtitle`
- [ ] 1.2 Scaffold failing Node lint tests in `tests/test_xp_ui_lint.mjs` asserting XP Luna DOM/CSS hooks, absence of `camera.up.set(0, 0, 1)`, and zero `Math.sin`/`Math.cos` in `static/app.js`
- [ ] 1.3 Scaffold failing Python tests in `tests/test_server_ui.py` for `GET /`, `GET /xp.css`, `GET /api/health` (`max_upload_bytes`, `accepted_formats`), and `GET /api/presets`

## 2. Migrate XP Luna Assets & Pure Modules

- [ ] 2.1 Copy `wax-robot/static/upload.js` and `wax-robot/static/threemf.js` to `static/upload.js` and `static/threemf.js`
- [ ] 2.2 Migrate `wax-robot/static/xp.css` to `static/xp.css`, swapping material tokens (`--wax-stock`, `--target-face-ghost`, `--rig-metal`, `--cutter-hot`) and adding `.transport-bar`, `.telemetry-readout`, and `.fault-badge` styles
- [ ] 2.3 Migrate `wax-robot/static/index.html` to `static/index.html` as `Carver Studio 2001` with facial sculpt sliders, stock/preset controls, `#simulate-button`, `.transport-bar`, `.status-bar`, and `#help-dialog`

## 3. Port Viewer & Align Server Routes

- [ ] 3.1 Port `wax-robot/static/viewer.js` into `static/app.js` (gallery Three.js scene with `+Y` up & `-90°` X-rotated root, XP menus/tabs/dialog/window controls, upload/3MF preview, `POST /api/sculpt-and-sim` columnar decoding, `THREE.Clock` playback, scrub snapshots, and fault auto-pause)
- [ ] 3.2 Update `server.py` so `GET /api/health` advertises `max_upload_bytes` and `accepted_formats`, `GET /api/presets` returns bundled presets, and `StaticFiles(html=True)` mounts at `/` after API routes
- [ ] 3.3 Update `openspec/changes/carver-sim-mvp/design.md` to reference `xp-ui-overhaul` as the active UI specification

## 4. Verification & Empirical Audit

- [ ] 4.1 Run `node --test tests/test_upload_js.mjs tests/test_xp_ui_lint.mjs` and `python3 -m unittest tests.test_server_ui -v` and verify clean passes
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate xp-ui-overhaul --strict`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix and verbatim execution logs

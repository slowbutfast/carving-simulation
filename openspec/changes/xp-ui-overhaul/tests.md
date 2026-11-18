## Automated Tests

- `node --test tests/test_upload_js.mjs`:
  - **Pre-Flight Upload Validation**: Verifies `limitsFromHealth`, `checkUploadAllowed`, and `uploadSubtitle` in `static/upload.js` reject unsupported extensions and files exceeding `max_upload_bytes`.
- `node --test tests/test_xp_ui_lint.mjs`:
  - **XP Chrome & Zero-Trig Guard**: Verifies `static/index.html`, `static/xp.css`, and `static/app.js` contain required XP Luna tokens/selectors (`.desktop`, `.window`, `.titlebar`, `.menu-bar`, `.transport-bar`, `.status-bar`, `#help-dialog`, `#simulate-button`, `#telemetry-readout`), zero `camera.up.set(0, 0, 1)`, and zero `Math.sin`/`Math.cos` kinematic calls in `static/app.js`.
- `python3 -m unittest tests.test_server_ui -v`:
  - **Backend Static & Health Contract**: Verifies `GET /` serves `text/html` containing `Carver Studio 2001`, `GET /xp.css` serves `text/css`, `GET /api/health` returns `max_upload_bytes` and `accepted_formats`, and `GET /api/presets` returns bundled presets.

## Manual Verification

- **XP Studio End-to-End Flow**:
  - **WHEN** the user opens `/` in a desktop and narrow (`< 900px`) browser viewport, tests menu dropdowns, uploads a `.3mf`/`.stl` or selects `Base Head`, adjusts facial sliders, clicks `⚡ SCULPT & SIMULATE`, and uses `Play/Pause`, `Scrub`, and `Carve to End`
  - **THEN** the XP Luna window chrome, `.mobile-tabs`, `#f0ede0` 3D viewport, rig animation, volumetric wax carving, and `#telemetry-readout` all operate without console errors.

## Automated Tests

- `node --test tests/test_upload_js.mjs`:
  - **Pre-Flight Upload Validation**: Verifies `limitsFromHealth`, `checkUploadAllowed`, and `uploadSubtitle` in `static/upload.js` reject unsupported extensions and files exceeding `max_upload_bytes`.
- `node --test tests/test_xp_ui_lint.mjs`:
  - **XP Chrome, Transport Dock & 5-Cell Status Bar**: Verifies `static/index.html`, `static/xp.css`, and `static/app.js` contain required XP Luna tokens/selectors (`.desktop`, `.window#studio-window`, `.titlebar`, `.menu-bar`, `.mobile-tabs`, `.inset-well.viewport-well`, `.transport-dock`, `.status-bar` with all 5 `#status-*` cells, `.status-badge-collision`, `#help-dialog`, `#simulate-button`, `ResizeObserver`).
  - **Zero-Trig & Emoji-Free Guard**: Asserts zero `camera.up.set(0, 0, 1)`, zero `Math.sin`/`Math.cos` kinematic calls in `static/app.js`, and zero Unicode emoji characters in `static/index.html`, `static/xp.css`, and `static/app.js`.
  - **Google `DESIGN.md` Structure**: Verifies `DESIGN.md` includes YAML front matter and the 8 ordered `##` sections (`Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`).
- `python3 -m unittest tests.test_server_ui -v`:
  - **Backend Static & Health Contract**: Verifies `GET /` serves `text/html` containing `4-DOF Wax Carver Studio 2001`, `GET /xp.css` serves `.transport-dock` CSS, `GET /api/health` returns `max_upload_bytes` and `accepted_formats`, and `GET /api/presets` returns bundled presets.

## Manual Verification

- **XP Studio End-to-End Flow**:
  - **WHEN** the user opens `/` in a desktop and narrow (`< 900px`) browser viewport, tests menu dropdowns + `Escape`, uploads a `.3mf`/`.stl` or selects `Base Head`, adjusts facial sliders, clicks `SCULPT & SIMULATE`, and uses `Prev`, `Play/Pause`, `Next`, `Carve to End`, and `#sim-scrubber`
  - **THEN** the XP Luna window chrome, `.mobile-tabs`, `#f0ede0` 3D viewport (`ResizeObserver`), `PrimitiveCarverRig` animation, `VolumetricWaxGrid` carving, and 5-cell `.status-bar` all operate without console errors or emojis.

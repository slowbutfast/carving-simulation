## Automated Tests

- `node --test tests/test_luna_ui.mjs`:
  - **6-Layer XP DOM & Transport Hooks**: Verifies `static/index.html` and `static/xp.css` define `.desktop`, `.window#studio-window`, `.titlebar`, `.menu-bar`, `.sidebar`, `.mobile-tabs`, `.inset-well.viewport-well`, `.transport-dock`, `.status-bar` (all 5 `#status-*` cells), and `.status-badge-collision`.
  - **Emoji-Free Guard**: Scans `static/index.html`, `static/xp.css`, and `static/app.js` and fails if any Unicode emoji characters are present.
  - **Google `DESIGN.md` Structure**: Verifies `DESIGN.md` includes YAML front matter and the 8 ordered `##` sections (`Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`).
- `python3 -m unittest tests.test_luna_server -v`:
  - **Static Serving & API Integration**: Verifies `GET /` serves `4-DOF Wax Carver Studio 2001` HTML, `GET /static/xp.css` serves `.transport-dock` CSS, and `GET /static/app.js` serves `updateRig`.

## Manual Verification

- **Interactive XP Studio Walkthrough**:
  - **WHEN** the user opens `/` on desktop and `< 900px` mobile width, tests `File`/`View`/`Help` menus + `Escape`, switches `Sculpt`/`Machine`/`Export` tabs, drags RBF sliders, clicks `RECALCULATE SURFACE`, and scrubs `#sim-scrubber`
  - **THEN** the 4-DOF Three.js rig updates smoothly, `.status-cell` panes remain aligned without overflow, and zero emojis appear in the UI.

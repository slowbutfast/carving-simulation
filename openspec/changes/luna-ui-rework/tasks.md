## 1. Test Scaffolding (TDD)

- [ ] 1.1 Scaffold failing Node tests in `tests/test_luna_ui.mjs` verifying the 6-layer XP DOM, `.transport-dock`, 5 `.status-cell` panes, Google `DESIGN.md` section order, and zero Unicode emojis in `static/index.html`, `static/xp.css`, and `static/app.js`
- [ ] 1.2 Scaffold failing Python tests in `tests/test_luna_server.py` verifying `GET /`, `GET /static/xp.css`, and `GET /static/app.js`

## 2. Google `DESIGN.md` & XP Luna Assets

- [ ] 2.1 Write root `DESIGN.md` following `github.com/google-labs-code/design.md` (via `opensrc`) and validate with `npx @google/design.md lint DESIGN.md` (or schema/contrast check)
- [ ] 2.2 Copy `wax-robot/static/xp.css` to `static/xp.css` and append `.transport-dock`, `.transport-btn`, `.transport-scrubber`, `.transport-time`, `.transport-speed`, and `.status-badge-collision` rules
- [ ] 2.3 Create emoji-free `static/index.html` with the 6-layer XP Luna shell, `Sculpt`/`Machine`/`Export` mobile tabs, RBF sliders, stock/kerf inputs, `.transport-dock`, and 5-cell `.status-bar`

## 3. Three.js 4-DOF Rig & Studio Controller

- [ ] 3.1 Implement `static/app.js` with `ResizeObserver` viewport, `OrbitControls`, 4-DOF `updateRig(thetaRad, rMm, hMm, phiRad)`, XP window/menu/mobile-tab/dialog wiring, and `.transport-dock` playback + telemetry updates

## 4. Verification & Empirical Audit

- [ ] 4.1 Run `node --test tests/test_luna_ui.mjs` and `python3 -m unittest tests.test_luna_server -v` and verify clean passes
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate luna-ui-rework --strict --json`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix and verbatim execution logs

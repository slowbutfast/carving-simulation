## Why

We want to rework the `carving-simulation` UI into **4-DOF Wax Carver Studio 2001** by porting the Windows XP Luna Retro Minimalist shell from `wax-robot`, formalizing the visual system in a Google `DESIGN.md`-compliant specification (sourced via `opensrc`), and keeping every control strictly emoji-free.

## What Changes

- **Google `DESIGN.md` Specification (`DESIGN.md`, `design.md`)**:
  - Author a machine-readable + human-readable Google `DESIGN.md` following `github.com/google-labs-code/design.md` (`Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`), explicitly prohibiting emojis.
- **XP Luna Shell & Transport Dock (`static/xp.css`, `static/index.html`)**:
  - Copy `wax-robot/static/xp.css` and append `.transport-dock`, `.transport-btn`, `.transport-scrubber`, `.transport-time`, `.transport-speed`, and `.status-badge-collision` rules.
  - Build `static/index.html` with the 6-layer XP DOM (`div.desktop` $\to$ `main.window` $\to$ `div.titlebar`, `nav.menu-bar`, `div.window-body`, `footer.status-bar`, `div.xp-dialog`), `Sculpt`/`Machine`/`Export` mobile tabs, RBF facial sliders, stock/kerf inputs, emoji-free buttons, and 5-cell telemetry `.status-bar`.
- **Three.js Rig & Studio Controller (`static/app.js`)**:
  - Wire XP window controls, menu dropdowns (`File`, `View`, `Help`), `< 900px` mobile tabs, `ResizeObserver` viewport sizing, `OrbitControls`, and the 4-DOF kinematic rig (`turntableGroup`, `gantryGroup`, `radialArmGroup`, `wristGroup`) with playback scrubbing and collision status updates.

## Capabilities

### New Capabilities
- `luna-studio-ui`: Emoji-free Windows XP Luna desktop studio UI, Google `DESIGN.md` token system, `.transport-dock` playback bar, 5-cell telemetry status bar, and 4-DOF Three.js viewport integration.

## Impact

- **New / Overhauled:** `DESIGN.md`, `static/xp.css`, `static/index.html`, `static/app.js`, `tests/test_luna_ui.mjs`, `tests/test_luna_server.py`.
- **Preserved:** `server.py` API routes, `kinematics.py`, `face_sculpt.py`, `toolpath_sim.py`.

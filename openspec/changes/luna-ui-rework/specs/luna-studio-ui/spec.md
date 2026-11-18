# luna-studio-ui Specification

## Purpose
Define the emoji-free Windows XP Luna Retro Minimalist UI for **4-DOF Wax Carver Studio 2001**, including the Google `DESIGN.md` token system, 6-layer XP window chrome, facial sculpt & stock/tool sidebar, `.transport-dock` playback controls, 5-cell telemetry `.status-bar`, and Three.js 4-DOF kinematic rig integration.

## ADDED Requirements

### Requirement: Emoji-free Windows XP Luna desktop shell and menu bar
The UI SHALL render inside the 6-layer Windows XP Luna DOM (`div.desktop` $\to$ `main.window#studio-window` $\to$ `div.titlebar`, `nav.menu-bar`, `div.window-body`, `footer.status-bar`, `div.xp-dialog#help-dialog`) styled by `static/xp.css`, with `Minimize` (`_`), `Maximize` (`□`), `Close` (`×`), and `File(F)`, `View(V)`, `Help(H)` dropdowns that dismiss on outside click or `Escape`. All UI labels, buttons, and icons SHALL be emoji-free (plain ASCII text or CSS geometric shapes only).

#### Scenario: Menu bar, window controls, and emoji-free guard pass
- **WHEN** `static/index.html`, `static/xp.css`, and `static/app.js` are rendered or linted
- **THEN** clicking `File`, `View`, or `Help` toggles `.menu-dropdown`, clicking outside or pressing `Escape` closes active menus, and zero Unicode emoji characters appear in UI markup or scripts

### Requirement: Responsive property-sheet sidebar for Sculpt, Machine, and Export
The `.sidebar` SHALL organize controls into three panels (`sculpt`, `machine`, `export`) controlled by `.mobile-tabs` below `900px`:
1. **Sculpt**: RBF sliders (`slider-nose`, `slider-brow`, `slider-cheeks`, `slider-jaw`, `slider-chin`) with live numeric readouts (`val-*`) and `RECALCULATE SURFACE` (`#btn-sculpt`).
2. **Machine**: `stock-radius`, `stock-height`, and `tool-kerf` numeric inputs.
3. **Export**: `Export Cylindrical G-Code (.ngc)` (`#btn-export-gcode`) and `Export Carved STL Mesh` (`#btn-export-mesh`).

#### Scenario: Narrow viewport switches sidebar tabs without viewport breakage
- **WHEN** the browser viewport width drops below `900px` and the user clicks `Sculpt`, `Machine`, or `Export`
- **THEN** `.window-body` stacks vertically and only the selected `data-tab-panel` is visible while `#viewport` remains functional

### Requirement: Subtractive carving transport dock and 5-cell telemetry status bar
Inside `.inset-well.viewport-well`, `.transport-dock` SHALL provide emoji-free playback controls (`Prev`, `Play`/`Pause`, `Next`), timeline scrubber (`#sim-scrubber`), time readout (`#sim-time`), and speed selector (`#sim-speed`: `1x`, `2x`, `5x`, `10x`). `footer.status-bar` SHALL display 5 inset `.status-cell` panes (`#status-text`, `#status-joints`, `#status-tip`, `#status-feed`, `#status-state`), applying `.status-badge-collision` (`#e81123` background, `#ffffff` text) on collision faults.

#### Scenario: Scrubber and fault state update telemetry cells cleanly
- **WHEN** the user scrubs `#sim-scrubber` or a collision fault occurs
- **THEN** `#status-joints` and `#status-tip` update in `Courier New` without wrapping/overflow, and `#status-state` applies `.status-badge-collision` on collision

### Requirement: Three.js 4-DOF kinematic rig inside ResizeObserver viewport
`static/app.js` SHALL mount a `THREE.WebGLRenderer` (`#f0ede0` background) with `OrbitControls` inside `#viewport`, observe container resizes via `ResizeObserver`, and articulate the 4-DOF rig (`turntableGroup.rotation.y = thetaRad`, `gantryGroup.position.y = hMm`, `radialArmGroup.position.x = rMm`, `wristGroup.rotation.z = phiRad`) via `updateRig(thetaRad, rMm, hMm, phiRad)`.

#### Scenario: Rig articulation and resize observer update smoothly
- **WHEN** `updateRig` is called with joint coordinates or `#viewport` resizes
- **THEN** the turntable, gantry, radial arm, and wrist groups update their transforms and `ResizeObserver` updates `camera.aspect` and `renderer.setSize`

# xp-studio-ui Specification

## Purpose
Define the migrated, emoji-free Windows XP Luna Retro Minimalist studio UI for `carving-simulation` (**4-DOF Wax Carver Studio 2001**), integrating `wax-robot`'s 6-layer desktop window chrome, upload/3MF preview utilities, and Three.js gallery viewport with the merged `CadCarverRig`, `VolumetricWaxGrid` Web Worker, `.transport-dock` playback, 5-cell telemetry `.status-bar`, and CAD/carving diagnostics.

## ADDED Requirements

### Requirement: Emoji-free Windows XP Luna desktop shell, menu bar, and responsive tabs
The web UI SHALL render inside the 6-layer Windows XP Luna `.desktop` and `.window#studio-window` shell (`static/xp.css`, `static/index.html`) featuring a Luna blue `.titlebar` (`Minimize`, `Maximize`, `Close`), horizontal `.menu-bar` (`File(F)`, `Presets(P)`, `Simulation(S)`, `Help(H)`) with outside-click and `Escape` dismissal, `.mobile-tabs` (`Model`, `Sculpt`, `Sim`) for viewports `< 900px`, a 5-cell `.status-bar`, and an accessible `#help-dialog`. All UI labels, titlebar icons, buttons, and transport controls SHALL be strictly emoji-free (plain ASCII text or CSS geometric shapes only).

#### Scenario: Window chrome, menus, mobile tabs, and emoji-free guard pass
- **WHEN** the user interacts with `.menu-item` dropdowns, toggles window minimize/maximize, opens `#help-dialog`, switches `.mobile-tab` below `900px`, or runs the UI lint check
- **THEN** menus/dialogs/panels update cleanly, dismiss on `Escape` or outside click, and zero Unicode emoji characters appear in `static/index.html`, `static/xp.css`, or `static/app.js`

### Requirement: Model preset selection, pre-flight upload validation, and 3MF preview
The UI SHALL reuse `static/upload.js` and `static/threemf.js` to validate `.stl`, `.obj`, and `.3mf` uploads against `GET /api/health` limits (`max_upload_bytes`, `accepted_formats`) before submission, previewing valid custom meshes in the 3D viewport and rejecting oversized or unsupported files with clear status messages.

#### Scenario: Oversized or unsupported upload is rejected client-side
- **WHEN** the user selects a file with an unsupported extension or size exceeding `max_upload_bytes` from `GET /api/health`
- **THEN** `checkUploadAllowed` refuses the upload immediately with a descriptive message in `#model-note` and `#status-text` without sending a network request

### Requirement: Facial sculpt controls, CAD rig controls, transport dock, and 5-cell fault/warning telemetry
The sidebar SHALL provide facial sculpt `.xp-slider` controls (`nose`, `brow`, `cheeks`, `jaw`, `chin`), stock/preset inputs (`R_stock`, `H_stock`, `demo`/`standard`, `Show Target Ghost`, `Machine Detail: Full / Tool Only` defaulting to `Tool Only` below `900px` with `>= 44px` touch target), `Unassigned Parts` and `Provenance` (`step_sha256`) readouts, and the green XP `#simulate-button` (`SCULPT & SIMULATE`). Anchored inside `.inset-well.viewport-well`, `.transport-dock` SHALL provide emoji-free playback controls (`Prev`, `Play`/`Pause`, `Next`, `Carve to End`), timeline `#sim-scrubber`, `#sim-time`, and `#sim-speed` (`1x`, `5x`, `10x`, `20x`). `footer.status-bar` SHALL display 5 inset `.status-cell` panes (`#status-text`, `#status-joints`, `#status-tip`, `#status-feed`, `#status-state`). Faults (`RAPID_COLLISION`, `SHANK_COLLISION`, `SOFT_LIMIT_EXCEEDED`, `STOCK_BOUNDS_EXCEEDED`) SHALL auto-pause playback and apply `.status-badge-collision` (`#e81123` background, `#ffffff` text), while warnings (`SINGULARITY_HIGH_THETA_DOT`, `UNREACHABLE_UNDERCUT_AREA`, `BLADE_BROADSIDE_FEED`, `GLB_LOAD_FAILED`) highlight amber (`#f59e0b`).

#### Scenario: Sculpt & Simulate drives CAD rig playback, scrubbing, and fault auto-pause
- **WHEN** the user clicks `SCULPT & SIMULATE`, presses `Play`, scrubs `#sim-scrubber`, toggles `Machine Detail`, or encounters a collision/limit diagnostic
- **THEN** `static/app.js` decodes the columnar `POST /api/sculpt-and-sim` payload, animates `CadCarverRig` and `VolumetricWaxGrid` via `THREE.Clock`, updates all 5 `.status-cell` panes without wrapping/overflow, and auto-pauses with `.status-badge-collision` on collision/limit errors

### Requirement: Gallery Three.js viewport with ResizeObserver, +Y-up root group, and zero JS trig
`static/app.js` SHALL import Three.js `0.187.0` from `/vendor/build/three.module.js`, initialize the `#f0ede0` gallery Three.js viewport (`SRGBColorSpace`, `ACESFilmicToneMapping`, `RoomEnvironment`, `OrbitControls` with damping, 3-point lighting), observe `#viewport` via `ResizeObserver`, keep default `+Y` up (`camera.up.set(0, 1, 0)`), and host `CadCarverRig` (`static/cad_rig.js`) and `VolumetricWaxGrid` inside a `-90°` X-rotated root group with zero kinematic trigonometry in JavaScript.

#### Scenario: Viewport resizes and renders CAD rig and wax stock with zero JS trig
- **WHEN** `static/app.js` and `static/cad_rig.js` are inspected or `#viewport` resizes
- **THEN** `ResizeObserver` updates `camera.aspect` and `renderer.setSize`, `camera.up` remains `(0, 1, 0)` with a `-90°` X-rotated machine root group, and neither file contains `Math.sin` or `Math.cos` kinematic pose calculations

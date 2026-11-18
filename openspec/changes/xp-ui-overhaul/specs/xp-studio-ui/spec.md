# xp-studio-ui Specification

## Purpose
Define the migrated Windows XP Luna Retro Minimalist studio UI for `carving-simulation`, integrating `wax-robot`'s desktop window chrome, upload/3MF preview utilities, and Three.js gallery viewport with `carver-sim-mvp`'s facial sculpting, transport playback, and collision telemetry.

## ADDED Requirements

### Requirement: Windows XP Luna desktop shell, menu bar, and responsive tabs
The web UI SHALL render inside the Windows XP Luna `.desktop` and `.window` shell (`static/xp.css`, `static/index.html`) featuring a Luna blue `.titlebar` (`Minimize`, `Maximize`, `Close`), horizontal `.menu-bar` (`File(F)`, `Presets(P)`, `Simulation(S)`, `Help(H)`) with keyboard navigation, `.mobile-tabs` (`Model`, `Sculpt`, `Sim`) for viewports `< 900px`, a 3-cell `.status-bar`, and an accessible `#help-dialog`.

#### Scenario: Window chrome, menus, and mobile tabs operate interactively
- **WHEN** the user clicks a `.menu-item`, toggles window minimize/maximize, opens `#help-dialog`, or switches `.mobile-tab` on a narrow viewport
- **THEN** the corresponding menu dropdown, window state, modal dialog, or property-sheet panel updates without console errors and closes cleanly on `Escape`

### Requirement: Model preset selection, pre-flight upload validation, and 3MF preview
The UI SHALL reuse `static/upload.js` and `static/threemf.js` to validate `.stl`, `.obj`, and `.3mf` uploads against `GET /api/health` limits (`max_upload_bytes`, `accepted_formats`) before submission, previewing valid custom meshes in the 3D viewport and rejecting oversized or unsupported files with clear status messages.

#### Scenario: Oversized or unsupported upload is rejected client-side
- **WHEN** the user selects a file with an unsupported extension or size exceeding `max_upload_bytes` from `GET /api/health`
- **THEN** `checkUploadAllowed` refuses the upload immediately with a descriptive message in `#model-note` and `#status-operation` without sending a network request

### Requirement: Facial sculpt controls, transport bar, and fault/warning telemetry
The sidebar SHALL provide facial sculpt `.xp-slider` controls (`nose`, `brow`, `cheeks`, `jaw`, `chin`), stock/preset inputs (`R_stock`, `H_stock`, `demo`/`standard`, `Show Target Ghost`), and the green XP `#simulate-button` (`⚡ SCULPT & SIMULATE`). Below `#viewport`, an XP-styled `.transport-bar` SHALL provide `Play/Pause`, `Carve to End`, timeline `Scrub` slider, `1x–20x` speed selector, and monospace `#telemetry-readout` displaying `(r, theta, h, phi)` and `(r_s, theta_s, z_s, v_tip)`. Faults (`RAPID_COLLISION`, `SHANK_COLLISION`, `SOFT_LIMIT_EXCEEDED`, `STOCK_BOUNDS_EXCEEDED`) SHALL auto-pause playback and display a red `#e81123` badge, while warnings (`SINGULARITY_HIGH_THETA_DOT`, `UNREACHABLE_UNDERCUT_AREA`) display an amber `#f59e0b` badge.

#### Scenario: Sculpt & Simulate drives playback, scrubbing, and fault auto-pause
- **WHEN** the user clicks `⚡ SCULPT & SIMULATE`, presses `Play`, scrubs the timeline, or encounters a collision/limit diagnostic
- **THEN** `static/app.js` decodes the columnar `POST /api/sculpt-and-sim` payload, animates `PrimitiveCarverRig` and `VolumetricWaxGrid` via `THREE.Clock`, updates `#telemetry-readout`, and auto-pauses with the corresponding `#e81123` fault badge on collision/limit errors

### Requirement: Gallery Three.js viewport with +Y-up root group and zero JS trig
`static/app.js` SHALL initialize the `#f0ede0` gallery Three.js viewport (`SRGBColorSpace`, `ACESFilmicToneMapping`, `RoomEnvironment`, `OrbitControls` with damping, 3-point lighting) using default `+Y` up (`camera.up.set(0, 1, 0)`) and hosting `PrimitiveCarverRig` and `VolumetricWaxGrid` inside a `-90°` X-rotated root group with zero kinematic trigonometry in JavaScript.

#### Scenario: Viewport renders wax stock and rig with zero JS trig
- **WHEN** `static/app.js` and `static/machine_rig.js` are inspected or executed
- **THEN** `camera.up` remains `(0, 1, 0)` with a `-90°` X-rotated machine root group, and neither file contains `Math.sin` or `Math.cos` kinematic pose calculations

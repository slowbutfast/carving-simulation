## Why

`wax-robot` already has a cohesive, polished **Windows XP Luna Retro Minimalist** desktop studio UI (`DESIGN.md`, `static/xp.css`, `static/index.html`, `static/viewer.js`, `static/upload.js`, `static/threemf.js`). Now that `carver-sim-mvp` and `machine-cad-integration` are merged and archived on `main`, we want to replace the current dark-mode `static/index.html` + `static/app.js` shell with `wax-robot`'s XP Luna UI (**4-DOF Wax Carver Studio 2001**), formalize the visual system in a Google `DESIGN.md`-compliant specification (sourced via `opensrc`), enforce strictly emoji-free controls, and preserve every `machine-cad-integration` capability (`CadCarverRig`, `static/models/*.glb`, `Machine Detail` toggle, `Unassigned Parts` & `Provenance` readouts, `VolumetricWaxGrid` Web Worker, and `BLADE_BROADSIDE_FEED` / `GLB_LOAD_FAILED` diagnostics).

## What Changes

- **Google `DESIGN.md` Specification (`DESIGN.md`, `design.md`)**:
  - Author a machine-readable + human-readable Google `DESIGN.md` following `github.com/google-labs-code/design.md` (`Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`), explicitly prohibiting Unicode emojis.
- **Migrate XP Luna Chrome & Transport Dock (`static/xp.css`, `static/index.html`)**:
  - Port the 6-layer `.desktop` / `.window` / `.titlebar` / `.menu-bar` / `.mobile-tabs` / `.status-bar` / `.xp-dialog` shell from `wax-robot`, branded as **4-DOF Wax Carver Studio 2001**, keeping the local `/vendor/build/three.module.js` (`three@0.187.0`) importmap.
  - Replace the current dark-mode controls with XP-styled `Model Source` (preset + `.stl`/`.obj`/`.3mf` upload), `Facial Sculpt` sliders (`nose`, `brow`, `cheeks`, `jaw`, `chin`), `Stock & Preset` controls (`Demo`/`Standard`, `Show Target Ghost`, `Machine Detail: Full / Tool Only`), `Unassigned Parts` & `Provenance` readouts, emoji-free `SCULPT & SIMULATE` CTA, a recessed `.transport-dock` (`Prev`, `Play/Pause`, `Next`, `Carve to End`, `#sim-scrubber`, `#sim-time`, `1x–20x`), and a 5-cell telemetry `.status-bar`.
- **Port Viewer & Pure Upload Modules (`static/app.js`, `static/upload.js`, `static/threemf.js`)**:
  - Reuse `upload.js` and `threemf.js` directly from `wax-robot`.
  - Port `viewer.js`'s Three.js gallery viewport (`#f0ede0`, `RoomEnvironment`, `OrbitControls`), `ResizeObserver` viewport sizing, XP menu/tab/dialog/window wiring, and `requestJson()` into `static/app.js`, preserving `CadCarverRig` (`static/cad_rig.js`, `-90°` X-rotated root, zero JS trig, `< 900px` `Tool Only` default) and `VolumetricWaxGrid` (`wax_worker.js`).
- **Align Backend Static & Health Endpoints (`server.py`)**:
  - Ensure `GET /api/health` advertises `max_upload_bytes` and `accepted_formats` (for `upload.js`), `GET /api/presets` lists bundled presets, and `StaticFiles(html=True)` mounts at `/` after API routes and `/vendor`.

## Capabilities

### New Capabilities
- `xp-studio-ui`: Emoji-free Windows XP Luna Retro Minimalist studio shell, Google `DESIGN.md` token system, upload/3MF preview, facial sculpt & CAD rig controls (`Machine Detail`, `Provenance`, `Unassigned Parts`), `.transport-dock` playback bar, 5-cell telemetry `.status-bar`, and fault/warning badges.

## Impact

- **New / Overhauled:** `DESIGN.md`, `static/xp.css`, `static/index.html`, `static/app.js`, `static/upload.js`, `static/threemf.js`, `tests/test_upload_js.mjs`, `tests/test_xp_ui_lint.mjs`, `tests/test_server_ui.py`.
- **Modified:** `server.py` (health upload limits + presets route + static mount).
- **Preserved Unchanged:** `kinematics.py`, `face_sculpt.py`, `toolpath_sim.py`, `tool_model.py`, `scripts/extract_machine.py`, `machine_geometry.json`, `cad_part_roles.json`, `static/models/*.glb`, `static/cad_rig.js`, `static/wax_sdf_core.js`, `static/wax_worker.js`, `static/wax_sdf.js`.

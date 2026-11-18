## Why

`wax-robot` already has a cohesive, polished **Windows XP Luna Retro Minimalist** desktop studio UI (`DESIGN.md`, `static/xp.css`, `static/index.html`, `static/viewer.js`, `static/upload.js`, `static/threemf.js`). Rather than building a separate generic dark-mode UI for `carving-simulation`, we want to migrate the `wax-robot` UI shell, interaction patterns, and upload/preview utilities into `carving-simulation` while preserving all `carver-sim-mvp` simulation capabilities (facial sculpt sliders, columnar trajectory playback, Web Worker volumetric SDF carving, zero-trig primitive rig, and fault telemetry).

## What Changes

- **Migrate XP Luna Design System & Chrome (`static/xp.css`, `static/index.html`)**:
  - Port the `.desktop` / `.window` / `.titlebar` / `.menu-bar` / `.mobile-tabs` / `.status-bar` / `.xp-dialog` shell from `wax-robot`, branded as **Carver Studio 2001**.
  - Replace Kintsugi-specific fracture controls with 4-DOF Carver controls (`Model Source` + `.stl`/`.obj`/`.3mf` upload, `Facial Sculpt` sliders for `nose`, `brow`, `cheeks`, `jaw`, `chin`, `Stock & Preset` controls, `⚡ SCULPT & SIMULATE` CTA, and an XP-styled `.transport-bar` with `Play/Pause`, `Carve to End`, `Scrub`, `1x–20x`, and live telemetry).
- **Port Viewer & Pure Upload Modules (`static/app.js`, `static/upload.js`, `static/threemf.js`)**:
  - Reuse `upload.js` and `threemf.js` directly from `wax-robot`.
  - Port `viewer.js`'s Three.js gallery viewport (`#f0ede0`, `RoomEnvironment`, `OrbitControls`), XP menu/tab/dialog/window wiring, and `requestJson()` into `static/app.js`, wired to `POST /api/sculpt-and-sim`, `PrimitiveCarverRig`, and `VolumetricWaxGrid` (`wax_worker.js`).
- **Align Backend Static & Health Endpoints (`server.py`)**:
  - Ensure `GET /api/health` advertises `max_upload_bytes` and `accepted_formats`, `GET /api/presets` lists bundled presets, and `StaticFiles(html=True)` mounts at `/` after API routes.

## Capabilities

### New Capabilities
- `xp-studio-ui`: Windows XP Luna Retro Minimalist studio shell, upload/3MF preview, facial sculpt & stock controls, simulation transport bar, live telemetry, and fault/warning badges for the 4-DOF wax carver.

## Impact

- **New / Overhauled:** `static/xp.css`, `static/index.html`, `static/app.js`, `static/upload.js`, `static/threemf.js`, `tests/test_upload_js.mjs`, `tests/test_xp_ui_lint.mjs`, `tests/test_server_ui.py`.
- **Modified:** `server.py` (health limits + presets route + static mount), `openspec/changes/carver-sim-mvp/design.md` (superseded by this overhaul).
- **Preserved Unchanged:** `kinematics.py`, `face_sculpt.py`, `toolpath_sim.py`, `static/machine_rig.js`, `static/wax_sdf_core.js`, `static/wax_worker.js`, `static/wax_sdf.js`.

## Why

`wax-robot` already has a cohesive, polished **Windows XP Luna Retro Minimalist** desktop studio UI (`DESIGN.md`, `static/xp.css`, `static/index.html`, `static/viewer.js`, `static/upload.js`, `static/threemf.js`). Rather than building a separate generic dark-mode UI for `carving-simulation`, we want to migrate the `wax-robot` UI shell, interaction patterns, and upload/preview utilities into `carving-simulation` as **4-DOF Wax Carver Studio 2001**, formalize the visual system in a Google `DESIGN.md`-compliant specification (sourced via `opensrc`), enforce strictly emoji-free controls, and preserve all `carver-sim-mvp` simulation capabilities (facial sculpt sliders, columnar trajectory playback, Web Worker volumetric SDF carving, zero-trig primitive rig, and fault telemetry).

## What Changes

- **Google `DESIGN.md` Specification (`DESIGN.md`, `design.md`)**:
  - Author a machine-readable + human-readable Google `DESIGN.md` following `github.com/google-labs-code/design.md` (`Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`), explicitly prohibiting Unicode emojis.
- **Migrate XP Luna Chrome & Transport Dock (`static/xp.css`, `static/index.html`)**:
  - Port the 6-layer `.desktop` / `.window` / `.titlebar` / `.menu-bar` / `.mobile-tabs` / `.status-bar` / `.xp-dialog` shell from `wax-robot`, branded as **4-DOF Wax Carver Studio 2001**.
  - Replace Kintsugi-specific fracture controls with 4-DOF Carver controls (`Model Source` + `.stl`/`.obj`/`.3mf` upload, `Facial Sculpt` sliders for `nose`, `brow`, `cheeks`, `jaw`, `chin`, `Stock & Preset` controls, emoji-free `SCULPT & SIMULATE` CTA, a recessed `.transport-dock` with `Prev`, `Play/Pause`, `Next`, `Carve to End`, `#sim-scrubber`, `#sim-time`, `1x–20x`, and a 5-cell telemetry `.status-bar`).
- **Port Viewer & Pure Upload Modules (`static/app.js`, `static/upload.js`, `static/threemf.js`)**:
  - Reuse `upload.js` and `threemf.js` directly from `wax-robot`.
  - Port `viewer.js`'s Three.js gallery viewport (`#f0ede0`, `RoomEnvironment`, `OrbitControls`), `ResizeObserver` viewport sizing, XP menu/tab/dialog/window wiring, and `requestJson()` into `static/app.js`, wired to `POST /api/sculpt-and-sim`, `PrimitiveCarverRig` (`-90°` X-rotated root, zero JS trig), and `VolumetricWaxGrid` (`wax_worker.js`).
- **Align Backend Static & Health Endpoints (`server.py`)**:
  - Ensure `GET /api/health` advertises `max_upload_bytes` and `accepted_formats`, `GET /api/presets` lists bundled presets, and `StaticFiles(html=True)` mounts at `/` after API routes.

## Capabilities

### New Capabilities
- `xp-studio-ui`: Emoji-free Windows XP Luna Retro Minimalist studio shell, Google `DESIGN.md` token system, upload/3MF preview, facial sculpt & stock controls, `.transport-dock` playback bar, 5-cell telemetry `.status-bar`, and fault/warning badges for the 4-DOF wax carver.

## Impact

- **New / Overhauled:** `DESIGN.md`, `static/xp.css`, `static/index.html`, `static/app.js`, `static/upload.js`, `static/threemf.js`, `tests/test_upload_js.mjs`, `tests/test_xp_ui_lint.mjs`, `tests/test_server_ui.py`.
- **Modified:** `server.py` (health limits + presets route + static mount), `openspec/changes/carver-sim-mvp/design.md` (superseded by this overhaul).
- **Preserved Unchanged:** `kinematics.py`, `face_sculpt.py`, `toolpath_sim.py`, `static/machine_rig.js`, `static/wax_sdf_core.js`, `static/wax_worker.js`, `static/wax_sdf.js`.

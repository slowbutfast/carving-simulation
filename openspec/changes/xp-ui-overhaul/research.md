## Source material

- **`wax-robot` Reference UI (`/home/node/global-sandbox/projects/wax-robot`)**:
  - `DESIGN.md` (182 lines): Windows XP Luna Retro Minimalist design system tokens, typography, bevels, and component specs.
  - `static/xp.css` (1000 lines): Complete vanilla CSS implementation of the XP window frame, Luna blue titlebar, menu bar, mobile property-sheet tabs, About dialog, inset wells, sliders, green Start-style action button, and 3-cell status bar.
  - `static/index.html` (277 lines): Desktop/window markup, Three.js `0.160.0` importmap, menu dropdowns, sidebar panels, `#viewport`, `.processing-overlay`, and `#help-dialog`.
  - `static/viewer.js` (1134 lines): Three.js `WebGLRenderer` (`SRGBColorSpace`, `ACESFilmicToneMapping`, `RoomEnvironment`), `OrbitControls`, XP menu/tab/dialog/window wiring, `requestJson()` with request-ID logging, and upload/preset handling.
  - `static/upload.js` (68 lines): Pure JS (zero DOM/Three.js) upload format & size limit validation (`DEFAULT_LIMITS`, `limitsFromHealth`, `checkUploadAllowed`, `uploadSubtitle`).
  - `static/threemf.js`: Client-side `.3mf` preview parser.
  - `web_app.py`: FastAPI `GET /api/health` advertising `max_upload_bytes` and `accepted_formats`, plus `StaticFiles(html=True)` mount at `/`.
- **Target Project (`carving-simulation`)**:
  - Must integrate cleanly with `carver-sim-mvp` backend (`server.py`, `POST /api/sculpt-and-sim` columnar base64 buffers) and 3D simulation modules (`static/machine_rig.js`, `static/wax_sdf.js`, `static/wax_worker.js`, `static/wax_sdf_core.js`).

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| XP Luna Shell | Windows XP-themed desktop frame (`.desktop`, `.window`, `.titlebar`, `.menu-bar`, `.status-bar`, `.xp-dialog`) from `wax-robot/static/xp.css` | Dark-mode Tailwind/modern flat UI |
| Transport Bar | Recessed XP control strip below `#viewport` with `Play/Pause`, `Carve to End`, timeline `Scrub` slider, `1x–20x` speed, and monospace telemetry | Separate floating modal |
| Zero-Trig Viewer | `static/app.js` + `static/machine_rig.js` consuming Python `tip_xyz_wax` / `tool_axis_wax` inside a `-90°` X-rotated root group (`+Y` up) | Recomputing FK/IK in JS or copying `wax-robot`'s `camera.up.set(0, 0, 1)` |

## Candidate tech

| Option | Decision | Reason |
| :--- | :--- | :--- |
| **Migrate `wax-robot` `xp.css` + `index.html` + `upload.js` + `threemf.js`** | Adopted | Battle-tested XP Luna retro studio UI with zero build step and mobile property-sheet tabs |
| **Keep `carver-sim-mvp` Web Worker SDF & Zero-Trig Rig seams** | Adopted | Preserves 30+ FPS volumetric undercut carving and single-source-of-truth Python kinematics |
| **External CSS framework (Tailwind/Bootstrap)** | Rejected | Explicitly prohibited by `wax-robot/DESIGN.md`; vanilla `xp.css` is self-contained |

## Verified facts

| Claim | Value | How verified | Date |
| :--- | :--- | :--- | :--- |
| `wax-robot/static/upload.js` is pure JS | 68 lines, zero DOM/Three.js imports | Read `wax-robot/static/upload.js` | 2026-11-17 |
| `wax-robot/static/xp.css` is self-contained | 1000 lines, CSS custom properties + XP bevels | Read `wax-robot/static/xp.css` | 2026-11-17 |
| `wax-robot` uses `camera.up.set(0, 0, 1)` | `viewer.js` line 124 | Read `wax-robot/static/viewer.js` | 2026-11-17 |

## Unverified assumptions

| Assumption | Confidence | How to verify |
| :--- | :--- | :--- |
| `wax-robot/static/threemf.js` works unchanged with `three@0.160.0` `fflate` import | High | Verify importmap and load a sample `.3mf` in manual browser check |

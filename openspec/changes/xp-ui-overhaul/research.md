## Source material

- **`wax-robot` Reference UI (`/home/node/global-sandbox/projects/wax-robot`)**:
  - `DESIGN.md` (182 lines): Windows XP Luna Retro Minimalist design system tokens, typography, bevels, and component specs.
  - `static/xp.css` (1000 lines): Complete vanilla CSS implementation of the XP window frame, Luna blue titlebar, menu bar, mobile property-sheet tabs, About dialog, inset wells, sliders, green Start-style action button, and 3-cell status bar.
  - `static/index.html` (277 lines) & `static/viewer.js` (1134 lines): 6-layer semantic DOM (`div.desktop` $\to$ `main.window` $\to$ `div.titlebar`, `nav.menu-bar`, `div.window-body`, `footer.status-bar`, `div.xp-dialog`) with `ResizeObserver` viewport sizing, `RoomEnvironment`, `OrbitControls`, and `< 900px` `.mobile-tabs`.
  - `static/upload.js` (68 lines) & `static/threemf.js`: Pure JS upload format/size limit validation and client-side `.3mf` preview.
- **Current `carving-simulation` `main` Baseline (post-`carver-sim-mvp` & `machine-cad-integration`)**:
  - `static/cad_rig.js` (`CadCarverRig`): Loads `static/models/*.glb` (`static ⊃ orbit ⊃ z ⊃ radial ⊃ tilt` with `tiltOffset`), hosts static wax, supports `Machine Detail` (`Full` vs `Tool only`), and emits `GLB_LOAD_FAILED`.
  - `static/wax_sdf.js` / `wax_worker.js` / `wax_sdf_core.js`: Web Worker volumetric SDF carving + `RAPID_COLLISION` / `SHANK_COLLISION`.
  - `server.py`: Serves `/vendor/` from `node_modules/three` (`three@0.187.0`), `GET /api/health`, and `POST /api/sculpt-and-sim`.
- **Google `DESIGN.md` Specification (via `opensrc`)**:
  - Cached at `/home/node/.opensrc/repos/github.com/google-labs-code/design.md/main/README.md`.
  - Defines YAML front matter + 8 ordered `##` sections (`Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`).
- **Emoji-Free Constraint**:
  - All UI labels, titlebar icons, action buttons, and transport controls MUST use plain ASCII text or CSS/SVG geometric shapes—no Unicode emojis.

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| XP Luna Shell | Windows XP-themed desktop frame (`.desktop`, `.window`, `.titlebar`, `.menu-bar`, `.status-bar`, `.xp-dialog`) from `wax-robot/static/xp.css` | Dark-mode layout in current `static/index.html` |
| Google `DESIGN.md` | YAML-front-matter + ordered-section design spec per `github.com/google-labs-code/design.md` | Unstructured prose |
| `.transport-dock` | Recessed XP playback bar inside `.inset-well.viewport-well` (`Prev`, `Play/Pause`, `Next`, `Carve to End`, `#sim-scrubber`, `#sim-time`, `#sim-speed`) | Floating dark-mode pill bar |
| Zero-Trig CAD Rig | `static/cad_rig.js` (`CadCarverRig`) + `static/app.js` consuming Python `tip_xyz_wax` / `tool_axis_wax` inside a `-90°` X-rotated root (`+Y` up) | `static/machine_rig.js` (deleted) or `wax-robot`'s `camera.up.set(0, 0, 1)` |

## Candidate tech

| Option | Decision | Reason |
| :--- | :--- | :--- |
| **Port `wax-robot/static/xp.css` + `.transport-dock` additions** | Adopted | Authentic XP Luna tactility with zero CSS framework overhead |
| **Preserve `CadCarverRig` (`static/cad_rig.js`) & `three@0.187.0` `/vendor/` mount** | Adopted | Keeps merged CAD GLB rig, `Machine Detail` toggle, and local Three.js offline support |
| **Google `DESIGN.md` schema for `design.md` & root `DESIGN.md`** | Adopted | Machine-readable tokens + lintable via `@google/design.md` |
| **Unicode emojis for icons/buttons** | Rejected | Explicitly excluded; use clean ASCII/text labels |

## Verified facts

| Claim | Value | How verified | Date |
| :--- | :--- | :--- | :--- |
| `static/cad_rig.js` replaced `static/machine_rig.js` | `CadCarverRig` on `main` (`a667fdd`) | Merged PR #2 & read `server.py` / `static/index.html` | 2026-11-20 |
| `server.py` mounts `node_modules/three` (`0.187.0`) at `/vendor` | `THREE_DIR = ROOT / "node_modules" / "three"` | Read `server.py` L36 & `static/index.html` L11-12 | 2026-11-20 |
| Google `DESIGN.md` repo cached in `opensrc` | `github.com/google-labs-code/design.md@main` | `opensrc list` & read `README.md` | 2026-11-18 |

## Unverified assumptions

| Assumption | Confidence | How to verify |
| :--- | :--- | :--- |
| `wax-robot/static/threemf.js` works with `three@0.187.0` `fflate` `/vendor/` import | High | Verify `three/addons/libs/fflate.module.js` exists in `node_modules/three` and test `.3mf` preview |

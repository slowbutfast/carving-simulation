# OpenCode Orchestration Handoff: OpenSpec Change 'xp-ui-overhaul'

You are the orchestration agent for OpenSpec change 'xp-ui-overhaul' running in OpenCode.
Your primary directive is to execute this change using the **`openspec-apply-sub`** skill, which delegates task implementation to the `spec-coder-sub` subagent.

## 1. Orchestration Directive
- **Change Name**: `xp-ui-overhaul`
- **Target Skill**: `openspec-apply-sub` (or `/opsx:apply-sub xp-ui-overhaul`)
- **Architecture Paradigm**: Vertical Slice Architecture (VSA). Maintain strict isolation between the UI shell (`xp-studio-ui`) and preserved backend/CAD/SDF modules.

## 2. Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `DESIGN.md` | `[NEW]` | Author Google `DESIGN.md` (`github.com/google-labs-code/design.md` format: YAML front matter with `{colors.*}` references + 8 ordered `##` sections: `Overview`, `Colors`, `Typography`, `Layout`, `Elevation & Depth`, `Shapes`, `Components`, `Do's and Don'ts`), explicitly forbidding Unicode emojis. |
| `static/upload.js` | `[NEW]` | Copy verbatim from `/home/node/global-sandbox/projects/wax-robot/static/upload.js` (pure JS upload limit & `.stl`/`.obj`/`.3mf` format validation). |
| `static/threemf.js` | `[NEW]` | Copy verbatim from `/home/node/global-sandbox/projects/wax-robot/static/threemf.js` (client-side `.3mf` previewer using `three/addons/libs/fflate.module.js`). |
| `static/xp.css` | `[NEW]` | Copy from `/home/node/global-sandbox/projects/wax-robot/static/xp.css`, swap 3D material tokens (`--wax-stock: #e8d595`, `--target-face-ghost: #3b82f6`, `--rig-metal: #64748b`, `--cutter-hot: #f97316`), and append `.transport-dock`, `.transport-btn`, `.transport-scrubber`, `.transport-time`, `.transport-speed`, and `.status-badge-collision` (`#e81123` / `#ffffff`) rules. |
| `static/index.html` | `L1-L387` | Replace dark-mode HTML with emoji-free 6-layer XP Luna DOM (`4-DOF Wax Carver Studio 2001`), keeping the `/vendor/build/three.module.js` (`three@0.187.0`) importmap; add `Model Source` (preset + upload), `Facial Sculpt` sliders, `Stock & CAD Rig` (`R_stock`, `H_stock`, `Demo`/`Standard`, `Show Target Ghost`, `Machine Detail: Full / Tool Only`, `Unassigned Parts`, `Provenance`), `#simulate-button` (`SCULPT & SIMULATE`), `.transport-dock` (`Prev`, `Play`/`Pause`, `Next`, `Carve to End`, `#sim-scrubber`, `#sim-time`, `#sim-speed`), 5-cell `.status-bar` (`#status-text`, `#status-joints`, `#status-tip`, `#status-feed`, `#status-state`), and `#help-dialog`. |
| `static/app.js` | `L1-L683` | Port `wax-robot/static/viewer.js` XP window/menu/mobile-tab/dialog/upload wiring, `#f0ede0` gallery lighting (`SRGBColorSpace`, `ACESFilmicToneMapping`, `RoomEnvironment`), `ResizeObserver` on `#viewport`, and `requestJson()`; keep `+Y` up (`camera.up.set(0, 1, 0)`) and `-90°` X-rotated root driving `CadCarverRig` (`static/cad_rig.js`, `< 900px` `Tool Only` default) and `VolumetricWaxGrid` (`static/wax_sdf.js` / `wax_worker.js`), `POST /api/sculpt-and-sim` columnar decoding, `THREE.Clock` playback, scrub snapshots, 5-cell telemetry, and fault/warning badges (`RAPID_COLLISION`, `SHANK_COLLISION`, `SOFT_LIMIT_EXCEEDED`, `STOCK_BOUNDS_EXCEEDED`, `SINGULARITY_HIGH_THETA_DOT`, `UNREACHABLE_UNDERCUT_AREA`, `BLADE_BROADSIDE_FEED`, `GLB_LOAD_FAILED`). |
| `server.py` | `L152-L160, L240-L248` | Update `GET /api/health` to include `max_upload_bytes` and `accepted_formats` (for `upload.js`), add `GET /api/presets`, and ensure static serving (`/` and `/xp.css` or `/static/xp.css`) works cleanly alongside `/vendor` (`three@0.187.0`). |
| `tests/test_upload_js.mjs` | `[NEW]` | Node tests for `limitsFromHealth`, `checkUploadAllowed`, and `uploadSubtitle` in `static/upload.js`. |
| `tests/test_xp_ui_lint.mjs` | `[NEW]` | Node lint tests verifying 6-layer XP DOM, `.transport-dock`, 5 `.status-cell` panes, `ResizeObserver`, `/vendor/` importmap, `CadCarverRig` wiring, Google `DESIGN.md` 8-section order, zero `camera.up.set(0, 0, 1)`, zero `Math.sin`/`Math.cos` in `static/app.js` and `static/cad_rig.js`, and zero Unicode emojis in `static/index.html`, `static/xp.css`, and `static/app.js`. |
| `tests/test_server_ui.py` | `[NEW]` | Python `unittest` verifying `GET /` (`4-DOF Wax Carver Studio 2001`), `GET /static/xp.css` (`.transport-dock`), `GET /api/health` (`max_upload_bytes`, `accepted_formats`), and `GET /api/presets`. |

## 3. Technical & Architectural Boundaries
- **In-Scope Decisions**:
  - **Coordinate & Up-Axis Reconciliation**: Keep `CadCarverRig`'s `+Y`-up camera (`camera.up.set(0, 1, 0)`) and `-90°` X-rotated root group; do NOT copy `wax-robot`'s `camera.up.set(0, 0, 1)`.
  - **Zero Kinematic Trig in JS**: `static/app.js` and `static/cad_rig.js` consume Python `tip_xyz_wax` / `tool_axis_wax` and joint deltas directly.
  - **Google `DESIGN.md` & Emoji-Free Chrome**: Zero Unicode emojis in HTML, CSS `content:`, or JS strings.
- **Hard Exclusions / No-Go**:
  - Do NOT modify `.env`, `.env.*`, or credential files.
  - Do NOT modify `kinematics.py`, `face_sculpt.py`, `toolpath_sim.py`, `tool_model.py`, `scripts/extract_machine.py`, `machine_geometry.json`, `cad_part_roles.json`, `static/models/*.glb`, `static/cad_rig.js`, `static/wax_sdf_core.js`, `static/wax_worker.js`, or `static/wax_sdf.js`.
  - Do NOT introduce unapproved CSS frameworks (Tailwind/Bootstrap) or Node build pipelines.

## 4. Visual & UI Design Specifications
- **Theme**: `Windows XP Luna Studio (4-DOF Wax Carver)` (`DESIGN.md` / `openspec/changes/xp-ui-overhaul/design.md`)
- **Key Tokens**:
  - Desktop: `#3a6ea5` | Surface: `#ece9d8` | Inset/Viewport: `#f0ede0`, `#ffffff`
  - Titlebar Luna Gradient: `#0058ee` $\to$ `#3593ff` $\to$ `#072a8c` (`#ffffff` text)
  - Action Green: `#70c040` $\to$ `#3e8e18` (border `#286010`, `#ffffff` text)
  - Fault / Collision: `#e81123` on `#ffffff` | Warning: `#f59e0b`
  - 3D Materials: Wax `#e8d595` | Target Ghost `#3b82f6` | Metal Rig `#64748b` | Cutter `#f97316`
  - Fonts: `Tahoma, Segoe UI, sans-serif` (`11px`/`12px`); `Courier New, monospace` (`11px`) for telemetry
- **Component Anatomy & States**:
  - **Transport Dock (`.transport-dock`)**: Anchored inside `.inset-well.viewport-well` (`bottom: 8px; left: 8px; right: 8px; z-index: 10`) with emoji-free `Prev`, `Play`/`Pause`, `Next`, `Carve to End`, `#sim-scrubber`, `#sim-time`, `#sim-speed`.
  - **5-Cell Status Bar (`footer.status-bar`)**: `#status-text`, `#status-joints`, `#status-tip`, `#status-feed`, `#status-state` (`.status-badge-collision` on faults).
- **Responsive Layout**:
  - Desktop (`>= 900px`): Horizontal `.window-body` (`320px` sidebar + viewport).
  - Mobile (`< 900px`): Vertical stack, `.mobile-tabs` (`Model`, `Sculpt`, `Sim`), `Machine Detail` defaults to `Tool Only` with touch targets `>= 44px`.

## 5. Test Scaffolding & Verification Commands
- **Primary Test Runners**:
  - Node: `node --test tests/test_upload_js.mjs tests/test_xp_ui_lint.mjs` and `npm run test:node`
  - Python: `.venv/bin/python -m unittest tests.test_server_ui -v` and `.venv/bin/python -m unittest discover -s tests -v`
- **TDD Requirement**: Task group `## 1` MUST scaffold failing unit/lint/API tests before touching implementation code. Verify they fail initially.

## 6. Implementation Task Checklist
- [ ] 1.1 Scaffold failing Node tests in `tests/test_upload_js.mjs` covering `limitsFromHealth`, `checkUploadAllowed`, and `uploadSubtitle`
- [ ] 1.2 Scaffold failing Node lint tests in `tests/test_xp_ui_lint.mjs` asserting 6-layer XP DOM, `.transport-dock`, 5 `.status-cell` panes, `ResizeObserver`, Google `DESIGN.md` 8-section order, absence of `camera.up.set(0, 0, 1)`, zero `Math.sin`/`Math.cos` in `static/app.js`, and zero Unicode emojis in `static/index.html`, `static/xp.css`, and `static/app.js`
- [ ] 1.3 Scaffold failing Python tests in `tests/test_server_ui.py` for `GET /`, `GET /xp.css`, `GET /api/health` (`max_upload_bytes`, `accepted_formats`), and `GET /api/presets`
- [ ] 2.1 Write root `DESIGN.md` following `github.com/google-labs-code/design.md` (via `opensrc`) and validate with `npx @google/design.md lint DESIGN.md` (or schema/contrast check)
- [ ] 2.2 Copy `wax-robot/static/upload.js` and `wax-robot/static/threemf.js` to `static/upload.js` and `static/threemf.js`
- [ ] 2.3 Migrate `wax-robot/static/xp.css` to `static/xp.css`, swapping material tokens (`--wax-stock`, `--target-face-ghost`, `--rig-metal`, `--cutter-hot`) and adding `.transport-dock`, `.transport-btn`, `.transport-scrubber`, `.transport-time`, `.transport-speed`, and `.status-badge-collision` styles
- [ ] 2.4 Migrate `wax-robot/static/index.html` to emoji-free `static/index.html` as `4-DOF Wax Carver Studio 2001` (preserving `/vendor/build/three.module.js` importmap) with facial sculpt sliders, stock/preset & CAD rig controls (`Machine Detail`, `Unassigned Parts`, `Provenance`), `#simulate-button`, `.transport-dock`, 5-cell `.status-bar`, and `#help-dialog`
- [ ] 3.1 Port `wax-robot/static/viewer.js` into `static/app.js` (gallery Three.js scene with `+Y` up, `-90°` X-rotated root, `ResizeObserver`, XP menus/tabs/dialog/window controls, upload/3MF preview, `CadCarverRig` + `< 900px` `Tool Only` default, `POST /api/sculpt-and-sim` columnar decoding, `THREE.Clock` playback, scrub snapshots, 5-cell telemetry, and fault/warning badges including `BLADE_BROADSIDE_FEED` & `GLB_LOAD_FAILED`)
- [ ] 3.2 Update `server.py` so `GET /api/health` advertises `max_upload_bytes` and `accepted_formats`, `GET /api/presets` returns bundled presets, and `StaticFiles(html=True)` mounts at `/` after `/api/*` and `/vendor` routes
- [ ] 4.1 Run `node --test tests/test_upload_js.mjs tests/test_xp_ui_lint.mjs`, `npm run test:node`, `.venv/bin/python -m unittest tests.test_server_ui -v`, and `.venv/bin/python -m unittest discover -s tests -v` and verify clean passes
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate xp-ui-overhaul --strict --json`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix and verbatim execution logs

## 7. Post-Implementation & Verification Obligations
When `spec-coder-sub` finishes:
1. Verify all checkboxes in `tasks.md` are marked `- [x]`. Only tick boxes that genuinely ran and passed.
2. Ensure `openspec/changes/xp-ui-overhaul/verification.md` is populated with:
   - Executive Summary & Environment
   - Requirement Adherence Audit Matrix (mapping every spec scenario to its verifying test)
   - Resolved Assumptions & Empirical Proof
   - Nomenclature & Code Symbol Audit
   - Verbatim Execution Logs
3. Automatically run verification via `openspec-verify-change`.
4. **Open a Pull Request**: Once implementation is complete and `openspec/changes/xp-ui-overhaul/verification.md` is written and verified with zero critical issues:
   - Ensure your work is on a dedicated feature branch (`feat/xp-ui-overhaul`).
   - Stage and commit all implementation code and every artifact within the change directory (`git add openspec/changes/xp-ui-overhaul <implementation-files>`), then push the branch (`git push -u origin HEAD`).
   - Open a Pull Request using `gh pr create --fill` and report the PR URL.

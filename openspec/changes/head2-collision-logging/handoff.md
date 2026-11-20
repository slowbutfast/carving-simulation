# OpenCode Orchestration Handoff: OpenSpec Change 'head2-collision-logging'

You are the orchestration agent for OpenSpec change 'head2-collision-logging' running in OpenCode.
Your primary directive is to execute this change using the **`openspec-apply-sub`** skill, which delegates task implementation to the `spec-coder-sub` subagent.

## 1. Orchestration Directive
- **Change Name**: `head2-collision-logging`
- **Target Skill**: `openspec-apply-sub` (or `/opsx:apply-sub head2-collision-logging`)
- **Architecture Paradigm**: Vertical Slice Architecture (VSA). Maintain strict isolation between feature compartments (`face_sculpt.py` mesh loading, `toolpath_sim.py` collision logging, `wax_sdf_core.js` shared `carveRange` audit, and the separate-commit red wax color change).

## 2. Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `scripts/import_head_mesh.py` | `[NEW]` | CLI converter `<zip_path>`: reads zip in-memory via `zipfile` + trimesh resolver (no `extractall()`), `merge_vertices()`, directed half-edge boundary loop chaining (all 3 loops, `ValueError` on boundary vertex degree > 2), select neck loop by edge count (`14` vs `6`), plain fan-cap ear holes, extrude neck loop via quad wall + flat bottom cap at `z_plinth_mm = 10.0` + `fix_normals()`, `(Z, X, Y)` rotation (`det=+1`), `trimesh.nsphere.minimum_nsphere` XY centering, uniform scale to `max_radius_mm = 32.0`, export `presets/head_2.stl`, `presets/head_2_license.txt`, and `presets/head_2.json` (`sha256` + transform). Reference prototype: `/private/tmp/claude-501/-Users-gregorylazatin-Documents-Dev-global-sandbox-projects-carving-simulation/d2c7cf49-25a4-4f98-b9dd-5cf2f9799d6c/scratchpad/proto_head2.py`. |
| `presets/head_2.stl`, `presets/head_2_license.txt`, `presets/head_2.json` | `[NEW]` | Pre-normalized watertight `head_2` STL, CC-BY-4.0 credit, and provenance/transform sidecar. |
| `machine_config.json` | `L83-L86` | Add `"target_mesh": {"path": "presets/head_2.stl"}` and `"logging": {"collision_log_path": "logs/last_collision_report.json", "max_events_per_code": 200}`. |
| `face_sculpt.py` | `L127-L143`, `L240-L258` | Load `config["target_mesh"]["path"]` when configured (`BASE_STL` only when `target_mesh` is `None`/omitted); resolve `presets/<stem>_landmarks.json` keyed to active mesh path; skip RBF and emit `SCULPT_SLIDERS_IGNORED` info diagnostic when no landmark sidecar exists and sliders are non-zero. |
| `toolpath_sim.py` | `L65-L74`, `L878-L965`, `L1761-L1885` | Add `CollisionEventLog` (run-counted cap `max_events_per_code`, keep deepest `N`, record `truncated`/`dropped`) and `ToolpathResult.collision_events` (`default_factory=list`). Preserve `DiagnosticCollector` and `detect_gouges`; add `detect_gouges_detailed` passing `frame`, `stage`, and joints through `gouge_sample_poses` with `deepest_sample_xyz_wax`, `surface_point_xyz_wax`, and sampled-stride run grouping (`GOUGE_FINISHING_STRIDE=4`, `GOUGE_LINK_STRIDE=50`). Add `BLADE_BROADSIDE_FEED` run grouping, `UNREACHABLE_UNDERCUT_AREA` summaries, and a vectorized `SOFT_LIMIT_EXCEEDED` post-pass over `frames` against `limits`. |
| `server.py` | `L65-L70`, `L194-L238` | Add `presets/`-restricted `mesh_path` on `SimulationRequest` (`422` on traversal), expose `sliders_enabled`, build `collision_log` before trajectory-error `422` checks, write atomically (`tempfile` + `os.replace`) to `config["logging"]["collision_log_path"]`, include `collision_log` in `200` and trajectory-error `422` `detail`, and return `collision_log: null` on non-trajectory `422`s. |
| `static/wax_sdf_core.js` | `[EXPORT]` | Export pure `carveRange(core, poses, rapidFlags, tool, { from, to, auditAll })` returning `{ current, runs, faulted }` (byte-for-byte halt-on-first-fault when `auditAll: false`; grouped `(code, body)` runs with `post_fault: true` after first fault when `auditAll: true`). |
| `scripts/audit_collisions.mjs` | `[NEW]` | CLI `<response_json_path> [--grid N]`: decode base64 columnar trajectory, call `carveRange(..., { auditAll: true })`, output JSON with `gridN`, `voxelSize`, and `runs`. |
| `static/wax_worker.js` | `L111-L175` | Call `carveRange`, include `pose` (`tip`, `axis`, `theta`, plus `previous` for `RAPID_COLLISION`), reset carve to frame `0` when `auditAll` toggles mid-playback, and truncate straddling runs on `restoreNearest`. |
| `static/app.js` | `L335-L365`, `L547-L560`, `L591-L625` | Disable/grey sliders when `sliders_enabled === false`, merge worker collision runs (enriched with `r, theta_deg, h, phi_deg, stage, is_rapid`), add `Audit all collisions` toggle and `Copy JSON` / `Download JSON` buttons. |
| `static/cad_rig.js` | `L25-L35`, `L79-L80` | *(Separate commit)* Change `SCENE_COLORS.wax` to `#b91c1c` and rename `SCENE_COLORS.error` -> `SCENE_COLORS.collision` (`#22d3ee`). |
| `static/wax_sdf.js` | `L19-L24` | *(Separate commit)* Change wax `MeshStandardMaterial` color to `0xb91c1c`. |
| `static/index.html` | `L28-L32`, `L325-L335` | *(Separate commit for `--wax: #b91c1c`)* Add `Audit all collisions` toggle and `Copy JSON` / `Download JSON` buttons in Diagnostics panel. |
| `tests/test_carver_sim.py` | `L424-L495` | Pin `TestFacialSculpting` and `TestSyntheticToolpaths` to `target_mesh=None` (note `TestSimulationAPI` and `TestPatch10APIRegressions` exercise `head_2.stl`); add `TestHead2Target` (`delta=1e-3` invariants, mesh-keyed landmarks, `demo` path + early-return `[]`, `CollisionEventLog` schema/cap/stride grouping, vectorized `SOFT_LIMIT_EXCEEDED`, deterministic patched `422` with temp `collision_log_path`, `mesh_path` traversal). |
| `tests/test_wax_sdf.mjs`, `tests/test_wax_worker.mjs`, `tests/test_cad_rig.mjs` | — | Add tests for `carveRange`, enriched `pose`, `auditAll` runs + `post_fault` + `restoreNearest` truncation + toggle reset, and `SCENE_COLORS.wax` / `SCENE_COLORS.collision`. |

## 3. Technical & Architectural Boundaries
- **Expected Baseline on `head_2` (`preset="demo"`)**: `~96,268` frames, `0` error diagnostics, `~28.5%` `UNREACHABLE_UNDERCUT_AREA`, and an `~8.85 mm` `GOUGE` warning at `[3.7, -12.7, 52.6]`. **Do NOT modify the mesh or toolpath algorithm to eliminate this `GOUGE`**—it is the expected baseline test case for `CollisionEventLog`.
- **Hard Exclusions / No-Go**:
  - Do NOT modify `machine_geometry.json`, `static/models/*.glb`, or `assets/`.
  - Do NOT modify `DiagnosticCollector` (`kinematics.py`) or `detect_gouges` return type.
  - Do NOT introduce `networkx` or other unapproved external dependencies.
  - Do NOT use `zipfile.extractall()` on untrusted archives.
  - Do NOT port `WaxSDFCore` to Python.

## 4. Visual & UI Design Specifications
- **Theme**: Dark Studio (`static/index.html`)
- **Key Tokens (separate commit)**:
  - Wax: `#b91c1c` (`SCENE_COLORS.wax`, `VolumetricWaxGrid` material `0xb91c1c`, CSS `--wax`)
  - Tool Collision Highlight: `SCENE_COLORS.collision = '#22d3ee'` (`cad_rig.js:34,79-80`, high-contrast cyan against red wax)
- **Diagnostics Controls**: `Audit all collisions` checkbox + `Copy JSON` / `Download JSON` buttons; greyed-out facial sliders when `sliders_enabled === false`.

## 5. Test Scaffolding & Verification Commands
- **Python Test Runner**: `.venv/bin/python -m unittest discover -s tests -v`
- **Node Test Runner**: `npm run test:node`
- **Headless Audit**: `node scripts/audit_collisions.mjs <response_json_path> --grid 128`
- **TDD Requirement**: Task group `## 1` MUST scaffold failing unit/integration tests before touching implementation code. Verify they fail initially.

## 6. Implementation Task Checklist
- [ ] 1.1 Pin `TestFacialSculpting` and `TestSyntheticToolpaths` in `tests/test_carver_sim.py` to `target_mesh=None` (noting `TestSimulationAPI` and `TestPatch10APIRegressions` exercise `head_2.stl` via `server.py`).
- [ ] 1.2 Add failing `TestHead2Target` tests in `tests/test_carver_sim.py` for `presets/head_2.stl` geometry invariants (`delta=1e-3`), mesh-keyed landmarks + `SCULPT_SLIDERS_IGNORED` + `sliders_enabled`, `demo` path generation (including early-return `collision_events == []`), `CollisionEventLog` schema + deepest-N run cap + sampled-stride grouping, vectorized `SOFT_LIMIT_EXCEEDED` logging, deterministic patched `422` atomic `collision_log` (with temp `collision_log_path` override and `null` on non-trajectory `422`s), and `mesh_path` traversal rejection.
- [ ] 1.3 Add failing Node tests in `tests/test_wax_sdf.mjs`, `tests/test_wax_worker.mjs`, and `tests/test_cad_rig.mjs` for `carveRange`, enriched collision `pose`, `auditAll` run grouping + `post_fault` + `restoreNearest` run truncation + mid-playback toggle reset, and `SCENE_COLORS.wax` / `SCENE_COLORS.collision`.
- [ ] 2.1 Implement `scripts/import_head_mesh.py <zip_path>`: safe in-memory `zipfile` + trimesh load, `merge_vertices()`, directed half-edge boundary loop chaining (all 3 loops, `ValueError` on boundary vertex degree > 2), select neck loop by edge count (`14` vs `6`), plain fan-cap ear holes, extrude neck loop via quad wall + flat bottom cap at `z_plinth_mm = 10.0` + `fix_normals()`, `(Z, X, Y)` rotation, `trimesh.nsphere.minimum_nsphere` XY centering, uniform scale to `max_radius_mm = 32.0`, export `presets/head_2.stl`, `presets/head_2_license.txt`, and `presets/head_2.json` (source `sha256` + transform params).
- [ ] 2.2 Run `scripts/import_head_mesh.py /Users/gregorylazatin/Downloads/head_2.zip` to generate and commit `presets/head_2.stl`, `presets/head_2_license.txt`, and `presets/head_2.json`.
- [ ] 2.3 Update `machine_config.json` (`target_mesh.path = "presets/head_2.stl"` + `logging`) and `face_sculpt.py` (`load_base_head`, `load_landmarks` keyed to `presets/<stem>_landmarks.json`, `apply_facial_modifications` skipping RBF and emitting `SCULPT_SLIDERS_IGNORED` when no landmark sidecar exists).
- [ ] 3.1 Add `CollisionEventLog` (deepest-N run cap `max_events_per_code` with `truncated`/`dropped`) and `ToolpathResult.collision_events` (`default_factory=list`) in `toolpath_sim.py`; keep `DiagnosticCollector` and `detect_gouges` return type unchanged; add `detect_gouges_detailed` passing `frame`, `stage`, and joints through `gouge_sample_poses` with `deepest_sample_xyz_wax`, `surface_point_xyz_wax`, and sampled-stride run grouping (`GOUGE_FINISHING_STRIDE=4`, `GOUGE_LINK_STRIDE=50`).
- [ ] 3.2 Add `BLADE_BROADSIDE_FEED` run grouping, `UNREACHABLE_UNDERCUT_AREA` angle/z/theta summaries, and a vectorized `SOFT_LIMIT_EXCEEDED` post-pass over `frames` against `limits` inside `toolpath_sim.py`.
- [ ] 3.3 Update `server.py`: add `presets/`-restricted `mesh_path` on `SimulationRequest`, expose `sliders_enabled`, build `collision_log` before trajectory-error `422` checks, write atomically (`tempfile` + `os.replace`) to `config["logging"]["collision_log_path"]`, include `collision_log` in `200` and trajectory-error `422` `detail`, and return `collision_log: null` on non-trajectory `422`s.
- [ ] 4.0 Extract `carveRange(core, poses, rapidFlags, tool, { from, to, auditAll })` into `static/wax_sdf_core.js` returning `{ current, runs, faulted }`.
- [ ] 4.1 Update `static/wax_worker.js` to call `carveRange`, include `pose` on collision events, reset carve to frame `0` when `auditAll` is toggled mid-playback, and truncate straddling runs on `restoreNearest`.
- [ ] 4.2 Update `static/app.js` and `static/index.html` to disable/grey sliders when `sliders_enabled === false`, merge worker collision runs (enriched with `r, theta_deg, h, phi_deg, stage, is_rapid`), add `Audit all collisions` toggle, and add `Copy JSON` / `Download JSON` buttons.
- [ ] 4.3 Create `scripts/audit_collisions.mjs <response_json_path> [--grid N]` decoding base64 columnar trajectory, calling `carveRange(..., { auditAll: true })`, and outputting JSON with `gridN`, `voxelSize`, and `runs`.
- [ ] 5.1 Update `SCENE_COLORS.wax` (`static/cad_rig.js:26`), `VolumetricWaxGrid` material (`static/wax_sdf.js:20`), and `--wax` (`static/index.html:29`) to `#b91c1c`, and rename `SCENE_COLORS.error` -> `SCENE_COLORS.collision` (`#22d3ee`) in `static/cad_rig.js:34,79-80`.
- [ ] 6.1 Run `.venv/bin/python -m unittest discover -s tests -v` and `npm run test:node` and confirm all non-skipped tests pass.
- [ ] 6.2 Run `POST /api/sculpt-and-sim` (`demo`) and `node scripts/audit_collisions.mjs /tmp/sim.json --grid 128`, verify `logs/last_collision_report.json`, and record results in `verification.md`.

## 7. Post-Implementation & Verification Obligations
When `spec-coder-sub` finishes:
1. Verify all checkboxes in `tasks.md` are marked `- [x]`.
2. Populate `openspec/changes/head2-collision-logging/verification.md` with verbatim test outputs and schema audit.
3. Run `openspec-verify-change` and sync specs if clean.

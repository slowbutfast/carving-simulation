## 1. Test Scaffolding (TDD)

- [x] 1.1 Pin `TestFacialSculpting` and `TestSyntheticToolpaths` in `tests/test_carver_sim.py` to `target_mesh=None` (noting `TestSimulationAPI` and `TestPatch10APIRegressions` exercise `head_2.stl` via `server.py`).
- [x] 1.2 Add failing `TestHead2Target` tests in `tests/test_carver_sim.py` for `presets/head_2.stl` geometry invariants (`delta=1e-3`), mesh-keyed landmarks + `SCULPT_SLIDERS_IGNORED` + `sliders_enabled`, `demo` path generation (including early-return `collision_events == []`), `CollisionEventLog` schema + deepest-N run cap + sampled-stride grouping, vectorized `SOFT_LIMIT_EXCEEDED` logging, deterministic patched `422` atomic `collision_log` (with temp `collision_log_path` override and `null` on non-trajectory `422`s), and `mesh_path` traversal rejection.
- [x] 1.3 Add failing Node tests in `tests/test_wax_sdf.mjs`, `tests/test_wax_worker.mjs`, and `tests/test_cad_rig.mjs` for `carveRange`, enriched collision `pose`, `auditAll` run grouping + `post_fault` + `restoreNearest` run truncation + mid-playback toggle reset, and `SCENE_COLORS.wax` / `SCENE_COLORS.collision`.

## 2. Pre-Normalized `head_2` Target Mesh & Mesh-Keyed Landmarks

- [x] 2.1 Implement `scripts/import_head_mesh.py <zip_path>`: safe in-memory `zipfile` + trimesh load (no `extractall`), `merge_vertices()`, directed half-edge boundary loop chaining (all 3 loops, `ValueError` on boundary vertex degree > 2), select neck loop by edge count (`14` vs `6`), plain fan-cap ear holes, extrude neck loop via quad wall + flat bottom cap at `z_plinth_mm = 10.0` + `fix_normals()`, `(Z, X, Y)` rotation, `trimesh.nsphere.minimum_nsphere` XY centering, uniform scale to `max_radius_mm = 32.0`, export `presets/head_2.stl`, `presets/head_2_license.txt`, and `presets/head_2.json` (source `sha256` + transform params). Reference prototype: `/private/tmp/claude-501/-Users-gregorylazatin-Documents-Dev-global-sandbox-projects-carving-simulation/d2c7cf49-25a4-4f98-b9dd-5cf2f9799d6c/scratchpad/proto_head2.py`.
- [x] 2.2 Run `scripts/import_head_mesh.py /Users/gregorylazatin/Downloads/head_2.zip` to generate and commit `presets/head_2.stl`, `presets/head_2_license.txt`, and `presets/head_2.json`.
- [x] 2.3 Update `machine_config.json` (`target_mesh.path = "presets/head_2.stl"` + `logging`) and `face_sculpt.py` (`load_base_head`, `load_landmarks` keyed to `presets/<stem>_landmarks.json`, `apply_facial_modifications` skipping RBF and emitting `SCULPT_SLIDERS_IGNORED` when no landmark sidecar exists).

## 3. Backend `CollisionEventLog` & Atomic Reporting

- [x] 3.1 Add `CollisionEventLog` (deepest-N run cap `max_events_per_code` with `truncated`/`dropped`) and `ToolpathResult.collision_events` (`default_factory=list`) in `toolpath_sim.py`; keep `DiagnosticCollector` and `detect_gouges` return type unchanged; add `detect_gouges_detailed` passing `frame`, `stage`, and joints through `gouge_sample_poses` with `deepest_sample_xyz_wax`, `surface_point_xyz_wax`, and sampled-stride run grouping (`GOUGE_FINISHING_STRIDE=4`, `GOUGE_LINK_STRIDE=50`).
- [x] 3.2 Add `BLADE_BROADSIDE_FEED` run grouping, `UNREACHABLE_UNDERCUT_AREA` angle/z/theta summaries, and a vectorized `SOFT_LIMIT_EXCEEDED` post-pass over `frames` against `limits` inside `toolpath_sim.py`.
- [x] 3.3 Update `server.py`: add `presets/`-restricted `mesh_path` on `SimulationRequest`, expose `sliders_enabled`, build `collision_log` before trajectory-error `422` checks, write atomically (`tempfile` + `os.replace`) to `config["logging"]["collision_log_path"]`, include `collision_log` in `200` and trajectory-error `422` `detail`, and return `collision_log: null` on non-trajectory `422`s.

## 4. Shared `carveRange`, Worker Audit Mode & Headless CLI Script

- [x] 4.0 Extract `carveRange(core, poses, rapidFlags, tool, { from, to, auditAll })` into `static/wax_sdf_core.js` returning `{ current, runs, faulted }` (preserving byte-for-byte halt-on-first-fault when `auditAll: false`, grouping contiguous `(code, body)` runs with `post_fault: true` after first fault when `auditAll: true`).
- [x] 4.1 Update `static/wax_worker.js` to call `carveRange`, include `pose` on collision events, reset carve to frame `0` when `auditAll` is toggled mid-playback, and truncate straddling runs on `restoreNearest`.
- [~] 4.2 Update `static/app.js` and `static/index.html` to disable/grey sliders when `sliders_enabled === false`, merge worker collision runs (enriched with `r, theta_deg, h, phi_deg, stage, is_rapid`), add `Audit all collisions` toggle, and add `Copy JSON` / `Download JSON` buttons. — implemented and statically verified (ids, handlers, CSS, `sliders_enabled` API contract); a rendered browser check needs a human because Chromium cannot start in this container (`No usable sandbox!`). See verification.md §5.
- [x] 4.3 Create `scripts/audit_collisions.mjs <response_json_path> [--grid N]` decoding base64 columnar trajectory, calling `carveRange(..., { auditAll: true })`, and outputting JSON with `gridN`, `voxelSize`, and `runs`.

## 5. Red Wax Color & High-Contrast Highlight (Separate Commit)

- [x] 5.1 Update `SCENE_COLORS.wax` (`static/cad_rig.js:26`), `VolumetricWaxGrid` material (`static/wax_sdf.js:20`), and `--wax` (`static/index.html:29`) to `#b91c1c`, and rename `SCENE_COLORS.error` -> `SCENE_COLORS.collision` (`#22d3ee`) in `static/cad_rig.js:34,79-80`.

## 6. Verification

- [x] 6.1 Run `.venv/bin/python -m unittest discover -s tests -v` and `npm run test:node` and confirm all non-skipped tests pass. — **All green: 124 Python tests discovered, 120 pass / 4 skip / 0 fail; Node 32 pass / 1 skip / 0 fail.** `npm run test:node` completed in one green run. The single-process discovery run was executed four times and is OOM-killed by this shared 12 GiB container at `TestSyntheticToolpaths.test_standard_preset_produces_denser_path` (the densest path in the suite, a pre-existing test); that class passes on its own (11/11, 712 s) and the remaining modules were run separately (40 pass / 4 skip). No failure or error was observed in any run. See `verification.md` §1 and §6.
- [x] 6.2 Run `POST /api/sculpt-and-sim` (`demo`) and `node scripts/audit_collisions.mjs /tmp/sim.json --grid 128`, verify `logs/last_collision_report.json`, and record results in `verification.md`. — HTTP 200 in 218 s, 96,141 frames, 250 collision events; on-disk report equals the response (`verification.md` §5).

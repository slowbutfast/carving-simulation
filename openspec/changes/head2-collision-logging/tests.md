# Tests: `head2-collision-logging`

## Automated Test Suites
- **Python unit & integration tests**:
  ```bash
  .venv/bin/python -m unittest discover -s tests -v
  ```
  - `TestFacialSculpting` and `TestSyntheticToolpaths` pin `target_mesh=None` (ellipsoid `presets/base_head.stl`). Note: `TestSimulationAPI` and `TestPatch10APIRegressions` call `server.py` (`load_config()`) and exercise `head_2.stl`.
  - New `TestHead2Target` tests:
    - `presets/head_2.stl` watertightness, consistent winding, positive volume, flat base (`abs(min_z - 10.0) < 1e-3`), `max_r <= 32.0 + 1e-3`.
    - Mesh-keyed landmarks (`presets/<stem>_landmarks.json`): `head_2.stl` disables sliders (`sliders_enabled: false`, `SCULPT_SLIDERS_IGNORED` on non-zero sliders), while `mesh_path: "base_head.stl"` keeps sliders enabled.
    - `generate_synthetic_carve_path` on `head_2.stl` with `preset="demo"` succeeds with zero fatal errors, populates `collision_events`, and early-return `ToolpathResult` paths have `collision_events == []`.
    - `CollisionEventLog` schema, deepest-N run cap (`max_events_per_code` + `truncated`/`dropped`), vectorized `SOFT_LIMIT_EXCEEDED` frame logging, and sampled-stride run grouping (`GOUGE` stride 4 / 50).
    - Deterministic `422` test: patch `toolpath_sim.generate_synthetic_carve_path` to return a `ToolpathResult` with an error diagnostic + events, override `logging.collision_log_path` to a temp path, and verify `collision_log` is written atomically and included in `detail` (while non-trajectory `422`s return `collision_log: null`).
    - `mesh_path` traversal outside `presets/` rejected with `422`.
- **Node unit tests**:
  ```bash
  npm run test:node
  ```
  - New cases in `tests/test_wax_sdf.mjs`, `tests/test_wax_worker.mjs`, `tests/test_cad_rig.mjs`:
    - `carveRange` with `auditAll: false` preserves halt-on-first-fault; `auditAll: true` groups contiguous runs and marks `post_fault: true`.
    - Worker collision message includes `pose`; `restoreNearest` truncates straddling runs; toggling `auditAll` resets carve to frame `0`.
    - `SCENE_COLORS.wax === '#b91c1c'` and `SCENE_COLORS.collision === '#22d3ee'`.
- **Headless CLI audit verification**:
  ```bash
  node scripts/audit_collisions.mjs /tmp/sim.json --grid 128
  ```

## Manual Verification
- Open `http://127.0.0.1:8000` in a WebGL browser, confirm red wax stock (`#b91c1c`) + `head_2` target mesh, disabled facial sliders, cyan tool highlight (`#22d3ee`) on `SHANK_COLLISION`, toggle `Audit all collisions`, and test `Copy JSON` / `Download JSON`.

## ADDED Requirements

### Requirement: Pre-normalized default target head mesh (`head_2`) with mesh-keyed landmarks
`face_sculpt.load_base_head(config)` SHALL resolve the active mesh from `config["target_mesh"]["path"]` (`presets/head_2.stl` by default in `machine_config.json`) when `target_mesh` is configured, and SHALL fall back to `presets/base_head.stl` only when `target_mesh` is `None` or omitted. `face_sculpt.load_landmarks` SHALL resolve the landmark sidecar `presets/<stem>_landmarks.json` keyed to the resolved mesh path (not `config.target_mesh.landmarks`). When no landmark sidecar exists for the active mesh, `apply_facial_modifications` SHALL skip RBF deformation cleanly with zero displacement, emit an info diagnostic `SCULPT_SLIDERS_IGNORED` if any slider is non-zero, and `server.py` SHALL return `sliders_enabled: false`. `presets/head_2.stl` SHALL be watertight, consistently wound, have positive volume, fit within `max_radius_mm = 32.0 + 1e-3`, and have a flat extruded neck-wall base seated at `z_plinth_mm` (`10.0 ± 1e-3`).

#### Scenario: `head_2.stl` is watertight, flat-seated, and within stock bounds
- **WHEN** `face_sculpt.load_base_head(kinematics.load_config())` is called
- **THEN** the returned mesh is `is_watertight`, `is_winding_consistent`, has `volume > 0`, `abs(min_z - z_plinth_mm) < 1e-3`, and `max_r <= 32.0 + 1e-3`

#### Scenario: Ellipsoid tests remain pinned to `base_head.stl` while API tests exercise `head_2.stl`
- **WHEN** `config` sets `target_mesh = None`
- **THEN** `load_base_head(config)` loads `presets/base_head.stl` and `presets/base_head_landmarks.json`
- **AND** `TestSimulationAPI` / `TestPatch10APIRegressions` calling `server.py` exercise the configured default `head_2.stl`

#### Scenario: Non-zero sliders on a mesh without landmarks emit `SCULPT_SLIDERS_IGNORED`
- **WHEN** `apply_facial_modifications` or `POST /api/sculpt-and-sim` runs on `head_2.stl` (no `head_2_landmarks.json`) with `{"nose": 0.8}`
- **THEN** `sliders_enabled` is `false`, displacement is `0.0`, and an info diagnostic `SCULPT_SLIDERS_IGNORED` is emitted

#### Scenario: `head_2` generates the expected baseline `demo` toolpath with zero errors
- **WHEN** `toolpath_sim.generate_synthetic_carve_path(head2_mesh, config, preset="demo")` is called
- **THEN** it completes with non-empty frames, zero `error`-severity diagnostics, and produces the expected baseline `GOUGE` and `UNREACHABLE_UNDERCUT_AREA` warnings

### Requirement: Structured, run-grouped backend `CollisionEventLog`
`toolpath_sim.generate_synthetic_carve_path` SHALL populate `ToolpathResult.collision_events` (default `[]` on early-return paths) via `CollisionEventLog` without altering `DiagnosticCollector` deduplication or `detect_gouges` return type. Events SHALL be capped per code in **runs** (`max_events_per_code: 200`), keeping the deepest/worst `N` runs and recording `truncated: true, dropped: k` on overflow:
- `GOUGE` events SHALL group consecutive **sampled** frames (accounting for `GOUGE_FINISHING_STRIDE = 4` and `GOUGE_LINK_STRIDE = 50`) and include `frame_range`, `stage`, worst-frame `joints` (`r_mm`, `theta_deg`, `h_mm`, `phi_deg`), `pose` (`tip_xyz_wax`, `tool_axis_wax`), `deepest_sample_xyz_wax`, `surface_point_xyz_wax`, `depth_mm`, and `excess_mm`.
- `BLADE_BROADSIDE_FEED` events SHALL group contiguous broadside cutting frames with `frame_range`, `stage`, and `length_mm`.
- `UNREACHABLE_UNDERCUT_AREA` SHALL emit summary angle/z/theta ranges.
- `SOFT_LIMIT_EXCEEDED` SHALL be collected via a vectorized post-pass over `frames` against `limits` inside `toolpath_sim.py`.

`server.py` SHALL handle the four HTTP `422` paths explicitly:
- Tool/stock config validation, sculpt fatal (`STOCK_BOUNDS_EXCEEDED`), and `FrameCapExceededError` SHALL include `collision_log: null` in `detail`.
- Trajectory errors (`SOFT_LIMIT_EXCEEDED`, etc.) SHALL build `collision_log` before raising `422`, write it atomically (`tempfile` + `os.replace`) to `config["logging"]["collision_log_path"]`, and include `collision_log` in `detail` (just as `200` responses do). `SimulationRequest.mesh_path` SHALL be restricted to `presets/` (returning HTTP `422` on path traversal).

#### Scenario: `collision_log` is written atomically on 200 and trajectory-error 422
- **WHEN** `POST /api/sculpt-and-sim` completes or raises `422` from trajectory errors (with `logging.collision_log_path` overridable to a temp path in tests)
- **THEN** `collision_log` is present in the response/detail and written atomically to the configured path
- **AND** non-trajectory `422` responses return `collision_log: null`

#### Scenario: `mesh_path` rejects path traversal outside `presets/`
- **WHEN** `POST /api/sculpt-and-sim` receives `mesh_path: "../machine_config.json"`
- **THEN** the server rejects the request with HTTP `422`

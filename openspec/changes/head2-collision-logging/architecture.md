# Architecture: `head2-collision-logging`

## System Components & Seams

### 1. Target Mesh Pipeline (`scripts/import_head_mesh.py`, `presets/head_2.*`, `face_sculpt.py`)
- **Offline import (`scripts/import_head_mesh.py <zip_path>`)**:
  - Takes `<zip_path>` as a CLI argument (never hardcodes Downloads). Reads in-memory via `zipfile.ZipFile` + trimesh resolver (never `extractall()`).
  - Merges duplicate glTF vertices (`merge_vertices()`).
  - Caps all 3 open boundary loops via **directed half-edge chaining**: builds directed boundary half-edges `(u, v)` whose reverse `(v, u)` is absent; raises `ValueError` if any boundary vertex has degree > 2.
  - Picks the neck loop by edge count (`14` edges vs `6` for the two ear holes). Plain fan-caps the ear holes; for the neck loop, adds a new ring at `z_plinth_mm` connected by a **quad wall** (~12 mm at the back of the neck) and fan-caps that bottom ring, then calls `fix_normals()`.
  - Applies `det = +1` rotation `(Z_gltf, X_gltf, Y_gltf)` -> `(+X forward, +Z up)`.
  - Centers XY using `trimesh.nsphere.minimum_nsphere` on the XY points (no new dependency), scales uniformly to `max_radius_mm = 32.0`, and seats `min_z` at `z_plinth_mm = 10.0`.
  - Exports `presets/head_2.stl`, `presets/head_2_license.txt`, and `presets/head_2.json` sidecar (source `sha256` + transform parameters: `rotation`, `center`, `scale`, `z_plinth_mm`).
- **Mesh-keyed landmarks & runtime loading (`face_sculpt.py`)**:
  - `load_base_head(config)` resolves the mesh path from `config["target_mesh"]["path"]` (or `BASE_STL` when `target_mesh` is `None`/omitted).
  - `load_landmarks(config, mesh_path=...)` resolves the sidecar `presets/<stem>_landmarks.json` for the active mesh path. Its existence determines `sliders_enabled`.
  - `apply_facial_modifications` skips RBF deformation when no landmarks sidecar exists; if any slider value is non-zero, it emits an info diagnostic `SCULPT_SLIDERS_IGNORED`.
- **API contract (`server.py`)**:
  - `SimulationRequest.mesh_path` (optional) is resolved relative to `ROOT / "presets"` and rejected with HTTP `422` on path traversal.
  - Response includes `sliders_enabled: bool` so `static/app.js` can disable/grey out sliders when `false`.

### 2. Backend Collision Event Log (`toolpath_sim.py`, `server.py`)
- `DiagnosticCollector` in `kinematics.py` is **untouched** (preserves `code:axis` deduplication).
- `CollisionEventLog` in `toolpath_sim.py` stores structured runs capped at `max_events_per_code` (default `200`, counted in **runs**). On overflow, it keeps the **deepest/worst** `N` runs and records `truncated: true, dropped: k` per code:
  - **`GOUGE`**: `detect_gouges_detailed` passes `frame`, `stage`, and `(r, theta_s, h, phi)` through `gouge_sample_poses`. Consecutive **sampled** frames (accounting for `GOUGE_FINISHING_STRIDE = 4` and `GOUGE_LINK_STRIDE = 50`) are grouped into `frame_range: [start, end]`, recording `deepest_sample_xyz_wax`, `surface_point_xyz_wax` (`mesh.nearest.on_surface`), `depth_mm`, `excess_mm`, and worst-frame `joints` + `pose`.
  - **`BLADE_BROADSIDE_FEED`**: Contiguous cutting frames classified `broadside` are grouped into `frame_range` runs with `stage`, `length_mm`, and sample `joints`/`pose`.
  - **`UNREACHABLE_UNDERCUT_AREA`**: Emits summary event with count, `z_range_mm`, `theta_deg_range`, and `required_phi_deg_range` vs `phi_limits_deg`.
  - **`SOFT_LIMIT_EXCEEDED`**: Collected via a **vectorized post-pass over `frames` against `limits`** inside `toolpath_sim.py` (since `kinematics.build_trajectory` already dedupes its diagnostics).
- Early-return paths in `toolpath_sim.py` (`L1800`) return `ToolpathResult` with `collision_events=[]` (`field(default_factory=list)`).
- **`422` paths in `server.py`**:
  - Tool/stock config validation, sculpt fatal (`STOCK_BOUNDS_EXCEEDED`), and `FrameCapExceededError` have no trajectory and return `collision_log: null` in `detail`.
  - Trajectory errors (`SOFT_LIMIT_EXCEEDED`, etc.) build `collision_log` **before** raising `422`, write it atomically (`tempfile` + `os.replace`) to `config["logging"]["collision_log_path"]` (overridable for tests), and include `collision_log` in `detail`.

### 3. Shared `carveRange`, Worker Audit & Headless CLI (`static/wax_sdf_core.js`, `static/wax_worker.js`, `scripts/audit_collisions.mjs`)
- **`carveRange` in `static/wax_sdf_core.js`**: Exported pure function `carveRange(core, poses, rapidFlags, tool, { from, to, auditAll })` returning `{ current, runs, faulted }`.
  - `auditAll: false` (default): byte-for-byte identical halt-on-first-fault behavior.
  - `auditAll: true`: groups contiguous `(code, body)` collisions into runs (`frame_range`, `code`, `body`, `worst_sdf_mm`, `worst_frame`, `pose`, `post_fault`), marking all runs after the first fault with `post_fault: true` without halting.
- **`static/wax_worker.js`**: Calls `carveRange`. Includes `pose: { tip, axis, theta }` (`previous` for `RAPID_COLLISION`). Toggling `auditAll` mid-playback resets the carve to frame `0`. `restoreNearest` **truncates** runs straddling the restore index and drops runs starting after it.
- **`scripts/audit_collisions.mjs`**: Takes `<response_json_path>` as CLI arg and `--grid <N>` (default `128`), decodes base64 columnar `trajectory`, calls `carveRange(..., { auditAll: true })`, and prints JSON with `gridN`, `voxelSize`, and grouped `runs`.

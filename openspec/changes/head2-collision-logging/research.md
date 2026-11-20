# Research: `head2-collision-logging`

## Verified Facts (Measured)
- **Source archive**: `/Users/gregorylazatin/Downloads/head_2.zip` (`scene.gltf`, `scene.bin`, `license.txt` CC-BY-4.0 by Joao G via Sketchfab).
- **Prototype script**: `/private/tmp/claude-501/-Users-gregorylazatin-Documents-Dev-global-sandbox-projects-carving-simulation/d2c7cf49-25a4-4f98-b9dd-5cf2f9799d6c/scratchpad/proto_head2.py` (working reference for directed half-edge capping, quad-wall neck extrusion, and scaling).
- **Raw mesh topology**: `406` raw glTF vertices -> `118` unique vertices after `merge_vertices()`, `204` faces, `winding = True`, `watertight = False`.
- **Open boundaries**: `26` boundary edges forming **3 closed loops**:
  - 14-edge neck opening (tilted ~22°, glTF normal `~(0, 0.93, 0.37)`).
  - Two 6-edge ear openings at `x ≈ ±273`.
  - All 3 loops are nearly planar (smallest spread ~1% of the others), so centroid fan triangulation caps them cleanly.
- **`trimesh.fill_holes()` limitation**: Requires `networkx`, which is not in `requirements.txt`. Directed half-edge chaining with reversed boundary-edge winding caps all 3 loops in pure NumPy without adding dependencies.
- **Coordinate transform & fit**:
  - glTF is `+Y` up, `+Z` forward (`mid-face +Z max: 365.33`, `-Z min: -283.18`).
  - Machine/wax frame is `+Z` up, `+X` forward (`det = +1` rotation: `(X_wax, Y_wax, Z_wax) = (Z_gltf, X_gltf, Y_gltf)`).
  - Scaling to `max_radius_mm = 32.0` gives scale `≈ 0.088`, height `~77 mm`, `z ∈ [10.0, 87.0]` (comfortably inside `R_stock_mm - finish_allowance_mm = 38.5 mm` and `H_stock_mm = 120.0 mm`).

## Prototype Toolpath Baseline (`preset="demo"`)
Measured by running the prototype `head_2` (capped, extruded flat neck wall, `r = 32.0 mm`) through `generate_synthetic_carve_path(preset="demo")`:

| Metric | Ellipsoid (`base_head.stl`) | `head_2` (prototype) |
| :--- | :--- | :--- |
| Frames | `84,800` | `96,268` |
| Generation time | `50 s` | `64 s` |
| `UNREACHABLE_UNDERCUT_AREA` | `17.0%` | **`28.5%`** |
| `GOUGE` | none | **`8.85 mm`** at `[3.7, -12.7, 52.6]` |
| `BLADE_BROADSIDE_FEED` | `13.8%` | `13.0%` |
| Error diagnostics | `0` | `0` |

> [!IMPORTANT]
> **Expected Baseline:** The `8.85 mm` `GOUGE` warning and `28.5%` `UNREACHABLE_UNDERCUT_AREA` on `head_2` are the **expected baseline** (and a ready-made first test case for the collision log). Do **NOT** modify the mesh or toolpath algorithm to make the `GOUGE` go away.

## Existing Codebase & Diagnostic Gaps
- **Landmarks**: `presets/base_head_landmarks.json` positions (`nose: [23, 0, 50]`, `chin: [18, 0, 22]`, `face_sculpt.py:72`) were placed for the ellipsoid. Landmarks must be resolved as a sidecar keyed to the mesh (`presets/<stem>_landmarks.json`), not solely from `config.target_mesh.landmarks`, so `mesh_path` per-request overrides work consistently.
- **API tests**: `TestSimulationAPI` and `TestPatch10APIRegressions` call `server.py` (which calls `kinematics.load_config()`), so they will exercise `head_2.stl` once it is the default in `machine_config.json`.
- **Diagnostics**:
  - `DiagnosticCollector` (`kinematics.py:96-135`) deduplicates by `code:axis` and drops per-frame details; `kinematics.build_trajectory` returns already-deduped `SOFT_LIMIT_EXCEEDED` diagnostics.
  - `detect_gouges` (`toolpath_sim.py:911-964`) keeps only the single deepest `samples[index]`; poses are sampled at `GOUGE_FINISHING_STRIDE = 4` and `GOUGE_LINK_STRIDE = 50` (`toolpath_sim.py:874-875`).
  - `carveForward` in `static/wax_worker.js:124-175` is a module-state closure; extracting `carveRange` to `static/wax_sdf_core.js` lets both the worker and `scripts/audit_collisions.mjs` share one implementation.
  - `SCENE_COLORS.error` in `static/cad_rig.js:34` is only used for the tool collision highlight (`cad_rig.js:79-80`).

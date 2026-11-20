# Proposal: `head2-collision-logging`

## Motivation
Debugging 4-DOF thermal CNC G-code / toolpath generation requires:
1. A realistic, repeatable default head mesh (`presets/head_2.stl`) committed in-repo so local runs and CI test the same geometry without depending on `/Users/.../Downloads`.
2. In-depth, structured collision and toolpath diagnostic logging (`CollisionEventLog` + shared `carveRange` JS SDF audit + headless Node script) so agents debugging toolpath algorithms receive exact frame ranges, joint coordinates `(r, theta_deg, h, phi_deg)`, poses, and contact geometry—even when `POST /api/sculpt-and-sim` returns HTTP `422` on trajectory errors.
3. Red default wax (`#b91c1c`) with a high-contrast cyan tool collision highlight (`SCENE_COLORS.collision = '#22d3ee'`) in a separate commit.

## Summary of Changes
1. **Pre-normalized `presets/head_2.stl`**: Add `scripts/import_head_mesh.py <zip_path>` to convert `head_2.zip` into a watertight, flat-extruded-base `presets/head_2.stl`, `presets/head_2_license.txt`, and `presets/head_2.json` metadata sidecar. Key facial landmarks to `presets/<stem>_landmarks.json` per mesh, emit `SCULPT_SLIDERS_IGNORED` + `sliders_enabled: false` when absent, and pin ellipsoid unit test classes to `target_mesh=None`.
2. **Backend `CollisionEventLog`**: Preserve `DiagnosticCollector` and `detect_gouges` contracts while adding `CollisionEventLog` (capped at `200` runs per code keeping deepest, with `truncated`/`dropped` metadata, vectorized `SOFT_LIMIT_EXCEEDED` post-pass, and sampled-stride `GOUGE` grouping). Write `logs/last_collision_report.json` atomically (`tempfile` + `os.replace`) before trajectory-error `422` raises, and return `collision_log: null` on non-trajectory `422`s.
3. **Shared `carveRange` & Headless Audit**: Extract `carveRange` into `static/wax_sdf_core.js` so `static/wax_worker.js` and `scripts/audit_collisions.mjs <response.json> [--grid N]` share one SDF loop. Support `auditAll` run grouping (`post_fault: true` after first fault, `restoreNearest` run truncation, mid-playback toggle reset to frame `0`) and UI `Copy JSON` / `Download JSON`.
4. **Red Wax & Cyan Collision Highlight (separate commit)**: Update wax to `#b91c1c` and rename `SCENE_COLORS.error` -> `SCENE_COLORS.collision` (`#22d3ee`).

## Non-Goals
- Porting the JS volumetric SDF (`WaxSDFCore`) to Python.
- Implementing connected-component gravity drop-off in the voxel grid.
- Modifying `machine_geometry.json`, `static/models/*.glb`, or `assets/`.

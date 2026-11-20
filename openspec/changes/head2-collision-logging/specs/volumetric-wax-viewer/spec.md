## ADDED Requirements

### Requirement: Shared `carveRange` SDF loop, worker audit runs, and headless Node audit
`static/wax_sdf_core.js` SHALL export a pure function `carveRange(core, poses, rapidFlags, tool, { from, to, auditAll })` returning `{ current, runs, faulted }` so `static/wax_worker.js` and `scripts/audit_collisions.mjs` share one implementation:
- With `auditAll: false` (default), halt-on-first-fault behavior SHALL remain byte-for-byte unchanged.
- With `auditAll: true`, `carveRange` SHALL group contiguous `(code, body)` collisions into runs (`frame_range`, `code`, `body`, `worst_sdf_mm`, `worst_frame`, `pose`, `post_fault`) and mark runs after the first fault with `post_fault: true` without halting.
- In `static/wax_worker.js`, collision messages SHALL include `pose` (`tip`, `axis`, `theta`, plus `previous` for `RAPID_COLLISION`); toggling `auditAll` mid-playback SHALL reset the carve to frame `0`; `restoreNearest` SHALL truncate runs straddling the restore index and drop runs starting after it.
- `scripts/audit_collisions.mjs <response_json_path> [--grid N]` SHALL decode the base64 columnar trajectory, run `carveRange(..., { auditAll: true })`, and output JSON including `gridN`, `voxelSize`, and `runs`.

#### Scenario: `auditAll` groups consecutive shank collisions, marks `post_fault`, and truncates on `restoreNearest`
- **WHEN** a trajectory triggers `SHANK_COLLISION` across multiple consecutive frames with `auditAll: true`
- **THEN** `carveRange` emits grouped runs with `post_fault: true` after the first fault
- **AND** `restoreNearest` truncates any run straddling the restore index

### Requirement: Red default wax color with high-contrast collision highlight
Default wax material color (`SCENE_COLORS.wax`, `VolumetricWaxGrid` material, CSS `--wax`) SHALL be `#b91c1c`, and `SCENE_COLORS.error` SHALL be renamed to `SCENE_COLORS.collision` (`#22d3ee`, high-contrast cyan) in `static/cad_rig.js` (`L34`, `L79-80`).

#### Scenario: Wax and collision highlight colors are distinct
- **WHEN** `SCENE_COLORS` is inspected
- **THEN** `SCENE_COLORS.wax === '#b91c1c'` and `SCENE_COLORS.collision === '#22d3ee'`

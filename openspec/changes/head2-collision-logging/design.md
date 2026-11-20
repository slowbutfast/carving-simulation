# Design: `head2-collision-logging`

## Visual & UI Design Tokens (Separate Commit)
- **Theme**: Dark Studio (`static/index.html`)
- **Wax Material Color**:
  - `SCENE_COLORS.wax` (`static/cad_rig.js:26`): `#b91c1c` (deep carving-wax red)
  - `VolumetricWaxGrid` material (`static/wax_sdf.js:20`): `0xb91c1c`
  - CSS `--wax` (`static/index.html:29`): `#b91c1c`
- **Tool Collision Highlight Token**:
  - Rename `SCENE_COLORS.error` -> `SCENE_COLORS.collision` (`static/cad_rig.js:34`, `L79-80`) and set to `#22d3ee` (high-contrast cyan against `#b91c1c` red wax, accessible for red-green colorblind viewers).
  - UI `.badge.error` CSS remains `#ef4444` on dark slate.

## Diagnostics & Slider UX (`static/index.html`, `static/app.js`)
- **Slider disable state**: When API response has `sliders_enabled === false`, disable/grey out facial slider inputs in `app.js` with a clear tooltip/hint.
- **Diagnostics Header Controls**:
  - Checkbox toggle: `Audit all collisions` (toggling resets carve to frame `0` and runs worker with `auditAll: true`).
  - Action buttons: `Copy JSON` and `Download JSON` (exports merged `state.collisionLog` containing backend `collision_log` + worker collision runs enriched with `r, theta_deg, h, phi_deg, stage, is_rapid`).

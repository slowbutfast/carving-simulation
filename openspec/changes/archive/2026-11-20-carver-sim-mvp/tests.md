## Automated Tests

- `python -m unittest tests.test_carver_sim -v`:
  - **Forward Kinematics Algebraic, Sign & Calibration Fixture**: Verifies `forward_kinematics` reproduces $(\theta_s, r_s, z_s)$, `tip_xyz_wax`, and `tool_axis_wax` within $10^{-5}\text{ mm}$ across $\phi = 0^\circ$, $\phi = 90^\circ$ ($r_s = r - x - p$, $z_s = h - h_2$), and $+\phi$ inward sign; includes a `±1.0 mm` calibration fixture test (skipped/tagged pending physical hardware pose measurements).
  - **Undercut IK Round-Trip, $\phi$-Policy & Soft Limits**: Verifies `FK(IK(target, normal, config)) == target` within $10^{-5}\text{ mm}$, `PHI_POLICY_CLAMPED` info diagnostic when ideal $\phi$ exceeds `phi_limits_deg`, tangential-normal fallback to $\phi = 0^\circ$, and `SOFT_LIMIT_EXCEEDED` with axis name and value when $(r, h, \phi, \theta)$ exceeds bounds.
  - **Relative Tip Speed, Timing & Singularity**: Verifies `v_tip` equals $\sqrt{\dot{r}_s^2 + (r_s \dot{\theta}_s)^2 + \dot{z}_s^2}$ for both pure $\theta$ rotation and combined $(r, \theta, h, \phi)$ motion with $\phi \ne 0^\circ$ (with unwrapped $\theta$), and verifies `SINGULARITY_HIGH_THETA_DOT` is emitted when $r_s < r_{s,\min}$ and $|\dot{\theta}_s| > \dot{\theta}_{\text{warn}}$.
  - **Watertight, Non-Self-Intersecting Facial Deformation**: Verifies `apply_facial_modifications` outputs a closed, positive-volume, non-self-intersecting mesh bounded within $(R_{\text{stock}} - \text{finish\_allowance\_mm}, H_{\text{stock}})$, and returns `STOCK_BOUNDS_EXCEEDED` when exceeded.
  - **Shadow Roughing, Undercut Finishing & Engaged-Length Sampling**: Verifies `generate_synthetic_carve_path` produces shadow-clipped roughing, $\phi$-tilted finishing with `UNREACHABLE_UNDERCUT_AREA` / `GOUGE` diagnostics, safe-by-construction `is_rapid` retracts, and $\Delta s_{\max} \le 0.5 \cdot \text{tip\_width}$ along the full engaged cone $L_{\text{tip}}$ with continuous unwrapped $\theta$.
  - **API Endpoint Contract**: Verifies `GET /api/health` and `POST /api/sculpt-and-sim` (`preset="demo"`) return HTTP 200 with decodable base64 `Float32Array`/`Uint8Array` columnar trajectory buffers and structured diagnostics.
- `node --test tests/test_wax_sdf.mjs`:
  - **Volumetric Undercut Carving & Chunk Boundary Seams**: Verifies a $\phi$-tilted segment across a `16³` chunk boundary subtracts SDF voxels beneath an overhang without collapsing upper voxels (`sdf < 0` within `1e-3`), marks both touched and adjacent neighbor chunks dirty, and generates seam-free MC triangles.
  - **Current-Stock Rapid & Shank Collisions**: Verifies `is_rapid` through carved voxels passes, `is_rapid` into uncarved voxels raises `RAPID_COLLISION`, and unheated shank intersection $[L_{\text{tip}}, L_{\text{tip}} + L_{\text{shank}}]$ during cutting raises `SHANK_COLLISION` (`sdf < -0.5 * voxel_size`).
  - **Snapshot Scrubbing & Zero-Trig Guard**: Verifies SDF snapshot restore + replay matches sequential subtraction, and asserts `static/machine_rig.js` / `static/app.js` contain no kinematic `Math.sin`/`Math.cos` calls.
  - **Carved Surface Fidelity**: Verifies end-of-trajectory SDF zero-isosurface approximates reachable target points within `2.0 * voxel_size`.

## Manual Verification

- **Interactive Sculpt & Undercut Carve Loop**:
  - **WHEN** the user adjusts facial sliders (`nose`, `brow`, `chin`), selects `Demo` or `Standard`, clicks **Sculpt & Simulate**, and presses **Play** (or **Scrub** / **Carve to End**)
  - **THEN** the primitive 4-DOF rig tracks the sampled trajectory smoothly at $\ge 30\text{ FPS}$ inside the `-90°` X-rotated Three.js world, `VolumetricWaxGrid` carves visible facial contours and nose/chin undercuts in `wax_worker.js`, and `RAPID_COLLISION` / `SHANK_COLLISION` do not trigger on valid roughing/finishing passes.

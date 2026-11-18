## 1. Test Scaffolding (TDD)

- [ ] 1.1 Scaffold failing tests in `tests/test_carver_sim.py` for 4-DOF FK algebraic/sign verification ($\phi = 0^\circ, 90^\circ$, `tip_xyz_wax`, `tool_axis_wax`), IK round-trip + `PHI_POLICY_CLAMPED` + tangential-normal fallback, `SOFT_LIMIT_EXCEEDED`, and a pending-hardware `±1.0 mm` calibration fixture
- [ ] 1.2 Scaffold failing tests for relative tip speed (`v_tip` on pure $\theta$ rotation and combined $(r, \theta, h, \phi)$ motion with $\phi \ne 0^\circ$ and unwrapped $\theta$), timing model, and `SINGULARITY_HIGH_THETA_DOT`
- [ ] 1.3 Scaffold failing tests for watertight, non-self-intersecting parametric facial deformation (`apply_facial_modifications`) bounded inside $(R_{\text{stock}} - \text{finish\_allowance\_mm}, H_{\text{stock}})$ and `STOCK_BOUNDS_EXCEEDED`
- [ ] 1.4 Scaffold failing tests for shadow-clipped roughing, $r$–$Z$ undercut finishing (`UNREACHABLE_UNDERCUT_AREA`, `GOUGE`), engaged-length resampling ($\Delta s_{\max} \le 0.5 \cdot \text{tip\_width}$), and `POST /api/sculpt-and-sim` columnar base64 payload contract
- [ ] 1.5 Scaffold failing Node tests in `tests/test_wax_sdf.mjs` for `wax_sdf_core.js`: undercut subtraction across `16³` chunk boundaries + dirty neighbors, `RAPID_COLLISION`, `SHANK_COLLISION`, snapshot scrub replay, surface fidelity, and zero-trig JS lint

## 2. Backend Kinematics, Sculpting & Synthetic Toolpaths

- [ ] 2.1 Create `machine_config.json` (datums, `pivot_to_tip_mm`, conical-bevel + shank profile, `melt_kerf_mm`, stock/plinth defaults, feeds, per-axis `v_max`, singularity thresholds, soft limits) and `package.json` (pinning Node `>=20` and Three.js)
- [ ] 2.2 Implement `kinematics.py` with Python-only FK/IK (`tip_xyz_wax`, `tool_axis_wax`, $r$–$Z$ normal projection, `PHI_POLICY_CLAMPED`, `SOFT_LIMIT_EXCEEDED`), segment timing, relative $v_{\text{tip}}$, and `SINGULARITY_HIGH_THETA_DOT`
- [ ] 2.3 Procedurally generate watertight `presets/base_head.stl` + `presets/base_head_landmarks.json` and implement `face_sculpt.py` (`cKDTree` RBF/Gaussian normal deformations, non-self-intersection guard, `STOCK_BOUNDS_EXCEEDED`)
- [ ] 2.4 Implement `toolpath_sim.py` Stage 1: shadow-aware cylindrical roughing ($\phi = 0^\circ$) with safe-by-construction `is_rapid` retracts
- [ ] 2.5 Implement `toolpath_sim.py` Stage 2: 2D $r$–$Z$ slice undercut finishing, $\phi$ selection, CC$\to$CL offset, `UNREACHABLE_UNDERCUT_AREA` / `GOUGE` diagnostics, engaged-length resampling, and `demo`/`standard` presets
- [ ] 2.6 Implement `server.py` (FastAPI) exposing `GET /api/health`, `POST /api/sculpt-and-sim` (columnar base64 `Float32Array`/`Uint8Array` buffers, `max_frames` cap), and static file serving

## 3. Three.js Primitive Rig & Volumetric SDF Wax Viewer

- [ ] 3.1 Run SDF performance benchmark spike measuring `128³` conical-bevel subtraction + `16³` dirty-chunk Marching Cubes remesh time to verify $\ge 30\text{ FPS}$ budget
- [ ] 3.2 Implement `static/machine_rig.js` (`PrimitiveCarverRig` inside `-90°` X-rotated root group, driven solely by backend poses with zero JS trig)
- [ ] 3.3 Implement `static/wax_sdf_core.js` (pure JS exact cylinder SDF + exterior padding, conical-bevel subtraction, `16³` chunks with 1-voxel apron + neighbor dirtying + global gradient normals, `RAPID_COLLISION`, `SHANK_COLLISION`, and snapshots)
- [ ] 3.4 Implement `static/wax_worker.js` and `static/wax_sdf.js` (Web Worker with transferable chunk mesh buffers and Three.js `BufferGeometry` adapter)
- [ ] 3.5 Implement `static/index.html` and `static/app.js` with facial sliders, `Demo`/`Standard` preset, `THREE.Clock` loop, transport bar (`Play/Pause`, `Scrub`, `1x–20x`, `Carve to End`), fault auto-pause, and live telemetry

## 4. Verification & Empirical Audit

- [ ] 4.1 Run full Python (`python -m unittest discover -s tests -v`) and Node (`node --test tests/test_wax_sdf.mjs`) test suites and verify clean passes
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate carver-sim-mvp --strict`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix, resolved assumptions, hardware calibration fixture status, and verbatim execution logs

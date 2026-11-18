## 1. Test Scaffolding (TDD)

- [ ] 1.1 Scaffold failing tests in `tests/test_carver_sim.py` for measured-pose 4-DOF forward kinematics (`forward_kinematics`) and soft-limit rejection (`SOFT_LIMIT_EXCEEDED`)
- [ ] 1.2 Scaffold failing tests for relative tip speed (`v_tip` including $r_s \dot{\theta}$) and $r_s \to 0$ singularity detection (`SINGULARITY_HIGH_THETA_DOT`)
- [ ] 1.3 Scaffold failing tests for watertight parametric facial deformation (`apply_facial_modifications`) bounded inside $(R_{\text{stock}}, H_{\text{stock}})$
- [ ] 1.4 Scaffold failing tests for distance-sampled synthetic 4-DOF trajectory generation (`generate_synthetic_carve_path`, $\Delta s \le 0.5 \cdot \text{tip\_width}$) and `POST /api/sculpt-and-sim`
- [ ] 1.5 Scaffold failing Node tests in `tests/test_wax_sdf.mjs` for volumetric SDF undercut subtraction and current-stock `RAPID_COLLISION` detection

## 2. Backend Kinematics, Sculpting & Synthetic Toolpaths

- [ ] 2.1 Create `machine_config.json` defining turntable origin, `pivot_to_tip_mm`, `arm_radial_offset_mm`, `arm_to_pivot_z_mm`, conical-bevel dimensions, `melt_kerf_mm`, and soft limits
- [ ] 2.2 Implement `kinematics.py` with Python-only FK/IK ($\phi$-selection policy for undercuts), relative $v_{\text{tip}}$, soft-limit validation, and singularity checks
- [ ] 2.3 Add watertight base head preset (`presets/base_head.stl`) and implement `face_sculpt.py` using `scipy.spatial.cKDTree` RBF/Gaussian facial deformations
- [ ] 2.4 Implement `toolpath_sim.py` generating distance-sampled cylindrical roughing and $\phi$-undercut finishing frames
- [ ] 2.5 Implement `server.py` (FastAPI) exposing `GET /api/health`, `POST /api/sculpt-and-sim`, and static file serving

## 3. Three.js Primitive Rig & Volumetric SDF Wax Viewer

- [ ] 3.1 Implement `static/machine_rig.js` (`PrimitiveCarverRig`) rendering the platter, Z-column, radial arm, $\phi$ wrist pivot in the $r$–$Z$ plane, and conical-bevel tip driven solely by backend poses
- [ ] 3.2 Implement `static/wax_sdf.js` (`VolumetricWaxGrid`) with chunked 3D SDF + Marching Cubes, swept conical-bevel + `melt_kerf_mm` subtraction, and current-stock `RAPID_COLLISION` detection
- [ ] 3.3 Implement `static/index.html` and `static/app.js` with facial modification sliders, `THREE.Clock` animation loop, transport bar (`Play/Pause`, `Scrub`, `1x–20x`), and live telemetry readout

## 4. Verification & Empirical Audit

- [ ] 4.1 Run full Python (`python -m unittest discover -s tests -v`) and Node (`node --test tests/test_wax_sdf.mjs`) test suites and verify clean passes
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate carver-sim-mvp --strict`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix, resolved assumptions, and verbatim execution logs

## Automated Tests

- `python -m unittest tests.test_carver_sim -v`:
  - **Measured-Pose FK Calibration**: Verifies `forward_kinematics` reproduces reference `(r, theta, h, phi) -> (r_s, theta_s, z_s)` poses within $10^{-5}\text{ mm}$ across $\phi = 0$ and $\phi \ne 0$.
  - **Soft-Limit & Unreachable Pose Rejection**: Verifies `SOFT_LIMIT_EXCEEDED` is returned with axis name and value when $r$, $h$, or $\phi$ exceeds configured bounds.
  - **Relative Tip Speed & Singularity**: Verifies `v_tip` equals $|r_s \dot{\theta}|$ during pure turntable rotation and `SINGULARITY_HIGH_THETA_DOT` is emitted near $r_s \to 0$.
  - **Watertight Facial Deformation**: Verifies `apply_facial_modifications` outputs a closed, positive-volume mesh bounded within $(R_{\text{stock}}, H_{\text{stock}})$.
  - **Swept Distance Sampling**: Verifies `generate_synthetic_carve_path` maintains $\Delta s \le 0.5 \cdot \text{tip\_width}$ and continuous unwrapped $\theta$.
  - **API Endpoint Contract**: Verifies `POST /api/sculpt-and-sim` returns valid JSON trajectory frames and diagnostics.
- `node --test tests/test_wax_sdf.mjs`:
  - **Volumetric Undercut Carving**: Verifies a $\phi$-tilted segment subtracts SDF voxels beneath an overhang without collapsing upper voxels.
  - **Current-Stock Rapid Collision**: Verifies `is_rapid` through previously carved SDF voxels passes, while `is_rapid` into uncarved voxels raises `RAPID_COLLISION`.

## Manual Verification

- **Interactive Sculpt & Undercut Carve Loop**:
  - **WHEN** the user adjusts facial sliders (`nose`, `brow`, `chin`), clicks **Sculpt & Simulate**, and presses **Play**
  - **THEN** the primitive 4-DOF rig tracks the sampled trajectory smoothly at interactive FPS, `VolumetricWaxGrid` carves visible facial contours and nose/chin undercuts, and `RAPID_COLLISION` does not trigger on valid roughing/finishing retracts.

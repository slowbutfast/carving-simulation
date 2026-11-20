## Why

We need an interactive, verifiable 3D simulation of the custom **4-DOF Cylindrical Thermal CNC Wax Carver** before investing in physical controller G-code post-processing or hardware trials. Specifically, the simulator must let us load or modify a 3D face mesh inside a cylindrical wax blank, generate synthetic 4-DOF trajectories (including $\phi$ wrist-pitch moves for facial undercuts), and watch the machine kinematically carve the wax in real time.

## What Changes

Build the v1 **Carver Simulation MVP (`carver-sim-mvp`)**:
- **Single-Source-of-Truth Kinematics (`kinematics.py`, `machine_config.json`)**:
  - Define right-handed turntable coordinates (`mm`, `+Z` up) and configurable physical parameters (`pivot_to_tip_mm`, `arm_radial_offset_mm`, `arm_to_pivot_z_mm`, conical-bevel tip geometry, `melt_kerf_mm`, soft limits).
  - Implement 4-DOF forward kinematics, inverse kinematics with an explicit $\phi$-selection policy for undercuts, relative tip speed $v_{\text{tip}}$ (including $r_s\dot{\theta}$), and $r_s \to 0$ singularity detection.
- **Parametric Facial Modification (`face_sculpt.py`)**:
  - Apply smooth `scipy.spatial.cKDTree` RBF/Gaussian normal deformations to a base head mesh (nose, brow, cheeks, jaw, chin) while preserving watertightness inside the cylindrical wax stock.
- **Synthetic 4-DOF Toolpath Generator (`toolpath_sim.py`, `server.py`)**:
  - Generate distance-sampled roughing and $\phi$-undercut finishing trajectories `(t, r, theta, h, phi, r_s, theta_s, z_s, v_tip, is_rapid, tip_xyz_wax, tool_axis_wax)` directly from the sculpted face mesh—deferring real controller G-code dialects to a future change.
- **Three.js Primitive Rig & Volumetric Undercut Carving (`static/`)**:
  - Render a primitive 4-DOF machine rig (`PrimitiveCarverRig`) driven exclusively by backend-sampled poses (zero trig in JS).
  - Simulate wax removal using a **3D Volumetric SDF + Chunked Marching Cubes** grid (`VolumetricWaxGrid` in a Web Worker) with swept-distance subtraction and current-stock `is_rapid` / `SHANK_COLLISION` checks.

## Capabilities

### New Capabilities
- `carver-kinematics`: 4-DOF cylindrical FK/IK, configurable machine geometry/datums, soft-limit validation, relative tip velocity $v_{\text{tip}}$, and $r_s \to 0$ singularity diagnostics.
- `face-sculpt-sim`: Watertight RBF facial feature deformation and synthetic undercut-capable 4-DOF toolpath sampling.
- `volumetric-wax-viewer`: Three.js primitive machine rig, playback transport controls, chunked 3D SDF Marching Cubes wax removal (supporting undercuts), and current-stock collision diagnostics.

## Impact

- **New:** `machine_config.json`, `package.json`, `kinematics.py`, `face_sculpt.py`, `toolpath_sim.py`, `server.py`, `presets/base_head.stl`, `presets/base_head_landmarks.json`, `static/index.html`, `static/app.js`, `static/machine_rig.js`, `static/wax_sdf_core.js`, `static/wax_sdf.js`, `static/wax_worker.js`, `tests/test_carver_sim.py`, `tests/test_wax_sdf.mjs`.
- **Reused:** `mesh_formats.py` (`load_3mf`), `requirements.txt`.
- **Deferred (Subsequent Changes):** Real controller G-code dialect post-processor (`G93`/`G94` `.gcode` export), CAD `.glb` visual skinning, and physical limit-switch homing animation.

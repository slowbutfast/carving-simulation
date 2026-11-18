# Carving Simulation — 4-DOF Thermal CNC Wax Carver Digital Twin

Interactive 3D kinematic, facial-sculpting, and volumetric material-removal simulator for a custom **4-DOF Cylindrical Thermal CNC Wax Carver** (heated conical-bevel T12 tip, rotary turntable, vertical leadscrew gantry, radial belt carriage, and wrist pitch joint $\phi$).

## Planned Architecture
- **Backend (`Python` / `FastAPI`)**:
  - `machine_config.json`: Physical datums, dimensions (`pivot_to_tip_mm`, `arm_radial_offset_mm`, `arm_to_pivot_z_mm`), conical-bevel profile, `melt_kerf_mm`, and soft travel limits.
  - `kinematics.py`: Single-source-of-truth 4-DOF forward/inverse kinematics ($\theta_s, r_s, z_s$) and singularity/limit diagnostics.
  - `face_sculpt.py`: Smooth `scipy.spatial.cKDTree` RBF/Gaussian facial modifications on a base head mesh inside cylindrical wax stock bounds.
  - `toolpath_sim.py`: Synthetic 4-DOF roughing + undercut-capable finishing trajectory generator sampled by swept distance.
- **Frontend (`Three.js`)**:
  - `PrimitiveCarverRig` (Phase 1) $\to$ `GlbSkinRig` (Phase 3 CAD `.glb` skin).
  - `VolumetricWaxGrid` (chunked 3D SDF + Marching Cubes) supporting $\phi$-axis undercuts and current-stock `G0` rapid collision checks.

See [`HANDOFF.md`](HANDOFF.md) for the complete architectural specification and implementation prompt.

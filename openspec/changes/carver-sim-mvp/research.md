## Source material

**2026-11-17, project owner (machine specification & simulation goals):**
- Custom **4-DOF Cylindrical Thermal CNC Wax Carver**:
  - Rotary platter/ring ($\theta$, NEMA 17 + GT2 timing belt),
  - Vertical leadscrew gantry ($h$, dual linear guide rails),
  - Radial horizontal carriage ($r$ / $x$ offset, GT2 belt on aluminum extrusion),
  - Wrist pitch joint ($\phi$) tilting the soldering iron in the radial–vertical ($r$–$Z$) plane.
- **Thermal End-Effector**: Heated soldering iron tip; for simulation, modeled as a **conical-bevel** tip (`T12-BC` / conical bevel) at a constant controlled setpoint temperature, removing carving wax (melting point $50^\circ\text{C}\text{–}80^\circ\text{C}$) geometrically with a `melt_kerf_mm` offset.
- **v1 Scope Decisions**:
  - Use **simulated/synthetic joint-space toolpaths** generated from a modified face mesh (real controller G-code dialect/post-processing deferred to a subsequent change).
  - Support **undercuts** (under nose, brow, chin) via a **volumetric SDF + Marching Cubes** stock representation rather than a 2.5D cylindrical heightfield.
  - Use a **Three.js primitive rig** in v1 before skinning with an exported CAD `.glb`.

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| Turntable Frame | Right-handed cylindrical/Cartesian frame (`mm`, `+Z` up) centered on the platter top surface (`0, 0, 0`), with `theta = 0` along `+X` | Arbitrary CAD assembly origin |
| `pivot_to_tip_mm` (`p`) | Exact distance from wrist pitch axis $\phi$ to the conical-bevel tip | Assumed equal to half of iron length $S/2$ without measurement |
| Relative Tip Speed ($v_{\text{tip}}$) | $\sqrt{\dot{r}_s^2 + (r_s\dot{\theta})^2 + \dot{z}_s^2}$ including turntable tangential speed | Joint-only speed without $r_s\dot{\theta}$ |
| Synthetic Toolpath | Distance-sampled joint-space frames `(t, r, theta, h, phi, r_s, theta_s, z_s, v_tip, is_rapid)` | Controller-specific `G93`/`G94` dialect file |
| Volumetric Wax SDF | 3D signed-distance voxel grid updated along swept distance steps and meshed via chunked Marching Cubes | 2.5D radial heightfield `r(theta, z)` (which cannot represent undercuts) |

## Candidate tech

| Option | Decision | Reason |
| :--- | :--- | :--- |
| **Python-only FK/IK (`kinematics.py`)** | Adopted | Single source of truth; avoids JS/Python trig drift and integrates cleanly with `unittest` |
| **Three.js Primitive Rig $\to$ `.glb` Skin** | Adopted | Unblocks kinematics, sculpting, and carving immediately without waiting on CAD pivot exports |
| **3D Volumetric SDF + Chunked Marching Cubes (`wax_sdf.js`)** | Adopted | Required to visibly carve $\phi$-axis facial undercuts and detect crashes against *current* carved stock |
| **2.5D Cylindrical Heightfield** | Rejected | Cannot represent overhangs/undercuts, defeating the purpose of the 4th DOF ($\phi$) |
| **Transient Lumped Thermal PDE** | Deferred | Constant setpoint + geometric `melt_kerf_mm` is verifiable and fast for v1 |

## Verified facts

| Claim | Value | How verified | Date |
| :--- | :--- | :--- | :--- |
| Starter dependencies available | `numpy`, `scipy`, `trimesh`, `manifold3d`, `fastapi`, `uvicorn`, `python-multipart` | Read `requirements.txt` | 2026-11-17 |
| Reusable mesh I/O present | `mesh_formats.py` supports `.stl`, `.obj`, `.3mf` validation and loading | Copied and verified in repo root | 2026-11-17 |
| Forward kinematics equations | $\theta_s = \theta$, $r_s = r - x - p\sin(\phi)$, $z_s = h - p\cos(\phi) - h_2$ | Machine technical explainer | 2026-11-17 |

## Unverified assumptions

| Assumption | Confidence | How to verify |
| :--- | :--- | :--- |
| `pivot_to_tip_mm` equals `0.5 * S` | Low–Medium | Measure on physical hardware / CAD; keep configurable in `machine_config.json` |
| Axis soft travel limits (`r`, `h`, `phi`) | Medium | Measure physical limit-switch spans on hardware; test via measured-pose FK harness |
| Chunked `128³` SDF Marching Cubes sustains interactive FPS on desktop WebGL | Medium–High | Benchmark incremental dirty-chunk remeshing during swept subtraction |

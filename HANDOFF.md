# Project Handoff Prompt: 4-DOF Thermal CNC Wax Carver & Face-Sculpt Simulator

You are building **`carving-simulation`**: an interactive 3D kinematic, facial-sculpting, and volumetric material-removal simulator for a custom **4-DOF Cylindrical Thermal CNC Wax Carver**.

This repository already contains starter boilerplate (`requirements.txt`, `requirements-dev.txt`, `mesh_formats.py` for `.stl`/`.obj`/`.3mf` parsing, and `.gitignore`). Follow the exact specifications, coordinate conventions, and phased plan below.

---

## 1. Machine & Physical Context

### Mechanical Architecture (4-DOF Cylindrical Thermal Carver)
- **Axis 1 / Axis 2 ($\theta$ — Rotary Turntable / Ring)**: Central platter and/or outer ring track driven by NEMA 17 steppers + GT2 timing belts.
- **Axis 3 ($h$ — Vertical Gantry Column)**: Standard leadscrew + dual linear guide rails lifting the horizontal radial arm.
- **Axis 4 ($r$ — Horizontal Radial Arm)**: Extruded aluminum arm with GT2 belt drive translating the wrist carriage radially.
- **4th DOF ($\phi$ — Wrist Pitch Joint)**: Articulated mount at the tip of the radial arm pitching the soldering iron in the radial–vertical ($r$–$Z$) plane.
- **Thermal End-Effector**: Heated soldering iron with a **conical-bevel tip** (e.g., Hakko T12-BC/conical bevel; *not* a spinning milling bit). Carving wax melts around $50^\circ\text{C}\text{–}80^\circ\text{C}$ while the iron runs at a constant controlled setpoint. For v1, model thermal removal geometrically via the **conical-bevel envelope + `melt_kerf_mm` offset** (deferring transient thermal PDEs).

### Coordinate Conventions & Kinematics (Single Source of Truth in Python)
Define all machine coordinates in a **right-handed turntable frame** (`mm`, `+Z` up):
- **Origin `(0, 0, 0)`**: Center of the central rotary platter's top surface.
- **`theta = 0` (`+X`)**: Home direction from turntable center toward the Z-column / radial gantry.
- **Wrist Pitch (`phi`)**: `phi = 0` points the conical-bevel tip straight down (`-Z`). Positive `+phi` tilts the tip inward toward `-r` in the radial–vertical (`r–Z`) plane (rotating around the local tangent axis, *not* global Y after platter/ring rotation).
- **Forward Kinematics (`kinematics.py`)**:
  $$\theta_s = \theta, \quad r_s = r - x - p \sin(\phi), \quad z_s = h - p \cos(\phi) - h_2$$
  where:
  - `p = pivot_to_tip_mm` (configurable in `machine_config.json`; initial guess `0.5 * S`, never hardcode `S/2` without config override),
  - `x = arm_radial_offset_mm`,
  - `h2 = arm_to_pivot_z_mm`.
- **Relative Tip Speed** (crucial for dwell/feed diagnostics):
  $$v_{\text{tip}} = \sqrt{\dot{r}_s^2 + (r_s \dot{\theta})^2 + \dot{z}_s^2}$$
  Must include the platter tangential velocity $r_s \dot{\theta}$ so a moving platter is never misreported as dwelling.
- **Single Source of Truth**: Python (`kinematics.py`) owns **all** FK/IK math. The API returns pre-sampled time-stamped frames `(t, r, theta, h, phi, r_s, theta_s, z_s, v_tip, is_rapid)`. Three.js **must never** duplicate trig equations.

---

## 2. Core Design Decisions & Guardrails

1. **Simulated / Synthetic Toolpaths for v1**:
   - Real controller G-code dialects (GRBL/FluidNC/Klipper `G93` vs `G94`) are deferred to a subsequent change.
   - For v1, `toolpath_sim.py` generates **synthetic joint-space trajectories** `(r, theta, h, phi)` directly from the sculpted face mesh—compiling `(r_s, theta_s, z_s)` targets through IK with an explicit **$\phi$-selection policy** (e.g., surface-normal alignment clamped to `phi_limits_deg` to reach facial undercuts).
   - `G1`-equivalent segments interpolate linearly in **joint space**; flag singularities when $r_s \to 0$ (high $\dot{\theta}$ sensitivity).
2. **Undercut-Capable Volumetric Wax Stock (Not 2.5D Heightmap)**:
   - Use a **3D Volumetric SDF / Voxel Grid + Chunked Marching Cubes** (`static/wax_sdf.js`) initialized to a cylindrical wax blank $(R_{\text{stock}}, H_{\text{stock}})$.
   - Why: A 2.5D cylindrical heightmap `r(theta, z)` cannot represent undercuts under the nose, brow, or chin—which is the primary reason the machine has a $\phi$ wrist axis.
3. **Distance-Sampled Swept Subtraction & Current-Stock Collisions**:
   - Sample swept tip subtraction **by Euclidean/tip distance** ($\Delta s \le 0.5 \cdot \text{tip\_width}$), never by fixed frame time, to avoid ridges on fast moves.
   - Check rapid (`is_rapid=True`) moves, iron shank, and radial arm bounding volumes against the **current** carved SDF stock (not the initial cylinder, so rapids through already-carved pockets are not falsely flagged).
4. **Primitive Rig First, `.glb` Skin Later**:
   - Build Phase 1 with a **Three.js primitive stick-figure rig** (cylinder platter, column, radial arm box, wrist pivot, conical-bevel tip) driven by `machine_config.json`.
   - Add `.glb` skinning (`GLTFLoader` with explicit `scale`, `up_axis`, and pivot-group reparenting) in Phase 3 without blocking kinematics or carving.

---

## 3. Target Module Architecture

| File | Responsibility |
| :--- | :--- |
| `machine_config.json` | Physical dimensions (`scale`, `up_axis`, `pivot_to_tip_mm`, `arm_radial_offset_mm`, `arm_to_pivot_z_mm`), conical-bevel tip dimensions, `melt_kerf_mm`, and soft limits (`r_limits`, `h_limits`, `phi_limits_deg`). |
| `kinematics.py` | `CarverGeometry`, `forward_kinematics`, `inverse_kinematics_with_policy`, soft-limit validation, and $r_s \to 0$ singularity detection. |
| `face_sculpt.py` | Parametric facial feature deformation (`apply_facial_modifications`) using `scipy.spatial.cKDTree` + smooth RBF/Gaussian normal displacement on a base head mesh, verifying watertightness and stock fit. |
| `toolpath_sim.py` | `generate_synthetic_carve_path` (cylindrical roughing from $R_{\text{stock}}$ + helical/undercut finishing) + distance-sampled frame emitter. |
| `server.py` | FastAPI backend (`POST /api/sculpt-and-sim`, `GET /api/health`, static mount) reusing `mesh_formats.py`. |
| `static/index.html` & `static/app.js` | Three.js viewport (`OrbitControls`, `THREE.Clock` animation loop), facial modification sliders, transport bar (`Play/Pause`, `Scrub`, `1x–20x`), and live `(r, theta, h, phi)` / `(r_s, theta_s, z_s, v_tip)` readout. |
| `static/machine_rig.js` | `PrimitiveCarverRig` (Phase 1) and `GlbSkinRig` (Phase 3) consuming API-sampled joint poses. |
| `static/wax_sdf.js` | `VolumetricWaxGrid` (chunked 3D SDF + Marching Cubes) subtracting the swept conical-bevel + `melt_kerf_mm` volume and checking current-stock rapid/shank collisions. |
| `tests/test_carver_sim.py` | Unit & geometry test suite (see §5). |

---

## 4. Phased Implementation Plan

### Phase 1: Kinematics, Face Sculpting & Primitive Rig Playback
1. Create `machine_config.json` and `kinematics.py` (Python-only FK/IK + soft limits + singularity checks).
2. Create `face_sculpt.py` + bundle/generate a watertight cylindrical-ready base head mesh (`presets/base_head.stl`).
3. Create `toolpath_sim.py` generating synthetic roughing + $\phi$-undercut finishing frames.
4. Build `server.py` (`POST /api/sculpt-and-sim`) and `static/` UI with `PrimitiveCarverRig` + `THREE.Clock` transport scrubber.

### Phase 2: Volumetric SDF Wax Carving & Current-Stock Collisions
1. Implement `VolumetricWaxGrid` in `static/wax_sdf.js` (e.g., `128³` or `160³` SDF partitioned into dirty chunks for incremental Marching Cubes updates).
2. Subtract swept conical-bevel + `melt_kerf_mm` capsules along distance-sampled steps ($\Delta s \le 0.5 \cdot \text{tip\_width}$).
3. Add distinct diagnostics: `RAPID_COLLISION` (checked against *current* SDF), `SHANK_COLLISION`, `SOFT_LIMIT_EXCEEDED`, and `SINGULARITY_HIGH_THETA_DOT`.

### Phase 3: CAD `.glb` Skin & Stepper Homing (Polish)
1. Support loading `assets/machine/wax_carver.glb` with explicit `scale`, `up_axis`, and pivot reparenting.
2. Add `Home Axes` animation (*seek fast → back off → seek slow → zero*) for axes equipped with limit switches.

---

## 5. Verification & Test Requirements (TDD)

Write failing tests in `tests/test_carver_sim.py` before implementing modules:
- **Measured-Pose FK Calibration**: Harness asserting `forward_kinematics` reproduces 3–4 measured physical `(r, theta, h, phi) -> (r_s, theta_s, z_s)` poses within `±1.0 mm` (catching sign errors in `x` or wrong `pivot_to_tip_mm`).
- **Undercut IK & Limits**: Assert $\phi$-tilted undercut targets respect `phi_limits_deg` and unreachable poses return structured limit errors (never silent clamping).
- **Relative Tip Speed**: Verify $v_{\text{tip}}$ reflects $r_s \dot{\theta}$ when only the turntable rotates.
- **Sculpt Watertightness**: Assert `apply_facial_modifications` produces a closed, positive-volume mesh inside $(R_{\text{stock}}, H_{\text{stock}})$.
- **Current-Stock Rapid Check**: Assert `is_rapid` through already-carved SDF voxels passes, while `is_rapid` into uncarved SDF voxels raises `RAPID_COLLISION`.

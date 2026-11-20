# carver-kinematics Specification

## Purpose
Define the right-handed turntable and wax coordinate frames, 4-DOF forward and inverse kinematics, soft-limit validation, timing model, relative tip-speed calculations, and singularity diagnostics for the thermal CNC wax carver.
## Requirements
### Requirement: Configurable 4-DOF forward kinematics and coordinate datums
The system SHALL compute the tool reference point's signed cylindrical coordinates $(\theta_s, r_s, z_s)$ and Cartesian wax-frame vectors (`tip_xyz_wax`, `tool_axis_wax`) from joint coordinates $(r, \theta, h, \phi)$ in Python. Dimensions come from `machine_geometry.json` (CAD-derived) merged under `machine_config.json` (feeds, stock, presets, overrides):
- **Frames & Orbit**: Right-handed `+Z`-up machine frame (`mm`) with origin `(0, 0, 0)` on the orbit axis at the **stock seat plane**. The wax is static. The single rotary coordinate $\theta$ (`rad`) is the **orbit-ring angle** $\theta = \theta_{\text{ring}}$, with $\theta = 0$ when the column lies on machine `+X`. Therefore $\theta_s = \theta$ is the tool azimuth in wax coordinates. There is no platter term.
- **Linear & Pivot Datums**:
  - `r` (`mm`, **signed**) is the horizontal distance from the orbit axis to the tilt pivot axis along $+\hat{e}_r(\theta)$. Negative `r` places the pivot on the far side of the axis.
  - `h` (`mm`) is the height of the tilt pivot axis above the stock seat plane.
  - `arm_radial_offset_mm` (`x`) and `arm_to_pivot_z_mm` (`h2`) are taken from `machine_geometry.json` (`pivot_radial_offset_mm`, and `0` by datum definition).
  - `p = pivot_to_tip_mm` is the distance from the tilt pivot axis along $\hat{u}$ to the **tool reference point** (blade bottom-face centre), 60.0 mm from CAD.
- **Wrist Plane & Sign**: $\phi$ (configured in `deg`, converted to `rad` internally) rotates about $+\hat{e}_\theta = (-\sin\theta, \cos\theta, 0)$ by the right-hand rule. At $\phi = 0$, $\hat{u} = -\hat{e}_z$. Positive $+\phi$ tilts the reference point toward $-\hat{e}_r$, giving $\hat{u}(\phi) = -\sin(\phi)\hat{e}_r - \cos(\phi)\hat{e}_z$, $r_s = r - x - p\sin(\phi)$, and $z_s = h - p\cos(\phi) - h_2$. `tip_xyz_wax` $= (r_s\cos\theta, r_s\sin\theta, z_s)$ holds for signed $r_s$.

#### Scenario: Forward kinematics algebraic and sign verification
- **WHEN** `forward_kinematics(r, theta, h, phi, config)` is evaluated at $\phi = 0^\circ$, $\phi = 90^\circ$, an arbitrary $\phi > 0^\circ$, and a negative `r`
- **THEN** $(\theta_s, r_s, z_s)$ match $\theta_s = \theta$, $r_s = r - x - p \sin(\phi)$, and $z_s = h - p \cos(\phi) - h_2$ within $10^{-5}\text{ mm}$. $\phi = 90^\circ$ yields $r_s = r - x - p$ and $z_s = h - h_2$. Increasing $+\phi$ decreases $r_s$. `r = -20`, $\theta = 0$ yields `tip_xyz_wax` with $x = -20 - p\sin\phi$. Both `tip_xyz_wax` and `tool_axis_wax` are returned in wax Cartesian coordinates.

#### Scenario: CAD reference pose reproduces the CAD tool reference point
- **WHEN** `forward_kinematics` is evaluated at `machine_geometry.json.cad_reference_pose`
- **THEN** `tip_xyz_wax` equals the CAD-measured tool reference point transformed into the machine frame (`(0, 0, 91.0)` for the committed STEP) within 0.05 mm

#### Scenario: Measured physical pose calibration fixture
- **WHEN** `forward_kinematics` is evaluated against the hardware calibration pose fixture (once measured physical poses are recorded)
- **THEN** all measured `(r, theta, h, phi) -> (r_s, theta_s, z_s)` poses match within $\pm 1.0\text{ mm}$

### Requirement: Undercut-aware inverse kinematics and soft limits
The system SHALL solve joint coordinates $(r, \theta, h, \phi)$ from target tool-reference-point poses $(r_s, \theta_s, z_s)$ and optional surface normals $\vec{n}$, using an explicit $\phi$-selection policy:
- Project $\vec{n}$ into the local $(e_r, e_z)$ plane. If $\sqrt{n_r^2 + n_z^2} < 10^{-3}$ (tangential normal), fall back to $\phi_{\text{ideal}} = 0^\circ$.
- If $\phi_{\text{ideal}}$ exceeds `phi_limits_deg`, clamp the policy preference to `phi_limits_deg` and emit an informational `PHI_POLICY_CLAMPED` diagnostic.
- Validate the solved joint tuple $(r, \theta, h, \phi)$ against `r_limits_mm` (signed), `h_limits_mm`, `phi_limits_deg`, and `theta_limits_deg`. These default to the CAD-derived `r_travel_mm`, `h_travel_mm` and `theta_travel_deg` when present in `machine_geometry.json`, and `machine_config.json` MAY only narrow them. Any out-of-bounds joint SHALL be rejected with a `SOFT_LIMIT_EXCEEDED` error naming the violating axis and value (never silently clamped).
- If a CAD-derived travel limit is `null`, runtime configuration SHALL provide an explicit conservative limit for that axis before generating toolpaths. The application SHALL NOT treat an unknown physical limit as unlimited; the configured fallback SHALL be labeled unverified in provenance until measured or computed from CAD.
- When a target is reachable with either sign of `r` (θ vs θ + π), the solver SHALL prefer the solution that keeps θ inside `theta_limits_deg` with the smaller |Δθ| from the previous pose. The normal SHALL be projected into $(e_r, e_z)$ of the chosen solution's own θ, so for a negative-`r` solution $\phi_{\text{ideal}}$ is computed against $\hat{e}_r(\theta)$, which points away from the target side.

#### Scenario: Inverse kinematics round-trip and phi-policy alignment
- **WHEN** `inverse_kinematics_with_policy` solves a reachable undercut target with a downward-tilted surface normal
- **THEN** `forward_kinematics(*ik_result, config)` reproduces the target $(r_s, \theta_s, z_s)$ within $10^{-5}\text{ mm}$, and a normal requesting $\phi_{\text{ideal}}$ beyond `phi_limits_deg` emits `PHI_POLICY_CLAMPED` while returning a valid clamped $\phi$

#### Scenario: Out-of-bounds joint target rejected
- **WHEN** a target tip pose requires $r$, $h$, $\phi$, or $\theta$ outside the configured soft travel limits
- **THEN** the solver rejects the pose with a `SOFT_LIMIT_EXCEEDED` diagnostic naming the violating axis and value instead of silently clamping

#### Scenario: Signed-r solution avoids a configured orbit stop
- **WHEN** a test machine configuration explicitly supplies `theta_limits_deg = [−170°, 170°]`, the previous pose is at θ = 160°, and the next target lies at azimuth −170°
- **THEN** the solver returns the signed-r solution (θ = 10°, r < 0) that stays inside the configured limits instead of rejecting the target; this synthetic fixture does not assert that ±170° has been measured from the committed CAD

#### Scenario: Unknown CAD travel limit requires explicit configuration
- **WHEN** a CAD-derived travel limit is `null` and the machine configuration supplies no fallback limit for that axis
- **THEN** configuration validation rejects toolpath generation and identifies the missing limit rather than treating the axis as unlimited

### Requirement: Relative tip speed, timing model, and axis singularity detection
The system SHALL compute segment timestamps $t$ from configured feed rates (`feed_cut_mm_s`, `feed_rapid_mm_s`) and per-axis velocity limits (`v_max_r_mm_s`, `v_max_theta_rad_s`, `v_max_h_mm_s`, `v_max_phi_deg_s`) via $\Delta t = \max(\Delta s / \text{feed}, \max_i |\Delta q_i| / v_{\text{max}, i})$. Using unwrapped $\theta$ (`rad`), the system SHALL compute relative tip speed in the wax frame $v_{\text{tip}} = \sqrt{\dot{r}_s^2 + (r_s \dot{\theta}_s)^2 + \dot{z}_s^2}$. It SHALL emit a `SINGULARITY_HIGH_THETA_DOT` warning whenever $|r_s| < r_{s,\min}$ (configured `r_s_min_mm`, default `2.0 mm`) and $|\dot{\theta}_s| > \dot{\theta}_{\text{warn}}$ (configured `theta_dot_warn_rad_s`, default `3.0 rad/s`), limiting segment speed to `v_max_theta_rad_s`. Because the orbit ring carries the column, arm and counterweight, `v_max_theta_rad_s` SHALL default to a value no greater than `1.0 rad/s` until measured.

#### Scenario: Pure turntable rotation and combined tilted motion report relative tip speed
- **WHEN** (a) only $\theta$ changes at $r_s = 30\text{ mm}$, or (b) $r, \theta, h, \phi$ change simultaneously with $\phi \ne 0^\circ$
- **THEN** `v_tip` matches $\sqrt{\dot{r}_s^2 + (r_s \dot{\theta}_s)^2 + \dot{z}_s^2}$ in the wax frame rather than zero or joint-only speed

#### Scenario: Near-axis trajectory triggers singularity warning
- **WHEN** a trajectory segment passes inside $|r_s| < r_{s,\min}$ (including a crossing from $r_s > 0$ to $r_s < 0$) with required $|\dot{\theta}_s| > \dot{\theta}_{\text{warn}}$
- **THEN** the trajectory diagnostics include `SINGULARITY_HIGH_THETA_DOT` and segment timing respects `v_max_theta_rad_s`


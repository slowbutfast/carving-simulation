# carver-kinematics Specification

## Purpose
Define the right-handed turntable and wax coordinate frames, 4-DOF forward and inverse kinematics, soft-limit validation, timing model, relative tip-speed calculations, and singularity diagnostics for the thermal CNC wax carver.

## ADDED Requirements

### Requirement: Configurable 4-DOF forward kinematics and coordinate datums
The system SHALL compute conical-bevel tip cylindrical coordinates $(\theta_s, r_s, z_s)$ and Cartesian wax-frame vectors (`tip_xyz_wax`, `tool_axis_wax`) from joint coordinates $(r, \theta, h, \phi)$ in Python using configured dimensions in `machine_config.json`:
- **Frames & Rotary Collapse**: Right-handed `+Z`-up frame (`mm`) with origin `(0, 0, 0)` at the center of the rotary platter top surface and `theta = 0` along `+X`. The single rotary coordinate $\theta$ (in `rad`) is $\theta = \theta_{\text{ring}} - \theta_{\text{platter}}$ (with default single-platter setup $\theta_{\text{ring}} = 0 \implies \theta = -\theta_{\text{platter}}$), so $\theta_s = \theta$ is the tool azimuth in **wax coordinates**.
- **Linear & Pivot Datums**: `r` (`mm`) is measured outward along $+\hat{e}_r$ from the platter centerline (`r = 0`) to the radial carriage datum (`x = arm_radial_offset_mm`); `h` (`mm`) is measured upward along `+Z` from the platter top (`z = 0`) to the arm datum (`h2 = arm_to_pivot_z_mm`); `p = pivot_to_tip_mm` is the distance from the wrist pitch axis along the tool unit vector $\hat{u}$ to the **conical-bevel tip apex** (never hardcoded to `0.5 * S` without config override).
- **Wrist Plane & Sign**: $\phi$ (configured in `deg`, converted to `rad` internally) rotates about the local **azimuthal unit vector** $+\hat{e}_\theta = (-\sin\theta, \cos\theta, 0)$ by the right-hand rule: at $\phi = 0$, $\hat{u} = -\hat{e}_z$; positive $+\phi$ tilts the tip inward toward $-r$, giving $\hat{u}(\phi) = -\sin(\phi)\hat{e}_r - \cos(\phi)\hat{e}_z$, $r_s = r - x - p\sin(\phi)$, and $z_s = h - p\cos(\phi) - h_2$.

#### Scenario: Forward kinematics algebraic and sign verification
- **WHEN** `forward_kinematics(r, theta, h, phi, config)` is evaluated at $\phi = 0^\circ$, $\phi = 90^\circ$, and arbitrary $\phi > 0^\circ$
- **THEN** $(\theta_s, r_s, z_s)$ match $\theta_s = \theta$, $r_s = r - x - p \sin(\phi)$, and $z_s = h - p \cos(\phi) - h_2$ within $10^{-5}\text{ mm}$, $\phi = 90^\circ$ yields $r_s = r - x - p$ and $z_s = h - h_2$, increasing $+\phi$ decreases $r_s$, and `tip_xyz_wax` / `tool_axis_wax` are returned in wax Cartesian coordinates

#### Scenario: Measured physical pose calibration fixture
- **WHEN** `forward_kinematics` is evaluated against the hardware calibration pose fixture (once measured physical poses are recorded)
- **THEN** all measured `(r, theta, h, phi) -> (r_s, theta_s, z_s)` poses match within $\pm 1.0\text{ mm}$

### Requirement: Undercut-aware inverse kinematics and soft limits
The system SHALL solve joint coordinates $(r, \theta, h, \phi)$ from target tip poses $(r_s, \theta_s, z_s)$ and optional surface normals $\vec{n}$ using an explicit $\phi$-selection policy:
- Project $\vec{n}$ into the local $(e_r, e_z)$ plane; if $\sqrt{n_r^2 + n_z^2} < 10^{-3}$ (tangential normal), fall back to $\phi_{\text{ideal}} = 0^\circ$.
- If $\phi_{\text{ideal}}$ exceeds `phi_limits_deg`, clamp the policy preference to `phi_limits_deg` and emit an informational `PHI_POLICY_CLAMPED` diagnostic.
- Validate the solved joint tuple $(r, \theta, h, \phi)$ against `r_limits_mm`, `h_limits_mm`, `phi_limits_deg`, and optional `theta_limits_deg`; any out-of-bounds joint SHALL be rejected with a `SOFT_LIMIT_EXCEEDED` error naming the violating axis and value (never silently clamped).

#### Scenario: Inverse kinematics round-trip and phi-policy alignment
- **WHEN** `inverse_kinematics_with_policy` solves a reachable undercut target with a downward-tilted surface normal
- **THEN** `forward_kinematics(*ik_result, config)` reproduces the target $(r_s, \theta_s, z_s)$ within $10^{-5}\text{ mm}$, and a normal requesting $\phi_{\text{ideal}}$ beyond `phi_limits_deg` emits `PHI_POLICY_CLAMPED` while returning a valid clamped $\phi$

#### Scenario: Out-of-bounds joint target rejected
- **WHEN** a target tip pose requires $r$, $h$, $\phi$, or $\theta$ outside the configured soft travel limits
- **THEN** the solver rejects the pose with a `SOFT_LIMIT_EXCEEDED` diagnostic naming the violating axis and value instead of silently clamping

### Requirement: Relative tip speed, timing model, and axis singularity detection
The system SHALL compute segment timestamps $t$ from configured feed rates (`feed_cut_mm_s`, `feed_rapid_mm_s`) and per-axis velocity limits (`v_max_r_mm_s`, `v_max_theta_rad_s`, `v_max_h_mm_s`, `v_max_phi_deg_s`) via $\Delta t = \max(\Delta s / \text{feed}, \max_i |\Delta q_i| / v_{\text{max}, i})$. Using unwrapped $\theta$ (`rad`), the system SHALL compute relative tip speed in the wax frame $v_{\text{tip}} = \sqrt{\dot{r}_s^2 + (r_s \dot{\theta}_s)^2 + \dot{z}_s^2}$ and SHALL emit a `SINGULARITY_HIGH_THETA_DOT` warning whenever $r_s < r_{s,\min}$ (configured `r_s_min_mm`, default `2.0 mm`) and $|\dot{\theta}_s| > \dot{\theta}_{\text{warn}}$ (configured `theta_dot_warn_rad_s`, default `3.0 rad/s`), limiting segment speed to `v_max_theta_rad_s`.

#### Scenario: Pure turntable rotation and combined tilted motion report relative tip speed
- **WHEN** (a) only $\theta$ changes at $r_s = 30\text{ mm}$, or (b) $r, \theta, h, \phi$ change simultaneously with $\phi \ne 0^\circ$
- **THEN** `v_tip` matches $\sqrt{\dot{r}_s^2 + (r_s \dot{\theta}_s)^2 + \dot{z}_s^2}$ in the wax frame rather than zero or joint-only speed

#### Scenario: Near-axis trajectory triggers singularity warning
- **WHEN** a trajectory segment passes inside $r_s < r_{s,\min}$ with required $|\dot{\theta}_s| > \dot{\theta}_{\text{warn}}$
- **THEN** the trajectory diagnostics include `SINGULARITY_HIGH_THETA_DOT` and segment timing respects `v_max_theta_rad_s`

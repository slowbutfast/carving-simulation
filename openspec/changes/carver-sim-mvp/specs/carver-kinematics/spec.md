# carver-kinematics Specification

## Purpose
Define the right-handed turntable coordinate frame, 4-DOF forward and inverse kinematics, soft-limit validation, and relative tip-speed calculations for the thermal CNC wax carver.

## ADDED Requirements

### Requirement: Configurable 4-DOF forward kinematics
The system SHALL compute conical-bevel tip cylindrical coordinates $(\theta_s, r_s, z_s)$ from joint coordinates $(r, \theta, h, \phi)$ in Python using configured dimensions (`pivot_to_tip_mm`, `arm_radial_offset_mm`, `arm_to_pivot_z_mm`) in a right-handed `+Z`-up turntable frame.

#### Scenario: Measured physical pose calibration
- **WHEN** `forward_kinematics(r, theta, h, phi, config)` is evaluated on configured machine dimensions for known joint poses
- **THEN** the returned tip coordinates $(\theta_s, r_s, z_s)$ match $\theta_s = \theta$, $r_s = r - x - p \sin(\phi)$, and $z_s = h - p \cos(\phi) - h_2$ within $10^{-5}\text{ mm}$

### Requirement: Undercut-aware inverse kinematics and soft limits
The system SHALL solve joint coordinates $(r, \theta, h, \phi)$ from target tip poses $(r_s, \theta_s, z_s)$ using an explicit $\phi$-selection policy clamped to `phi_limits_deg`, and SHALL return structured limit errors whenever any joint exceeds configured soft travel bounds (`r_limits`, `h_limits`, `phi_limits_deg`).

#### Scenario: Out-of-bounds joint target rejected
- **WHEN** a target tip pose requires $r$, $h$, or $\phi$ outside the configured soft travel limits
- **THEN** the solver rejects the pose with a `SOFT_LIMIT_EXCEEDED` diagnostic naming the violating axis and value instead of silently clamping

### Requirement: Relative tip speed and axis singularity detection
The system SHALL compute relative tip speed $v_{\text{tip}} = \sqrt{\dot{r}_s^2 + (r_s \dot{\theta})^2 + \dot{z}_s^2}$ including turntable tangential motion, and SHALL emit a `SINGULARITY_HIGH_THETA_DOT` warning when a trajectory passes near $r_s \to 0$.

#### Scenario: Pure turntable rotation reports non-zero tip speed
- **WHEN** only $\theta$ changes at $r_s = 30\text{ mm}$ while $r$, $h$, and $\phi$ are constant
- **THEN** `v_tip` equals $|r_s \dot{\theta}| > 0$ rather than zero

# face-sculpt-sim Specification

## Purpose
Define parametric facial modification on a watertight base head mesh and synthetic 4-DOF undercut-capable trajectory generation.

## ADDED Requirements

### Requirement: Watertight parametric facial deformation
The system SHALL apply smooth RBF/Gaussian normal deformations to a base head mesh (`nose`, `brow`, `cheeks`, `jaw`, `chin`) using `scipy.spatial.cKDTree` while preserving watertightness, positive volume, and cylindrical stock containment $(R_{\text{stock}}, H_{\text{stock}})$.

#### Scenario: Facial slider deformation preserves watertightness
- **WHEN** non-zero facial modification parameters are applied to `presets/base_head.stl`
- **THEN** the output mesh remains a closed, positive-volume `trimesh.Trimesh` bounded within $(R_{\text{stock}}, H_{\text{stock}})$

### Requirement: Synthetic distance-sampled 4-DOF trajectory generation
The system SHALL generate synthetic joint-space trajectories (cylindrical roughing from $R_{\text{stock}}$ plus helical/undercut finishing) sampled by Euclidean tip distance $\Delta s \le 0.5 \cdot \text{tip\_width}$, returning pre-sampled `(t, r, theta, h, phi, r_s, theta_s, z_s, v_tip, is_rapid)` frames from Python.

#### Scenario: Swept sampling prevents coarse step gaps
- **WHEN** a trajectory moves across steep facial contours
- **THEN** consecutive sampled tip positions satisfy $\Delta s \le 0.5 \cdot \text{tip\_width}$ with continuous unwrapped $\theta$

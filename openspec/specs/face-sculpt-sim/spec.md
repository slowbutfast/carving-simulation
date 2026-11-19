# face-sculpt-sim Specification

## Purpose
Define parametric facial modification on a procedural watertight base head mesh, synthetic shadow-aware roughing and $\phi$-undercut finishing trajectory generation, and the FastAPI simulation endpoint contract.

## Requirements

### Requirement: Watertight parametric facial deformation with stock containment
The system SHALL bundle a procedurally generated, watertight `presets/base_head.stl` (facing `+X` at $\theta = 0$, seated on a cylindrical plinth $z \in [0, z_{\text{plinth}}]$) with `presets/base_head_landmarks.json`. `apply_facial_modifications` SHALL apply smooth `scipy.spatial.cKDTree` RBF/Gaussian normal deformations (`nose`, `brow`, `cheeks`, `jaw`, `chin`) bounded by a per-landmark max displacement guard to prevent self-intersection, while preserving watertightness, positive volume, and cylindrical stock containment $(r \le R_{\text{stock}} - \text{finish\_allowance\_mm},\; z \in [0, H_{\text{stock}}])$.

#### Scenario: Facial slider deformation preserves watertightness and non-self-intersection
- **WHEN** non-zero facial modification parameters are applied to `presets/base_head.stl`
- **THEN** the output mesh remains a closed, positive-volume, non-self-intersecting `trimesh.Trimesh` bounded within $(R_{\text{stock}} - \text{finish\_allowance\_mm}, H_{\text{stock}})$

#### Scenario: Out-of-stock deformation returns structured error
- **WHEN** facial parameters or stock dimensions cause the sculpted mesh to exceed $(R_{\text{stock}}, H_{\text{stock}})$
- **THEN** the system returns a `STOCK_BOUNDS_EXCEEDED` diagnostic instead of silently clipping the face

### Requirement: Synthetic shadow-aware roughing and undercut-capable finishing trajectories
The system SHALL generate synthetic joint-space trajectories (`generate_synthetic_carve_path`) in two stages:
1. **Shadow-Aware Cylindrical Roughing ($\phi = 0^\circ$)**: Z-level terracing from $H_{\text{stock}}$ down to $z_{\text{plinth}}$ using `rough_stepdown_mm` and `rough_stepover_mm`, clipping each level's minimum radius to the top-down shadow $r_{\text{shadow}}(\theta, z) = \max_{z' \ge z} r_{\text{target}}(\theta, z') + \text{finish\_allowance\_mm}$ so the vertical shank never collides with overhangs.
2. **Undercut-Capable Finishing**: Sampled across 2D $r$–$Z$ cross-section slices per $\theta$ step (supporting multi-valued overhangs), selecting $\phi$ from $r$–$Z$ projected surface normals, applying the Contact-Point (CC) to Tip-Apex (CL) offset $(\rho + \text{melt\_kerf\_mm})$, flagging unreachable overhangs ($\beta > \phi_{\max} - \alpha$) with `UNREACHABLE_UNDERCUT_AREA`, and flagging target mesh intersections with `GOUGE`.
3. **Safe-by-Construction Rapids & Engaged-Length Sampling**: `is_rapid` transitions retract radially to $r \ge R_{\text{stock}} + \text{retract\_clearance\_mm}$ before traversing, and all segments are resampled so the maximum displacement of any point on the engaged heated cone $L_{\text{tip}}$ satisfies $\Delta s_{\max} \le 0.5 \cdot \text{tip\_width}$ with continuous unwrapped $\theta$ (`rad`), returning `(t, r, theta, h, phi, r_s, theta_s, z_s, v_tip, is_rapid, tip_xyz_wax, tool_axis_wax)` frames.

#### Scenario: Swept sampling prevents coarse step gaps across steep and near-axis moves
- **WHEN** a trajectory moves across steep facial contours or rotates near $r_s \to 0$
- **THEN** consecutive sampled poses satisfy $\Delta s_{\max} \le 0.5 \cdot \text{tip\_width}$ along the full engaged cone length $L_{\text{tip}}$ with continuous unwrapped $\theta$ and valid `is_rapid` retract clearances

#### Scenario: Unreachable steep chin overhang reports diagnostic
- **WHEN** a target face contains an overhang steeper than $\phi_{\max} - \alpha$
- **THEN** the generator emits `UNREACHABLE_UNDERCUT_AREA` with the unreachable surface percentage while completing reachable passes

### Requirement: Simulation API endpoint and columnar payload contract
`server.py` SHALL expose `GET /api/health` and `POST /api/sculpt-and-sim` accepting `{ sliders, stock_cfg, tool_cfg, preset }` (`"demo"` or `"standard"`), returning the sculpted target mesh, machine config, diagnostics, and columnar base64-encoded `Float32Array` trajectory buffers capped at `max_frames` (default `250,000`).

#### Scenario: Sculpt-and-sim endpoint returns valid columnar trajectory and diagnostics
- **WHEN** a client sends a valid `POST /api/sculpt-and-sim` request with `preset: "demo"`
- **THEN** the response returns HTTP 200 with decodable columnar frame buffers, target mesh geometry, and structured diagnostics

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
The system SHALL generate synthetic joint-space trajectories (`generate_synthetic_carve_path`) in two stages. All tool geometry comes from `tool_model.py` (blade-tool-model), never from local constants:
1. **Shadow-Aware Cylindrical Roughing ($\phi = 0^\circ$)**: Z-level terracing from $H_{\text{stock}}$ down to $z_{\text{plinth}}$ using `rough_stepdown_mm` and `rough_stepover_mm`. Each level SHALL be clipped so that the heated region, placed with `place_on_contact` against the top-down shadow $r_{\text{shadow}}(\theta, z) = \max_{z' \ge z} r_{\text{target}}(\theta, z') + \text{finish\_allowance\_mm}$, never enters the shadow. Each level's passes SHALL run along θ at constant `r` (slice feed), with radial stepovers between passes.
2. **Undercut-Capable Finishing**: Sampled across 2D $r$–$Z$ cross-section slices per $\theta$ step (supporting multi-valued overhangs). For each contact point the generator SHALL:
   - select $\phi$ from the projected surface normal via the IK policy
   - place the tool with `tool_model.place_on_contact` (support-function CC→CL, including `melt_kerf_mm`)
   - accept the pose only if `tool_model.body_penetrates` is false against the target mesh, otherwise retry $\phi$ candidates within `phi_limits_deg` at `finish_phi_search_step_deg` (default 5°) ordered by distance from $\phi_{\text{ideal}}$
   - flag points with no collision-free candidate as `UNREACHABLE_UNDERCUT_AREA`, with the unreachable surface percentage
   - flag heated-region intersections with the target beyond `finish_allowance_mm` as `GOUGE`

   The closed-form cone bound ($\beta > \phi_{\max} - \alpha$) SHALL NOT be used.
3. **Safe-by-Construction Rapids & Engaged-Length Sampling**:
   - `is_rapid` transitions retract radially until the heated region and shaft clear the stock cylinder by `retract_clearance_mm` (that is, $|r_s| \ge R_{\text{stock}} + \text{retract\_clearance\_mm} + $ the tool's radial support extent at the current $\phi$) before traversing.
   - All segments are resampled so the maximum displacement of any point on the heated region satisfies $\Delta s_{\max} \le 0.5 \cdot (\text{blade\_thickness\_mm} + 2 \cdot \text{melt\_kerf\_mm})$, with continuous unwrapped $\theta$ (`rad`).
   - Frames are returned as `(t, r, theta, h, phi, r_s, theta_s, z_s, v_tip, is_rapid, tip_xyz_wax, tool_axis_wax)`.
4. **Feed-Direction Diagnostics**: Every cutting segment SHALL be classified with `tool_model.feed_class`. Trajectories containing `broadside` cutting segments SHALL emit a `BLADE_BROADSIDE_FEED` warning reporting the broadside fraction of cutting path length and the first offending frame index.

#### Scenario: Swept sampling prevents coarse step gaps across steep and near-axis moves
- **WHEN** a trajectory moves across steep facial contours or rotates near $r_s \to 0$
- **THEN** consecutive sampled poses satisfy $\Delta s_{\max} \le 0.5 \cdot (\text{blade\_thickness\_mm} + 2 \cdot \text{melt\_kerf\_mm})$ for every point of the heated region, with continuous unwrapped $\theta$ and valid `is_rapid` retract clearances

#### Scenario: Unreachable steep chin overhang reports diagnostic
- **WHEN** a target face contains an overhang for which every $\phi$ candidate within `phi_limits_deg` makes `body_penetrates` true
- **THEN** the generator emits `UNREACHABLE_UNDERCUT_AREA` with the unreachable surface percentage while completing reachable passes

#### Scenario: Roughing passes slice rather than plow
- **WHEN** the `demo` preset roughing stage is generated on the base head
- **THEN** ≥ 90 % of roughing cutting path length is classified `slice`, and any `broadside` segments are reported through `BLADE_BROADSIDE_FEED`

#### Scenario: CL placement uses the blade support point
- **WHEN** a finishing contact point lies on a surface whose normal has a tangential component ($|n_\theta| > 0.3$)
- **THEN** the emitted `tip_xyz_wax` equals `place_on_contact(cc, n, pose)` within 1e-6 mm, and is not `cc + (ρ + kerf)·n`

### Requirement: Simulation API endpoint and columnar payload contract
`server.py` SHALL expose `GET /api/health` and `POST /api/sculpt-and-sim` accepting `{ sliders, stock_cfg, tool_cfg, preset }` (`"demo"` or `"standard"`), returning the sculpted target mesh, the merged machine config (including the `machine_geometry.json` provenance block), diagnostics, and columnar base64-encoded `Float32Array` trajectory buffers capped at `max_frames` (default `250,000`). `tool_cfg` SHALL accept only `melt_kerf_mm` and `heated_length_mm` (≤ `blade_length_mm`). Blade dimensions are CAD-derived and not client-overridable. Removed cone keys (`tip_radius_mm`, `cone_half_angle_deg`, `engaged_length_mm`, `tip_width_mm`, `shank_radius_mm`, `shank_length_mm`) SHALL be rejected with HTTP 422 naming the key.

#### Scenario: Sculpt-and-sim endpoint returns valid columnar trajectory and diagnostics
- **WHEN** a client sends a valid `POST /api/sculpt-and-sim` request with `preset: "demo"`
- **THEN** the response returns HTTP 200 with decodable columnar frame buffers, target mesh geometry, structured diagnostics, and `config.geometry_provenance.step_sha256`

#### Scenario: Legacy cone tool keys are rejected
- **WHEN** a client sends `tool_cfg: { "cone_half_angle_deg": 30 }`
- **THEN** the response is HTTP 422 and the error names `cone_half_angle_deg`


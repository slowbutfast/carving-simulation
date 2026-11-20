# blade-tool-model Specification

## Purpose
TBD - created by archiving change machine-cad-integration. Update Purpose after archive.
## Requirements
### Requirement: Blade tool definition and tool frame
`tool_model.py` SHALL be the single runtime definition of the cutting tool. It SHALL load from `machine_geometry.json.tool`:
- `blade_thickness_mm` (1.2), `blade_width_mm` (6.0), `blade_length_mm` (14.0)
- `shaft_radius_mm` (2.5) over `[blade_length_mm, 75.0]`
- `body_radius_mm` (3.5) over `[75.0, 140.0]`
- `head_clearance_mm`: distance from the reference point to the lowest tilt-head part (about 46.6)

It SHALL also load `melt_kerf_mm` and `heated_length_mm` (default = `blade_length_mm`) from `machine_config.json`. For a pose with tool axis u (pointing toward the reference point) and azimuth θ, the tool frame SHALL be:
- a_w = e_θ(θ) (blade width)
- a_n = a_w × u (blade thickness normal)
- u

The ordered frame `(a_n, a_w, u)` SHALL be right-handed (`a_n × a_w = u`). At φ = 0 this gives `a_n = −e_r`; the blade thickness axis is an unoriented line, so this is the same physical CAD axis as `+e_r`.

#### Scenario: Tool frame matches the CAD blade orientation
- **WHEN** the tool frame is computed at θ = 0, φ = 0
- **THEN** a_n = −X, a_w = +Y, u = −Z in the machine frame, with `a_n × a_w = u`. The blade's thickness axis is the machine X axis (sign-independent), and its width axis is the machine Y axis (sign-independent), matching the CAD extents.

#### Scenario: Tool frame stays orthonormal under tilt
- **WHEN** the tool frame is computed for φ ∈ {−60°, 0°, 45°, 75°} and θ ∈ {0°, 90°, 225°}
- **THEN** (a_n, a_w, u) is right-handed orthonormal within 1e-12, and a_w equals e_θ(θ) for every φ

### Requirement: Heated-region signed distance
`tool_model.heated_sdf(points, pose)` SHALL return the exact signed distance to the blade prism (half-extents `blade_thickness/2`, `blade_width/2`, `heated_length/2`, centred `heated_length/2` above the reference point along −u) inflated by `melt_kerf_mm`. Distances are negative inside. `static/wax_sdf_core.js` SHALL implement the same function, reading identical constants from `machine_geometry.json` and `machine_config.json`.

#### Scenario: Analytic SDF probes
- **WHEN** `heated_sdf` is evaluated at θ = 0, φ = 0 with the reference point at the origin
- **THEN** the reference point returns −`melt_kerf_mm`, the point (0.6 + kerf, 0, 7.0) returns 0 within 1e-9, the point (0, 3.0 + kerf + 1.0, 7.0) returns 1.0 within 1e-9, and the point (0, 0, −kerf − 2.0) returns 2.0 within 1e-9

#### Scenario: Python and JS SDF agree
- **WHEN** 1,000 seeded random points and 20 random poses are evaluated by both implementations
- **THEN** the maximum absolute difference is ≤ 1e-5 mm

### Requirement: Support-function CC to CL placement
`tool_model.place_on_contact(cc, n, pose_axes)` SHALL return the tool reference point such that the heated region touches the surface tangent plane at contact point `cc` with outward unit normal `n`. It SHALL use the inflated blade's support point s(−n) relative to the reference point: `cl = cc + kerf·n − s₀(−n)`, where s₀ is the support point of the un-inflated prism. When the support set is a face or edge, s₀ SHALL be that face's or edge's centroid so placement is deterministic. It SHALL NOT apply a scalar offset along n alone.

#### Scenario: Placement is tangent for arbitrary normals
- **WHEN** `place_on_contact` is evaluated for 500 seeded random unit normals and tool poses
- **THEN** `heated_sdf(cc)` at the returned pose is 0 within 1e-9, and the heated region lies on the outer side of the tangent plane (no point of the inflated prism has (x − cc)·n < −1e-9)

#### Scenario: Flat-top contact offsets by the kerf only
- **WHEN** n = +Z (a horizontal top face), φ = 0
- **THEN** the returned reference point is cc + (kerf)·Z, because the blade bottom face is the support face

### Requirement: Tool-body collision bodies
`tool_model.body_penetrates(mesh_or_sdf, poses)` SHALL report, per pose, whether any of these unheated bodies enters the target. The tool reference point is the local origin; axial distances are measured from it along `−u`. `machine_geometry.json` SHALL store the tilt-head envelope as an explicit box or capsule with dimensions and pose relative to that origin, not only as a scalar clearance. All body samples SHALL be transformed from this tool-local definition into the world pose using `(a_n, a_w, u)`.
- the shaft cylinder
- the body cylinder
- the tilt-head envelope (a capsule or box hull recorded in `machine_geometry.json`)

It SHALL sample each body at spacing ≤ 0.5 mm along u and ≤ 30° around its circumference, at that body's radius. It SHALL use the inside-positive sign of `trimesh.proximity.signed_distance` for meshes, and the inside-negative sign of the wax SDF for the voxel grid.

#### Scenario: Shaft collision against a known wall
- **WHEN** a box spanning 20–40 mm above the reference point along −u is placed with its face normal to a_n at 2.0 mm from the tool axis (clear of the 14 mm blade)
- **THEN** `body_penetrates` returns true (shaft radius 2.5 > 2.0), and returns false when the face is moved to 3.0 mm

### Requirement: Broadside-feed classification
`tool_model.feed_class(direction, pose_axes)` SHALL classify a cutting-move direction d by its largest absolute component on (a_n, a_w, u) as `broadside`, `slice` or `plunge`. A move is `broadside` when |d·a_n| > cos(`broadside_threshold_deg`) (config, default 45°).

#### Scenario: Radial feed at phi zero is broadside
- **WHEN** a cutting move at θ = 0, φ = 0 has direction +e_r
- **THEN** it is classified `broadside`, a +e_θ move is classified `slice`, and a −Z move is classified `plunge`


# volumetric-wax-viewer Specification

## Purpose
Define the Three.js primitive 4-DOF rig, playback/scrub transport, Web Worker chunked volumetric SDF Marching Cubes wax subtraction, current-stock rapid/shank collision diagnostics, and carved surface fidelity.
## Requirements
### Requirement: Primitive 4-DOF kinematic rig and transport controls driven by backend poses
The web viewer SHALL render the carver rig specified by "CAD-derived carver rig with orbiting ring and static wax", driven exclusively by Python-sampled joint poses and `tip_xyz_wax` / `tool_axis_wax` without duplicating kinematic trigonometry in JavaScript. The viewer SHALL provide `Play/Pause`, `Scrub`, `1x–20x` speed, and `Carve to End` controls, and SHALL auto-pause on `RAPID_COLLISION`, `SHANK_COLLISION`, or `SOFT_LIMIT_EXCEEDED`.

#### Scenario: Playback animates joints from sampled trajectory without JS trig
- **WHEN** the user runs a `demo` or `standard` sculpt-and-sim job and presses Play
- **THEN** `THREE.Clock` advances the simulation timeline, updates the orbit ring (`+theta`), Z-carriage (`h`), radial carriage (`r`), and tilt $\phi$ transforms from backend poses, keeps the wax static, and maintains interactive frame rates

### Requirement: Chunked volumetric SDF wax subtraction with undercut and scrub support
The web viewer SHALL represent the cylindrical wax stock (`R_stock`, `H_stock`, seated on the stock seat plane `z = 0`) in a Web Worker (`wax_worker.js` wrapping `wax_sdf_core.js`) as a 3D float32 grid (default `128³` partitioned into `16³` chunks). The grid is initialized to the exact Euclidean cylinder SDF for $z \in [0, H_{\text{stock}}]$ with $\ge 2$ voxels of exterior padding on all sides. Each step SHALL subtract the **blade heated region**, the oriented prism (`blade_thickness_mm` × `blade_width_mm` × `heated_length_mm`) in the tool frame $(a_n, a_w, u)$ inflated by `melt_kerf_mm`, using `max(sdf, -d_heated)`. The worker SHALL build the tool frame from the frame's `tool_axis_wax` and `theta_s` ($a_w = \hat{e}_\theta$), mark touched chunks and adjacent boundary-neighbor chunks dirty, and remesh via Marching Cubes with a 1-voxel apron and global SDF gradient normals. Periodic SDF snapshots SHALL allow backward/forward scrubbing without freezing the main thread.

#### Scenario: Undercut carving updates dirty chunks and neighbors without seams
- **WHEN** a $\phi$-tilted finishing segment sweeps beneath a nose or chin overhang across a chunk boundary
- **THEN** `wax_sdf_core.js` subtracts the tilted blade envelope, marks both the touched chunk and adjacent boundary-sharing chunks dirty, preserves upper overhang voxels (`sdf < 0` above the cavity within `1e-3` tolerance), and produces a seam-free Marching Cubes mesh

#### Scenario: Blade kerf is direction-dependent
- **WHEN** a single cutting move of 20 mm at φ = 0 is subtracted along $+\hat{e}_\theta$ in one grid and along $+\hat{e}_r$ in another
- **THEN** the carved slot width perpendicular to the motion is `blade_thickness_mm + 2·melt_kerf_mm` (± 1 voxel) for the θ move and `blade_width_mm + 2·melt_kerf_mm` (± 1 voxel) for the r move

#### Scenario: Scrubbing restores from nearest SDF snapshot
- **WHEN** the user drags the timeline scrubber backward or forward to an arbitrary percentage
- **THEN** the rig updates immediately while the Web Worker restores the nearest preceding SDF snapshot and replays intervening steps asynchronously

### Requirement: Current-stock rapid and shank collision diagnostics
The simulator SHALL evaluate both `is_rapid` moves (`RAPID_COLLISION`, heated region plus unheated bodies) and cutting-move unheated tool bodies (`SHANK_COLLISION`) against the **current** carved SDF stock state using threshold `sdf < -0.5 * voxel_size`. The unheated bodies are the ⌀`2·shaft_radius_mm` shaft over $[\text{heated\_length}, 75]$ mm, the ⌀`2·body_radius_mm` cartridge body over $[75, 140]$ mm, and the explicitly dimensioned tilt-head box or capsule hull. All axial spans are measured from the tool reference point along `−u`; dimensions and poses are recorded in `machine_geometry.json` and sampled in the tool frame defined by `blade-tool-model`.

#### Scenario: Rapid through already-carved pocket succeeds while uncarved rapid fails
- **WHEN** an `is_rapid` traverse passes through voxels previously subtracted by roughing
- **THEN** no `RAPID_COLLISION` error is raised, whereas an `is_rapid` traverse entering uncarved stock (`sdf < -0.5 * voxel_size`) raises `RAPID_COLLISION`

#### Scenario: Unheated shank intersecting uncarved overhang raises shank collision
- **WHEN** a $\phi$-tilted cutting pose causes the shaft, cartridge body, or tilt-head envelope to enter uncarved stock (`sdf < -0.5 * voxel_size`)
- **THEN** the simulator emits a `SHANK_COLLISION` diagnostic with the offending frame index and the body name (`shaft`, `body`, or `head`)

### Requirement: Carved SDF surface fidelity on reachable target regions
The zero-isosurface of the carved `VolumetricWaxGrid` after a complete `demo` or `standard` trajectory SHALL match reachable target face surface points within `2.0 * voxel_size`.

#### Scenario: Completed carve approximates target face
- **WHEN** a full roughing + finishing trajectory finishes on `VolumetricWaxGrid`
- **THEN** sampled points on reachable regions of the target face mesh exhibit $|\text{sdf}(\vec{p})| \le 2.0 \cdot \text{voxel\_size}$

### Requirement: CAD-derived carver rig with orbiting ring and static wax
The web viewer SHALL replace `PrimitiveCarverRig` with `CadCarverRig` (`static/cad_rig.js`). It loads `static/models/{static,orbit,z,radial,tilt,unassigned}.glb` into a nested link hierarchy `static ⊃ orbit ⊃ z ⊃ radial ⊃ tilt` inside the existing `-90°` X-rotated root group. Per frame it SHALL set only:
- the `orbit` rotation about machine Z by `+theta`
- the `z` translation by `h − cad_reference_pose.h`
- the `radial` translation along the orbit link's local `+X` by `r − cad_reference_pose.r`
- the `tilt` rotation about the pivot axis (from `machine_geometry.json`) by `phi`

These use `.position.set` / `.rotation.set` / pre-baked pivot offsets only, with no kinematic trigonometry in JS. The wax stock mesh SHALL be parented to `static` and SHALL NOT rotate. `unassigned` parts SHALL be rendered ghosted (parented to `static` at their CAD placement), with an on-screen note listing their names. `stock_placeholder` parts SHALL NOT be rendered. If any GLB fails to load, the viewer SHALL fall back to rendering only the tool (from `tool_model` constants) and the wax, and show a non-blocking error.

#### Scenario: Rig tip coincides with the backend reference point
- **WHEN** a trajectory is played and paused at 20 frames sampled across `demo`, including frames with φ ≠ 0 and r < 0
- **THEN** the world position of the cartridge's lowest-point marker in `CadCarverRig` matches the frame's `tip_xyz_wax` (mapped through the root group) within 0.1 mm

#### Scenario: Wax stays still while the ring orbits
- **WHEN** θ advances by 90° during playback
- **THEN** the wax mesh's world transform is unchanged and the orbit link's world rotation about Z has changed by 90°


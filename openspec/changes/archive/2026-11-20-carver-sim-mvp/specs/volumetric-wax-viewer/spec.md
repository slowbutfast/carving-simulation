# volumetric-wax-viewer Specification

## Purpose
Define the Three.js primitive 4-DOF rig, playback/scrub transport, Web Worker chunked volumetric SDF Marching Cubes wax subtraction, current-stock rapid/shank collision diagnostics, and carved surface fidelity.

## ADDED Requirements

### Requirement: Primitive 4-DOF kinematic rig and transport controls driven by backend poses
The web viewer SHALL render a primitive 4-DOF carver rig (turntable platter, Z-column, radial arm, $\phi$ wrist pivot in the local $r$–$Z$ plane, and conical-bevel iron tip) inside a `-90°` X-rotated root group (mapping machine `+Z` up to Three.js `+Y` up), driven exclusively by Python-sampled joint poses and `tip_xyz_wax` / `tool_axis_wax` without duplicating kinematic trigonometry in JavaScript. The viewer SHALL provide `Play/Pause`, `Scrub`, `1x–20x` speed, and `Carve to End` controls, and SHALL auto-pause on `RAPID_COLLISION`, `SHANK_COLLISION`, or `SOFT_LIMIT_EXCEEDED`.

#### Scenario: Playback animates joints from sampled trajectory without JS trig
- **WHEN** the user runs a `demo` or `standard` sculpt-and-sim job and presses Play
- **THEN** `THREE.Clock` advances the simulation timeline, updates the platter (`-theta`), Z-carriage (`h`), radial arm (`r`), and wrist $\phi$ transforms from backend poses, and maintains interactive frame rates

### Requirement: Chunked volumetric SDF wax subtraction with undercut and scrub support
The web viewer SHALL represent the cylindrical wax stock (`R_stock`, `H_stock`) in a Web Worker (`wax_worker.js` wrapping `wax_sdf_core.js`) as a 3D float32 grid (default `128³` partitioned into `16³` chunks) initialized to the exact Euclidean cylinder SDF for $z \in [0, H_{\text{stock}}]$ with $\ge 2$ voxels of exterior padding on all sides. Each step SHALL subtract the axisymmetric conical-bevel + `melt_kerf_mm` frustum (`tip_radius_mm`, `cone_half_angle_deg`, `engaged_length_mm`, `melt_kerf_mm`) using `max(sdf, -d_tool)`, mark touched chunks and adjacent boundary-neighbor chunks dirty, and remesh via Marching Cubes with a 1-voxel apron and global SDF gradient normals. Periodic SDF snapshots SHALL allow backward/forward scrubbing without freezing the main thread.

#### Scenario: Undercut carving updates dirty chunks and neighbors without seams
- **WHEN** a $\phi$-tilted finishing segment sweeps beneath a nose or chin overhang across a chunk boundary
- **THEN** `wax_sdf_core.js` subtracts the tilted conical-bevel envelope, marks both the touched chunk and adjacent boundary-sharing chunks dirty, preserves upper overhang voxels (`sdf < 0` above the cavity within `1e-3` tolerance), and produces a seam-free Marching Cubes mesh

#### Scenario: Scrubbing restores from nearest SDF snapshot
- **WHEN** the user drags the timeline scrubber backward or forward to an arbitrary percentage
- **THEN** the rig updates immediately while the Web Worker restores the nearest preceding SDF snapshot and replays intervening steps asynchronously

### Requirement: Current-stock rapid and shank collision diagnostics
The simulator SHALL evaluate both `is_rapid` moves (`RAPID_COLLISION`) and cutting-move unheated shank volumes (`SHANK_COLLISION`, cylinder over $[L_{\text{tip}}, L_{\text{tip}} + L_{\text{shank}}]$ of radius `shank_radius_mm`) against the **current** carved SDF stock state using threshold `sdf < -0.5 * voxel_size`.

#### Scenario: Rapid through already-carved pocket succeeds while uncarved rapid fails
- **WHEN** an `is_rapid` traverse passes through voxels previously subtracted by roughing
- **THEN** no `RAPID_COLLISION` error is raised, whereas an `is_rapid` traverse entering uncarved stock (`sdf < -0.5 * voxel_size`) raises `RAPID_COLLISION`

#### Scenario: Unheated shank intersecting uncarved overhang raises shank collision
- **WHEN** a $\phi$-tilted cutting pose causes the unheated shank cylinder $[L_{\text{tip}}, L_{\text{tip}} + L_{\text{shank}}]$ to enter uncarved stock (`sdf < -0.5 * voxel_size`)
- **THEN** the simulator emits a `SHANK_COLLISION` diagnostic with the offending frame index

### Requirement: Carved SDF surface fidelity on reachable target regions
The zero-isosurface of the carved `VolumetricWaxGrid` after a complete `demo` or `standard` trajectory SHALL match reachable target face surface points within `2.0 * voxel_size`.

#### Scenario: Completed carve approximates target face
- **WHEN** a full roughing + finishing trajectory finishes on `VolumetricWaxGrid`
- **THEN** sampled points on reachable regions of the target face mesh exhibit $|\text{sdf}(\vec{p})| \le 2.0 \cdot \text{voxel\_size}$

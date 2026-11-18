# volumetric-wax-viewer Specification

## Purpose
Define the Three.js primitive 4-DOF rig, playback transport, volumetric SDF Marching Cubes wax subtraction, and current-stock collision diagnostics.

## ADDED Requirements

### Requirement: Primitive 4-DOF kinematic rig driven by backend poses
The web viewer SHALL render a primitive 4-DOF carver rig (turntable platter, Z-column, radial arm, $\phi$ wrist pivot in the local $r$–$Z$ plane, and conical-bevel iron tip) driven exclusively by Python-sampled joint and tip poses without duplicating kinematic trigonometry in JavaScript.

#### Scenario: Playback animates joints from sampled trajectory
- **WHEN** the user loads or runs a sculpt-and-sim job and presses Play
- **THEN** `THREE.Clock` advances the simulation timeline and updates the platter, Z-carriage, radial arm, and wrist $\phi$ transforms at each frame

### Requirement: Volumetric SDF wax subtraction with undercut support
The web viewer SHALL represent the cylindrical wax stock as a chunked 3D signed-distance voxel grid meshed via Marching Cubes, subtracting the swept conical-bevel + `melt_kerf_mm` envelope along each distance-sampled step so $\phi$-axis undercuts are visibly carved.

#### Scenario: Undercut carving removes overhanging wax
- **WHEN** a $\phi$-tilted finishing segment sweeps beneath a nose or chin overhang
- **THEN** the volumetric SDF updates only the affected dirty chunks and renders the carved undercut cavity without collapsing vertical overhangs

### Requirement: Current-stock rapid collision diagnostics
The simulator SHALL evaluate `is_rapid` moves against the **current** carved SDF stock state and emit a `RAPID_COLLISION` diagnostic only when a rapid move intersects remaining uncarved wax.

#### Scenario: Rapid through already-carved pocket succeeds
- **WHEN** an `is_rapid` retract or traverse passes through voxels previously subtracted by roughing
- **THEN** no `RAPID_COLLISION` error is raised, whereas traversing uncarved stock raises `RAPID_COLLISION`

## ADDED Requirements

### Requirement: Deterministic STEP extraction into derived machine artifacts
`scripts/extract_machine.py` SHALL read `assets/Wax+Face+Carver+v2.stp` through `cadquery-ocp` (dev-only, listed in `requirements-cad.txt`) and write `machine_geometry.json` plus one GLB per link (`static`, `orbit`, `z`, `radial`, `tilt`, `unassigned`) under `static/models/`. It SHALL:
- Force the STEP reader output unit to millimetres and record the source unit found in the STEP header (`source_length_unit`).
- Transform CAD coordinates into the machine frame by `(x, y, z)_cad → (x, −z, y − seat_y_cad)`, where `seat_y_cad` is the stock seat plane height in the CAD frame. Record the transform matrix and `seat_y_cad` in `machine_geometry.json`.
- Produce byte-identical `machine_geometry.json` across repeated runs on the same STEP and OCP version, and record the STEP file's SHA-256 and the OCP version.

No runtime module (`server.py`, `kinematics.py`, `toolpath_sim.py`, `tool_model.py`, any `static/*.js`) SHALL import `OCP` or read the STEP file.

#### Scenario: Extraction converts units and frames
- **WHEN** the extractor runs on the committed STEP
- **THEN** `machine_geometry.json` reports `source_length_unit: "cm"`, the base plate diameter measures 700.0 ± 0.1 mm, and the orbit axis is the machine Z axis through (0, 0)

#### Scenario: Extraction is deterministic and traceable
- **WHEN** the extractor runs twice on the same inputs
- **THEN** both `machine_geometry.json` outputs are byte-identical and carry the same `step_sha256` and `ocp_version`

#### Scenario: Runtime never depends on OCP
- **WHEN** the runtime test suite runs in an environment without `cadquery-ocp` installed
- **THEN** every runtime test passes or is unaffected, and a static import scan of runtime modules finds no `OCP` import

### Requirement: Explicit CAD part-to-link role mapping with unassigned reporting
The extractor SHALL assign every CAD leaf occurrence to exactly one link via the committed `cad_part_roles.json`. The file holds ordered name-prefix rules mapping to `static | orbit | z | radial | tilt | stock_placeholder | unassigned`. Any occurrence that matches no rule SHALL be assigned `unassigned`. All `unassigned` and `stock_placeholder` occurrences SHALL be listed by name in `machine_geometry.json`. `Cold_Tool_6mm_Shank` SHALL be mapped to `unassigned`, and `Wax_Block_Cast_120x100x56` to `stock_placeholder`. Neither SHALL contribute to kinematic constants, collision bodies or wax subtraction.

#### Scenario: Unknown and placeholder parts are reported, not dropped
- **WHEN** extraction completes
- **THEN** `machine_geometry.json.unassigned_parts` contains `Cold_Tool_6mm_Shank:1`, `stock_placeholder_parts` contains `Wax_Block_Cast_120x100x56:1`, and the sum of per-link occurrence counts equals the 295 leaf occurrences in the STEP

#### Scenario: New CAD part without a rule surfaces as unassigned
- **WHEN** a STEP revision adds an occurrence whose name matches no rule in `cad_part_roles.json`
- **THEN** that occurrence appears in `unassigned_parts` and the extractor's summary output names it

### Requirement: CAD-derived kinematic constants and travel evidence with provenance
`machine_geometry.json` SHALL contain, each with a `provenance` string naming the CAD parts and measurement used:
- `pivot_to_tip_mm` (tilt pivot axis to tool reference point)
- `pivot_radial_offset_mm` (tool axis to pivot axis, measured perpendicular to the axis in the tilt plane)
- `tangential_tool_offset_mm` (tool axis to the radial line through the orbit axis)
- `r_travel_mm` from radial stop faces minus carriage half-length
- `h_travel_mm` from Z stop parts and the carriage-to-pivot offset
- `theta_travel_deg` from the orbit stop block
- `cad_reference_pose` (the joint values of the CAD pose as modelled)

`home_pose` SHALL be `null` until confirmed by the owner. Values the extractor could not compute SHALL be `null` with a `reason`, never defaulted.

#### Scenario: Constants match the verified CAD measurements
- **WHEN** extraction completes on the committed STEP
- **THEN** `pivot_to_tip_mm` = 60.0 ± 0.05, `pivot_radial_offset_mm` = 0.0 ± 0.05, `tangential_tool_offset_mm` = 0.0 ± 0.05, `r_travel_mm` = [−51.0, 135.0] ± 0.5, and `cad_reference_pose` = {r: 0.0, theta_deg: 0.0, phi_deg: 0.0, h: 151.0 ± 0.05}

#### Scenario: Home pose is never inferred from the CAD pose
- **WHEN** `machine_geometry.json` is generated
- **THEN** `home_pose` is `null` and `cad_reference_pose` is reported separately

### Requirement: Link meshes in the machine frame within a size budget
Each link GLB SHALL contain that link's CAD parts in the machine frame at the link's joint-zero placement (the `cad_reference_pose`), with mesh node names equal to the CAD occurrence names. The total size of `static/models/*.glb` SHALL be ≤ 8 MiB, controlled by per-link tessellation tolerance. The `tilt` link's cartridge SHALL be tessellated at a linear deflection ≤ 0.02 mm.

#### Scenario: Link meshes reassemble the CAD pose
- **WHEN** all link GLBs are loaded with identity link transforms
- **THEN** the T12 cartridge's lowest point lies at the tool reference point recorded in `machine_geometry.json` within 0.05 mm, and the summed size of the GLBs is ≤ 8 MiB

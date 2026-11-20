## Why

The owner's CAD (`assets/Wax+Face+Carver+v2.stp`) contradicts the machine `carver-sim-mvp` simulates (research.md → Superseded claims):

- **Tool:** the tool is a rectangular **blade** (1.2 × 6.0 × 14.0 mm), not an axisymmetric cone.
- **Pivot:** p is 60 mm, not 30, and the radial offset is 0, not 45.
- **Motion:** the wax is static and an **orbit ring** carries the tool.
- **Travel:** r is signed and crosses the orbit axis, and θ is bounded by a stop block.

Every toolpath, reachability and collision result from the MVP is computed for a machine that doesn't exist. More agent rounds on PATCH-10 can't fix that, so this has to come next.

## What Changes

- **CAD extraction pipeline (new, dev-only).** `scripts/extract_machine.py` reads the STEP through `cadquery-ocp` (in `requirements-cad.txt`, never imported at runtime). It converts cm → mm and the Y-up CAD frame → the machine frame, then writes two committed outputs:
  - `machine_geometry.json`: kinematic constants, tool geometry and travel evidence, each with CAD provenance.
  - One GLB per link (`static`, `orbit`, `z`, `radial`, `tilt`).

  A committed `cad_part_roles.json` maps CAD part names to links. Unmatched parts are reported as `unassigned`, never dropped silently.
- **BREAKING (kinematics datums).** These change:
  - θ is the orbit-ring angle (θ = θ_ring, no platter term).
  - r is signed, measured to the tilt pivot axis.
  - h is the pivot height above the stock seat plane.
  - `arm_radial_offset_mm` and `arm_to_pivot_z_mm` become 0.
  - p = 60.
  - Limits come from CAD stop faces.

  The FK equations keep their form.
- **BREAKING (tool model).** These change:
  - The conical-bevel profile is replaced by a blade prism plus kerf (the heated region), a ⌀5 shaft, the ⌀7 cartridge body, and a tilt-head envelope (collision bodies).
  - The "tip apex" becomes the **tool reference point** (blade bottom-face centre).
  - `tool.*` cone keys are removed.
  - A Python `tool_model.py` is the single definition. The JS SDF stamp mirrors its constants, which come from `machine_geometry.json`.
- **Toolpath generator (modified).** These change:
  - CC→CL placement uses the tool's support function instead of `ρ + kerf` along n.
  - Reachability is decided by body-collision checks instead of the closed-form cone bound (β ≤ φ_max − α).
  - Engaged-length sampling uses the blade's minimum heated dimension.
  - Cutting moves that feed the 6 mm face broadside emit `BLADE_BROADSIDE_FEED`.

  Undercut finishing is otherwise unchanged in scope. Redesigning it for the blade is a follow-up change.
- **Viewer (modified).** `PrimitiveCarverRig` is replaced by a `CadCarverRig` that loads the link GLBs. The **orbit link** rotates by θ while the wax stays static. Unassigned parts render ghosted and excluded from interaction. Zero kinematic trig in JS is kept.
- **Wax SDF (modified).** The heated-region subtraction becomes an oriented inflated-box SDF in the tool frame. The cylindrical stock SDF is kept (the owner confirmed a cylindrical block, dimensions configurable).
- **Assets.** `assets/Wax+Face+Carver+v2.stp` is committed as the source of truth. The STL is git-ignored (derived, nameless soup).

## Capabilities

### New Capabilities

- `machine-cad-model`: STEP → derived machine geometry (frames, units, link roles, kinematic constants, travel evidence, tool geometry, link meshes), its provenance, determinism, and the `unassigned`/reference-pose rules.
- `blade-tool-model`: The blade tool definition: tool frame, heated-region SDF, collision bodies, support-function CC→CL placement, and broadside-feed classification.

### Modified Capabilities

These capabilities are introduced by `carver-sim-mvp`, which is not yet archived. This change archives after it.

- `carver-kinematics`: Orbit-ring θ, signed r to the pivot axis, h to the pivot, CAD-derived constants and limits, and the tool reference point in place of the cone apex.
- `face-sculpt-sim`: Support-function CL placement, collision-based reachability, blade-based sampling bound, and the `BLADE_BROADSIDE_FEED` diagnostic.
- `volumetric-wax-viewer`: CAD link rig with orbiting ring and static wax, blade-box SDF subtraction, and shaft/head collision bodies.

## Impact

- **Prerequisite (met):** `carver-sim-mvp` merged to `main` on 2026-11-19 as squash commit `98ac91d` (PR #1), including cone-based undercut finishing with one test marked `expectedFailure` (PATCH-10f). This change is implemented from `main` and **replaces** every piece of that code that encodes `p = 30` or cone geometry. Removing the `expectedFailure` on `test_finishing_follows_planar_contours` is an exit criterion.
- **New:**
  - `scripts/extract_machine.py`, `requirements-cad.txt`
  - `cad_part_roles.json`, `machine_geometry.json`
  - `tool_model.py`
  - `static/models/{static,orbit,z,radial,tilt,unassigned}.glb`
  - `static/cad_rig.js`
  - `tests/test_machine_cad.py`, `tests/test_tool_model.py`
- **Modified:**
  - `machine_config.json` (loads its geometry from `machine_geometry.json`, keeps feeds/stock/presets)
  - `kinematics.py`, `toolpath_sim.py`, `server.py` (`tool_cfg` schema)
  - `static/app.js`, `static/wax_sdf_core.js`, `static/wax_worker.js`
  - `tests/test_carver_sim.py`, `tests/test_wax_sdf.mjs`
  - `.gitignore`
- **Removed:** `static/machine_rig.js` (`PrimitiveCarverRig`), and the cone keys `tool.tip_radius_mm`, `cone_half_angle_deg`, `engaged_length_mm`, `tip_width_mm`, `shank_*`.
- **Dependencies:** `cadquery-ocp==8.0.1.1.0` as dev-only. No new runtime dependency.
- **Open owner questions carried in the artifacts:**
  - Is the pivot the horn axis or `Dowel_3x37`?
  - What is `Cold_Tool_6mm_Shank`?
  - What is the home pose?
  - What are the stock cylinder dimensions?
  - What is the T12-K heated length?

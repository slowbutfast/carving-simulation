## Source material

**2026-11-18, project owner (chat, verbatim):**

> "i'm not sure i how i got this far without realized, but let's pause and begin integrating the actual model into the design. i just uploaded the .stp file at @assets/Wax+Face+Carver+v2.stp , and i'll upload the stl shortly. can you begin analyzing it, along with the current version of the pr to begin intgrating it into the simulation?"

> "the stl has also been uploaded at @Wax+Face+Carver+v2.stl"

**2026-11-19, project owner (chat, verbatim):**

> "i updated the models with @assets/Wax+Face+Carver+v2(1).stl and @assets/Wax+Face+Carver+v2(1).stp . can you update the openspec change with these updates in mind (not totally sure what the differences are, if at all, between the two models)"

Result: both `(1)` files are byte-identical to the originals (see Verified facts → STEP identity), so the geometry, constants and roles in this change are unaffected. If a CAD edit was intended, it did not make it into the export (for example, exported from an unsaved Fusion version).

> "the blade in the cad is the real thing. we're carving a cylindrical block. i'm not sure what cold_tool is. i'm not sure if its in the home position. can you fast forward openspec artifacts on main for a change integrating the real model?"

**Earlier (same conversation, PR #1 review):** "and by model i mean the actual 3d model of the tool can be uploaded". The `carver-sim-mvp` proposal deferred "CAD `.glb` visual skinning" to a later change; this is that change, widened because the CAD contradicts core MVP assumptions (see Superseded claims).

### Raised but not acted on

- **`Wax_Block_Cast_120x100x56` (the rectangular block in the CAD).** Owner states the real stock is a cylindrical block. The CAD block is treated as a placeholder and excluded from simulation geometry. Cylinder dimensions are not in the CAD and stay configurable (`stock.R_stock_mm`, `stock.H_stock_mm`).
- **`Block_Fixture_PLA`.** Its pocket is shaped for the rectangular placeholder, so it is rendered but not used as a collision keep-out until a cylinder fixture exists in CAD.
- **`Cold_Tool_6mm_Shank`.** Owner does not know its purpose. It is extracted, rendered as an `unassigned` part and reported, but excluded from kinematics, collision and wax subtraction.
- **CAD pose as home.** Not confirmed. The CAD pose is recorded as `cad_reference_pose`, and `home_pose` stays `null`.
- **Undercut-finishing strategy redesign.** The cone-based finishing merged in `98ac91d` has its geometry primitives swapped for `tool_model.py` by this change. Redesigning the finishing *strategy* for a blade (pass direction, slice-oriented contours) is a separate follow-up change.
- **Machine self-collision** (arm vs column, tilt head vs bracket across full φ, ring vs stop block). Out of scope, apart from extracting the stop positions as limit evidence.
- **The uploaded STL.** It is a 241,970-triangle single soup with no part names. Not used as an input.

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| CAD frame | The STEP assembly frame: Y up, mm after unit conversion, orbit axis on the Y axis through the origin, column toward +X. | The machine/wax frame used by `kinematics.py` (Z up). |
| Machine frame | The right-handed, Z-up frame of `carver-sim-mvp`. Mapped from the CAD frame by `(x, y, z)_cad → (x, −z, y)` (+90° about X), with z = 0 moved to the stock seat plane. | The Three.js frame (the viewer still applies its −90° X root rotation). |
| Stock seat plane | The plane the bottom face of the wax stock rests on (CAD y = 3.0 for the placeholder block). It is z = 0 of the machine frame. | The top of `Block_Fixture_PLA`, or the top of `Pedestal_PLA`. |
| Orbit ring | The rotating platform (`Platform_Ring_Seg*`) that carries column, Z carriage, arm, rail and tilt head about the vertical orbit axis. | A rotary platter under the wax. The wax does not rotate. |
| θ (theta) | Orbit ring angle. θ = 0 when the column lies on machine +X. With a static platter, θ = θ_ring and θ_s = θ. | Platter angle, or −θ_platter. |
| r | Signed horizontal distance from the orbit axis to the tilt pivot axis along e_r(θ). Negative r places the tool on the far side of the axis. | An unsigned radius ≥ 0, or the carriage position measured from the rail end. |
| h | Height of the tilt pivot axis above the stock seat plane. | The Z-carriage block height, or the leadscrew nut height. |
| Tilt pivot | The MG90D-270 servo output axis: horn centre at CAD (x = 0, y = 154), axis along CAD Z = machine ∓e_θ. | `Dowel_3x37` (at CAD x = 14, y = 154, purpose unverified). |
| Blade | The 1.2 × 6.0 × 14.0 mm rectangular prism at the bottom of `T12_K_Cartridge`: 1.2 along the tilted radial axis, 6.0 along e_θ, 14.0 along the tool axis, square end. | A cone, a bevelled knife, or anything axisymmetric. |
| Tool reference point | The centre of the blade's bottom face (CAD (0, 94, 0) in the CAD pose). It replaces the "conical-bevel tip apex". | The blade's corner, or the cartridge centroid. |
| Tool frame | Right-handed orthonormal (a_n, a_w, u): u = tool axis toward the reference point, a_w = e_θ (blade width), a_n = a_w × u (blade thickness/normal). At φ = 0, a_n = −e_r; the blade thickness axis is unoriented, so ±e_r describe the same CAD axis. | A frame that spins about u. Nothing rotates the blade about its own axis. |
| Heated region | The blade prism inflated by `melt_kerf_mm`: the volume that removes wax. | The ⌀5 shaft, the ⌀7 body, or the holder. |
| Broadside feed | A cutting move whose direction is mostly along a_n, pushing the 6 mm face through wax. | Slicing along a_w, or plunging along u. |
| Link | A rigid group of CAD parts moved by one joint: `static`, `orbit` (θ), `z` (h), `radial` (r), `tilt` (φ). | A single STEP body. |
| Unassigned part | A CAD part whose link role is unknown (currently `Cold_Tool_6mm_Shank`). | A part that is deleted or ignored silently. |

## External research

| Source | What it establishes | Licence | Accessed |
| :--- | :--- | :--- | :--- |
| `cadquery-ocp` 8.0.1.1.0 (PyPI), OpenCASCADE Python bindings | Reads STEP AP214 with assembly names and placements (`STEPCAFControl_Reader` + XCAF `XCAFDoc_ShapeTool`), tessellates B-rep (`BRepMesh_IncrementalMesh`). | LGPL-2.1 (OCCT) / Apache-2.0 (bindings); used as a dev-only tool, not linked into the runtime. | 2026-11-18 |
| OCP 8.0.1 binding quirks | `TDF_LabelSequence` is not exposed. Use `TDF_ChildIterator` with `IsComponent_s` / `IsFree_s`. `Bnd_Box.Get()` fails to bind: use `CornerMin()/CornerMax()`. `TopoDS.Face_s` is `TopoDS.Face`. | — | 2026-11-18 |
| Inigo Quilez, "distance functions" (box SDF) | Exact Euclidean SDF of an oriented box: `q = |p| − b; length(max(q,0)) + min(max(q.x,max(q.y,q.z)),0)`. Inflating by k is `sdBox − k` (a rounded box). | Formulas (not copyrightable); no code copied. | 2026-11-18 |
| Support-function placement of convex bodies (standard computational-geometry result) | A convex body touching a plane with outward normal n at point c has its support point s(−n) at c. This lets one CL-offset formula cover any convex tool. | — | 2026-11-18 |

## Candidate tech

| Option | Decision | Reason | Date |
| :--- | :--- | :--- | :--- |
| `cadquery-ocp` in a dev-only `requirements-cad.txt` | **Adopted** | Only option here that keeps STEP names and placements. Kept out of `requirements.txt` so the server never imports it. | 2026-11-18 |
| Full `cadquery` package | Rejected | Pulls a much larger stack. We only need the reader and the mesher. | 2026-11-18 |
| `gmsh` / `cascadio` | Rejected | `cascadio` drops the assembly tree we need for link roles. `gmsh` is heavier with no gain. | 2026-11-18 |
| Using the uploaded STL | Rejected | Single soup, no part names, no link separation. | 2026-11-18 |
| Mesh decimation library (`fast-simplification`, `open3d`) | Rejected | Triangle budget is controlled by per-link OCP tessellation tolerance instead, so no extra dependency. | 2026-11-18 |
| Git LFS for `assets/` | Rejected for now | `git lfs` is not installed in this environment. The STEP (5.8 MB) is committed directly, and the STL is git-ignored. | 2026-11-18 |
| `trimesh` GLB export | **Adopted** | Already a runtime dependency; writes GLB with no extras. | 2026-11-18 |
| networkx / scipy-dependent trimesh paths (`section`, `split`) | Rejected | networkx is disallowed (carver-sim-mvp constraint). `intersections.mesh_plane` covers what we need. | 2026-11-18 |

## Patterns adopted

- **Derived-artifact pipeline.** CAD is the source of truth. A deterministic offline script writes committed JSON/GLB artifacts, and runtime code reads only those. Lands in `scripts/extract_machine.py` → `machine_geometry.json` + `static/models/*.glb`.
- **Analytic oriented-box SDF** (Quilez) for the heated region in `wax_sdf_core.js` and for collision sampling in Python.
- **Support-function CC→CL placement** for convex tools in `tool_model.py`.

## Verified facts

| Claim | Value | How verified | Date | Volatility |
| :--- | :--- | :--- | :--- | :--- |
| STEP identity | SHA-256 `00882f0ebeaeaae66b7b8eb28e4d2dc9bbf30d65c2d66705f86deec566fd7bd0` (5,792,081 bytes). The 2026-11-19 re-upload `Wax+Face+Carver+v2(1).stp` is byte-identical, and so is `(1).stl` (`35c8462d…`). The second parse also gives 295 leaves. | `sha256sum` on both pairs + OCP re-parse | 2026-11-19 | decays (CAD revisions) |
| STEP schema / origin | AP214 (`AUTOMOTIVE_DESIGN`), Autodesk Translation Framework v15.17 (Fusion export), top product `Wax Face Carver v2 v54` | STEP header + `PRODUCT` entities read as text | 2026-11-18 | decays (CAD revisions) |
| STEP length unit | centimetre (`SI_UNIT(.CENTI.,.METRE.)`). OCP with `xstep.cascade.unit = MM` returns mm. | Header text, plus base plate measures exactly 700.0 mm after conversion | 2026-11-18 | stable |
| Assembly size | 295 placed leaf occurrences, 212 `MANIFOLD_SOLID_BREP`, flat top-level structure (no sub-assemblies carry link meaning) | OCP XCAF walk (`step_tree.py`) | 2026-11-18 | decays |
| CAD up axis | +Y (base plate at y = −131, column top at y ≈ 347) | Placed bboxes | 2026-11-18 | stable |
| Orbit axis | CAD Y axis through origin | Ring segments at ±121.9 symmetric in X and Z; wax placeholder centred at (0, 0) | 2026-11-18 | stable |
| Wax is static | Wax placeholder sits on `Block_Fixture_PLA` on `Pedestal_PLA`, which stands on the base plate, not on the ring | Placed bboxes and stacking order | 2026-11-18 | stable |
| Blade geometry | 1.2 (CAD X) × 6.0 (CAD Z) × 14.0 (CAD Y) mm, constant section from apex to 14.0 mm, square end | `mesh_plane` sections every 0.25 mm on the OCP-tessellated cartridge (watertight, 1528 faces) | 2026-11-18 | stable (owner: "the blade in the cad is the real thing") |
| Blade orientation | 1.2 mm thickness along radial (CAD X), 6.0 mm width along tangential (CAD Z = e_θ at θ = 0) | Same sections | 2026-11-18 | stable |
| Cartridge profile above blade | ⌀5.0 round from 14 to 75 mm, ⌀7.0 from 75 to 140 mm, ⌀5.5 above 140 mm (socket end at y = 246) | Same sections (r_max = half-width ⇒ round) | 2026-11-18 | stable |
| Tool reference point (CAD pose) | (0.0, 94.0, 0.0) | Cartridge bbox min y | 2026-11-18 | decays |
| Lowest non-cartridge tool-head part | Tilt bracket min y = 140.6, servo 143.2, holder 146.0 ⇒ about 46.6 mm of bare blade + shaft below the head | Placed bboxes | 2026-11-18 | decays |
| Servo horn centre | CAD (0.0, 154.0), horn plate normal along CAD Z | Horn bbox 20 × 20 × 2 mm with thin axis Z | 2026-11-18 | decays |
| Tool axis lies on the radial line through the orbit axis | Cartridge centred at CAD z = 0, while the rail and carriage sit at CAD z = 45 (bracket offsets the tool by 45 mm tangentially) | Placed bboxes | 2026-11-18 | decays |
| Radial carriage vs tool axis | Carriage centre x = 0.0 = cartridge x in the CAD pose | Placed bboxes | 2026-11-18 | decays |
| Radial rail span | CAD x ∈ [−75, 195] (MGN12, 270 mm). Carriage length 35 mm. | Placed bboxes | 2026-11-18 | stable |
| Radial stop faces | Inner stop face x = −68.5, outer stop face x = 152.5 ⇒ carriage centre ∈ [−51.0, 135.0] before bumper compliance | `Radial_Stop_M_PLA` bboxes | 2026-11-18 | decays |
| Orbit stop | `Stop_Block_PLA` + `Orbit_Limit_Switches` on the static side at CAD x ≈ −240 (θ ≈ 180° from the column) ⇒ orbit travel is bounded, not continuous | Placed bboxes | 2026-11-18 | decays |
| Wax placeholder | 120 (X) × 56 (Y) × 100 (Z), bottom at y = 3.0, top at y = 59.0 | Placed bbox | 2026-11-18 | superseded for stock (owner: cylinder) |
| Uploaded STL | Binary, 241,970 triangles, mm, Y-up, extents 770 × 601 × 700 | trimesh load | 2026-11-18 | stable |

## Unverified assumptions

- **The tilt pivot is the servo horn axis.** `Dowel_3x37` sits parallel at CAD x = 14, y = 154 and could be a hinge pin. If it is, the tool axis is offset 14 mm from the pivot and FK needs a lateral pivot offset. To check: owner confirmation, or test-sweep the tilt link about both candidate axes and see which leaves the holder / bracket screw holes concentric.
- **Only the blade is heated** (the shaft and body are unheated collision bodies). To check: the T12-K datasheet's heated length, or a thermal measurement. Kept configurable as `tool.heated_length_mm = 14.0`.
- **Which parts belong to the tilt link** (holder, cartridge, socket, horn, `HW_Tilt` screws) and which stay on the radial link (bracket, servo body). Inferred from names and adjacency. To check: owner review of `cad_part_roles.json`.
- **Z travel limits.** `Z_Bottom_Switch_Clamp_U_PLA` (y 9–33) and `Z_Top_Stops_TPU` (y 285.5–289) bound the carriage, but the carriage-to-pivot offset at each stop has not been computed. To check: extraction script, about 1 h.
- **Tilt (φ) limits.** MG90D-270 gives 270° of servo travel, but holder/bracket/wax interference limits are unmeasured. Current `phi_limits_deg = [−60, 75]` is carried over unverified.
- **Orbit (θ) limits** from the stop block geometry: about ±170° estimated, not computed.
- **The cylindrical stock is centred on the orbit axis and seated at the placeholder's seat plane (CAD y = 3.0).** To check: owner, or a cylinder fixture in a later CAD revision.

## Superseded claims

| Previously believed (carver-sim-mvp) | Why wrong | Replaced by |
| :--- | :--- | :--- |
| `pivot_to_tip_mm = 30` | CAD pivot y = 154, reference point y = 94 | p = 60.0 (subject to the dowel assumption) |
| `arm_radial_offset_mm = 45` (radial) | The tool axis is radially aligned with the pivot and carriage. The 45 mm offset is tangential (rail at CAD z = 45) and the bracket cancels it. | x = 0. Tangential offset is a rendering detail of the bracket, not a kinematic term. |
| `arm_to_pivot_z_mm = 25`, h measured to the arm datum | Arbitrary datum with no CAD anchor | h measured to the pivot axis (h2 = 0) |
| `r ∈ [0, 120]` unsigned | The rail crosses the orbit axis | signed r ∈ [−51, 135] from stop faces |
| `theta_limits_deg = null` (continuous) | Orbit stop block and limit switches exist | bounded θ (values to be extracted) |
| θ = θ_ring − θ_platter, rotating platter | The wax is static and the ring orbits | θ = θ_ring |
| Axisymmetric conical-bevel tip (tip_r 0.5, α 30°, engaged 8) | The CAD blade is a rectangular prism, confirmed real by the owner | blade prism 1.2 × 6.0 × 14.0 + kerf |
| Shank: cylinder r 3, len 40 | CAD shaft ⌀5 (r 2.5) from 14 to 75 mm, holder from about 52 mm | shaft r 2.5 + cartridge body + tilt-head envelope |
| Sampling bound `Δs ≤ 0.5 · tip_width (1.6)` | No `tip_width` exists for a prism | `Δs ≤ 0.5 · (blade_thickness + 2·kerf)` |

## Links out

- `openspec/changes/carver-sim-mvp/` (specs, architecture, patch.md PATCH-01…10d). The MVP this change amends.
- PR #1: https://github.com/slowbutfast/carving-simulation/pull/1 (`feat/carver-sim-mvp`).
- `assets/Wax+Face+Carver+v2.stp`: the source-of-truth CAD.

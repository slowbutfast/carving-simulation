# Owner questions (tasks 7.1 / 7.2)

These are the questions a headless agent cannot answer. Everything else in the
change is complete; these two tasks stay unticked pending the owner.

1. **Tilt pivot axis.** Is the wrist pivoting about the MG90D-270 servo horn
   axis (CAD x = 0, y = 154; the current extraction,
   `machine_geometry.json.pivot_candidates[0]`), or about the `Dowel_3x37` at
   CAD x = 14.03, y = 153.99 (`pivot_candidates[1]`)? The dowel would add a
   14.03 mm radial pivot offset (`arm_radial_offset_mm`).
2. **Cylindrical stock dimensions.** What are the real stock radius and height?
   The current values are `R_stock_mm = 40`, `H_stock_mm = 120`, carried over
   from the MVP and marked unverified. The CAD contains only the rectangular
   placeholder block.
3. **Home pose.** Is the as-exported CAD pose the machine home? It is recorded
   as `cad_reference_pose` (`{r: 0, theta: 0, h: 151, phi: 0}`), while
   `home_pose` stays `null`.
4. **`Cold_Tool_6mm_Shank`.** What is it for? It is extracted, rendered ghosted
   as `unassigned`, and excluded from kinematics, collision and wax removal.
5. **T12-K heated length.** Is the whole 14 mm blade heated? `heated_length_mm`
   defaults to the blade length (14.0) and is capped there.
6. **Roles sign-off (7.1).** Review `cad_part_roles.json` and
   `joint-sweep.json` (every joint swept through its travel, with the rig deltas
   the viewer applies). No part should move with the wrong link. `unassigned`
   currently contains exactly `Cold_Tool_6mm_Shank:1` and `Dowel_3x37:1`;
   `stock_placeholder` contains `Wax_Block_Cast_120x100x56:1`.

To answer: edit `cad_part_roles.json` / `machine_config.json` and regenerate
`machine_geometry.json` with
`.venv-cad/bin/python scripts/extract_machine.py` — never hand-edit the
generated artifact.

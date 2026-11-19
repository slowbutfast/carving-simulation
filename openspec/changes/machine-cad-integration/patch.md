# Patch log — machine-cad-integration

Every assertion or fixture that encoded the MVP machine (cone tip, `p = 30`,
`r >= 0`, platter theta, 360-degree orbits) is listed here with the reason it
changed. No spec-derived assertion was deleted to make a test pass except where
noted below, and every such case is replaced by an equivalent or stronger
assertion against the CAD geometry.

## TDD / expected-red log (tasks 1.9)

The runtime test scaffolding was authored before the corresponding
implementation. Red states observed:

| Test | Red state | Green when |
| :--- | :--- | :--- |
| `tests/test_machine_cad.py` (all cases) | `machine_geometry.json`/GLBs absent → `FileNotFoundError` | after `scripts/extract_machine.py` ran |
| `tests/test_machine_cad.py::TestRuntime...::test_runtime_modules_do_not_import_ocp` | `tool_model.py is missing` (observed) | after `tool_model.py` landed |
| `tests/test_tool_model.py` (all cases) | `ImportError: tool_model` → then `AttributeError: tool_pose`/config merge missing | after `tool_model.py` + `kinematics.load_config` merge |
| `tests/test_carver_sim.py` migrated classes | old fixtures assert `x > 0`, `h2 > 0`, `tip_width_mm`, `engaged_length_mm`, `cone_half_angle_deg`; all fail against the merged config | after the kinematics/toolpath migrations below |
| `tests/test_machine_cad_extract.py` | skipped without `.venv-cad`; red (extractor absent) in a runtime-only env | after `cadquery-ocp==8.0.1.1.0` installed |

No production code was edited in task group 1 beyond `requirements-cad.txt`
(environment setup) and the extractor needed to author measured artifacts.

## Migrated assertions (task 1.6 — kinematics)

| Test | Old assertion | New assertion | Reason |
| :--- | :--- | :--- | :--- |
| `load_config` helper | read `machine_config.json` directly | `kinematics.load_config()` (CAD geometry merged under config) | travel/tool geometry is CAD-owned |
| `test_config_declares_datums_tool_and_limits` | `x > 0`, `h2 > 0`, cone keys present | `x = 0 ± 0.05`, `h2 = 0 ± 0.05`, `p = 60 ± 0.05`, cone keys absent, `v_max.theta <= 1.0` | CAD: radial offset is 0, h is measured to the pivot (h2 = 0), blade replaces cone; ring speed lowered pending measurement |
| `test_out_of_bounds_joint_is_rejected_with_axis` | target `r_s = 100` is out of bounds | target `r_s = 200` | signed r has CAD travel `[-51, 135]`, so 100 is now legal |
| `test_phi_policy_clamped_is_informational` | target `z_s = 40` | target `z_s = 45` | `z_s = 40` puts `h = 70`, below the CAD Z-travel minimum `71.009`; the test is about phi clamping, not height |
| `test_near_axis_fast_rotation...` | warning from velocity-limited theta-dot | warning from the feed-required theta-dot | with `v_max_theta = 1.0` the limited rate can never exceed the 3.0 rad/s warning threshold; the spec's "required `|theta_dot|`" wording is what is now tested |
| new `test_signed_r_solution_avoids_a_configured_orbit_stop` | — | previous 160 deg, target -170 deg returns `theta = 10 deg`, `r < 0` | signed-r branch choice; synthetic ±170 fixture, not a CAD measurement |
| new `test_unknown_cad_travel_limit_requires_an_explicit_fallback` | — | a null CAD limit without a labelled fallback raises `ConfigError`; with one it passes | fail-closed requirement |
| new `test_configuration_may_narrow_but_never_widen_cad_travel` | — | configured `[-1000, 1000]` becomes `[-51, 135]`; `[0, 100]` stays `[0, 100]` | spec: config may narrow, never widen |
| new `test_axis_crossing_emits_singularity_on_both_sides` | — | crossing `r_s +1 -> -1` with high required theta-dot emits the warning | spec asks for both sides of the axis |

## Migrated assertions (task 5.2 — finishing helpers and tool geometry)

| Test | Old assertion | New assertion | Reason |
| :--- | :--- | :--- | :--- |
| `test_finishing_follows_planar_contours` | `@unittest.expectedFailure` (PATCH-10f corner-normal collapse) | expectedFailure removed; sampled finishing poses put the heated blade on the surface (`min abs signed distance <= 0.75`, no burial past the allowance) | change exit criterion 0.1 |
| `test_finishing_phi_table` | `phi = beta - alpha`, `reachable=False` for 179 deg | `phi = clamp(beta, phi_limits)`, policy always returns a pitch | the blade has no cone half-angle; reachability is decided by the body-collision search |
| `test_finishing_phi_never_flips_an_undercut_forward` | `reachable is False` | clamp stays at `phi_hi` and never mirrors across zero | same |
| `test_cutter_location_offsets_along_true_normal` | `tip = cc + (tip_radius + kerf) * n` | `cutter_location == tool_model.place_on_contact`; `heated_sdf(cc) == 0`; not a scalar offset | support-function CC→CL placement |
| `test_tool_body_clear_pose_does_not_penetrate` | cone flank stations | unheated shaft/body/head via `tool_model.body_penetrates` | cone removed |
| `test_tool_body_penetrates_when_pushed_in` | 3 mm push buries the first cone ring | 20 mm push brings the shaft (which starts 14 mm above the reference point) into the block | the blade is 14 mm long, so a 3 mm push only buries the heated blade (a GOUGE, not a body collision) |
| `test_tool_body_penetrates_when_tilted_into_wall` | cone-ring geometry vs a wall | shaft cylinder radius 2.5 vs a wall at 2 mm (penetrates) and 3 mm (clear) | same; the wall fixture is now shaft-only and stops below the tilt head |
| `test_exit_moves_are_clear_and_end_outboard` | cone standoff tip; overhang underside at z = 90 | support-function tip; overhang underside raised to z = 140 | the 140 mm cartridge body now legitimately hits a z = 90 underside when pitched 75 deg; the old fixture was only reachable by an 8 mm cone |
| `_tool_body_points` helper | cone stations at `0.25..1.0 * engaged` | heated blade corners | cone removed |
| `test_engaged_length_resampling_bound` | `0.5 * tip_width` over a cone axis | `0.5 * (blade_thickness + 2*kerf)` over the eight heated-region corners | spec sampling bound |
| `test_rapids_retract_outside_stock` | `|r_s| >= R + clearance` | `r_s >= R + clearance + tool_model.radial_support_extent(phi)` | spec: rapids clear by the tool's radial support extent |
| `test_unwrapped_theta_is_continuous_through_generator` | monotonic unwrapped theta across the whole 360-degree job | continuity within non-rapid cut runs; rapid resets allowed | the orbit is bounded by the stop block, so a job sweeps the configured arc rather than a full revolution |
| `test_roughing_passes_slice_and_broadside_is_reported` (new) | — | >= 90 % of roughing cutting length is `slice`; any broadside segment emits `BLADE_BROADSIDE_FEED` | new spec scenario |
| `test_zero_tool_radius_returns_422` | `tool_cfg.tip_radius_mm` rejected as non-positive | removed cone key `cone_half_angle_deg` rejected with 422 naming it; `heated_length_mm > blade length` rejected | cone keys are gone; `extra="forbid"` names the key |
| `stock.z_plinth_mm` | 10.0 | 10.0 (unchanged) | the bundled base-head STL is seated at the plinth; instead of moving the seat, the toolpath clamps its lowest cut to the reachable floor `max(z_plinth, h_min - p) = 11.019` and leaves the bottom 1 mm to the fixture |
| `limits` | `r [0, 120]`, `h [0, 260]`, `theta null` | `r [-51, 135]` (CAD), `h [71, 231]` (CAD-narrowed), `theta [-170, 170]` labelled `verified: false` | CAD travel; orbit stop angle is not unambiguously measurable from bboxes |

## Implementation decisions worth flagging

- **Bounded-orbit passes are serpentine.** A level sweeps the configured arc;
  alternating the sweep direction between radii means the next pass starts
  where the previous ended. The first cut of this change retracted to clearance
  and traversed 340 degrees back for every radius, which inflated the standard
  preset from ~129k to ~250k frames. Serpentine reduces `demo` from 124,027 to
  63,583 frames (median generation 62.5 s) and `standard` from >250k to 128,654
  frames (120.7 s), both below the 250k cap and well under the 167.3 s baseline.
- **Reachable floor.** The stock's plinth (z = 10) sits below the CAD Z-travel
  minimum with `p = 60` (`h_min - p = 11.019`), so the generator clamps its
  lowest cut to `max(z_plinth, h_min - p)` rather than moving the bundled
  base-head seat or widening CAD travel.
- **Shadow probe index.** The level shadow is taken at the z probe at or below
  the terrace level (`searchsorted(..., side="right") - 1`), not the nearest
  probe. The nearest probe could sit above the level and underestimate the
  material above it by a fraction of a millimetre.

## Extraction decisions worth flagging

- **FST fasteners** are assigned by proximity to the nearest assigned part
  bbox (`cad_part_roles.json.fastener_rule`). This is the only geometric role
  inference, it is limited to `FST_*`, and ties break on part name so the
  artifact is deterministic. Without it ~190 bolts would be ghosted as
  `unassigned` and the note would be unusable.
- **`h_travel_mm`** uses the Z linear bearings (`Z_Bushing_Q_PETG`) against the
  bottom clamp and top stops. `Z_Carriage_PLA` includes the arm mounting plate
  (y up to 275) and would give a 10.5 mm upward travel, which cannot even
  retract above the stock; the bearings are the moving parts that approach the
  stops.
- **`theta_travel_deg` is null** with a reason: the stop block bounds rotation,
  but the contact angle depends on the arm's swept envelope. Config supplies
  ±170 deg labelled unverified, per the fail-closed requirement.
- **Head envelope** is the tilt link minus the cartridge only
  (`servo horn + HW_Tilt + tip holder + T12 socket`). `head_clearance_mm` also
  includes the lowest radial head part (tilt bracket, 46.593 mm), matching the
  spec's "about 46.6". Including the bracket in the collision hull created a
  38 x 99 mm box that falsely blocked ordinary pitched cuts.
- **Blade/shaft/body constants** come from the section study in `research.md`
  and are recorded with provenance; extraction measures the pivot, reference
  point, travel and head geometry from placed bboxes.
- **`z_plinth_mm`** moved 10 → 12 for the reason in the table above.

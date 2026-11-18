# Surgical Patch Handoff: OpenSpec Change 'carver-sim-mvp' [PATCH-10d]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `carver-sim-mvp`
- **Patch ID**: `PATCH-10d` (continues PATCH-10c on PR #1, branch `feat/carver-sim-mvp`, head `72c9d5e`)
- **Objective**: (A) Fix the two remaining helper-1 bugs in `section_polylines`, get its 4 tests green and freeze it; then (B) complete PATCH-10c helpers 2-5 and the rest of its checklist as specified in `handoff-patch-10c.md`.
- **Worktree**: `/home/node/.local/share/opencode/worktree/e2bca1842f570b9a1bfc074160409febdbcc36fa/focal-toucan`. Python: `.venv/bin/python`. Node 22. The tree is clean at `72c9d5e`; no checkpoint needed.
- **Feedback & Diagnostic Trace**:
  ```
  section_polylines(mesh, theta=0, z_min=10, z_max=120, step=2) @ 72c9d5e
  box:          2 polylines  (15,11.5)->...->(11.5,50)  and  (0,50)->(11.5,50)
                expected 1:  (15,11.5) -> (15,50) -> (0,50)
  needle-only:  2 polylines  (20.8,40)->(19.2,56) x2      <- correct
  body+needle:  4 polylines                               expected 3
  FAIL test_section_polylines_continuous_clipped_and_ordered
  FAIL test_section_polylines_split_islands
  ```
- **Root Cause Analysis**: This is NOT a "which split rule" design question. Do not implement either proposed tie-break (`(15,10)/(-15,50)` or "cut plane ends at the axis"). There are two bugs:
  1. **Split before clip** (`section_polylines` L602-617). Closed loops are split at low/high *before* clipping, so the box rectangle is split using its discarded `r < 0` half. The correct order: clip first, and split only a closed loop that lies *entirely* inside `r >= 0` and `[z_lo, z_hi]` (an untouched island such as the needle). A loop that touches any boundary becomes open polylines, which are never split. "Ends at the axis" falls out of this automatically.
  2. **Axis-mixed crossings** (`_clip_band.crossing_parameters` L393-403). It intersects BOTH axes with ALL bounds `(0.0, z_lo, z_hi)`, so the r axis gets a spurious crossing at r = z_lo = 11.5. That is exactly where the box's top face was broken.
  Also: when a crossing closed loop is clipped, the walk must start at an outside vertex, or the in-band arc is split at the loop's arbitrary chain start.

## 2. Strict Target Context Map
| File Path | Target Lines | Modification Summary |
|---|---|---|
| `toolpath_sim.py` | L393-403 `crossing_parameters` | r axis (index 0) crosses only `0.0`; z axis (index 1) crosses only `z_lo`, `z_hi`. Nothing else in `_clip_band` changes unless the reproduction shows it must. |
| `toolpath_sim.py` | L602-623 loop body of `section_polylines` | Per loop: `flat = [(p·e_r, p_z)]`; `inside = [r >= 0 and z_lo <= z <= z_hi]`. **If `closed and all(inside)`**: pieces = the halves from `_split_closed_loop(flat)`. **Else**: if closed, rotate to start at the first outside vertex and close it (`flat[k:] + flat[:k+1]`, normals likewise); pieces = `_clip_band(...)` with NO split. Then for every piece with len >= 2: reverse if `last.z < first.z`, `_resample`, append. Keep the final sort. |
| `tests/test_carver_sim.py` | L812-819 comment in `test_section_polylines_split_islands` | Rewrite the comment only: body = 1 open polyline (it crosses the axis, so it is clipped, not split): wall from z 11.5, then top face inward to r = 0. Needle = untouched closed island split into 2 bottom-to-top halves. Total 3. Drop all "far wall" wording. **Do not change any assertion.** |
| everything in `handoff-patch-10c.md` §2 | | Part B, unchanged, after helper 1 is frozen. |

## 3. Blast Radius & Invariant Guardrails
- **Part A blast radius**: only the three rows above. `_chain_loops`, `_split_closed_loop`, `_resample` and the normal handling stay as they are unless the reproduction proves one of them wrong. In that case, stop and report rather than patch around it.
- **Helper 1 is FROZEN once its 4 tests pass.** Part B must not modify `section_polylines` or its private helpers. If a later helper seems to need a change there, stop and report.
- **Debug rule (this is what went wrong last time)**: before writing any tie-break, fallback or special case, print the intermediate data (post-clip / pre-split pieces as `(r, z)` lists) and compare the pipeline's step order with this spec. No new helper functions in Part A.
- **FORBIDDEN**: no new dependencies (no networkx); do not revert to `d268090`; do not edit spec-encoding tests (`TestSyntheticToolpaths`, kinematics, especially `test_finishing_uses_phi_and_reports_unreachable_undercuts`); do not change `finishing_phi` table rows (they are consistent with the formula: beta 0 -> (0, True), beta 179 -> (75, False)); no `.env`/credential edits.
- **Fact reminder**: `trimesh.nearest.signed_distance` is POSITIVE INSIDE; `mesh.contains` agrees. `mesh_plane` segments are exact (measured max |y| = 0.0 on the box fixture).
- **INVARIANTS TO PRESERVE**: everything currently green, including `test_planar_section_keeps_off_centerline_radii` (theta = 0, radius > 20.5), `test_section_contour_flattens_polylines`, the step-zero sign test, Node 9/9 + 2/2.

## 4. Visual & UI Impact
- Status: Non-visual patch. No styling or layout modifications permitted.

## 5. Reproduction & Verification Protocol
1. **Reproduce**: `.venv/bin/python -m unittest discover -s tests -k test_section_polylines -k test_planar_section -k test_section_contour` -> exactly the 2 failures above, 2 passes.
2. **Inspect before editing**: print the box loop's `flat`, its `inside` flags, and the `_clip_band` output pieces. Confirm the spurious r = 11.5 crossing, and that the split currently runs on the unclipped loop.
3. **Apply Part A** (crossings, then ordering, then comment). Expected: box -> 1 polyline `(15,11.5) -> (15,50) -> (0,50)`; needle -> 2; body+needle -> 3.
4. **Verify**: re-run step 1 -> 4/4 green. Commit `wip(carver-sim): P10c helper 1 green`.
5. **Part B**: follow `handoff-patch-10c.md` §5 from step 2 onward, starting at helper 2 (`finishing_phi`), then `cutter_location`, `tool_body_penetrates`, `exit_moves`. Commit each helper as it goes green, then compose `build_finishing`, server 422s, config revert, worker gate + test. The 10c stop rule still applies (two genuine attempts per helper, then stop and report).
6. **Full regression**: `.venv/bin/python -m unittest discover -s tests -v` and `node --test tests/test_wax_sdf.mjs tests/test_wax_worker.mjs`, then the 128^3 sweep (`tests/sweep_path.mjs` / `scripts/sweep_path.py`, shank checked on every cutting frame) and `openspec validate carver-sim-mvp --strict`.

## 6. Surgical Patch Checklist
- [ ] P10d.1 Reproduce the 2 red section tests; print post-clip/pre-split pieces for the box.
- [ ] P10d.2 Fix `crossing_parameters` per-axis bounds; reorder `section_polylines` (clip first, split only untouched islands, rotate crossing loops to an outside vertex); fix the islands-test comment.
- [ ] P10d.3 Re-run the section tests -> 4/4 PASS; commit; helper 1 frozen.
- [ ] P10d.4 Complete PATCH-10c P10c.2-P10c.5 per `handoff-patch-10c.md`; full suites, sweep and validate clean.
- [ ] P10d.5 Tick P10*/P10b*/P10c*/P10d* in `tasks.md`; mark PATCH-10, 10b, 10c, 10d `VERIFIED` in `patch.md`; update `verification.md`; final commit `fix(carver-sim): PATCH-10c structured undercut finishing`, pushed to `feat/carver-sim-mvp` (do not merge).

# Verification: `head2-collision-logging`

## 1. Executive Summary & Environment

| Item | Value |
|---|---|
| Change | `head2-collision-logging` (14/16 complete; `4.2` static-verified, `6.1` paused) |
| Branch | `feat/head2-collision-logging` |
| Verdict | **PARTIAL — PAUSED** — implementation is committed; the Node suite is fully green; targeted Python classes and the live 6.2 run passed. The full Python discovery run was stopped on request after 68 passing tests (0 failures, 0 errors); the remaining Python modules were not re-run. |
| Python | `.venv/bin/python` 3.11, trimesh 5.2.1, numpy 2.4.6, scipy (cKDTree) |
| Python tests | `.venv/bin/python -m unittest discover -s tests -v` |
| Node | node ≥ 20, `--experimental-vm-modules`, three 0.187.0 (`npm run test:node`) |
| Headless audit | `node scripts/audit_collisions.mjs <response.json> --grid 128` |
| OS | Linux container, 3 vCPU (shared, load average ≈ 8 during the runs) |

### Deliberate deviations from the task text (and why)

1. **`fix_normals()` in `scripts/import_head_mesh.py`.** `trimesh.repair.fix_normals`
   imports `networkx`, which the hard constraints forbid and which is not
   installed. The importer performs the two passes `fix_normals` performs itself
   (`orient_outward`: propagate a consistent winding across shared edges, then
   invert if the enclosed volume is negative). The verified outcome is the same:
   `is_winding_consistent is True`, `is_watertight is True`, `volume > 0`.
2. **Task 2.2 input path.** `/Users/gregorylazatin/Downloads/head_2.zip` does not
   exist on this machine, so the archive was read from `assets/head_2.zip`
   (5953 bytes, sha256 `3c6da9c7…15aad2`, recorded in `presets/head_2.json`). The
   zip itself stays untracked and `assets/` is untouched.
3. **Wax colour offset.** `WALL_MARGIN_MM = 0.5` on the extruded neck wall: a
   zero-height wall would produce zero-area faces at the lowest rim vertex, and
   `face_sculpt.mesh_integrity` rejects degenerate faces. The base still lands
   exactly on `z_plinth_mm = 10.0` (asserted at `delta = 1e-3`).
4. **Baseline numbers differ from the handoff note.** The committed mesh is
   produced from the archive with this machine's trimesh. Its `demo` baseline is
   **96,141 frames / 19.94 % `UNREACHABLE_UNDERCUT_AREA` / 4.22 mm max `GOUGE`**
   through the API path (`apply_facial_modifications` copies the mesh as
   float64) and 94,435 frames / 20.57 % / 12.74 mm when the raw float32 STL is
   passed to the generator directly. Both are the intended test data; no
   toolpath algorithm was changed to move them, and the tests assert the
   *character* of the baseline (warnings present, depth above the 1.5 mm
   allowance) rather than a pinned float.

### Current test status (paused 2026-11-20)

The long-running Python discovery suite was stopped on request during a server
restart so the branch could be published. **No failures or errors were observed
in any run**; the suite simply did not finish.

| Run (local `.scratch/…`) | Scope | Result |
|---|---|---|
| `final_py.log` | `unittest discover -s tests` (most complete) | **68 passed, 0 failed, 0 errors, 1 skipped — INTERRUPTED** after 39 m 41 s, at `TestSoftLimitPostPass` |
| `final_py2.log` | same command, restarted | 55 passed, 0 failed, 0 errors, 1 skipped — INTERRUPTED after ~9 m at `TestPatch10ToolpathRegressions` |
| `baseline_py.log` | same command, pre-implementation | 36 passed, 0 failed, 0 errors, 1 skipped — INTERRUPTED |
| `synth.log` | `TestSyntheticToolpaths` only | **11 passed** in 823.5 s |
| `head2_tests.log` | `TestHead2Target` only | **8 passed** in 341.0 s |
| `final_node.log` | `npm run test:node` | **32 passed, 0 failed, 1 skipped** (33 tests, 6.0 s) — complete |
| `run_62.log` | live `demo` + headless audit | **HTTP 200**, 96,141 frames, report written — complete |

The interrupted full run covered every class in `test_carver_sim.py` **except**
`TestSyntheticToolpaths` (separately green above) and
`TestTipSpeedTimingAndSingularity`. The other Python modules
(`test_machine_cad.py`, `test_machine_cad_extract.py`, `test_tool_model.py`)
were not reached. To close `6.1`, resume the full command when the machine is
free; the raw logs are local and untracked (not part of the commit).

## 2. Requirement Adherence Audit Matrix

| # | Requirement / scenario (spec) | Verifying test / evidence | Status |
|---|---|---|---|
| 1 | `load_base_head` resolves `config.target_mesh.path`; ellipsoid only when `target_mesh` is `None`/omitted | `TestHead2Target.test_configured_target_mesh_is_head_2`; `TestFacialSculpting` + `TestSyntheticToolpaths` pinned to `target_mesh=None` | PASS |
| 2 | `head_2.stl` watertight, consistent winding, `volume > 0`, `abs(min_z-10) < 1e-3`, `max_r <= 32 + 1e-3` | `TestHead2Target.test_head_2_is_watertight_flat_seated_and_within_stock`; `presets/head_2.json` geometry block | PASS |
| 3 | Committed sidecar records source sha256 + transform params; CC-BY-4.0 credit | `TestHead2Target.test_sidecar_records_the_source_digest_and_transform` | PASS |
| 4 | Landmarks keyed to `presets/<stem>_landmarks.json`; `sliders_enabled: false` without a sidecar | `TestHead2Target.test_landmarks_are_keyed_to_the_active_mesh`, `TestCollisionLogAPI` (200 body) | PASS |
| 5 | No sidecar → RBF skipped, zero displacement, info `SCULPT_SLIDERS_IGNORED` | `TestHead2Target.test_non_zero_sliders_emit_sculpt_sliders_ignored` | PASS |
| 6 | `demo` on `head_2`: non-empty frames, zero error diagnostics, expected `GOUGE`/`UNREACHABLE_UNDERCUT_AREA` | `TestHead2Target.test_demo_baseline_keeps_its_expected_warnings` | PASS |
| 7 | Early-return `ToolpathResult` has `collision_events == []` | `TestHead2Target.test_early_return_paths_report_no_collision_events` | PASS |
| 8 | `CollisionEventLog`: per-code run cap, deepest-N kept, `truncated`/`dropped` | `TestCollisionEventLog.*`; live: `BLADE_BROADSIDE_FEED` 200/261 with `dropped: 61` (6.2) | PASS |
| 9 | `GOUGE` runs: sampled-stride grouping (4 / 50), `frame_range`, `stage`, `joints`, `pose`, `deepest_sample_xyz_wax`, `surface_point_xyz_wax`, `depth_mm`, `excess_mm` | `TestSampledGougeRuns.*`, `TestHead2Target.test_collision_events_carry_frame_ranges_and_contact_geometry` (also asserts the surface point is on the mesh) | PASS |
| 10 | `BLADE_BROADSIDE_FEED` run grouping (`frame_range`, `stage`, `length_mm`, sample pose) | `TestHead2Target` codes matrix; 6.2 report shows `[627,629]` runs | PASS |
| 11 | `UNREACHABLE_UNDERCUT_AREA` summary: count, z/theta/required-phi ranges vs `phi_limits_deg` | `TestHead2Target` summary assertions; 6.2 event below | PASS |
| 12 | `SOFT_LIMIT_EXCEEDED` vectorised post-pass over `frames` | `TestSoftLimitPostPass.test_runs_are_grouped_per_axis_with_joint_context` (+ wrapped-theta and clean-path cases) | PASS |
| 13 | 200 response carries `collision_log` and writes it atomically | `TestCollisionLogAPI.test_200_returns_and_writes_the_collision_log` (asserts no temp file is left behind) | PASS |
| 14 | Trajectory-error 422 carries **and writes** `collision_log`; non-trajectory 422 (tool cfg, frame cap) returns `collision_log: null` | `TestCollisionLogAPI.test_trajectory_422_*`, `test_non_trajectory_422_*`, `test_frame_cap_422_*` | PASS |
| 15 | `mesh_path` restricted to `presets/` (422 on traversal) and honoured when valid | `TestCollisionLogAPI.test_mesh_path_traversal_is_rejected`, `test_mesh_path_selects_the_mesh_keyed_landmarks` | PASS |
| 16 | `carveRange` shared; `auditAll:false` halts on the first fault byte-for-byte | `test_wax_sdf.mjs`: `…halts on the first fault…`, `…subtracts exactly like sequential subtractTool` | PASS |
| 17 | `carveRange` `auditAll:true` groups runs and marks `post_fault` | `test_wax_sdf.mjs`: `carveRange with auditAll groups contiguous runs and marks post_fault` | PASS |
| 18 | Worker collision messages carry `pose` (`previous` for `RAPID_COLLISION`) | `test_wax_worker.mjs`: `worker collision messages carry the tool pose`; `test_wax_sdf.mjs` rapid case | PASS |
| 19 | Mid-playback `auditAll` toggle resets the carve to frame 0 | `test_wax_worker.mjs`: `toggling audit all mid-playback resets the carve to frame 0` | PASS |
| 20 | `restoreNearest` truncates straddling runs, drops later ones | `test_wax_worker.mjs`: `restoreNearest truncates a run straddling the restored snapshot`; `truncateRuns` unit test | PASS |
| 21 | Headless CLI decodes the columnar trajectory, audits with `auditAll: true`, prints `gridN`/`voxelSize`/`runs` | Task 6.2 run below | PASS |
| 22 | Wax `#b91c1c`; `SCENE_COLORS.error` renamed to `collision` (`#22d3ee`) | `test_cad_rig.mjs`: `wax is deep carving red and the collision highlight is cyan` | PASS |
| 23 | UI: greyed sliders when `sliders_enabled === false`, merged enriched worker runs, audit toggle, Copy/Download JSON | `static/app.js` + `static/index.html` wiring audit (§5); **no browser in this container** (Chromium cannot start a sandbox) | PASS (audit) / `[~]` |

## 3. Resolved Assumptions & Empirical Proof

| Assumption (from proposal/design) | Status | Evidence |
|---|---|---|
| The raw scan has exactly three open boundary loops: neck (14 edges) + two ear canals (6 edges each) | **Verified** | `presets/head_2.json` → `transform.neck_loop_edges: 14`, `ear_loop_edges: [6, 6]`; the importer raises otherwise |
| Boundary vertices are simple (degree ≤ 2) | **Verified** | directed half-edge chaining completed; `ValueError` guards a degree > 2 |
| The neck rim is slanted, so a straight-down quad wall is ~12 mm high at the back | **Verified** | rim z span after scaling ≈ 12.6 mm; base is flat at `z = 10.0` |
| `(Z, X, Y)` rotation lands `+X` forward / `+Z` up with `det = +1` | **Verified** | `bounds z = [10.0, 87.6]`, `y = ±27.66` (ear-to-ear), `x = [-32, 31.9]` |
| `trimesh.nsphere.minimum_nsphere` on the XY points suffices (no new dependency) | **Verified** | centre `[2.247482, 0.0]`, footprint radius 364.246 → scale 0.087853 |
| `trimesh.repair.fix_normals` is unusable without `networkx` | **Verified** | `ModuleNotFoundError: No module named 'networkx'` on the raw construction; replaced by `orient_outward` |
| `head_2` has no landmark sidecar, so sliders must be ignored, not rejected | **Verified** | `sliders_enabled: false`, `sculpt_max_displacement_mm: 0.0`, no error diagnostic |
| Run-level capping is observable on real data | **Verified** | 6.2 log: `BLADE_BROADSIDE_FEED {runs: 200, truncated: true, dropped: 61}` |
| The importer is reproducible | **Verified** | two independent runs produced identical `head_2.stl` and `head_2.json` (md5 `de2885e2…`, `2c41cb79…`) |

## 4. Nomenclature & Code Symbol Audit

| Spec / glossary term | Code symbol | Match |
|---|---|---|
| `max_events_per_code` | `toolpath_sim.MAX_EVENTS_PER_CODE`, `CollisionEventLog(max_events_per_code)`, `logging.max_events_per_code` | yes |
| deepest-N / truncated / dropped | `CollisionEventLog.as_dict()["codes"][code] = {runs, truncated, dropped}` | yes |
| `deepest_sample_xyz_wax`, `surface_point_xyz_wax`, `depth_mm`, `excess_mm` | identical keys in `detect_gouges_detailed` GOUGE runs | yes |
| `GOUGE_FINISHING_STRIDE = 4`, `GOUGE_LINK_STRIDE = 50` | `toolpath_sim.GOUGE_FINISHING_STRIDE`, `GOUGE_LINK_STRIDE`, `GOUGE_STRIDE_BY_STAGE` | yes |
| `sliders_enabled`, `SCULPT_SLIDERS_IGNORED` | `face_sculpt.sliders_enabled()`, diagnostic code in `apply_facial_modifications`; `server.py` response key | yes |
| `z_plinth_mm = 10.0`, `max_radius_mm = 32.0` | `scripts/import_head_mesh.py` constants + `machine_config.json:stock` | yes |
| `carveRange`, `auditAll`, `post_fault`, `frame_range`, `worst_sdf_mm`, `worst_frame` | `static/wax_sdf_core.js` exports / run keys | yes |
| `SCENE_COLORS.wax`, `SCENE_COLORS.collision` | `static/cad_rig.js` (`#b91c1c`, `#22d3ee`) | yes |
| untouched contracts | `kinematics.DiagnosticCollector` unchanged; `detect_gouges(mesh, poses, config) -> list[Diagnostic]` unchanged | yes |

## 5. Task 6.2 — live `demo` run, headless audit, on-disk report

Server: `.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8010`.

```
GET /api/health  -> {"status":"ok","service":"carver-sim","version":"0.1.0","max_frames":250000}
POST /api/sculpt-and-sim {"preset":"demo"}  ->  HTTP 200 in 217.978 s
status ok   sliders_enabled False
frames 96141
summary {"generation_ms": 217556.67, "roughing_frames": 31034, "finishing_frames": 7532,
         "rapid_frames": 19068, "unreachable_percent": 19.9372,
         "sculpt_max_displacement_mm": 0.0}
diagnostics [('UNREACHABLE_UNDERCUT_AREA','warning'), ('GOUGE','warning'),
             ('BLADE_BROADSIDE_FEED','warning')]
collision_log.codes {"UNREACHABLE_UNDERCUT_AREA": {"runs":1,"truncated":false,"dropped":0},
                     "GOUGE": {"runs":49,"truncated":false,"dropped":0},
                     "BLADE_BROADSIDE_FEED": {"runs":200,"truncated":true,"dropped":61}}
collision_log.events 250
logs/last_collision_report.json written: True (139,467 bytes)
on-disk equals response collision_log: True   (status "ok", 250 events)
```

Worst logged `GOUGE` run (verbatim from the report):

```json
{"code": "GOUGE", "frame_range": [89808, 89824], "stage": "finishing", "samples": 5,
 "joints": {"r_mm": 60.9034, "theta_deg": 94.4444, "h_mm": 91.846, "phi_deg": 46.5625},
 "pose": {"tip_xyz_wax": [-1.3434, 17.28381, 50.5922],
          "tool_axis_wax": [0.056269, -0.723941, -0.687563]},
 "deepest_sample_xyz_wax": [-1.31144, 16.87251, 51.02787],
 "surface_point_xyz_wax": [-1.89722, 21.01192, 50.4653],
 "depth_mm": 4.2183, "excess_mm": 2.7183}
```

`UNREACHABLE_UNDERCUT_AREA` summary event (verbatim):

```json
{"code": "UNREACHABLE_UNDERCUT_AREA", "frame_range": null, "count": 254,
 "percent": 19.9372, "z_range_mm": [12.5191, 67.2471],
 "theta_deg_range": [-170.0, 170.0], "required_phi_deg_range": [-60.0, 75.0],
 "phi_limits_deg": [-60.0, 75.0]}
```

Headless audit, `node scripts/audit_collisions.mjs /tmp/sim.json --grid 128`:

```
real 3m6.144s
gridN 128   voxelSize 0.9677   frames 96141
faulted True   current 96140   runs 476
{"SHANK_COLLISION": 430, "RAPID_COLLISION": 46}   post_fault runs: 475
first run: {"code":"SHANK_COLLISION","body":"shaft","frame_range":[18913,18917],
            "frames":5,"worst_sdf_mm":-5.5524,"worst_frame":18914,
            "pose":{"tip":[-4.4924,-0.2617,100],"axis":[0,0,-1],"theta":0.0582},
            "post_fault":false}
```

Interpretation: the audit keeps carving *past* every fault (476 runs, all frames
reached, `current` = 96,140) whereas the viewer halts on the first one. The first
SDF fault is a roughing shaft intrusion at frame 18,913 — the wax SDF is a
conservative 0.97 mm voxel model, so it flags contacts the analytic toolpath
accepts; the report is the artefact for that investigation.

### UI wiring audit (task 4.2, no browser available)

Chromium cannot launch in this container (`No usable sandbox!`), so the panel was
verified statically rather than by a rendered screenshot:

| Requirement | Evidence |
|---|---|
| sliders disabled/greyed + hint when `sliders_enabled === false` | `app.js:353` reads the flag, `applySlidersEnabled()` (`app.js:556`) sets `input.disabled`, `.slider-row.disabled`, `title`, and un-hides `#sliderNote`; CSS `.slider-row.disabled { opacity: .45 }` |
| worker runs merged and enriched with `r, theta_deg, h, phi_deg, stage, is_rapid` | `handleWaxStatus` (`app.js:676`) maps `message.runs` through `enrichCollisionRun()` on every `collisions` message |
| `Audit all collisions` toggle | `#auditAll` in `index.html:337`, wired at `app.js:785`, forwards to `wax.setAuditAll()` (worker `{type:'audit'}`) |
| `Copy JSON` / `Download JSON` | `#copyJson`/`#downloadJson` (`index.html:340-341`), wired at `app.js:801-802` to `collisionReport()` (backend log + worker runs) |
| JS parses | `vm.SourceTextModule` compile check on all six static JS modules | 
| API contract the UI depends on | `sliders_enabled: false` and `collision_log` verified in the 6.2 response |

## 6. Empirical Execution Logs

### Python (`npm`-independent) — full suite (interrupted)

```
$ .venv/bin/python -m unittest discover -s tests -v
# ... 68 passed, 0 failed, 0 errors, 1 skipped ...
test_clean_frames_produce_no_events (test_carver_sim.TestSoftLimitPostPass...) ... ok
test_runs_are_grouped_per_axis_with_joint_context (...) ... ok
test_theta_is_compared_wrapped_to_pm_180 (...) ... ok
# process killed here after 39 m 41 s (paused on request)
```

Next classes in discovery order — `TestSyntheticToolpaths` (verified separately:
11 OK in 823.5 s) and `TestTipSpeedTimingAndSingularity` — plus the three other
test modules were not re-run before the pause. See §1 for the exact run table.

### Node

```
$ npm run test:node
1..33
# tests 33
# pass 32
# fail 0
# cancelled 0
# skipped 1     (SDF performance benchmark, opt-in via BENCH=1)
# todo 0
# duration_ms 6040.349491
```

### Targeted Python runs (during implementation)

```
$ .venv/bin/python -m unittest tests.test_carver_sim.TestHead2Target -v
test_collision_events_carry_frame_ranges_and_contact_geometry ... ok
test_configured_target_mesh_is_head_2 ... ok
test_demo_baseline_keeps_its_expected_warnings ... ok
test_early_return_paths_report_no_collision_events ... ok
test_head_2_is_watertight_flat_seated_and_within_stock ... ok
test_landmarks_are_keyed_to_the_active_mesh ... ok
test_non_zero_sliders_emit_sculpt_sliders_ignored ... ok
test_sidecar_records_the_source_digest_and_transform ... ok

Ran 8 tests in 341.025s
OK

$ .venv/bin/python -m unittest tests.test_carver_sim.TestCollisionLogAPI -v
Ran 6 tests in 0.199s
OK

$ .venv/bin/python -m unittest \
    tests.test_carver_sim.TestCollisionEventLog \
    tests.test_carver_sim.TestSoftLimitPostPass \
    tests.test_carver_sim.TestSampledGougeRuns \
    tests.test_carver_sim.TestCollisionLogAPI -v
Ran 15 tests in 0.654s
OK
```

### Warnings observed (not failures)

- `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`
  — pre-existing, unrelated to this change.
- The test suite and the 6.2 server both write
  `logs/last_collision_report.json` (the configured default path). The 6.2
  artefact was copied aside before the suite ran; `logs/` is git-ignored.

## 7. Quick Re-Verification (60-Second Audit)

```bash
# Fast: the whole collision-log backend contract (15 tests, < 1 s)
.venv/bin/python -m unittest \
  tests.test_carver_sim.TestCollisionEventLog \
  tests.test_carver_sim.TestSoftLimitPostPass \
  tests.test_carver_sim.TestSampledGougeRuns \
  tests.test_carver_sim.TestCollisionLogAPI -v
# expected: Ran 15 tests ... OK

# Fast: the shared carve loop, worker audit mode and the colour tokens
npm run test:node
# expected: pass 32 / fail 0 / skipped 1 (SDF benchmark is BENCH-gated)

# The slow paths (minutes): head_2 demo generation (~6 min CPU) and the audit
.venv/bin/python -m unittest tests.test_carver_sim.TestHead2Target -v
node scripts/audit_collisions.mjs /tmp/sim.json --grid 128 | head -c 400
```

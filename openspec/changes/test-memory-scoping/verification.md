# Verification: `test-memory-scoping`

Branch: `feat/test-memory-scoping`
Date: 2026-11-21
Reference container: cgroup v1, 12 GiB limit, 3 vCPU.

## Outcome

| Run | Result | Peak RSS | Wall | Exit |
|---|---|---:|---:|---:|
| `scripts/safe-test.sh` (default tier) | 158 tests, `OK (skipped=19)` | 356 MiB | 254 s | 0 |
| `scripts/safe-test.sh --node` | 32 pass / 0 fail / 1 skip | 127 MiB | 3 s | 0 |
| Task 4.3 heavy tier (prescribed 9,216 MiB floor) | **headroom-blocked**: refused at 4,784 MiB available | — | — | 75 |
| `openspec validate test-memory-scoping --strict` | `valid: true`, 0 issues | — | — | 0 |

```text
safe-test: status=0 peak_rss_mb=356 wall_s=254 tier=default
safe-test: status=0 peak_rss_mb=127 wall_s=3 tier=default
safe-test: available_mb=4784 threshold_mb=9216
safe-test: only 4784 MiB available (< 9216 MiB); refusing to run
```

The 19 default-tier skips are the four OCP-gated extractor tests, the
hardware-calibration fixture test (`tests/fixtures/hardware_poses.json` is not
committed) and the 14 `@heavy` test methods that are collected in this run.

### Task 4.3: headroom-blocked

The prescribed command was attempted twice, including once after PATCH-01:

```bash
RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 \
  SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh
```

It exited `75` both times because the shared container had far less headroom
than the 9,216 MiB floor (4,521 MiB before PATCH-01, 4,889 MiB after PATCH-01,
4,784 MiB for PATCH-02):

```text
safe-test: available_mb=4784 threshold_mb=9216
safe-test: only 4784 MiB available (< 9216 MiB); refusing to run
```

**Task 4.3 therefore stays unchecked.** An *exploratory* heavy run was made
before PATCH-01 with `SAFE_TEST_MIN_AVAIL_MB=2048`; it passed (153 tests,
`OK (skipped=5)`, 5,919 MiB peak, 1,333 s). That override was **below** the
4,521 MiB headroom measured at the time — exactly the risk PATCH-01 fixes — so
it is **not** evidence for 4.3. The runner now enforces
`effective_floor = max(SAFE_TEST_MIN_AVAIL_MB, SAFE_TEST_AS_KB / 1024 + 512)`:
8,704 MiB for the 8 GiB heavy cap, and 9,216 MiB with the prescribed minimum.
**Task 4.3 is formally deferred to the `toolpath-memory` follow-up change.**
That change lowers `build_finishing`'s ~3.3 GB transient so the prescribed
heavy cap and 9,216 MiB floor fit the shared 12 GiB container; 4.3 is its
acceptance gate. If the container reports `>= 9,216 MiB` available before then,
4.3 can be run with the exact prescribed command and this section must be
updated. Until either happens, 4.3 stays unchecked and the default tier remains
the merge gate.

The exploratory heavy run is also labelled historical/do-not-rerun in
`patch.md`: its `SAFE_TEST_MIN_AVAIL_MB=2048` override is now clamped to the
cap-coupled floor.

The default-tier run uses the unmodified `scripts/safe-test.sh` (default floor
4,608 MiB = 4 GiB cap + 512) with no overrides.

## Before / after (default tier)

“Before” is the measured full-suite RSS log quoted in `research.md`
(`scratchpad/rss.log`, 2048-MiB-era run): 4,872 MiB peak, 22 m 14 s
(1,334 s), about 12 full generations, the runner SIGKILLed on the next
base_head `standard` test.

| Metric | Before | After |
|---|---:|---:|
| Peak RSS | 4,872 MiB | **356 MiB** |
| Wall time | 1,334 s (22 m 14 s) | **254 s** |
| Full generations in the default tier | ~12 | **0** |
| Class fixtures freed | no | yes (`tearDownClass` + `gc.collect`) |
| Concurrent runs | overlap, second OOM | serialised by `flock`, second waits |

The spec budget is 1,536 MiB / 600 s; both are met with a wide margin.

## Requirement Adherence Matrix

| Requirement | Implementation | Evidence |
|---|---|---|
| Default and heavy tiers | `tests/_tiers.py` `heavy`; every full-generation test decorated | 14 `@heavy` tests skipped in the default run with reason `heavy test: set RUN_HEAVY_TESTS=1`; the exploratory heavy run executed them (Task 4.3 itself is headroom-blocked, see above); `TestTiers` runs the four default-tier classes under a generator probe |
| No real-target generation by default | Short-stock fixture and stubbed API generation | `TestTiers.test_default_tier_sample_never_generates_on_a_real_target` loads `TestSyntheticToolpaths`, `TestHead2Target`, `TestSimulationAPI`, `TestPatch10APIRegressions`; zero calls match a real target |
| Default budget ≤ 1,536 MiB / 600 s | `tests/_run.py` reports `ru_maxrss`, exits 4 over `SAFE_TEST_BUDGET_MB` | 356 MiB / 254 s; `RunnerTest.test_budget_overrun_exits_4` |
| Budget overrun fails a passing run | `_run.py` returns 4 and prints `BUDGET EXCEEDED` | `RunnerTest.test_budget_overrun_exits_4` |
| Cached fixtures released per class | `ReleasesClassFixtures` mixin in `test_carver_sim.py`, `test_tool_model.py`, `test_machine_cad.py`, `test_machine_cad_extract.py` | `TestFixtureRelease` (weakref dead after `tearDownClass`) |
| Frame cap fails before materialising | `resample_path(..., max_frames=)` checked after each input segment; `generate_synthetic_carve_path` passes `api.max_frames`; post-check kept | `TestResampleFrameCap` (abort ≤ 500 + 2¹¹, identical under cap); `test_max_frames_exceedance_maps_to_422` (real generator, `api.max_frames = 500`) |
| `FrameCapExceededError` contract unchanged | Same class, same `FRAME_CAP_EXCEEDED` diagnostic | `TestResampleFrameCap`, API 422 test |
| `flock` serialisation + waiting message | `exec 9>`, `flock -n` then `flock -w`; message `waiting for <lock>` | `RunnerTest.test_concurrent_runs_queue_and_do_not_overlap` (disjoint intervals), `test_lock_wait_timeout_exits_75` |
| Available memory: v1 → v2 → `MemAvailable`, page cache excluded | Python block in the runner; `SAFE_TEST_CGROUP_ROOT` / `SAFE_TEST_MEMINFO` fixtures | `RunnerTest.test_cgroup_v1_*`, `test_cgroup_v2_*`, `test_cgroup_v2_max_falls_back_to_mem_available` (9,216 / 9,216 / 7,000 MiB) |
| Low memory exits 75 and releases the lock | Floor check before any test; fd released on exit | `RunnerTest.test_low_memory_refuses_and_releases_the_lock` |
| Floor is coupled to the address-space cap | `effective_floor = max(SAFE_TEST_MIN_AVAIL_MB, SAFE_TEST_AS_KB / 1024 + 512)` | `RunnerTest.test_floor_cannot_drop_below_the_address_space_cap` (4,608), `test_floor_is_coupled_to_a_larger_address_space_cap` (6,656) |
| Missing virtualenv is a hard error | `[ -x .venv/bin/python ]` before the memory probe, exit `1` | `RunnerTest.test_missing_virtualenv_exits_1` |
| Python cap + single-threaded BLAS | Soft `ulimit -S -v ${SAFE_TEST_AS_KB:-4194304}`, `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MALLOC_ARENA_MAX=2` | `RunnerTest.test_runaway_allocation_fails_with_memory_error` (6 GiB allocation under the 4 GiB cap → `MemoryError`, non-zero) |
| Target conversion | `_run.py` `tests/<file>.py` → module; dotted names pass | `RunnerTest.test_python_file_targets_become_module_names`, `test_dotted_targets_pass_through` |
| Node under the lock without `ulimit -v` | `--node` lifts the soft cap, sets `NODE_OPTIONS=--max-old-space-size=2048`, runs `npm run test:node` | `RunnerTest.test_node_mode_skips_the_address_space_cap`; `safe-test.sh --node` 32/0/1 |
| Summary line | `_run.py` prints status, peak, wall, tier | `RunnerTest.test_summary_line_format` |
| Agent test policy | `AGENTS.md` + `CLAUDE.md` (`@AGENTS.md`) | Both committed; usage for targeted/default/heavy runs and the prohibitions are present |
| Base_head spike diagnosed (D7) | Capped phase probe, recorded in `patch.md` / `phase-probe.json`; `toolpath-memory` follow-up opened | See below |

## Task 2.1 phase table (D7)

Sculpted base_head `demo`, `SAFE_TEST_AS_KB=6291456`, one run:

| Phase | Wall (s) | RSS before (MiB) | RSS after (MiB) | Peak (MiB) |
|---|---:|---:|---:|---:|
| `build_roughing` | 0.89 | 85.3 | 91.6 | 175.6 |
| `build_finishing` | 184.49 | 91.6 | 272.8 | **3,313.1** |
| `resample_path` | 31.49 | 266.0 | 266.0 | 3,313.1 |
| `build_trajectory` | 1.21 | 266.0 | 266.0 | 3,313.1 |
| `soft_limit_runs` | 0.07 | 266.0 | 266.0 | 3,313.1 |
| `detect_gouges_detailed` | 28.15 | 266.0 | 294.4 | 3,313.1 |

```text
safe-test: status=0 peak_rss_mb=3313 wall_s=247 tier=default
```

**D7 decision:** transient allocation inside `build_finishing` (91.6 MiB
before, 272.8 MiB retained after, 3,313 MiB transient peak). Not fixed here:
no safe single-function O(N·M) defect was identified, and the finishing output
is pinned by invariant tests. Recorded in `patch.md` and opened as the
`toolpath-memory` change. The exploratory heavy run completed under the 8 GiB
cap (5,919 MiB peak); the prescribed Task 4.3 run is headroom-blocked, so its
clean-`MemoryError` fallback path is not exercised yet.

## 4.4 Coverage of assertions removed from the default tier

| Removed / rewritten default assertion | Covered by |
|---|---|
| Real sculpted base_head `demo` invariants in `TestSyntheticToolpaths` (shadow clipping, rapids, cross-axis, finishing phi, resampling bound, broadside, theta continuity, azimuth bins) | `TestSyntheticToolpathsFullTarget` (`@heavy`, inherits every assertion) **and** the short-stock `TestSyntheticToolpaths` equivalent |
| Real-target `test_standard_preset_produces_denser_path` | `TestSyntheticToolpathsFullTarget.test_standard_preset_produces_denser_path` (`@heavy`) **and** the short-stock default copy |
| `TestHead2Target.test_demo_baseline_keeps_its_expected_warnings` (real head_2 `demo`) | `TestHead2ToolpathBaseline` (`@heavy`) |
| `test_collision_events_carry_frame_ranges_and_contact_geometry` (real head_2 `demo`) | `TestHead2ToolpathBaseline` (`@heavy`) |
| Real end-to-end `POST /api/sculpt-and-sim` contract | Default stub with a real `ToolpathResult` (about 60 frames from `kinematics.build_trajectory`) **plus** `TestSimulationAPI.test_demo_post_end_to_end_generates_the_real_target` (`@heavy`) |
| Real-generation geometry provenance | Default stub (provenance comes from the config) **plus** the heavy end-to-end POST |
| `test_max_frames_exceedance_maps_to_422` on 600 mm stock (accepted `SOFT_LIMIT_EXCEEDED` too) | Rewritten on `api.max_frames = 500` with the real generator and the needle fixture; the `SOFT_LIMIT_EXCEEDED` early-return path stays covered by `TestPatch10ToolpathRegressions.test_out_of_bounds_stock_emits_soft_limit_exceeded` |
| Three separate `_FakeNeedle` `demo` generations | One shared `TestPatch10ToolpathRegressions.needle_result` (small fixture, still default tier) |
| `tests/__init__.py` `RLIMIT_AS` ceiling | Removed; the runner's `ulimit -v` is the single enforcement point (`tests/__init__.py` keeps its docstring only) |

`TestHead2Target`'s geometry, sidecar, landmark and slider-ignored assertions
still run in the default tier; only its toolpath assertions moved to the heavy
tier.

## Residual notes

- The runner's floor is coupled to its own cap, so lowering
  `SAFE_TEST_MIN_AVAIL_MB` cannot start a run with less headroom than the
  address space it will allocate: default tier 4,608 MiB (4 GiB + 512), heavy
  tier 8,704 MiB (8 GiB + 512) or the prescribed 9,216 MiB, whichever is
  higher. Earlier in the session the shared container reported 2,811–4,889 MiB  and the runner correctly refused (exit 75); the final default run saw at
  least 4,608 MiB and passed unmodified.
- The Python `ulimit -v` is set as a **soft** limit so a nested `--node` run can
  lift it for V8; `--node` itself never sets an address-space cap.
- `tests/_phase_probe.py` is tooling, excluded from discovery and skipped unless
  `RUN_PHASE_PROBE=1`; run it through `scripts/safe-test.sh` so it shares the
  flock and the cap-coupled memory floor.

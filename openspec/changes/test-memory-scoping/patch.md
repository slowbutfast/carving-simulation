# Patch Evidence: `test-memory-scoping`

## 2.1 Base_head phase probe (D7)

Run once, through the guarded runner, on the sculpted analytic base head
(`{"nose": 1.0, "chin": 0.6, "brow": 0.4}`, `target_mesh=None`, preset `demo`):

```bash
# HISTORICAL / EXPLORATORY — do not rerun.
# Recorded before the cap-coupled floor existed. SAFE_TEST_MIN_AVAIL_MB=2048 is
# now clamped up to AS_KB/1024 + 512 (6,656 MiB for this 6 GiB cap), so the
# runner refuses that command on the shared container.
RUN_PHASE_PROBE=1 SAFE_TEST_AS_KB=6291456 SAFE_TEST_MIN_AVAIL_MB=2048 \
  SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh tests/_phase_probe.py
```

Current guarded invocation (probe lives under `tests/` again):

```bash
RUN_PHASE_PROBE=1 SAFE_TEST_AS_KB=6291456 \
  scripts/safe-test.sh tests/_phase_probe.py
```

Reference container: cgroup v1, 12 GiB limit, 3 vCPU; 3,094 MiB available by the
runner's page-cache-excluded formula at start.

| Phase | Wall (s) | RSS before (MiB) | RSS after (MiB) | Peak RSS (MiB) |
|---|---:|---:|---:|---:|
| `build_roughing` | 0.89 | 85.3 | 91.6 | 175.6 |
| `build_finishing` | **184.49** | 91.6 | 272.8 | **3,313.1** |
| `resample_path` | 31.49 | 266.0 | 266.0 | 3,313.1 |
| `build_trajectory` | 1.21 | 266.0 | 266.0 | 3,313.1 |
| `soft_limit_runs` | 0.07 | 266.0 | 266.0 | 3,313.1 |
| `detect_gouges_detailed` | 28.15 | 266.0 | 294.4 | 3,313.1 |

Verbose summary line:

```text
safe-test: status=0 peak_rss_mb=3313 wall_s=247 tier=default
```

Raw JSON: `phase-probe.json` (written by the probe).

**D7 decision:** the multi-GB peak is a **transient allocation inside
`build_finishing`**: RSS is 91.6 MiB before the phase and 272.8 MiB after it, so
the path state itself is small (about 180 MiB), while the phase peaks at
3,313 MiB. Roughing, resampling, trajectory building and the gouge scan all stay
at or below 294 MiB. No single O(N·M) array with an obviously safe O(M)
replacement was found by inspection; the phi-candidate batches feed
`tool_model.body_penetrates`, and any change there risks changing the pinned
finishing output. Per the D7 rule, the spike is **recorded for the
`toolpath-memory` follow-up change** (`openspec/changes/toolpath-memory/`)
instead of being fixed here. The heavy tier still runs under the 8 GiB cap and
fails cleanly with `MemoryError` if it cannot finish, never by an uncapped
allocation.

## 2.3 Short-stock fixture

`tests/_fixtures.py` builds a 40 mm stock (`H_stock_mm = 40`, plinth at 10 mm,
1 mm top clearance) and sculpts the analytic head at its natural height, then
scales it uniformly (factor 0.3625 for the demo sliders) and seats it on the
plinth. Bounds: `x [-12.32, 11.46]`, `y [-9.42, 9.42]`,
`z [10.00, 39.00]`; watertight.

One `demo` generation on that fixture: **36,415 frames**, **26.4 s**,
**159 MiB** peak RSS in-process; the class run through the runner reports:

```text
Ran 2 tests in 25.598s
safe-test: status=0 peak_rss_mb=179 wall_s=26 tier=default
```

Both are inside the 2.3 target of under 200 MB and under 30 s. Invariants hold:
every one of the 36 azimuth bins has cutting frames, there are negative-`r_s`
frames, and roughing/finishing/rapid stages are all populated.

---

### [PATCH-01] PR #5 Review Fixes: Real-Suite Tier Probe, Floor-to-Cap Coupling & Verification Reconciliation

- **Date**: 2026-11-21 23:43:00 UTC
- **Feedback Source**: Code Review (PR #5 at `d5def8f` — `REQUEST CHANGES`)
- **Feedback Summary**:
  - **Important (3)**:
    1. `tests/test_carver_sim.py:773-805` (`TestTiers.test_default_tier_sample_never_generates_on_a_real_target`): Calls the patched generator itself with the short-stock mesh instead of running the default-tier test classes (`TestSyntheticToolpaths`, `TestHead2Target`, `TestSimulationAPI`, `TestPatch10APIRegressions`) under the probe. Also wastes ~26 s.
    2. `scripts/safe-test.sh:19-25, L118-122` & `AGENTS.md:46-51`: `SAFE_TEST_MIN_AVAIL_MB` is not coupled to `SAFE_TEST_AS_KB`, allowing overrides down to `2048` under 6 GiB / 8 GiB caps (heavy run peaked at `5,919 MiB` with `4,521 MiB` available). Enforce `effective_floor = max(MIN_AVAIL_MB, AS_KB / 1024 + 512)` and forbid lowering `SAFE_TEST_MIN_AVAIL_MB` in `AGENTS.md`.
    3. `openspec/changes/test-memory-scoping/verification.md:27-48` & `tasks.md:28-34`: Correct the heavy-tier note (`2048` is *below* `4,521`, not above), state that Task 4.3's `9216 MiB` command refused to run at `4,521 MiB` headroom, and either run Task 4.3 with `SAFE_TEST_MIN_AVAIL_MB=9216` when headroom allows or mark 4.3 accurately as blocked-by-headroom / deviation.
  - **Nits (4)**:
    4. `tests/test_carver_sim.py:1836+`: Add a cheap stubbed test restoring HTTP 422 `SOFT_LIMIT_EXCEEDED` API mapping coverage.
    5. `scripts/safe-test.sh:53-55`: Hard-fail (`exit 1`) with an explicit message when `.venv/bin/python` is missing instead of returning `75`.
    6. `tests/test_carver_sim.py:498`: Add `"config"` to `TestSyntheticToolpaths._class_fixtures`.
    7. Move `tests/_phase_probe.py` to `scripts/probe_phase.py` (tooling, not a test).
- **Reported Issue / Raw Trace**:
  ```
  PR #5 Verdict: REQUEST CHANGES (d5def8f)
  - TestTiers.test_default_tier_sample_never_generates_on_a_real_target never runs default-tier classes under the probe
  - scripts/safe-test.sh allows SAFE_TEST_MIN_AVAIL_MB=2048 under 8 GiB cap (5919 MiB peak > 4521 MiB avail)
  - verification.md:43 misstates 2048 as "above the measured page-cache-excluded headroom"
  - tasks.md:32 ticks 4.3 despite prescribed 9216 MiB floor refusing to run
  ```
- **Root Cause**:
  - `TestTiers` tested a synthetic self-call rather than loading and running the actual default-tier classes via `unittest.defaultTestLoader`.
  - `scripts/safe-test.sh` checked `AVAIL_MB -lt MIN_AVAIL_MB` independently of `AS_KB`.
- **Target Files**: `scripts/safe-test.sh`, `tests/test_safe_test_runner.py`, `tests/test_carver_sim.py`, `AGENTS.md`, `scripts/probe_phase.py` (moved from `tests/_phase_probe.py`), `openspec/changes/test-memory-scoping/verification.md`, `openspec/changes/test-memory-scoping/tasks.md`
- **Resolution Strategy**:
  - Clamp `effective_floor = max(MIN_AVAIL_MB, AS_KB / 1024 + 512)` in `scripts/safe-test.sh` (plus missing-`.venv` `exit 1` check), add a runner unit test for floor-to-cap clamping, and add the rule to `AGENTS.md`.
  - Rewrite `TestTiers.test_default_tier_sample_never_generates_on_a_real_target` to run `TestSyntheticToolpaths`, `TestHead2Target`, `TestSimulationAPI`, and `TestPatch10APIRegressions` via `unittest.defaultTestLoader` under the generator probe (matching real targets by vertex count), add `"config"` to `_class_fixtures`, and add a stubbed 422 `SOFT_LIMIT_EXCEEDED` test.
  - Reconcile `verification.md` and `tasks.md` 4.3 honestly (run with `9216` floor if headroom permits, else uncheck/document headroom block).
- **Status**: VERIFIED
- **Verification (2026-11-21)**:
  - `scripts/safe-test.sh tests/test_safe_test_runner.py`: 15 tests, OK; the new
    cap-coupled-floor tests (4,608 / 6,656 MiB) and missing-`.venv` exit `1`
    test pass.
  - `scripts/safe-test.sh` (default tier): 157 tests, `OK (skipped=19)`,
    `peak_rss_mb=356 wall_s=226`, exit 0.
  - `scripts/safe-test.sh --node`: 32 pass / 0 fail / 1 skip.
  - `TestTiers` now runs `TestSyntheticToolpaths`, `TestHead2Target`,
    `TestSimulationAPI` and `TestPatch10APIRegressions` under the generator
    probe; the stubbed `SOFT_LIMIT_EXCEEDED` 422 test passes.
  - Task 4.3 attempted with the prescribed `SAFE_TEST_MIN_AVAIL_MB=9216` floor:
    refused at 4,889 MiB available (exit `75`). **4.3 remains unchecked** and is
    documented as headroom-blocked in `verification.md`.
  - `openspec validate test-memory-scoping --strict`: valid, 0 issues.

---

### [PATCH-02] Height-Based `is_real_target` Matcher, Restore Probe Under Runner & Task 4.3 Disposition

- **Date**: 2026-11-22 00:16:00 UTC
- **Feedback Source**: Code Review (PR #5 at `b7979d24` — `REQUEST CHANGES`)
- **Feedback Summary**:
  - **Important (3)**:
    1. `tests/test_carver_sim.py:773-805` (`is_real_target`): Checking all 3D bounds within `1.0 mm` returns `False` when facial sliders shift `base_head` extremes (`max-x` moves `5.6 mm` on `nose=1.0, chin=0.6, brow=0.4`), hiding the exact 3.5 GB OOM case. Match on `(len(vertices), extents[2] within 10%)` and self-test `is_real_target` against sculpted `base_head` (`True`), `head_2` (`True`), and `short_stock_target` (`False`).
    2. `scripts/probe_phase.py:8-14`: Moving the probe out of `tests/` put it outside `scripts/safe-test.sh`, causing its docstring to instruct a raw `ulimit` invocation without `flock` or the memory floor. Move it back to `tests/_phase_probe.py` (gated on `RUN_PHASE_PROBE=1`) and restore the `scripts/safe-test.sh` docstring command.
    3. `openspec/changes/test-memory-scoping/tasks.md:32` & `verification.md`: Task 4.3 remains blocked at `4,889 MiB` vs `9,216 MiB` floor; either run 4.3 if `>= 9,216 MiB` is available, or formally record its waiver/deferral to `toolpath-memory` in `verification.md` (and `architecture.md`/`tasks.md`).
  - **Nit (1)**:
    4. `openspec/changes/test-memory-scoping/patch.md:8-11`: Label the historical `SAFE_TEST_MIN_AVAIL_MB=2048` phase-probe command clearly as historical/exploratory (do not rerun).
- **Reported Issue / Raw Trace**:
  ```
  PR #5 Verdict: REQUEST CHANGES (b7979d24)
  - tests/test_carver_sim.py:782-787: is_real_target returns False for sculpted base_head (max-x shifts 5.6 mm)
  - scripts/probe_phase.py:8-14: raw ulimit invocation skips flock and memory floor
  - tasks.md:32 (Task 4.3): blocked at 4,889 MiB vs 9,216 MiB floor
  ```
- **Root Cause**:
  - `is_real_target` compared full `mesh.bounds` with `atol=1.0`, which breaks under facial slider deformations.
  - Moving `_phase_probe.py` to `scripts/` bypassed `scripts/safe-test.sh` (which only accepts `tests/` targets).
- **Target Files**: `tests/test_carver_sim.py`, `tests/_phase_probe.py` (moved from `scripts/probe_phase.py`), `openspec/changes/test-memory-scoping/patch.md`, `openspec/changes/test-memory-scoping/verification.md`, `openspec/changes/test-memory-scoping/tasks.md`
- **Resolution Strategy**:
  - Update `is_real_target` to match `(len(mesh.vertices), float(mesh.extents[2]))` with `abs(height - expected_h) < 0.1 * expected_h`, and assert `is_real_target` on sculpted `base_head`, `head_2`, and `short_stock_target`.
  - Move `scripts/probe_phase.py` back to `tests/_phase_probe.py` and restore `scripts/safe-test.sh tests/_phase_probe.py` in its docstring.
  - Mark the historical `2048` command in `patch.md` as exploratory/do-not-rerun, and either execute Task 4.3 with `9216 MiB` if free or record its formal deferral to `toolpath-memory` in `verification.md`.
- **Status**: VERIFIED
- **Verification (2026-11-22)**:
  - 3-mesh self-test reproduced the defect first: the bounds matcher returned
    `False` for the sculpted `base_head`; `(vertex count, extents[2])` within
    10% returns `True` for sculpted `base_head` and `head_2`, `False` for the
    short-stock fixture.
  - `scripts/safe-test.sh tests/test_carver_sim.py`: `158 tests, OK
    (skipped=19)`, `peak_rss_mb=356 wall_s=254`, exit 0.
  - `scripts/safe-test.sh --node`: 32 pass / 0 fail / 1 skip.
  - Task 4.3 attempted with the prescribed `SAFE_TEST_MIN_AVAIL_MB=9216` floor:
    refused at 4,784 MiB available (exit `75`). Formally deferred to
    `toolpath-memory` and documented in `verification.md`; 4.3 stays unchecked.
  - `tests/_phase_probe.py` restored under `tests/` with the
    `scripts/safe-test.sh` invocation; the historical `2048` command is labelled
    do-not-rerun in `patch.md`.
  - `openspec validate test-memory-scoping --strict`: valid, 0 issues.

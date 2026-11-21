> Run every test command in this change through `scripts/safe-test.sh` once it exists (task 3.1).
> Until then, run only single targeted test files, in the foreground, never `unittest discover -s tests`, never detached (`nohup`, `setsid`, `&`).

## 1. Test Scaffolding (TDD)

- [x] 1.1 Create `tests/test_safe_test_runner.py` with failing tests for the runner: lock serialisation (disjoint intervals plus the waiting message), lock-wait timeout → 75, cgroup v1 / v2 / `max` / `MemAvailable` available-memory computation through `SAFE_TEST_CGROUP_ROOT` fixtures, the low-memory refusal → 75 with the lock released, target conversion, `MemoryError` under the address-space cap, budget overrun → 4, summary-line format, and `--node` running without `ulimit -v`
- [x] 1.2 Add failing `TestResampleFrameCap` to `tests/test_carver_sim.py`: abort at `max_frames=500` with overshoot ≤ `500 + 2**11`, identical output under the cap, error type and `FRAME_CAP_EXCEEDED` unchanged
- [x] 1.3 Add failing `TestTiers` (no real-target generation without `RUN_HEAVY_TESTS`; heavy skip reason) and `TestFixtureRelease` (weakref dead after `tearDownClass`) to `tests/test_carver_sim.py`
- [x] 1.4 Run 1.1–1.3 as single targeted files in the foreground and confirm they fail for the expected reasons

## 2. Diagnose and Bound the Toolpath Cost

- [x] 2.1 After 3.1 exists, run the phase probe on the sculpted base_head `demo` (`{"nose": 1.0, "chin": 0.6, "brow": 0.4}`, `target_mesh=None`) once through `scripts/safe-test.sh` with `SAFE_TEST_AS_KB=6291456`. Record each phase's time and peak RSS in `patch.md`, and apply the D7 decision rule: fix inside the phase with a memory-asserting regression test, or record it for a `toolpath-memory` follow-up change
- [x] 2.2 Implement the frame-cap fail-early (`resample_path(..., max_frames=None)`, passed from `generate_synthetic_carve_path`, post-check kept) until `TestResampleFrameCap` passes
- [x] 2.3 Add `tests/_fixtures.py` (`short_stock_config()`, `short_stock_target(config, sliders)`; 40 mm stock, base_head scaled and seated to fit) and confirm one `demo` on it is under 200 MB peak and under 30 s, recorded in `patch.md`

## 3. Runner, Tiers and Fixture Release

- [x] 3.1 Create `scripts/safe-test.sh` (executable) and `tests/_run.py` per architecture D5 until `tests/test_safe_test_runner.py` passes
- [x] 3.2 Create `tests/_tiers.py` with `heavy` and the `ReleasesClassFixtures` mixin; apply the mixin to every class that caches a result, mesh, sculpt or `TestClient` (`tests/test_carver_sim.py`, `tests/test_tool_model.py`, `tests/test_machine_cad.py`, `tests/test_machine_cad_extract.py`)
- [x] 3.3 Rewrite `TestSyntheticToolpaths` (including `test_standard_preset_produces_denser_path`) onto the short-stock fixture, and add a `@heavy` real-target copy
- [x] 3.4 Make `TestHead2Target.setUpClass` generation-free; move the head_2 path assertions to the short-stock fixture or `@heavy`
- [x] 3.5 Stub generation in `test_sculpt_and_sim_columnar_contract` and `test_demo_response_carries_geometry_provenance` with a small real `ToolpathResult`; add one `@heavy` end-to-end `demo` POST; rewrite `test_max_frames_exceedance_maps_to_422` on `api.max_frames = 500`
- [x] 3.6 Share one `demo` needle result between the two `TestPatch10ToolpathRegressions` tests that use the same config
- [x] 3.7 Remove the `RLIMIT_AS` block from `tests/__init__.py` (keep the docstring)
- [x] 3.8 Add `AGENTS.md` (the runner usage for targeted, default and heavy runs; forbids raw `unittest discover` and detached test runs) and `CLAUDE.md` containing `@AGENTS.md`

## 4. Verification & Empirical Audit

- [x] 4.1 `scripts/safe-test.sh` (default tier, no args): all pass, `peak_rss_mb <= 1536`, `wall_s <= 600`; record the summary line verbatim
- [x] 4.2 `scripts/safe-test.sh --node`: 32 pass / 0 fail / 1 skip
- [x] 4.3 Heavy tier once, serialised: `RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh`; record the outcome (pass, or a clean `MemoryError` tied to the 2.1 follow-up)
- [x] 4.4 Confirm every assertion removed from the default tier is covered by a `@heavy` test or a fixture-based equivalent; list the mapping in `verification.md`
- [x] 4.5 `openspec validate test-memory-scoping --strict`; populate `verification.md` (Requirement Adherence Matrix, the 2.1 phase table, before/after peak RSS and wall time against `rss.log`, verbatim runner summary lines)

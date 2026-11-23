# OpenCode Orchestration Handoff: OpenSpec Change 'test-memory-scoping'

You are the orchestration agent for OpenSpec change 'test-memory-scoping' running in OpenCode.
Your primary directive is to execute this change using the **`openspec-apply-sub`** skill, which delegates task implementation to the `spec-coder-sub` subagent.

> [!CAUTION]
> **Test Execution Guard (Critical)**:
> Run every test command in this change through `scripts/safe-test.sh` once Task 3.1 exists.
> Until Task 3.1 exists, run **only single targeted test files in the foreground** (e.g. `.venv/bin/python -m unittest tests.test_safe_test_runner -v`). **NEVER** run `unittest discover -s tests` and **NEVER** launch backgrounded or `nohup`/`setsid` test runs.

## 1. Orchestration Directive
- **Change Name**: `test-memory-scoping`
- **Target Skill**: `openspec-apply-sub` (or `/opsx:apply-sub test-memory-scoping`)
- **Architecture Paradigm**: Vertical Slice Architecture (VSA). Keep tiering, fixture release, runner containment, and early frame-cap abort cleanly isolated.

## 2. Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `tests/test_safe_test_runner.py` | `[NEW]` | TDD tests for `scripts/safe-test.sh` & `tests/_run.py`: `flock` serialization + waiting message, lock-wait timeout → exit 75, cgroup v1/v2/`max`/`MemAvailable` computation via `SAFE_TEST_CGROUP_ROOT`, low-memory refusal → exit 75 with lock released, target conversion (`tests/x.py` → `x`), `MemoryError` under `SAFE_TEST_AS_KB`, budget overrun → exit 4, summary line regex, and `--node` without `ulimit -v`. |
| `scripts/safe-test.sh` | `[NEW]` | Executable runner: `flock` on `/tmp/carving-sim-test.lock` (`SAFE_TEST_LOCK`, `SAFE_TEST_LOCK_WAIT_S=3600`), available-memory check (v1 → v2 → `/proc/meminfo`, excluding reclaimable page cache, exit 75 below `SAFE_TEST_MIN_AVAIL_MB=4608`), `ulimit -v ${SAFE_TEST_AS_KB:-4194304}` + `OPENBLAS_NUM_THREADS=1` + `OMP_NUM_THREADS=1` + `MALLOC_ARENA_MAX=2` for Python, `--node` mode (`NODE_OPTIONS=--max-old-space-size=2048`), summary line + exit 4 on budget overrun (`SAFE_TEST_BUDGET_MB=1536`). |
| `tests/_run.py` | `[NEW]` | ~40-line Python `unittest` runner entry point converting `tests/<file>.py` targets, running `unittest`, printing `safe-test: status= peak_rss_mb= wall_s= tier=`, and returning exit 4 on budget overrun. |
| `tests/_tiers.py` | `[NEW]` | Export `heavy = unittest.skipUnless(os.environ.get("RUN_HEAVY_TESTS") == "1", "heavy test: set RUN_HEAVY_TESTS=1")` and `ReleasesClassFixtures` (`tearDownClass` deletes `_class_fixtures` and runs `gc.collect()`). |
| `tests/_fixtures.py` | `[NEW]` | Plain helper functions `short_stock_config()` (`H_stock_mm=40`, `target_mesh=None`) and `short_stock_target(config, sliders)` (scaled/seated `base_head`), with no module-level cache. |
| `tests/__init__.py` | `[NEW]` | Docstring-only package marker (no `RLIMIT_AS` guard). |
| `toolpath_sim.py` | `L510-L590, L2116-L2165` | Add optional `max_frames: int | None = None` to `resample_path`, raising `FrameCapExceededError` as soon as `len(out_joints) > max_frames` (one subdivided segment overshoot `<= 2**11` max). Pass `max_frames` from `generate_synthetic_carve_path` while keeping the post-check. (Plus any bounded single-phase fix from Task 2.1 if D7 applies.) |
| `tests/test_carver_sim.py` | `L489-L686, L687-L1039, L1040-L1120, L1121-L1579, L1580-end` | Add `TestResampleFrameCap`, `TestTiers`, `TestFixtureRelease`; apply `ReleasesClassFixtures`; rewrite `TestSyntheticToolpaths` & `test_standard_preset_produces_denser_path` onto `short_stock_*` + add `@heavy` real-target copy; make `TestHead2Target.setUpClass` generation-free + `@heavy` path assertions; stub `generate_synthetic_carve_path` in `test_sculpt_and_sim_columnar_contract` & `test_demo_response_carries_geometry_provenance` + `@heavy` end-to-end POST; rewrite `test_max_frames_exceedance_maps_to_422` on `api.max_frames=500`; share one `cls.needle_result` in `TestPatch10ToolpathRegressions`. |
| `tests/test_tool_model.py`, `tests/test_machine_cad.py`, `tests/test_machine_cad_extract.py` | `[MODIFY]` | Apply `ReleasesClassFixtures` (`tearDownClass` cleanup only). |
| `AGENTS.md` | `[NEW]` | Agent test policy requiring `scripts/safe-test.sh` for targeted, default-tier (before PR), and heavy-tier (verification only) runs; forbidding raw `unittest discover` and detached test runs. |
| `CLAUDE.md` | `[NEW]` | Import `@AGENTS.md`. |

## 3. Technical & Architectural Boundaries
- **In-Scope Decisions**:
  - **Tier by `@heavy` decorator** (`RUN_HEAVY_TESTS=1`), keeping default-tier rewrites and `@heavy` full-scale tests side by side.
  - **Budget**: Default tier `<= 1.5 GiB` (`1536 MiB`) peak RSS and `<= 600 s` wall time; exit `4` on overrun, exit `75` on lock timeout / low memory.
  - **Cgroup v1 → v2 → `/proc/meminfo`**, subtracting reclaimable page cache and taking `min(..., MemAvailable)`.
  - **Phase probe (Task 2.1)**: Run once via `scripts/safe-test.sh` with `SAFE_TEST_AS_KB=6291456` and apply D7 decision rule.
- **Hard Exclusions / No-Go**:
  - Do NOT modify `.env`, `.env.*`, or credential files.
  - Do NOT change `ToolpathResult.frames` to columnar format or alter `package.json` or Node test assertions.
  - Do NOT edit user-level `~/.claude/skills` (out of repo).

## 4. Visual & UI Design Specifications
- **Status: Non-visual / Backend change.** No user-facing components, layout, or styling affected. Do NOT generate UI components or CSS rules.

## 5. Test Scaffolding & Verification Commands
- **Primary Test Runner**: `scripts/safe-test.sh` (once Task 3.1 exists; single targeted foreground files only before 3.1)
  - Default tier: `scripts/safe-test.sh` (`peak_rss_mb <= 1536`, `wall_s <= 600`)
  - Node tier: `scripts/safe-test.sh --node` (`32 pass / 0 fail / 1 skip`)
  - Heavy tier (Task 4.3 verification only): `RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh`
- **TDD Requirement**: Task group `## 1` MUST scaffold failing tests before touching implementation code.

## 6. Implementation Task Checklist
- [ ] 1.1 Create `tests/test_safe_test_runner.py` with failing tests for the runner: lock serialisation (disjoint intervals plus the waiting message), lock-wait timeout → 75, cgroup v1 / v2 / `max` / `MemAvailable` available-memory computation through `SAFE_TEST_CGROUP_ROOT` fixtures, the low-memory refusal → 75 with the lock released, target conversion, `MemoryError` under the address-space cap, budget overrun → 4, summary-line format, and `--node` running without `ulimit -v`
- [ ] 1.2 Add failing `TestResampleFrameCap` to `tests/test_carver_sim.py`: abort at `max_frames=500` with overshoot ≤ `500 + 2**11`, identical output under the cap, error type and `FRAME_CAP_EXCEEDED` unchanged
- [ ] 1.3 Add failing `TestTiers` (no real-target generation without `RUN_HEAVY_TESTS`; heavy skip reason) and `TestFixtureRelease` (weakref dead after `tearDownClass`) to `tests/test_carver_sim.py`
- [ ] 1.4 Run 1.1–1.3 as single targeted files in the foreground and confirm they fail for the expected reasons
- [ ] 2.1 After 3.1 exists, run the phase probe on the sculpted base_head `demo` (`{"nose": 1.0, "chin": 0.6, "brow": 0.4}`, `target_mesh=None`) once through `scripts/safe-test.sh` with `SAFE_TEST_AS_KB=6291456`. Record each phase's time and peak RSS in `patch.md`, and apply the D7 decision rule: fix inside the phase with a memory-asserting regression test, or record it for a `toolpath-memory` follow-up change
- [ ] 2.2 Implement the frame-cap fail-early (`resample_path(..., max_frames=None)`, passed from `generate_synthetic_carve_path`, post-check kept) until `TestResampleFrameCap` passes
- [ ] 2.3 Add `tests/_fixtures.py` (`short_stock_config()`, `short_stock_target(config, sliders)`; 40 mm stock, base_head scaled and seated to fit) and confirm one `demo` on it is under 200 MB peak and under 30 s, recorded in `patch.md`
- [ ] 3.1 Create `scripts/safe-test.sh` (executable) and `tests/_run.py` per architecture D5 until `tests/test_safe_test_runner.py` passes
- [ ] 3.2 Create `tests/_tiers.py` with `heavy` and the `ReleasesClassFixtures` mixin; apply the mixin to every class that caches a result, mesh, sculpt or `TestClient` (`tests/test_carver_sim.py`, `tests/test_tool_model.py`, `tests/test_machine_cad.py`, `tests/test_machine_cad_extract.py`)
- [ ] 3.3 Rewrite `TestSyntheticToolpaths` (including `test_standard_preset_produces_denser_path`) onto the short-stock fixture, and add a `@heavy` real-target copy
- [ ] 3.4 Make `TestHead2Target.setUpClass` generation-free; move the head_2 path assertions to the short-stock fixture or `@heavy`
- [ ] 3.5 Stub generation in `test_sculpt_and_sim_columnar_contract` and `test_demo_response_carries_geometry_provenance` with a small real `ToolpathResult`; add one `@heavy` end-to-end `demo` POST; rewrite `test_max_frames_exceedance_maps_to_422` on `api.max_frames = 500`
- [ ] 3.6 Share one `demo` needle result between the two `TestPatch10ToolpathRegressions` tests that use the same config
- [ ] 3.7 Remove the `RLIMIT_AS` block from `tests/__init__.py` (keep the docstring)
- [ ] 3.8 Add `AGENTS.md` (the runner usage for targeted, default and heavy runs; forbids raw `unittest discover` and detached test runs) and `CLAUDE.md` containing `@AGENTS.md`
- [ ] 4.1 `scripts/safe-test.sh` (default tier, no args): all pass, `peak_rss_mb <= 1536`, `wall_s <= 600`; record the summary line verbatim
- [ ] 4.2 `scripts/safe-test.sh --node`: 32 pass / 0 fail / 1 skip
- [ ] 4.3 Heavy tier once, serialised: `RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh`; record the outcome (pass, or a clean `MemoryError` tied to the 2.1 follow-up)
- [ ] 4.4 Confirm every assertion removed from the default tier is covered by a `@heavy` test or a fixture-based equivalent; list the mapping in `verification.md`
- [ ] 4.5 `openspec validate test-memory-scoping --strict`; populate `verification.md` (Requirement Adherence Matrix, the 2.1 phase table, before/after peak RSS and wall time against `rss.log`, verbatim runner summary lines)

## 7. Post-Implementation & Verification Obligations
When `spec-coder-sub` finishes:
1. Verify all checkboxes in `tasks.md` are marked `- [x]`. Only tick boxes that genuinely ran and passed.
2. Populate `openspec/changes/test-memory-scoping/verification.md` (Requirement Adherence Matrix, Task 2.1 phase table, before/after peak RSS & wall time, verbatim `safe-test.sh` summary lines).
3. Automatically run verification via `openspec-verify-change`.
4. **Open a Pull Request**: Once implementation is complete and `verification.md` is written and verified with zero critical issues:
   - Ensure your work is on a dedicated feature branch (`feat/test-memory-scoping`).
   - Stage and commit all implementation code and every artifact within `openspec/changes/test-memory-scoping`, push (`git push -u origin HEAD`), open a Pull Request using `gh pr create --fill`, and report the PR URL.

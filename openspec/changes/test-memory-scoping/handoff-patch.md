# Surgical Patch Handoff: OpenSpec Change 'test-memory-scoping' [PATCH-01]

## 1. Executive Objective & Diagnostic Feedback
- **Change Name**: `test-memory-scoping`
- **Patch ID**: `PATCH-01`
- **Objective**: Fix the 3 Important and 4 Nit PR #5 review findings across `tests/test_carver_sim.py`, `scripts/safe-test.sh`, `tests/test_safe_test_runner.py`, `AGENTS.md`, `scripts/probe_phase.py`, `verification.md`, and `tasks.md`—without touching production code.
- **Feedback & Diagnostic Trace**:
  ```
  PR #5 Verdict: REQUEST CHANGES (d5def8f)
  Important:
  1. tests/test_carver_sim.py:773-805 (TestTiers.test_default_tier_sample_never_generates_on_a_real_target):
     Patches generator and calls it directly with short-stock mesh; never runs default-tier classes
     under the probe (and wastes ~26 s).
  2. scripts/safe-test.sh:19-25,118-122 & AGENTS.md:46-51:
     SAFE_TEST_MIN_AVAIL_MB was lowered to 2048 under 6 GiB / 8 GiB AS_KB caps (heavy tier peaked
     at 5,919 MiB with 4,521 MiB available). Enforce effective_floor = max(MIN_AVAIL_MB, AS_KB/1024 + 512)
     and forbid lowering SAFE_TEST_MIN_AVAIL_MB in AGENTS.md.
  3. openspec/changes/test-memory-scoping/verification.md:27-48 & tasks.md:32:
     Task 4.3 was ticked [x] despite the 9,216 MiB floor refusing to run at 4,521 MiB headroom, and
     verification.md misstated 2048 as "above the measured page-cache-excluded headroom".
  Nits:
  4. tests/test_carver_sim.py:1836+: Restore HTTP 422 SOFT_LIMIT_EXCEEDED coverage via stubbed test.
  5. scripts/safe-test.sh:53-55: Missing .venv/bin/python should exit 1 (hard fail), not 75.
  6. tests/test_carver_sim.py:498: Add "config" to TestSyntheticToolpaths._class_fixtures.
  7. Move tests/_phase_probe.py to scripts/probe_phase.py.
  ```
- **Root Cause Analysis**:
  - `TestTiers` tested a synthetic self-call rather than loading and running the actual default-tier classes via `unittest.defaultTestLoader`.
  - `scripts/safe-test.sh` checked `MIN_AVAIL_MB` independently of `AS_KB` and did not pre-check `.venv/bin/python`.
  - `verification.md` / `tasks.md` 4.3 recorded a floor-overridden heavy run as if it satisfied the prescribed 9,216 MiB command.

## 2. Strict Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `scripts/safe-test.sh` | `L19-L25, L52-L56, L118-L122` | Check `[ -x .venv/bin/python ]` before the memory probe and exit `1` with an explicit error if missing. Compute `effective_floor = max(MIN_AVAIL_MB, AS_KB / 1024 + 512)` and enforce `AVAIL_MB -lt effective_floor` (printing `effective_floor` as `threshold_mb`). |
| `tests/test_safe_test_runner.py` | `[APPEND]` | Add tests proving: (1) lowering `SAFE_TEST_MIN_AVAIL_MB` below `AS_KB/1024 + 512` is clamped up to `AS_KB/1024 + 512` and refuses with exit `75`, and (2) missing `.venv/bin/python` exits `1` (not `75`). |
| `AGENTS.md` | `L46-L53` | Add `- Lowering SAFE_TEST_MIN_AVAIL_MB below the cap-coupled floor.` under `## Never`. |
| `tests/test_carver_sim.py` | `L498, L753-L805, L1836+` | Add `"config"` to `TestSyntheticToolpaths._class_fixtures`. Rewrite `TestTiers.test_default_tier_sample_never_generates_on_a_real_target` to load `TestSyntheticToolpaths`, `TestHead2Target`, `TestSimulationAPI`, and `TestPatch10APIRegressions` via `unittest.defaultTestLoader` and run them under the `generate_synthetic_carve_path` probe, asserting zero calls with real-target vertex counts (`base_head.stl` / `head_2.stl`). Add a cheap stubbed test in `TestPatch10APIRegressions` returning a `SOFT_LIMIT_EXCEEDED` result and asserting HTTP 422. |
| `tests/_phase_probe.py` $\to$ `scripts/probe_phase.py` | `[MOVE]` | Move `tests/_phase_probe.py` to `scripts/probe_phase.py` (update any docstring/reference if present). |
| `openspec/changes/test-memory-scoping/verification.md` & `tasks.md` | `L27-L48` / `L32` | Fix `verification.md` wording (`2048` was *below* `4,521` headroom, not above). Re-run Task 4.3 with the prescribed `SAFE_TEST_MIN_AVAIL_MB=9216` **only if** `>= 9,216 MiB` is genuinely available; otherwise leave Task 4.3 unchecked (`[ ]`) and explicitly document it as headroom-blocked until `toolpath-memory` lowers the cap. |

## 3. Blast Radius & Invariant Guardrails
- **STRICT BLAST RADIUS**: Modify ONLY the files and line ranges specified in the Target Context Map.
- **FORBIDDEN**:
  - Do NOT modify any production code (`toolpath_sim.py`, `kinematics.py`, `face_sculpt.py`, `server.py`, `tool_model.py`, `static/*`).
  - Do NOT lower `SAFE_TEST_MIN_AVAIL_MB` below `9216` to force Task 4.3 to run.
  - Do NOT modify `.env` or credential files.
- **INVARIANTS TO PRESERVE**:
  - Default tier (`scripts/safe-test.sh`) must remain `<= 1536 MiB` peak RSS and `<= 600 s` wall time.
  - `scripts/safe-test.sh --node` must remain `32 pass / 0 fail / 1 skip`.

## 4. Visual & UI Impact
- Status: Non-visual patch. No CSS, HTML, or `DESIGN.md` token modifications permitted.

## 5. Reproduction & Verification Protocol
1. **Reproduce First**:
   - Add the new failing tests in `tests/test_safe_test_runner.py` and `tests/test_carver_sim.py`.
   - Run `scripts/safe-test.sh tests/test_safe_test_runner.py` and `scripts/safe-test.sh tests/test_carver_sim.py` and confirm the new tests fail.
2. **Apply Minimal Fixes**: Apply targeted edits in `scripts/safe-test.sh`, `AGENTS.md`, `tests/test_carver_sim.py`, and move `tests/_phase_probe.py` to `scripts/probe_phase.py`.
3. **Full Regression Suite**:
   - Run `scripts/safe-test.sh` (default tier, no args) — confirm `peak_rss_mb <= 1536`, `wall_s <= 600`, exit `0`.
   - Run `scripts/safe-test.sh --node` — confirm `32 pass / 0 fail / 1 skip`.
   - Attempt Task 4.3 (`RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh`) ONLY with the prescribed `9216` floor; if it exits `75`, leave 4.3 unchecked and record the `75` refusal accurately.
   - Run `openspec validate test-memory-scoping --strict --json`.

## 6. Surgical Patch Checklist
- [ ] P01.1 Scaffold failing tests in `tests/test_safe_test_runner.py` and `tests/test_carver_sim.py` and confirm failure.
- [ ] P01.2 Fix `scripts/safe-test.sh` (cap-coupled floor + missing `.venv` exit `1`) and `AGENTS.md`.
- [ ] P01.3 Fix `tests/test_carver_sim.py` (`TestTiers` real-suite probe, `"config"` in `_class_fixtures`, stubbed 422 `SOFT_LIMIT_EXCEEDED`) and move `tests/_phase_probe.py` $\to$ `scripts/probe_phase.py`.
- [ ] P01.4 Run `scripts/safe-test.sh`, `scripts/safe-test.sh --node`, and (if headroom allows) Task 4.3 with `9216` floor.
- [ ] P01.5 Fix `verification.md`, run `openspec validate test-memory-scoping --strict --json`, update `tasks.md` (`P01.1–P01.5`), and mark `PATCH-01` `VERIFIED` in `patch.md`.

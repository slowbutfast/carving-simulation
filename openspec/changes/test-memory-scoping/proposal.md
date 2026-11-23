## Why

The Python suite OOM-kills the 12 GiB container. One run peaks at about 3.5–5 GB of RSS and takes over 30 minutes, and two agents running it at once take out every other process. The cause isn't a leak. It's scope: the default command does about 12 **full generations**, one of which (sculpted base_head `demo`, `TestSyntheticToolpaths.setUpClass`) peaks at 3.5 GB by itself, and the next one (`standard` on the same mesh) got OOM-killed. The guard PR #4 added in `tests/__init__.py` never runs under `discover -s tests` (research.md, Verified facts).

## What Changes

- **Test tiers.** Add a `heavy` skip decorator (`RUN_HEAVY_TESTS=1`) in `tests/_tiers.py`. Every test that does a **full generation** moves to the **heavy tier** or is rewritten onto a small fixture or a stubbed generation.
- **Small fixtures.** A short-stock target fixture for the toolpath invariant tests. API contract tests patch `generate_synthetic_carve_path` with a small real `ToolpathResult`. The three `_FakeNeedle` demo generations with the same config share one class fixture.
- **Free fixtures.** Every class that caches a generation or a mesh gets a `tearDownClass` that deletes it and runs `gc.collect()`.
- **Diagnose the base_head spike** with a capped phase probe and record which phase spikes. If it's a production defect, fix it in this change only if the fix fits in that phase; otherwise record it and open a follow-up change.
- **Fail early on the frame cap.** `resample_path` raises `FrameCapExceededError` as soon as the resampled count exceeds `api.max_frames`, instead of building every frame first. Same contract, bounded memory.
- **`scripts/safe-test.sh`**: a `flock` queue on `/tmp/carving-sim-test.lock` shared across worktrees; an available-memory check (cgroup v1 → v2 → `/proc/meminfo`, page cache excluded) that refuses below 4.5 GiB; `ulimit -v 4194304` plus single-threaded BLAS for Python; a peak-RSS and wall-time summary line; a non-zero exit if the run goes over budget. Node tests go through the same lock without `ulimit -v` (V8 can't start under it).
- **Remove** the dead `RLIMIT_AS` code from `tests/__init__.py` (keep the file).
- **Agent policy.** A new `AGENTS.md` (with `CLAUDE.md` importing it) tells agents to run targeted files through `scripts/safe-test.sh` during implementation, run the default tier before a PR, and run the heavy tier once, serialised, for verification only.

## Capabilities

### New Capabilities
- `test-resource-budget`: test tiers, the default-tier memory and time budget, the serialised and memory-guarded runner, and the agent test policy.

### Modified Capabilities
- (none) The frame-cap fail-early is an implementation change: `face-sculpt-sim`'s existing requirement that a path over `api.max_frames` raises `FrameCapExceededError` is unchanged.

## Impact

- **Tests:** `tests/test_carver_sim.py` (tiers, fixtures, stubs, `tearDownClass`), `tests/test_tool_model.py` / `tests/test_machine_cad.py` (`tearDownClass` only), new `tests/_tiers.py`, new `tests/test_safe_test_runner.py`, `tests/__init__.py` (ceiling removed).
- **Production:** `toolpath_sim.py` (`resample_path` gains an optional `max_frames`; `generate_synthetic_carve_path` passes it). Any phase fix from task 2.1 is limited to the phase it names.
- **Tooling and docs:** new `scripts/safe-test.sh`, `AGENTS.md`, `CLAUDE.md`. `package.json` is unchanged (the runner wraps `npm run test:node`).
- **Depends on PR #4** (`feat/head2-collision-logging`) being merged: it scopes the `TestHead2Target`, `TestCollisionLogAPI` and `TestSampledGougeRuns` classes PR #4 adds.
- **Process:** handoffs and verification run `scripts/safe-test.sh` instead of raw `unittest discover`.

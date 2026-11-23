## Automated Tests

All commands go through the runner; none call `unittest discover` directly.

- `scripts/safe-test.sh tests/test_safe_test_runner.py`: the runner's behaviour, using a temp lock path and a fixture cgroup root (`SAFE_TEST_CGROUP_ROOT`):
  - two concurrent invocations don't overlap (each writes start/end timestamps from a sleep target; the intervals must be disjoint), and the second prints the waiting message;
  - `SAFE_TEST_LOCK_WAIT_S=1` with the lock held elsewhere → exit 75;
  - cgroup v1 fixture `limit=12 GiB, usage=9 GiB, total_inactive_file=6 GiB` → available 9 GiB; v2 fixture equivalent; v2 `max` → falls back to `MemAvailable`;
  - `SAFE_TEST_MIN_AVAIL_MB` above the fixture's available memory → exit 75, no tests run, lock released (a following run gets it immediately);
  - target conversion: `tests/test_tool_model.py` → `test_tool_model`; dotted names pass through;
  - a target that allocates 6 GiB under the default cap errors with `MemoryError` and the runner exits non-zero;
  - `SAFE_TEST_BUDGET_MB=1` on a trivial passing target → exit 4 and a `BUDGET EXCEEDED` line;
  - the summary line matches `safe-test: status=\d+ peak_rss_mb=\d+ wall_s=\d+ tier=(default|heavy)`;
  - `--node` runs without `ulimit -v` (`ulimit -v` in the child reports `unlimited`) and with `--max-old-space-size=2048` in `NODE_OPTIONS`.
- `scripts/safe-test.sh tests/test_carver_sim.py`: tier and fixture contracts:
  - `TestTiers`: with `RUN_HEAVY_TESTS` unset, a probe wrapping `generate_synthetic_carve_path` across a default-tier sample run records no call on a real target mesh (`base_head.stl` / `head_2.stl` by vertex count and bounds); `heavy` tests report the skip reason;
  - `TestFixtureRelease`: a weakref to a class fixture is dead after `tearDownClass`, for a `ReleasesClassFixtures` subclass;
  - `TestResampleFrameCap`: aborts with `max_frames=500` and overshoot ≤ `500 + 2**11`; identical output with and without `max_frames` under the cap; error type and `FRAME_CAP_EXCEEDED` diagnostic unchanged;
  - all rewritten default-tier classes (short-stock `TestSyntheticToolpaths`, the generation-free `TestHead2Target`, stubbed API tests, shared needle result) pass with the same assertions as before.
- `scripts/safe-test.sh` (no args, default tier): the whole Python suite passes; summary `peak_rss_mb <= 1536`, `wall_s <= 600`, exit 0.
- `scripts/safe-test.sh --node`: 32 pass / 0 fail / 1 skip (unchanged count from PR #4).
- `RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh`: verification only, once. The heavy tier passes, or any test that fails does so with a clean `MemoryError` recorded as a known follow-up (D7), never by a container OOM.

## Manual Verification

- **Concurrent agents**:
  - **WHEN** two terminals in different worktrees run `scripts/safe-test.sh` at the same time
  - **THEN** the second prints `waiting for /tmp/carving-sim-test.lock` and starts after the first's summary line; `free -m` never drops below 4 GiB available during the overlap window
- **Low-memory refusal**:
  - **WHEN** `SAFE_TEST_MIN_AVAIL_MB=999999 scripts/safe-test.sh tests/test_tool_model.py`
  - **THEN** it prints the available MiB and the threshold, exits 75 and runs no tests
- **Agent policy**:
  - **WHEN** a fresh Claude Code or OpenCode session in the repo is asked to "run the tests"
  - **THEN** it uses `scripts/safe-test.sh` (as `AGENTS.md` / `CLAUDE.md` instruct), not `unittest discover`

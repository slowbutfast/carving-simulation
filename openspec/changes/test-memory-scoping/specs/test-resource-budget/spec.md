## ADDED Requirements

### Requirement: Default and heavy test tiers
The Python suite SHALL have two tiers. Any test that performs a **full generation** (`toolpath_sim.generate_synthetic_carve_path` on a real target with the `demo` or `standard` preset, directly or through `POST /api/sculpt-and-sim` without a stubbed generator) SHALL be decorated with the `heavy` decorator from `tests/_tiers.py` and SHALL be skipped unless `RUN_HEAVY_TESTS=1`. A full-generation test SHALL NOT run in the default tier.

#### Scenario: Heavy tests skip without the flag
- **WHEN** `scripts/safe-test.sh` runs the Python suite without `RUN_HEAVY_TESTS`
- **THEN** every `heavy` test is reported as skipped with the reason `heavy test: set RUN_HEAVY_TESTS=1`
- **AND** a probe that wraps `toolpath_sim.generate_synthetic_carve_path` records zero calls whose mesh is `presets/base_head.stl` or `presets/head_2.stl` (sculpted or not)

#### Scenario: Heavy tests run with the flag
- **WHEN** the suite runs with `RUN_HEAVY_TESTS=1`
- **THEN** the `heavy` tests execute and are not skipped

### Requirement: Default-tier memory and time budget
Run through `scripts/safe-test.sh` without `RUN_HEAVY_TESTS`, the whole Python default tier SHALL finish in one process with a peak RSS of at most 1.5 GiB (1,536 MiB) and a wall time of at most 10 minutes on the reference container (3 vCPU). The runner SHALL print the measured peak RSS and wall time, and SHALL exit non-zero if the peak RSS budget is exceeded even when every test passed.

#### Scenario: Default tier fits the budget
- **WHEN** `scripts/safe-test.sh` runs with no arguments
- **THEN** the summary line reports `peak_rss_mb <= 1536` and `wall_s <= 600`, and the exit status is 0

#### Scenario: A budget overrun fails the run
- **WHEN** the runner's measured peak RSS exceeds `SAFE_TEST_BUDGET_MB` (default 1536) while every test passes
- **THEN** the runner prints `BUDGET EXCEEDED` with the measured peak and exits with status 4

### Requirement: Cached fixtures are released per class
Every test class that stores a toolpath result, a sculpted or loaded mesh, or a `TestClient` on the class in `setUpClass` SHALL delete those attributes and call `gc.collect()` in `tearDownClass`, so no class fixture outlives its class.

#### Scenario: A class fixture does not outlive its class
- **WHEN** a class with a cached `ToolpathResult` finishes
- **THEN** the result's class attributes are gone (`not hasattr(cls, "result")`) and a `weakref` to it taken in the test is dead after `tearDownClass`

### Requirement: Frame cap fails before materialising the path
`toolpath_sim.resample_path` SHALL accept an optional `max_frames` and SHALL raise `FrameCapExceededError` as soon as the resampled joint count exceeds it, without building the rest of the path. `generate_synthetic_carve_path` SHALL pass `api.max_frames`. The error type and its `diagnostic()` output (`FRAME_CAP_EXCEEDED`) SHALL be unchanged.

#### Scenario: Resampling stops at the cap
- **WHEN** `resample_path` is called with a joint list whose full resampling would exceed `max_frames = 500`
- **THEN** `FrameCapExceededError` is raised with `max_frames == 500` and `frames > 500`
- **AND** no more than `max_frames + 2**11` resampled joints were built before it raised (one subdivided segment of overshoot at most)

#### Scenario: Paths under the cap are byte-identical
- **WHEN** `resample_path` runs on a path under the cap, with and without `max_frames`
- **THEN** the returned joints, rapid flags and stages are identical

### Requirement: Serialised, memory-guarded test runner
`scripts/safe-test.sh` SHALL be executable and SHALL:
1. take an exclusive `flock` on `/tmp/carving-sim-test.lock` (override `SAFE_TEST_LOCK`), waiting up to `SAFE_TEST_LOCK_WAIT_S` (default 3600) and printing a waiting message, then exit 75 if it never gets the lock;
2. after acquiring the lock, compute available memory as cgroup v1 (`memory.limit_in_bytes − (memory.usage_in_bytes − total_inactive_file)`), else cgroup v2 (`memory.max − (memory.current − inactive_file)`), else `/proc/meminfo` `MemAvailable`, taking the minimum with `MemAvailable` when a cgroup limit exists, and refuse to start (exit 75) below `SAFE_TEST_MIN_AVAIL_MB` (default 4608);
3. run Python tests with `ulimit -v ${SAFE_TEST_AS_KB:-4194304}`, `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1` and `MALLOC_ARENA_MAX=2`, through `.venv/bin/python -m unittest`;
4. accept zero or more test targets: `tests/<file>.py` paths become dotted module names, and dotted `module.Class.test` names pass through; with no targets it discovers `tests/`;
5. accept `--node` to run `npm run test:node` under the same lock and memory check, without `ulimit -v` and with `NODE_OPTIONS=--max-old-space-size=2048`;
6. print one summary line `safe-test: status=<rc> peak_rss_mb=<n> wall_s=<n> tier=<default|heavy>`.

#### Scenario: Concurrent runs queue instead of overlapping
- **WHEN** two `scripts/safe-test.sh` invocations start together
- **THEN** the second prints `waiting for /tmp/carving-sim-test.lock` and starts only after the first exits, with no overlap in their run windows

#### Scenario: Low memory refuses to start
- **WHEN** available memory is below `SAFE_TEST_MIN_AVAIL_MB`
- **THEN** the runner prints the measured available MiB and the threshold, runs no tests, releases the lock and exits 75

#### Scenario: Page cache is not counted as used
- **WHEN** a cgroup v1 fixture reports `limit = 12 GiB`, `usage = 9 GiB` and `total_inactive_file = 6 GiB`
- **THEN** available memory is computed as 9 GiB, not 3 GiB

#### Scenario: A runaway allocation fails the test, not the container
- **WHEN** a Python test allocates past `SAFE_TEST_AS_KB`
- **THEN** that test errors with `MemoryError`, the runner exits non-zero, and no process outside the runner is OOM-killed

#### Scenario: Targeted file runs
- **WHEN** `scripts/safe-test.sh tests/test_tool_model.py` runs
- **THEN** only `test_tool_model` executes under the lock and caps

### Requirement: Agent test policy
The repo SHALL have an `AGENTS.md` and a `CLAUDE.md` that imports it (`@AGENTS.md`). They SHALL state that agents and sub-agents run tests only through `scripts/safe-test.sh`; that during implementation they run the targeted files they touched; that before opening a PR they run the default tier once; that the heavy tier (`RUN_HEAVY_TESTS=1`) runs only during verification, once, through the runner; and that raw `python -m unittest discover -s tests` and backgrounded or `nohup` test runs are not allowed.

#### Scenario: Policy is discoverable
- **WHEN** `AGENTS.md` is read
- **THEN** it contains the `scripts/safe-test.sh` usage for a targeted file, the default tier and the heavy tier, and forbids raw `unittest discover` and detached test runs

## Source material

### 2026-11-20 — owner, after the container ran out of memory twice

Container status the owner relayed (first OOM, during the PR #4 6.1 full-suite run):

> | PID | Role | %CPU | Resident RAM (RSS) | Virtual Memory (VSZ) | Elapsed Runtime | Command / Context |
> | **1650585** | **Test Runner** | **107.0%** | **4,872 MB (4.87 GB)** *(peaked)* | **5,721 MB (5.72 GB)** | **22m 14s** | `.venv/bin/python -m unittest discover -s tests -v` in `carving-simulation` |
>
> Before: 15Gi total, 9.3Gi used, 6.3Gi available (Swap: 3.6Gi used). After kill: 5.8Gi used, 9.8Gi available.

Second OOM (two concurrent runs):

> terminate both active Python test processes (`3205348` holding 5,180 MB and `3206202` holding 4,660 MB)

The owner's requested remediation, quoted in full:

> Our Python `unittest` suite in `tests/` is consuming ~5 GB of RSS per run and running for 30+ minutes, which hits our 12 GB container memory ceiling whenever multiple agents run tests concurrently. Please do the following:
> 1. **Diagnose the memory bloat:** Audit `tests/` (and check `.../scratchpad/rss.log` if still present) to identify which specific test files, fixtures, large simulation grids/meshes, or unclosed resources are retaining multi-gigabyte allocations across `unittest` cases.
> 2. **Fix the test memory footprint:**
>    * Add explicit `tearDown` / `tearDownClass` cleanup (`del` large arrays/simulation states + `gc.collect()`) so `unittest` does not hold every test class's objects in memory until the entire suite finishes.
>    * Downscale simulation grid resolutions, step counts, or fixture sizes in unit tests to the minimum needed to validate correctness, moving any full-scale/heavy benchmarks behind an environment flag (e.g., `@unittest.skipUnless(os.getenv("RUN_HEAVY_TESTS"), "heavy test")`).
> 3. **Add a deterministic test runner wrapper & agent policy:**
>    * Create `./scripts/safe-test.sh` (and make it executable) that uses `flock /tmp/carving-sim-test.lock` so concurrent agents queue instead of overlapping, checks container cgroup memory (`/sys/fs/cgroup/memory.current` vs `/sys/fs/cgroup/memory.max`) to abort if less than 4.5 GB is available, and enforces `ulimit -v 4194304` (4 GB cap) before invoking `.venv/bin/python -m unittest`.
>    * Update `CLAUDE.md` / `AGENTS.md` to instruct all agents and sub-agents to run targeted test files via `./scripts/safe-test.sh tests/<specific_test>.py` instead of full `discover -s tests` during implementation tasks.

### Raised but not acted on

- **The cgroup v2 paths `/sys/fs/cgroup/memory.current` / `memory.max`.** They don't exist in this container (verified below). The runner reads cgroup v1 first, then v2, then `/proc/meminfo`. This adapts the request rather than skipping it.
- **"Unclosed resources."** We audited for them and found none that matter. `TestClient(app)` is created without a context manager, so no lifespan runs; there are no subprocesses, workers or open files. No change.
- **"Downscale simulation grid resolutions."** The Python suite has no voxel grid; that lives in the JS worker, which is cheap under `npm run test:node`. Here, "downscale" means toolpath *fixture size* (a shorter stock, a smaller target) and stubbing generation where a test only checks the response contract.
- **Converting `ToolpathResult.frames` from a list of dicts to columnar numpy.** That would roughly cut retained memory per result by about 5×, but it's a production data-model change touching `server.py`, the gouge and broadside scans and the tests. Out of scope. Recorded so it isn't re-proposed as part of this change.

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| **default tier** | Tests that run with no environment flag, through `scripts/safe-test.sh`, and must fit the memory and time budget. | "Unit tests only". Integration tests can be default tier if they use small fixtures. |
| **heavy tier** | Tests gated by `@heavy` (`RUN_HEAVY_TESTS=1`): full-scale `demo`/`standard` generation on the real targets, and real end-to-end API generation. | Optional or unimportant. They run before merge (verification), just not during implementation loops. |
| **full generation** | One call to `toolpath_sim.generate_synthetic_carve_path` on a real target with the `demo` or `standard` preset (about 85–180k frames). | A call on a small fixture (`_FakeNeedle`, the short-stock fixture), or a stubbed generation. |
| **peak RSS** | The highest resident memory of the test process (`ru_maxrss`), measured by the runner. | VSZ / address space, which `ulimit -v` limits and which is always larger than RSS. |
| **address-space cap** | `ulimit -v` / `RLIMIT_AS`: a backstop that makes allocations fail (Python `MemoryError`) instead of the container OOM-killing everything. | A budget. Hitting it means a test is broken; the budget is the peak-RSS assertion. |
| **available memory** | cgroup limit minus (usage − reclaimable page cache), or `MemAvailable` without a cgroup. | `limit − usage`. Usage includes about 4 GB of page cache here, which would make the check refuse to run for no reason. |
| **test lock** | `flock` on `/tmp/carving-sim-test.lock`, shared by every worktree in the container. | A per-worktree lock. Worktrees share `/tmp` and the memory, so they must share the lock too. |

## External research

| Source | What it establishes | Licence | Accessed |
| :--- | :--- | :--- | :--- |
| Python `unittest` docs, "Test Discovery" | With `-s tests` and no `-t`, the top-level directory *is* `tests/`, so `tests/__init__.py` is never imported as a package. | PSF docs | 2026-11-20 |
| Linux cgroup v1 memory docs (`memory.usage_in_bytes`, `memory.stat: total_inactive_file`) | Usage includes page cache; the working set is usage minus inactive file pages (the same rule `docker stats` uses). | kernel docs | 2026-11-20 |
| `flock(1)` man page | `flock -w <s>` waits up to s seconds for the lock, then exits 1; the lock is released when the holder dies, including on SIGKILL. | util-linux | 2026-11-20 |
| V8 / Node.js address-space reservation | V8 reserves many GB of *virtual* memory (pointer-compression cage, WASM). `ulimit -v 4194304` stops Node from starting. Use `--max-old-space-size` for Node instead. | — | 2026-11-20 |

## Candidate tech

| Candidate | Decision | Reason | Date |
| :--- | :--- | :--- | :--- |
| `flock` (util-linux, `/usr/bin/flock`) | **Adopted** | Already installed; the lock disappears with the holder, so no stale-lock cleanup. | 2026-11-20 |
| `ulimit -v` in the runner | **Adopted (Python only)** | A hard backstop that fails a test cleanly instead of OOM-killing the container. Needs `OPENBLAS_NUM_THREADS=1` and `MALLOC_ARENA_MAX=2` so VSZ tracks RSS. | 2026-11-20 |
| `RLIMIT_AS` in `tests/__init__.py` (PR #4) | **Rejected / removed** | Dead code under the standard command (verified); and if it did run, the limit would only exist inside whichever process imported it. | 2026-11-20 |
| `prlimit --as` | Rejected | Same as `ulimit -v` and adds nothing. | 2026-11-20 |
| `systemd-run --scope -p MemoryMax=` | Rejected | No systemd inside the container. | 2026-11-20 |
| `/usr/bin/time -v` for peak RSS | Rejected | Not installed. The runner reports `ru_maxrss` from inside Python instead. | 2026-11-20 |
| pytest + pytest-xdist / pytest-memray | Rejected | New dev dependencies, and parallel workers multiply memory. The suite is plain `unittest`. | 2026-11-20 |

## Patterns adopted

- **Tiered tests via a skip decorator**: a single `heavy = unittest.skipUnless(os.getenv("RUN_HEAVY_TESTS") == "1", ...)` in `tests/_tiers.py`, applied to classes or methods.
- **Share one expensive fixture per class, then free it**: `setUpClass` builds it, `tearDownClass` deletes it and runs `gc.collect()`.
- **Stub at the seam**: API contract tests patch `toolpath_sim.generate_synthetic_carve_path` with a small real `ToolpathResult` built via `kinematics.build_trajectory`. `TestCollisionLogAPI._stub` in PR #4 already does this.
- **Fail early in production code**: `resample_path` checks the frame cap as it grows, instead of after building every frame.

## Verified facts

| Claim | Method |
| :--- | :--- |
| `tests/__init__.py`'s `RLIMIT_AS` ceiling never applies under `unittest discover -s tests` | In-process probe: after `TestLoader().discover('tests')`, no `tests*` module was in `sys.modules` and `getrlimit(RLIMIT_AS) == (-1, -1)`. The runner's 5.7 GB VSZ (above the 4 GB "cap") agrees. |
| The container is cgroup v1 with a 12 GiB limit | `/sys/fs/cgroup/memory/memory.limit_in_bytes = 12884901888`; `/sys/fs/cgroup/memory.max` doesn't exist. |
| cgroup usage includes about 4 GB of page cache | `memory.usage_in_bytes = 4.28 GB` while `MemAvailable` was 12.4 GB with no tests running. |
| One `demo` on `head_2` keeps about 130 MB and peaks at 392 MB | Probe: 96,141 frames in 177 s; RSS 82 → 211 MB retained, peak 392 MB, back to 105 MB after `del` + `gc`. |
| Frames are 13-key Python dicts (two tuples each) | Same probe: `t, r, theta, h, phi, r_s, theta_s, z_s, v_tip, is_rapid, tip_xyz_wax, tool_axis_wax, stage`. |
| **`TestSyntheticToolpaths.setUpClass` (sculpted base_head, `demo`) is the multi-GB spike** | Per-test RSS log: peak went from 611 MB to **3,495 MB** across that `setUpClass` (about 306 s); RSS afterwards was 530 MB. |
| **`test_standard_preset_produces_denser_path` (base_head, `standard`) got OOM-killed** | The runner was SIGKILLed (exit 137, not the 3.5 GB self-cap's exit 3) at 1,424 s, on the next test after the class fixture. |
| Base_head roughing is cheap | Phase probe: `build_roughing` 0.8 s, peak 176 MB, 5,896 joints. The probe was stopped before `build_finishing` finished, so the spike is in finishing, resampling, `build_trajectory`, the gouge scan or the broadside scan. |
| About 12 full generations per suite run | Source audit of `tests/test_carver_sim.py` (on `feat/head2-collision-logging` @ `0ef2167`): SyntheticToolpaths setUpClass + `standard`; Head2Target setUpClass; 3 `_FakeNeedle` demos plus a 600 mm-stock demo and a cap test; API demos in `TestSimulationAPI` (1) and `TestPatch10APIRegressions` (2, one at 600 mm stock). |
| The slowest default tests are API round trips | RSS log: `test_sculpt_and_sim_columnar_contract` 226 s, `test_demo_response_carries_geometry_provenance` 219 s, `test_max_frames_exceedance_maps_to_422` 169 s. |
| The frame cap is checked only after full resampling | `toolpath_sim.py:2166-2171`: `resample_path(...)` and then `if len(joints) > max_frames: raise`. |
| Retained RSS grows across the run | RSS log: 113 MB at the start, 530 MB at 1,424 s, with class fixtures never released. |
| `flock` and `prlimit` are installed; `/usr/bin/time` isn't; numpy uses scipy-openblas64 | `which`, `ls`, `numpy.show_config()`. |
| No `CLAUDE.md`, `AGENTS.md` or `TESTING.md` exists in the repo | `ls` at the repo root (`.gitignore` mentions a `TESTING.md` that doesn't exist). |

## Unverified assumptions

| Assumption | Cost to check |
| :--- | :--- |
| The base_head spike is in one phase after roughing, most likely `build_finishing` on the sculpted (nose 1.0) mesh or the gouge scan on its resampled frames | One capped phase probe (`ulimit -v 4194304`, about 5 min): **task 2.1**. |
| A 40 mm-tall stock with a scaled target keeps every structural invariant the toolpath tests assert (36 azimuth bins, negative `r_s` coverage, shadow clipping, retract planes) | Run those tests on the fixture: task 2.3. If one invariant needs full height, that test moves to the heavy tier. |
| A 4 GiB address-space cap with single-threaded BLAS doesn't fail healthy default-tier tests | Run the default tier under the runner: task 4.1. |

## Superseded claims

| Believed | Why wrong | Replaced by |
| :--- | :--- | :--- |
| "The 4 GB ceiling in `tests/__init__.py` protects the container" (PR #4, `0680411`) | It never runs under `discover -s tests`. | The runner's `ulimit -v` plus a peak-RSS budget. |
| "Each full generation costs about 400 MB, so it's just how many accumulate" | That's true for `head_2` (392 MB peak); the sculpted base_head `demo` peaks at about 3.5 GB. | Diagnosis task 2.1; the budget is per test. |
| "`memory.max − memory.current` is the available memory" | cgroup v1 here, and usage includes page cache. | The available-memory definition in the glossary. |

## Links out

- Per-test RSS log: `/tmp/claude-1001/-home-node-global-sandbox-projects-carving-simulation/7d85a417-af30-442b-b34b-be2e830e155e/scratchpad/rss.log` (scratchpad, may be cleared)
- Logging runner used: `.../scratchpad/rss_runner.py`; phase probe: `.../scratchpad/probe_phase.py`
- PR #4: https://github.com/slowbutfast/carving-simulation/pull/4 (adds the dead `tests/__init__.py` ceiling and the head2 test classes this change scopes)

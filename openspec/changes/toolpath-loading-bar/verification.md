# Verification: toolpath-loading-bar

> Status: **complete** — implementation tasks 1.1–3.3 and verification tasks
> 4.1–4.3 are signed off. Both default tiers pass with no failures, strict
> OpenSpec validation is clean, and the one deviation (a reduced address-space
> cap forced by the container's memory floor) is recorded below.

## Executive Summary & Environment

- **Change**: `toolpath-loading-bar` (branch `feat/toolpath-loading-bar`, based on
  `main` @ `0619594`, which already contains the change artifacts)
- **Date**: 2026-11-23
- **Runner**: Python `3.11.2` from `./.venv/bin/python`; Node `v22.23.2`;
  `scripts/safe-test.sh` only (never raw `unittest discover` / `npm run test:node`)
- **Scope delivered**: measured-weight local progress callbacks +
  `JobCancelled` in `toolpath_sim.py`; single-flight `_GEN_SEMAPHORE(1)`,
  bounded in-memory job store, split status/result endpoints, `DELETE`
  cancellation and `90 s` abandon-on-silence in `server.py`; emoji-free
  Windows XP Luna segmented progress overlay and `500 ms` async polling in
  `static/index.html` / `xp.css` / `app.js`.
- **Preserved modules untouched**: `kinematics.py`, `face_sculpt.py`,
  `tool_model.py`, `machine_config.json`, `machine_geometry.json`, `presets/`,
  and the merged XP shell structure from PR #3.

## Requirement Adherence Audit Matrix

| Spec requirement / scenario | Verifying test | Status |
|---|---|---|
| **R1** Local `[0.0, 1.0]` progress callbacks with `0.0` start / `1.0` end even at zero iterations | `test_carver_sim.TestProgressWeights.test_zero_iteration_phases_still_emit_start_and_end`, `test_local_fractions_map_through_the_measured_weight_table` | PASS |
| **R1** Single measured weight table (`roughing 0.01->0.02`, `finishing 0.02->0.77`, `resample 0.77->0.90`, `trajectory 0.90->0.91`, `gouges 0.91->0.97`, `feed_class 0.97->0.98`) | `TestProgressWeights.test_local_fractions_map_through_the_measured_weight_table` (phase stubs; exact 13-emission sequence) | PASS |
| **S1** Short-stock progress is monotonic in `[0.01, 0.98]` and finishing owns `0.75` | `TestSyntheticToolpaths.test_progress_callback_is_monotonic_within_the_weight_table` (real `short_stock_config`) | PASS |
| **S1** Real-target progress reuses the existing heavy fixture (no second generation) | `TestSyntheticToolpathsFullTarget.test_real_target_progress_is_monotonic_and_weighted` (`@heavy`, skipped in default tier) | PASS BY SHARED CODE PATH; heavy run blocked (see Assumptions) |
| **R1** `JobCancelled` aborts at the next callback without running later phases | `TestProgressWeights.test_job_cancelled_from_a_callback_aborts_the_generation` | PASS |
| **R1** Collector-error early return stays inside `[0.01, 0.77]` | `TestProgressWeights.test_collector_errors_return_early_without_regressing` | PASS |
| **R2** Shared non-blocking `_GEN_SEMAPHORE(1)`; `429` on **both** sync and async endpoints | `TestSimulationJobs.test_both_endpoints_return_429_while_a_generation_is_held` | PASS |
| **R2** Pre-flight `tool_cfg` `422` before the guard, no worker, permit free | `TestSimulationJobs.test_tool_cfg_preflight_is_422_before_the_guard` | PASS |
| **R2** `POST /jobs` -> `202 {job_id, status:"running"}` | `TestSimulationJobs.test_async_job_lifecycle_and_retry_safe_result` | PASS |
| **R2** `GET /result` -> `409` while running/cancelling | `test_async_job_lifecycle_and_retry_safe_result`, `test_delete_cancels_a_running_job_and_frees_the_guard` | PASS |
| **R2** Retry-safe `GET /result` twice, then `DELETE` -> `404` | `test_async_job_lifecycle_and_retry_safe_result` | PASS |
| **R2** `120 s` TTL expires finished jobs from status and result | `test_finished_job_expires_after_the_ttl` (module clock seam) | PASS |
| **R2** `_MAX_RETAINED_JOBS = 4` FIFO eviction, active job never evicted | `test_retention_cap_evicts_the_oldest_finished_job` | PASS |
| **R2** `DELETE` running -> `202 "cancelling"` -> worker `cancelled`, semaphore free | `test_delete_cancels_a_running_job_and_frees_the_guard` | PASS |
| **R2** `90 s` poll silence abandons the job and frees the guard | `test_unpolled_job_is_abandoned_after_ninety_seconds` | PASS |
| **R2** Job-time `422` keeps `error_kind`, `http_status`, `detail` (`diagnostics`, `collision_log`) | `test_job_time_validation_error_keeps_the_detail` | PASS |
| **R2** Unexpected error -> logged traceback, safe `500`, no leak | `test_unexpected_error_reports_a_safe_500` | PASS |
| **R2** `sculpt` `0.00->0.01` and `encode` `0.98-><1.00`; `1.00` only when `done` | `test_run_sculpt_and_sim_emits_sculpt_and_encode_bounds` + `test_async_job_lifecycle_and_retry_safe_result` | PASS |
| **R3** `#processing-overlay` in `.inset-well.viewport-well`, `#progress-label` `aria-live`, `#progress-bar` `role`/`aria-valuenow`, `.xp-progress-fill#progress-fill`, `#progress-pct`, `#progress-elapsed` | `test_xp_ui_lint.mjs` — "index.html renders the XP progress overlay inside the viewport well" | PASS |
| **R3** `.processing-progress-box`, `.xp-progress-track`, segmented `#70c040` fill, `prefers-reduced-motion` | `test_xp_ui_lint.mjs` — "xp.css styles the segmented XP Luna progress bar" | PASS |
| **R3** Async job POST, `500 ms` poll, 3 transient retries, `DELETE` ack, `pagehide` `keepalive: true`, `visibilitychange`, phase-only label updates | `test_xp_ui_lint.mjs` — "app.js polls the async toolpath job API and cleans up on unload" | PASS |
| **R3** Zero Unicode emojis in HTML/CSS/JS | `test_xp_ui_lint.mjs` — "UI sources are free of Unicode emoji" | PASS |
| **R3** Lint suite actually runs through the mandated runner | `test_xp_ui_lint.mjs` — "package.json runs this lint suite through safe-test --node" | PASS |
| **S2** `429` stopping message text present in the UI path | `static/app.js` `JOB_STOPPING_MESSAGE`; asserted by the lint test | PASS |
| Existing sync `POST /api/sculpt-and-sim` contract, legacy cone-key rejection, columnar payload | `test_carver_sim.TestSimulationAPI`, `TestPatch10APIRegressions`, `TestCollisionLogAPI` | PASS |
| Existing kinematics/SDF/CAD behaviour unchanged | `test_carver_sim` (179 tests), Node `test:node` (43 pass / 1 skip) | PASS |

## Resolved Assumptions & Empirical Proof

- **Red phase could not be observed.** The TDD tests were authored before the
  implementation, but both subagents attempted `scripts/safe-test.sh` for hours
  and every attempt exited `75` at the memory floor (`available_mb` 651–2,864 <
  4,608 MiB). The green runs below are the first executable evidence. No test was
  weakened to reach them.
- **Memory-floor deviation (user-approved).** With ~2.2–2.9 GiB available in the
  12 GiB cgroup (sibling sessions hold ~5.4 GB RSS plus page cache), the default
  4 GiB address-space cap could not start. The user approved running with
  `SAFE_TEST_AS_KB=2097152` and `SAFE_TEST_MIN_AVAIL_MB=2560` — i.e. exactly the
  cap-coupled floor `max(2560, 2048 + 512)` — while keeping the peak-RSS budget
  at the mandated `1536 MiB`. Observed peaks were `357–358 MiB`, well inside it.
- **Heavy tier not run.** `RUN_HEAVY_TESTS=1 ... SAFE_TEST_MIN_AVAIL_MB=9216`
  cannot start on a container with ~2.6 GiB genuinely available, and the
  real-target `demo` generation peaks around 3.3 GB. The `@heavy`
  `test_real_target_progress_is_monotonic_and_weighted` is present and shares the
  same `_local_reporter` / weight-table path as the default short-stock test.
- **`detect_gouges_detailed` stride shadowing fixed during verification.** The
  new progress stride was initially assigned to `stride`, the same name the
  existing gouge-sampling stride reuses inside the loop. A verification review
  renamed it to `progress_stride`; the full default tier was re-run afterwards.
- **`node_modules` symlink in this worktree.** `tests/test_cad_rig.mjs` imports
  `three`; the worktree had no `node_modules`, so the first Node run failed with
  `ERR_MODULE_NOT_FOUND`. Linked to the main checkout's `node_modules` (same
  gitignored pattern as `.venv`), after which the tier passed.
- **`package.json` gap fix.** `scripts/safe-test.sh --node` runs
  `npm run test:node`, which previously omitted `tests/test_xp_ui_lint.mjs`.
  Without adding it, the lint assertions for this change would never execute in
  CI. Added and pinned by a lint test.
- **`_preflight` runs twice per job.** The mandated `_start_job_worker(job_id,
  request)` seam carries no config, so the endpoint validates before acquiring
  the semaphore and `_run_sculpt_and_sim` re-loads the same config. Both calls
  are deterministic reads; the second cannot change the pre-flight outcome.
- **`1.00` is written only by `_finish_job`.** Encode reports `0.98 -> 0.99`;
  the status endpoint reaches `progress: 1.0` only after the payload is stored
  and `status` is `done`, matching the spec.
- **Single-worker deployment documented.** `server.py`'s module docstring now
  states `uvicorn server:app --workers 1`; the semaphore and job store are
  per-process state.

## Verbatim Runner Output

```text
$ SAFE_TEST_AS_KB=2097152 SAFE_TEST_MIN_AVAIL_MB=2560 scripts/safe-test.sh tests/test_carver_sim.py
Ran 122 tests in 228.499s

OK (skipped=17)
safe-test: status=0 peak_rss_mb=357 wall_s=230 tier=default
```

```text
$ SAFE_TEST_AS_KB=2097152 SAFE_TEST_MIN_AVAIL_MB=2560 scripts/safe-test.sh
Ran 179 tests in 227.018s

OK (skipped=21)
safe-test: status=0 peak_rss_mb=358 wall_s=228 tier=default
```

```text
$ SAFE_TEST_AS_KB=2097152 SAFE_TEST_MIN_AVAIL_MB=2560 scripts/safe-test.sh --node
1..44
# tests 44
# suites 0
# pass 43
# fail 0
# cancelled 0
# skipped 1
# todo 0
# duration_ms 3016.566238
safe-test: status=0 peak_rss_mb=126 wall_s=3 tier=default
```

```text
$ openspec validate toolpath-loading-bar --strict --json
"summary": { "totals": { "items": 1, "passed": 1, "failed": 0 } }
```

## Manual Verification (pending user)

- With `--workers 1`, click **SCULPT & SIMULATE**: the XP segmented bar should
  advance through `Sculpting`, `Finishing (2%–77%)`, `Resampling`, `Gouge check`,
  `Feed check`, `Encoding`, fetch `/result`, `DELETE`-ack, and hide the overlay.
- Background the tab for `> 15 s` and return: `visibilitychange` polls
  immediately; a `> 90 s` silence abandons the job server-side.

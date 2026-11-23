## Automated Tests

All Python and Node tests run through `scripts/safe-test.sh` (per `AGENTS.md`):

- `scripts/safe-test.sh tests/test_carver_sim.py`:
  - **Weight Table & Short-Stock Progress**: Fake-callback unit test verifying the measured weight table (`0.01->0.02`, `0.02->0.77`, `0.77->0.90`, `0.90->0.91`, `0.91->0.97`, `0.97->0.98`) including zero-iteration bounds, plus monotonic `on_progress` on `short_stock_target`.
  - **Cooperative `JobCancelled`**: Raising `JobCancelled` from `on_progress` aborts `generate_synthetic_carve_path` immediately and releases `_GEN_SEMAPHORE`.
  - **Job Lifecycle, `409`, Retry-Safe Result & `DELETE`** (patching `_start_job_worker` + `_stub_toolpath_result`): `POST /api/sculpt-and-sim/jobs` (`202`) $\to$ `GET /result` (`409` while running) $\to$ `GET /jobs/{id}` (`done`) $\to$ `GET /result` twice (identical payload) $\to$ `DELETE /jobs/{id}` $\to$ `404`.
  - **TTL Expiry & 4-Job Retention Cap**: Monkeypatched clock confirms `120 s` TTL expiry $\to$ `404`; 5 completed jobs evict the oldest finished job while never evicting an active `running`/`cancelling` job.
  - **`DELETE` Cancel & `90 s` Abandon-on-Silence**: `DELETE` on `running` returns `202` `status: "cancelling"`, worker aborts to `cancelled` and frees `_GEN_SEMAPHORE`; `last_poll_at` stale by `> 90 s` triggers `JobCancelled` and frees `_GEN_SEMAPHORE`.
  - **Single-Flight `429` Guard**: Holding `_GEN_SEMAPHORE` causes both `POST /api/sculpt-and-sim` and `POST /api/sculpt-and-sim/jobs` to return `429` immediately.
  - **Pre-Flight `422`, Job-Time `422` Parity & Safe `500`**: Immediate `422` on invalid Pydantic request or `tool_cfg.heated_length_mm > blade_length_mm`, job-time `422` `detail` parity (`diagnostics`, `collision_log`), and `500` generic message (traceback logged server-side).
- `RUN_HEAVY_TESTS=1 ... scripts/safe-test.sh tests/test_carver_sim.py` (verification only, reusing the existing `@heavy` `TestSyntheticToolpathsFullTarget` class fixture without adding a second 246 s generation; note container headroom requirement `>= 9,216 MiB`):
  - **Real-Target `on_progress`**: Confirms monotonic progress on `base_head` `demo`.
- `scripts/safe-test.sh --node` (`tests/test_xp_ui_lint.mjs`):
  - **XP Progress UI & Accessibility Lint**: Verifies `#processing-overlay`, `#progress-bar`, `#progress-fill.xp-progress-fill`, `aria-valuenow`, `aria-live`, `prefers-reduced-motion`, `pagehide` `keepalive: true`, `visibilitychange`, and zero Unicode emojis in `static/index.html`, `static/xp.css`, and `static/app.js`.

## Manual Verification

- **XP Progress Bar & Tab-Switch Resilience**:
  - **WHEN** the user clicks **SCULPT & SIMULATE**, switches to another browser tab for `> 15 s`, switches back, and lets the job finish
  - **THEN** `visibilitychange` polls immediately, the segmented green XP bar advances through `Finishing (2%–77%)`, `Resample`, `Gouges`, `Feed check`, and `Encoding`, fetches `/result`, sends `DELETE` ack, and hides cleanly.

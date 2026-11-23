## Automated Tests

All Python and Node tests run through `scripts/safe-test.sh` (per `AGENTS.md`):

- `scripts/safe-test.sh tests/test_carver_sim.py`:
  - **Weight Table & Short-Stock Progress**: Fake-callback test verifying the measured weight table (`0.01 / 0.75 / 0.13 / 0.01 / 0.08`), plus monotonic `[0.0, 0.98]` `on_progress` on `short_stock_target`.
  - **Job Lifecycle & Retry-Safe Result** (deterministic `_run_job` + `_stub_toolpath_result`): `POST /api/sculpt-and-sim/jobs` (`202`) $\to$ `GET /jobs/{id}` (`done`) $\to$ `GET /jobs/{id}/result` twice (retry-safe) $\to$ `DELETE /jobs/{id}` $\to$ `404`.
  - **Single-Flight `429` Guard**: Holding `_GEN_SEMAPHORE` causes both `POST /api/sculpt-and-sim` and `POST /api/sculpt-and-sim/jobs` to return `429` immediately.
  - **Structured `422` & Safe `500` Errors**: Immediate Pydantic `422`, job-time `422` `detail` parity (`diagnostics`, `collision_log`), and `500` generic message (traceback logged server-side).
  - **Cooperative Cancellation**: Raising `JobCancelled` from `on_progress` (via `DELETE` or >15 s silence) aborts cleanly and releases `_GEN_SEMAPHORE`.
- `RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh tests/test_carver_sim.py` (verification only):
  - **Real-Target `on_progress`**: Confirms monotonic progress on `base_head` `demo`.
- `scripts/safe-test.sh --node` (`tests/test_xp_ui_lint.mjs`):
  - **XP Progress UI & Accessibility Lint**: Verifies `#processing-overlay`, `#progress-bar`, `#progress-fill`, `aria-valuenow`, `aria-live`, `prefers-reduced-motion`, and zero Unicode emojis in `static/index.html`, `static/xp.css`, and `static/app.js`.

## Manual Verification

- **XP Progress Bar End-to-End**:
  - **WHEN** the user clicks **SCULPT & SIMULATE** in the XP Studio UI
  - **THEN** `#processing-overlay` displays the segmented green XP bar advancing from `1%` through `Finishing (75%)`, `Resample`, `Gouges`, and `Encoding`, fetches `/result`, sends `DELETE` ack, and hides cleanly.

## 1. Test Scaffolding (TDD)

- [ ] 1.1 Scaffold failing Python tests in `tests/test_carver_sim.py` for: measured weight-table mapping, short-stock monotonic `on_progress` + `@heavy` real-target `on_progress`, `JobCancelled` abort + `_GEN_SEMAPHORE` release, deterministic job API lifecycle (`202 -> done -> GET /result` retryable `-> DELETE -> 404`), `429` on both sync & async when `_GEN_SEMAPHORE` held, immediate & job-time `422` `detail` parity, and `500` safe error
- [ ] 1.2 Scaffold failing Node lint assertions in `tests/test_xp_ui_lint.mjs` for `#processing-overlay`, `#progress-bar`, `#progress-fill`, `aria-valuenow`, `aria-live`, `prefers-reduced-motion`, and zero Unicode emojis
- [ ] 1.3 Run `scripts/safe-test.sh tests/test_carver_sim.py` and `scripts/safe-test.sh --node` and confirm new tests fail

## 2. Backend Progress, Cancellation & Single-Flight Job API

- [ ] 2.1 Add `JobCancelled` and local `[0.0, 1.0]` `on_progress` callbacks to `resample_path`, `detect_gouges_detailed`, `build_roughing`, and `build_finishing` in `toolpath_sim.py`, mapped through the single measured weight table (`0.01/0.75/0.13/0.01/0.08`) in `generate_synthetic_carve_path`
- [ ] 2.2 Update `server.py`: add `_GEN_SEMAPHORE = threading.Semaphore(1)` (non-blocking `429` on both sync and async endpoints, always released in `finally`), `_JOBS` (`_MAX_RETAINED_JOBS = 4` finished jobs, `120 s` TTL, `100 ms` throttled updates, `15 s` abandon-on-silence), `POST /api/sculpt-and-sim/jobs`, `GET .../jobs/{id}`, retry-safe `GET .../jobs/{id}/result`, `DELETE .../jobs/{id}`, and structured `422`/`500` error mapping

## 3. Accessible XP Luna Segmented Progress UI

- [ ] 3.1 Add `#processing-overlay` markup (`#progress-label` `aria-live="polite"`, `#progress-bar` `role="progressbar"` `aria-valuenow`, `#progress-fill`, `#progress-pct`, `#progress-elapsed`, emoji-free) inside `.inset-well.viewport-well` in `static/index.html`
- [ ] 3.2 Style `.processing-progress-box`, `.xp-progress-track`, `.xp-progress-fill` (segmented `#70c040`), `.processing-overlay[hidden]`, and `@media (prefers-reduced-motion: reduce)` in `static/xp.css`
- [ ] 3.3 Update `sculptAndSimulate()` in `static/app.js` to handle non-202 POSTs, poll `GET .../jobs/{id}` every `500 ms` (3 transient retries, `404` recovery), fetch `/result`, send `DELETE` ack (plus `pagehide` cleanup), update `#progress-label` on phase change only + `aria-valuenow` on every tick, and always hide `#processing-overlay` in `finally`

## 4. Verification & Empirical Audit

- [ ] 4.1 Run `scripts/safe-test.sh` (default tier) and `scripts/safe-test.sh --node` and verify clean passes within budget
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate toolpath-loading-bar --strict --json`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix and verbatim `safe-test.sh` summary lines

## 0. Precondition

- [x] 0.1 PR #5 (`test-memory-scoping`) and PR #3 (`xp-ui-overhaul`) merged on `main` (`d979a03`); branch `feat/toolpath-loading-bar` from `main`

## 1. Test Scaffolding (TDD)

- [ ] 1.1 Scaffold failing Python tests in `tests/test_carver_sim.py` for: measured weight-table mapping (`0.01->0.02`, `0.02->0.77`, `0.77->0.90`, `0.90->0.91`, `0.91->0.97`, `0.97->0.98`) + zero-iteration bounds, short-stock monotonic `on_progress` + reusing existing `@heavy` `TestSyntheticToolpathsFullTarget` fixture for real-target `on_progress`, `JobCancelled` abort + `_GEN_SEMAPHORE` release, deterministic `_start_job_worker` + `_stub_toolpath_result` lifecycle (`202 -> 409 while running -> done -> GET /result` twice `-> DELETE -> 404`), `120 s` TTL expiry, 4-job FIFO eviction + active-job protection, `DELETE` `202` `cancelling -> cancelled`, `90 s` abandon-on-silence, `429` on both sync & async when `_GEN_SEMAPHORE` held, immediate `422` on `tool_cfg` + job-time `422` `detail` parity, and `500` safe message
- [ ] 1.2 Scaffold failing Node lint assertions in `tests/test_xp_ui_lint.mjs` for `#processing-overlay`, `#progress-bar`, `#progress-fill.xp-progress-fill`, `aria-valuenow`, `aria-live`, `prefers-reduced-motion`, `pagehide` `keepalive: true`, `visibilitychange`, and zero Unicode emojis
- [ ] 1.3 Run `scripts/safe-test.sh tests/test_carver_sim.py` and `scripts/safe-test.sh --node` and confirm new tests fail

## 2. Backend Progress, Cancellation & Single-Flight Job API

- [ ] 2.1 Add `JobCancelled` and local `[0.0, 1.0]` `on_progress(local_fraction, message)` callbacks (emitting `0.0` start and `1.0` end even on 0 iterations) to `resample_path` (throttled every `N` segments), `detect_gouges_detailed`, `build_roughing`, `build_finishing`, and the post-gouge `feed_class` loop in `toolpath_sim.py`, mapped through the single measured weight table in `generate_synthetic_carve_path`
- [ ] 2.2 Update `server.py` (documenting `--workers 1`): add `_GEN_SEMAPHORE = threading.Semaphore(1)` (non-blocking `429` on both sync and async endpoints, always released in `finally`), `_start_job_worker` seam, pre-flight `tool_cfg` `422` before semaphore acquisition, `_JOBS` (`running | cancelling | cancelled | done | error`, `_MAX_RETAINED_JOBS = 4` finished jobs FIFO, `120 s` TTL from completion, lock-free `100 ms` pre-check throttling, `90 s` abandon-on-silence), `POST /api/sculpt-and-sim/jobs`, `GET .../jobs/{id}`, retry-safe `GET .../jobs/{id}/result` (`409` while running), `DELETE .../jobs/{id}` (`202` `cancelling`), and structured `422`/`500` error mapping

## 3. Accessible XP Luna Segmented Progress UI

- [ ] 3.1 Add `#processing-overlay` markup (`#progress-label` `aria-live="polite"`, `#progress-bar` `role="progressbar"` `aria-valuenow`, `<div class="xp-progress-fill" id="progress-fill">`, `#progress-pct`, `#progress-elapsed`, emoji-free) inside `.inset-well.viewport-well` in `static/index.html`
- [ ] 3.2 Style `.processing-progress-box`, `.xp-progress-track`, `.xp-progress-fill` (segmented `#70c040`), and `@media (prefers-reduced-motion: reduce)` in `static/xp.css` (reusing PR #3's `.processing-overlay` and `[hidden]` rules)
- [ ] 3.3 Update `sculptAndSimulate()` in `static/app.js` to handle non-202 POSTs (`422`, `429` `"Previous generation is stopping..."`, `500`), poll `GET .../jobs/{id}` every `500 ms` (3 transient retries, `404` recovery, immediate poll on `visibilitychange`), fetch `/result`, send `DELETE` ack (plus `pagehide` `fetch(..., { method: "DELETE", keepalive: true })`), update `#progress-label` on phase change only + `aria-valuenow` on every tick, and always hide `#processing-overlay` in `finally`

## 4. Verification & Empirical Audit

- [ ] 4.1 Run `scripts/safe-test.sh` (default tier) and `scripts/safe-test.sh --node` and verify clean passes within budget
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate toolpath-loading-bar --strict --json`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix and verbatim `safe-test.sh` summary lines

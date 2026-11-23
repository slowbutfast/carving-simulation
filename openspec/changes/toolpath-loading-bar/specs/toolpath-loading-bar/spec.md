# toolpath-loading-bar Specification

## Purpose
Define loop-boundary progress reporting with measured phase weights, cooperative job cancellation, a shared single-flight generation guard with retry-safe split result retrieval, and an accessible, emoji-free Windows XP Luna segmented loading bar.

## ADDED Requirements

### Requirement: Measured-weight local progress callbacks and cooperative cancellation
`build_roughing`, `build_finishing`, `resample_path`, `detect_gouges_detailed`, and the post-gouge `feed_class` pass in `toolpath_sim.py` SHALL accept `on_progress: Callable[[float, str], None] | None = None`, reporting local `[0.0, 1.0]` progress (`0.0` at start, `1.0` at completion even when 0 iterations occur) at loop boundaries. `generate_synthetic_carve_path` SHALL accept `on_progress: Callable[[str, float, str], None] | None = None` and map local fractions through a single measured weight table:
- `sculpt`: `0.00 -> 0.01` (emitted by `server.py` before `apply_facial_modifications`)
- `roughing`: `0.01 -> 0.02`
- `finishing`: `0.02 -> 0.77`
- `resample`: `0.77 -> 0.90`
- `trajectory`: `0.90 -> 0.91`
- `gouges`: `0.91 -> 0.97`
- `feed_class`: `0.97 -> 0.98`
- `encode`: `0.98 -> 1.00` (emitted by `server.py`; `1.00` is emitted only when `status == "done"` and the result is stored)

Raising `JobCancelled` from `on_progress` SHALL abort generation cleanly at the next loop boundary.

#### Scenario: Phase progress is monotonic and respects measured weights
- **WHEN** `generate_synthetic_carve_path` runs with `on_progress` on a short-stock fixture (or fake phase callbacks)
- **THEN** emitted global fractions are monotonically non-decreasing in `[0.01, 0.98]`, `finishing` accounts for `0.75` (`0.02 -> 0.77`), and zero-iteration phases still emit start and end bounds

#### Scenario: Cooperative cancellation aborts at next callback
- **WHEN** `on_progress` raises `JobCancelled` during `build_finishing` or `resample_path`
- **THEN** `generate_synthetic_carve_path` aborts immediately without executing subsequent phases

### Requirement: Single-flight generation guard, split job/result endpoints, and structured errors
`server.py` SHALL guard both `POST /api/sculpt-and-sim` and `POST /api/sculpt-and-sim/jobs` with a shared per-process `_GEN_SEMAPHORE = threading.Semaphore(1)` using non-blocking acquire (`429 Too Many Requests` when busy, always releasing in `finally`). Job `status` SHALL be one of `running | cancelling | cancelled | done | error`.
- Pre-flight validation (Pydantic request validation and `tool_cfg.heated_length_mm > blade_length_mm`) SHALL run before acquiring `_GEN_SEMAPHORE`, returning an immediate HTTP 422.
- `POST /api/sculpt-and-sim/jobs` SHALL return `202` with `{ job_id, status: "running" }` and initialize `last_poll_at = time.monotonic()`.
- `GET /api/sculpt-and-sim/jobs/{job_id}` SHALL refresh `last_poll_at` and return lightweight `{ job_id, status, phase, progress, message, elapsed_ms, error_kind?, http_status?, detail? }` (`404` if unknown or expired).
- `GET /api/sculpt-and-sim/jobs/{job_id}/result` SHALL return `409` while `running`/`cancelling`, `404` if missing/expired/cancelled, and the full encoded payload retry-safely when `done` until `DELETE` or `120 s` post-completion TTL.
- Finished job retention (`_MAX_RETAINED_JOBS = 4`) SHALL evict the oldest finished (`done | error | cancelled`) job by `completed_at` and SHALL NEVER evict a `running` or `cancelling` job.
- `DELETE /api/sculpt-and-sim/jobs/{job_id}` SHALL return `202` `{ job_id, status: "cancelling" }` when active (setting `cancel_event`, transitioning to `cancelled` once `_GEN_SEMAPHORE` is released) or delete a finished job immediately (`200`).
- Poll silence `> 90 s` SHALL trigger `JobCancelled` on the next `on_progress` call.
- Job-time `422` errors SHALL preserve `_validation_error`'s `detail` (`diagnostics`, `collision_log`), while `500` errors log tracebacks server-side and return a safe generic message.

#### Scenario: Async job lifecycle and retry-safe result
- **WHEN** a client submits `POST /api/sculpt-and-sim/jobs`, polls `GET /jobs/{id}` until `done`, fetches `GET /jobs/{id}/result` twice, and sends `DELETE /jobs/{id}`
- **THEN** both `GET /result` calls return the identical payload, and a subsequent `GET /jobs/{id}` returns `404`

#### Scenario: Result endpoint returns 409 while job is running
- **WHEN** `GET /api/sculpt-and-sim/jobs/{job_id}/result` is called while `status` is `running` or `cancelling`
- **THEN** the endpoint returns HTTP `409`

#### Scenario: Finished job expires after 120 s TTL
- **WHEN** `120 s` elapse after a job reaches `done`, `error`, or `cancelled`
- **THEN** subsequent `GET /jobs/{id}` and `GET /jobs/{id}/result` requests return `404`

#### Scenario: Retention cap evicts oldest finished job without evicting active job
- **WHEN** four finished jobs are retained and a fifth job completes (while an active job is running)
- **THEN** the oldest finished job is evicted, the active job is never evicted, and `GET` on the evicted ID returns `404`

#### Scenario: DELETE cancels running job and frees semaphore
- **WHEN** `DELETE /api/sculpt-and-sim/jobs/{job_id}` is called on a `running` job
- **THEN** `DELETE` returns `202` with `status: "cancelling"`, the worker raises `JobCancelled` at the next callback, transitions the job to `cancelled`, and releases `_GEN_SEMAPHORE`

#### Scenario: Abandon-on-silence cancels unpolled job after 90 s
- **WHEN** `time.monotonic() - last_poll_at > 90.0` on a `running` job
- **THEN** the next `on_progress` invocation raises `JobCancelled`, transitions the job to `cancelled`, and frees `_GEN_SEMAPHORE`

#### Scenario: Immediate 422 on invalid tool_cfg and job-time 422 detail parity
- **WHEN** `tool_cfg.heated_length_mm > blade_length_mm` is submitted OR generation produces a `SOFT_LIMIT_EXCEEDED`/`FRAME_CAP_EXCEEDED` error
- **THEN** `POST /jobs` returns immediate `422` for invalid `tool_cfg`, and job-time `422` errors populate `error_kind: "validation"`, `http_status: 422`, and full `detail` (`diagnostics`, `collision_log`)

#### Scenario: Internal 500 logs traceback and returns safe message
- **WHEN** an unexpected exception occurs inside `_run_job`
- **THEN** the traceback is logged server-side, `_GEN_SEMAPHORE` is released in `finally`, and `GET /jobs/{id}` reports `error_kind: "internal"`, `http_status: 500`, and a safe generic message without raw tracebacks

#### Scenario: Concurrent submission returns 429
- **WHEN** `POST /api/sculpt-and-sim/jobs` or `POST /api/sculpt-and-sim` is called while `_GEN_SEMAPHORE` is held
- **THEN** the endpoint returns `429` immediately

### Requirement: Accessible, emoji-free Windows XP Luna segmented progress bar
`static/index.html`, `static/xp.css`, and `static/app.js` SHALL render `#processing-overlay` inside `.inset-well.viewport-well` with an emoji-free segmented `#70c040` `.xp-progress-track` / `#progress-fill.xp-progress-fill`, `#progress-label` (`aria-live="polite"`, updated only on phase transitions), `#progress-bar` (`role="progressbar"`, `aria-valuenow`), `#progress-pct`, `#progress-elapsed`, and `@media (prefers-reduced-motion: reduce)`. `sculptAndSimulate()` SHALL handle non-202 POST errors (`422`, `429` shown as `"Previous generation is stopping — try again in a moment"`, `500`), poll every `500 ms` with up to `3` transient network retries, poll immediately on `visibilitychange` when returning to a visible tab, fetch `/result`, send `DELETE` ack, register `pagehide` cleanup using `fetch(url, { method: "DELETE", keepalive: true })`, and always hide `#processing-overlay` in `finally`.

#### Scenario: UI polling updates accessible XP progress bar and recovers on every terminal path
- **WHEN** the user triggers `SCULPT & SIMULATE` and the job completes, fails with `422`/`500`, receives `429`, expires (`404`), or the page unloads (`pagehide`)
- **THEN** `#progress-fill.xp-progress-fill` and `aria-valuenow` track progress without emojis, `#progress-label` updates only on phase transitions, `pagehide` sends `fetch(..., { method: "DELETE", keepalive: true })`, and `#processing-overlay` hides cleanly in `finally`

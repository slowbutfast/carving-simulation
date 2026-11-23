# toolpath-loading-bar Specification

## Purpose
Define loop-boundary progress reporting with measured phase weights, cooperative job cancellation, a shared single-flight generation guard with retry-safe split result retrieval, and an accessible, emoji-free Windows XP Luna segmented loading bar.

## ADDED Requirements

### Requirement: Measured-weight local progress callbacks and cooperative cancellation
`build_roughing`, `build_finishing`, `resample_path`, and `detect_gouges_detailed` in `toolpath_sim.py` SHALL accept an optional `on_progress(local_fraction, message)` callback reporting local `[0.0, 1.0]` progress (`0.0` at start, `1.0` at completion even when 0 iterations occur) at loop boundaries. `generate_synthetic_carve_path` SHALL map local fractions through a single measured weight table (`roughing: 0.01->0.02`, `finishing: 0.02->0.77`, `resample: 0.77->0.90`, `trajectory: 0.90->0.91`, `gouges: 0.91->0.98`, leaving `0.98->1.00` for encoding) and SHALL NOT emit `1.00` until the job result is stored. Raising `JobCancelled` from `on_progress` SHALL abort generation cleanly at the next loop boundary.

#### Scenario: Phase progress is monotonic and respects measured weights
- **WHEN** `generate_synthetic_carve_path` runs with `on_progress` on a short-stock fixture (or fake phase callbacks)
- **THEN** emitted global fractions are monotonically non-decreasing in `[0.0, 0.98]`, `finishing` accounts for ~`75%` of the bar, and raising `JobCancelled` inside `on_progress` aborts without completing remaining phases

### Requirement: Single-flight generation guard, split job/result endpoints, and structured errors
`server.py` SHALL guard both `POST /api/sculpt-and-sim` and `POST /api/sculpt-and-sim/jobs` with a shared per-process `_GEN_SEMAPHORE = threading.Semaphore(1)` using non-blocking acquire (`429 Too Many Requests` when busy, always releasing in `finally` including submission/cancellation errors). `POST /api/sculpt-and-sim/jobs` SHALL return `202` with `{ job_id, status: "running" }` (or immediate `422` on Pydantic validation error). `GET /api/sculpt-and-sim/jobs/{job_id}` SHALL refresh `last_poll_at` and return lightweight `{ job_id, status, phase, progress, message, elapsed_ms, error_kind?, http_status?, detail? }`. `GET /api/sculpt-and-sim/jobs/{job_id}/result` SHALL return the full encoded payload retry-safely until `DELETE /api/sculpt-and-sim/jobs/{job_id}` or `120 s` post-completion TTL (`409` if running, `404` if missing/expired), retaining at most `4` finished jobs (never evicting an active job). Job-time `422` errors SHALL preserve `_validation_error`'s `detail` (`diagnostics`, `collision_log`), while `500` errors log tracebacks server-side and return a safe generic message. `DELETE` or `> 15 s` poll silence SHALL trigger `JobCancelled`.

#### Scenario: Job lifecycle, retry-safe result, 429 guard, 422 parity, and cancellation
- **WHEN** a client submits `POST /api/sculpt-and-sim/jobs`
- **THEN** concurrent sync or async requests receive `429`, `GET .../result` succeeds across repeated fetches until `DELETE` or TTL expiry (`404`), invalid `tool_cfg` produces `error_kind: "validation"` with `422` `detail`, and `DELETE` (or `JobCancelled`) frees `_GEN_SEMAPHORE`

### Requirement: Accessible, emoji-free Windows XP Luna segmented progress bar
`static/index.html`, `static/xp.css`, and `static/app.js` SHALL render `#processing-overlay` inside `.inset-well.viewport-well` with an emoji-free segmented `#70c040` `.xp-progress-track` / `#progress-fill`, `#progress-label` (`aria-live="polite"`, updated only on phase changes), `#progress-bar` (`role="progressbar"`, `aria-valuenow`), `#progress-pct`, `#progress-elapsed`, and `@media (prefers-reduced-motion: reduce)`. `sculptAndSimulate()` SHALL handle non-202 POST errors (`422`, `429`, `500`), poll every `500 ms` with up to `3` transient network retries and `404` expiry/restart recovery, fetch `/result`, send `DELETE` ack (and `pagehide` cleanup), and always hide `#processing-overlay` in `finally`.

#### Scenario: UI polling updates accessible XP progress bar and recovers on every terminal path
- **WHEN** the user triggers `SCULPT & SIMULATE` and the job completes, fails with `422`/`500`, returns `429`, or expires (`404`)
- **THEN** `#progress-fill` and `aria-valuenow` track progress without emojis, `#progress-label` updates only on phase transitions, and `#processing-overlay` hides cleanly in `finally`

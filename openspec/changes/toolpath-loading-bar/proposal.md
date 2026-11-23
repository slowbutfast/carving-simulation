## Why

`POST /api/sculpt-and-sim` runs synchronously for ~246 s (`demo` on `base_head`, > 5 min on `standard`) while `toolpath_sim.generate_synthetic_carve_path` computes roughing, finishing, resampling, kinematics, gouges, and feed-direction checks, leaving the XP Luna UI with static `"Generating toolpath..."` text and risking Cloudflare/browser timeouts.

## What Changes

- **Measured-Weight Local Progress & Cooperative Cancellation (`toolpath_sim.py`)**:
  - Add `JobCancelled` and local `[0.0, 1.0]` `on_progress(local_fraction, message)` callbacks to `build_roughing`, `build_finishing`, `resample_path`, `detect_gouges_detailed`, and the post-gouge `feed_class` loop.
  - Map local fractions through a single measured weight table in `generate_synthetic_carve_path` (`roughing: 0.01->0.02`, `finishing: 0.02->0.77`, `resample: 0.77->0.90`, `trajectory: 0.90->0.91`, `gouges: 0.91->0.97`, `feed_class: 0.97->0.98`), while `server.py` emits `sculpt` (`0.00->0.01`) and `encode` (`0.98->1.00`).
- **Single-Flight Guard & Split Async Job API (`server.py`, `specs/face-sculpt-sim/spec.md`)**:
  - Add `_GEN_SEMAPHORE = threading.Semaphore(1)` (non-blocking `429` on **both** `POST /api/sculpt-and-sim` and `POST /api/sculpt-and-sim/jobs`), lock-free pre-check throttling (`>= 100 ms` or phase change), `_start_job_worker` seam for deterministic tests, `DELETE /api/sculpt-and-sim/jobs/{id}` (`202` `cancelling` → `cancelled`) + `90 s` abandon-on-silence, split `GET .../jobs/{id}` (status) and retry-safe `GET .../jobs/{id}/result` (`409` while running, retained until `DELETE` ack or `120 s` TTL, `_MAX_RETAINED_JOBS = 4` finished jobs), pre-flight `422` for `tool_cfg`, and structured `422`/`500` error parity.
- **Accessible XP Luna Segmented Progress Bar (`static/index.html`, `static/xp.css`, `static/app.js`)**:
  - Add `#processing-overlay` inside `.inset-well.viewport-well` reusing PR #3's `.processing-overlay` / `[hidden]` rules, replace `.processing-spinner` with an emoji-free segmented `#70c040` `.xp-progress-track` / `#progress-fill.xp-progress-fill` (`aria-valuenow`, `aria-live="polite"` on phase change only, `prefers-reduced-motion`), and wire `500 ms` polling with transient retry, `visibilitychange` immediate poll, `404` recovery, `429` stopping message, and `pagehide` `fetch(..., { method: "DELETE", keepalive: true })`.

## Capabilities

### New Capabilities
- `toolpath-loading-bar`: Phase-weighted progress callbacks, cooperative job cancellation, single-flight bounded async job/result API, and accessible Windows XP Luna segmented progress bar.

### Modified Capabilities
- `face-sculpt-sim`: `POST /api/sculpt-and-sim` returns HTTP 429 non-blockingly when `_GEN_SEMAPHORE` is occupied.

## Impact

- **Modified:** `toolpath_sim.py`, `server.py`, `static/index.html`, `static/xp.css`, `static/app.js`, `tests/test_carver_sim.py`, `tests/test_xp_ui_lint.mjs`.
- **Sequencing:** PR #5 (`test-memory-scoping`) and PR #3 (`xp-ui-overhaul`) are already merged on `main`; `feat/toolpath-loading-bar` branches cleanly from `main`.

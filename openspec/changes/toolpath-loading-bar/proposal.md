## Why

`POST /api/sculpt-and-sim` runs synchronously for 60–195 s while `toolpath_sim.generate_synthetic_carve_path` computes roughing, finishing, resampling, kinematics, and gouge checks, leaving the XP Luna UI with static `"Generating toolpath..."` text and risking Cloudflare/browser timeouts.

## What Changes

- **Measured-Weight Local Progress & Cooperative Cancellation (`toolpath_sim.py`)**:
  - Add `JobCancelled` and local `[0.0, 1.0]` `on_progress` callbacks to `build_roughing`, `build_finishing`, `resample_path`, and `detect_gouges_detailed`, mapped through a single measured weight table (`0.01 / 0.75 / 0.13 / 0.01 / 0.08`, plus `0.02` encode) in `generate_synthetic_carve_path`.
- **Single-Flight Guard & Split Async Job API (`server.py`)**:
  - Add `_GEN_SEMAPHORE = threading.Semaphore(1)` (non-blocking `429` on **both** `POST /api/sculpt-and-sim` and `POST /api/sculpt-and-sim/jobs`), throttled progress updates (`>= 100 ms` or phase change), `DELETE /api/sculpt-and-sim/jobs/{id}` + `15 s` abandon-on-silence cancellation, split `GET .../jobs/{id}` (status) and retry-safe `GET .../jobs/{id}/result` (retained until `DELETE` ack or `120 s` TTL, `_MAX_RETAINED_JOBS = 4` finished jobs), and structured `422` `detail` parity.
- **Accessible XP Luna Segmented Progress Bar (`static/index.html`, `static/xp.css`, `static/app.js`)**:
  - Add `#processing-overlay` inside `.inset-well.viewport-well`, replace `.processing-spinner` with an emoji-free segmented `#70c040` `.xp-progress-track` / `.xp-progress-fill` (`aria-valuenow`, `aria-live="polite"` on phase change only, `prefers-reduced-motion`), and wire `500 ms` polling with transient retry, `404` recovery, and `pagehide` cleanup.

## Capabilities

### New Capabilities
- `toolpath-loading-bar`: Phase-weighted progress callbacks, cooperative job cancellation, single-flight bounded async job/result API, and accessible Windows XP Luna segmented progress bar.

## Impact

- **Modified:** `toolpath_sim.py`, `server.py`, `static/index.html`, `static/xp.css`, `static/app.js`, `tests/test_carver_sim.py`, `tests/test_xp_ui_lint.mjs`.
- **Branch Ordering:** Sequence after PR #5 (`test-memory-scoping`) and PR #3 (`xp-ui-overhaul`) merge into `main`.

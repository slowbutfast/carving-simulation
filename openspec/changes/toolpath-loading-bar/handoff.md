# OpenCode Orchestration Handoff: OpenSpec Change 'toolpath-loading-bar'

You are the orchestration agent for OpenSpec change 'toolpath-loading-bar' running in OpenCode.
Your primary directive is to execute this change using the **`openspec-apply-sub`** skill, which delegates task implementation to the `spec-coder-sub` subagent.

> [!IMPORTANT]
> **Primary Test Runner (`AGENTS.md`)**:
> Run all Python and Node tests through `scripts/safe-test.sh` (never raw `python -m unittest discover -s tests` or raw `npm run test:node`, and never lower `SAFE_TEST_MIN_AVAIL_MB`).

## 1. Orchestration Directive
- **Change Name**: `toolpath-loading-bar`
- **Target Skill**: `openspec-apply-sub` (or `/opsx:apply-sub toolpath-loading-bar`)
- **Architecture Paradigm**: Vertical Slice Architecture (VSA). Keep local `[0.0, 1.0]` phase callbacks decoupled from the single weight table in `generate_synthetic_carve_path`, and keep the job store cleanly isolated in `server.py`.

## 2. Target Context Map
| File Path (relative to repo root) | Target Lines | Modification Summary |
|---|---|---|
| `toolpath_sim.py` | `L510-L595, L1224-L1317, L1318-L1415, L1862-L1950, L2125-L2250` | Add `JobCancelled(RuntimeError)` and optional `on_progress(local_fraction, message)` (`[0.0, 1.0]`, emitting `0.0` at start and `1.0` at end even on 0 iterations) to `resample_path` (throttled every `max(1, total // 20)` segments), `detect_gouges_detailed`, `build_roughing`, `build_finishing`, and the post-gouge `feed_class` loop. In `generate_synthetic_carve_path`, accept `on_progress(phase, global_fraction, message)` and map via the single measured weight table (`roughing: 0.01->0.02`, `finishing: 0.02->0.77`, `resample: 0.77->0.90`, `trajectory: 0.90->0.91`, `gouges: 0.91->0.97`, `feed_class: 0.97->0.98`). |
| `server.py` | `L1-L45, L310-L410` | Document `--workers 1` requirement in module docstring. Add `_GEN_SEMAPHORE = threading.Semaphore(1)` (always released in `finally`), `_JOBS_LOCK`, `_JOBS` (`running \| cancelling \| cancelled \| done \| error`, `_MAX_RETAINED_JOBS = 4` finished jobs FIFO by `completed_at`, never evicting active jobs, `120 s` TTL from completion), and `_start_job_worker(job_id, request)` test seam. Extract `_run_sculpt_and_sim(request, on_progress=None)` emitting `sculpt` (`0.00->0.01`) and `encode` (`0.98->1.00`, never `1.00` until `done` & stored). Make `POST /api/sculpt-and-sim` non-blocking (`429` if busy). Add pre-flight `tool_cfg` `422` before semaphore acquisition; add `POST /api/sculpt-and-sim/jobs` (`202` / `429`), `GET /api/sculpt-and-sim/jobs/{job_id}` (refreshes `last_poll_at`, lock-free `100 ms` pre-check throttling), `GET /api/sculpt-and-sim/jobs/{job_id}/result` (`409` while running/cancelling, retry-safe when `done`, `404` when missing/expired/cancelled), and `DELETE /api/sculpt-and-sim/jobs/{job_id}` (`202` `cancelling` → `cancelled` on next callback; `200` on finished jobs). Trigger `JobCancelled` on `cancel_event` or `> 90 s` poll silence. Preserve structured `422` `detail` (`diagnostics`, `collision_log`), and log `500` tracebacks server-side with a safe generic message. |
| `static/index.html` | `L179-L198` | Add `#processing-overlay` inside `.inset-well.viewport-well` with `.processing-box.processing-progress-box`, `#progress-label` (`aria-live="polite"`), `#progress-bar` (`role="progressbar"`, `aria-labelledby="progress-label"`, `aria-valuemin="0"`, `aria-valuemax="100"`, `aria-valuenow="0"`), `<div class="xp-progress-fill" id="progress-fill">`, `#progress-pct`, and `#progress-elapsed` (strictly emoji-free). |
| `static/xp.css` | `L810-L850` | Reuse existing `.processing-overlay` and `.processing-overlay[hidden] { display: none; }` rules; add `.processing-progress-box`, `.xp-progress-track`, `.xp-progress-fill` (XP Luna segmented `#70c040` blocks), and `@media (prefers-reduced-motion: reduce) { .xp-progress-fill { transition: none; } }`. |
| `static/app.js` | `L600-L650` | Update `sculptAndSimulate()` to handle non-202 POSTs (`422`, `429` `"Previous generation is stopping — try again in a moment"`, `500`), poll `GET /api/sculpt-and-sim/jobs/{id}` every `500 ms` (up to `3` transient retries, `404` recovery, immediate poll on `visibilitychange`), fetch `GET .../result` on `done`, send `DELETE` ack (plus `pagehide` `fetch(url, { method: "DELETE", keepalive: true })`), update `#progress-label` only on phase transitions + `aria-valuenow` on every tick, and always hide `#processing-overlay` in `finally`. |
| `tests/test_carver_sim.py` | `[APPEND]` | Add TDD tests for: measured weight-table mapping + zero-iteration bounds, short-stock monotonic `on_progress` + reusing existing `@heavy` `TestSyntheticToolpathsFullTarget` fixture for real-target `on_progress`, `JobCancelled` abort + `_GEN_SEMAPHORE` release, deterministic `_start_job_worker` + `_stub_toolpath_result` lifecycle (`202 -> 409 -> done -> GET /result` twice `-> DELETE -> 404`), `120 s` TTL expiry, 4-job FIFO eviction + active-job protection, `DELETE` `202` `cancelling -> cancelled`, `90 s` abandon-on-silence, `429` on both sync & async, pre-flight `tool_cfg` `422` + job-time `422` parity, and `500` safe error. |
| `tests/test_xp_ui_lint.mjs` | `[APPEND]` | Assert `#processing-overlay`, `#progress-bar`, `#progress-fill.xp-progress-fill`, `aria-valuenow`, `aria-live`, `prefers-reduced-motion`, `pagehide` `keepalive: true`, `visibilitychange`, and zero Unicode emojis in `static/index.html`, `static/xp.css`, and `static/app.js`. |

## 3. Technical & Architectural Boundaries
- **In-Scope Decisions**:
  - **Measured Weight Table**: `sculpt (0.00->0.01)`, `roughing (0.01->0.02)`, `finishing (0.02->0.77)`, `resample (0.77->0.90)`, `trajectory (0.90->0.91)`, `gouges (0.91->0.97)`, `feed_class (0.97->0.98)`, `encode (0.98->1.00)`. Never emit `1.00` until `status == "done"` and `result` is stored.
  - **Per-Process Single-Flight Guard (`--workers 1`)**: `_GEN_SEMAPHORE = threading.Semaphore(1)` protects both sync and async endpoints (`429` non-blocking). Do NOT use `ProcessPoolExecutor`.
  - **Throttle Outside `_JOBS_LOCK`**: Check `monotonic() - last_write >= 0.1` and `phase == last_phase` before acquiring `_JOBS_LOCK`.
- **Hard Exclusions / No-Go**:
  - Do NOT modify `.env`, `.env.*`, or credential files.
  - Do NOT add a UI Cancel button (v1 uses `DELETE` + `pagehide` `keepalive: true` + `90 s` abandon-on-silence).
  - Do NOT use Unicode emojis in UI markup, CSS, or JS strings.

## 4. Visual & UI Design Specifications
- **Theme**: `Windows XP Luna Studio (4-DOF Wax Carver)` (`DESIGN.md` / `openspec/changes/toolpath-loading-bar/design.md`)
- **Key Tokens**:
  - Surface: `#ece9d8` | Track Inset: `#ffffff` | Border Highlight: `#ffffff` | Border Shadow: `#918e82` | Progress Fill: `#70c040` (`8px` blocks, `2px` gap)
  - Text: `#222222` (`Tahoma 11px` labels, `Courier New 11px` pct/elapsed)
- **Component States**:
  - **Busy / Active**: `#processing-overlay` visible, `#simulate-button` disabled, `#progress-fill.xp-progress-fill` advancing.
  - **Phase Transition**: `#progress-label` (`aria-live="polite"`) updates only when `phase` changes.
  - **Complete / Error / `429` Stopping**: `#processing-overlay` hides in `finally`; `#status-state` shows `ERROR` (`.status-badge-collision`) or `"Previous generation is stopping — try again in a moment"`.

## 5. Test Scaffolding & Verification Commands
- **Primary Test Runners**:
  - Targeted Python: `scripts/safe-test.sh tests/test_carver_sim.py`
  - Default Python Tier: `scripts/safe-test.sh` (`peak_rss_mb <= 1536`, `wall_s <= 600`)
  - Node Tier: `scripts/safe-test.sh --node` and `node --test tests/test_xp_ui_lint.mjs`
- **TDD Requirement**: Task group `## 1` MUST scaffold failing unit/lint/API tests before touching implementation code. Verify they fail initially.

## 6. Implementation Task Checklist
- [x] 0.1 PR #5 (`test-memory-scoping`) and PR #3 (`xp-ui-overhaul`) merged on `main` (`d979a03`); branch `feat/toolpath-loading-bar` from `main`
- [ ] 1.1 Scaffold failing Python tests in `tests/test_carver_sim.py` for: measured weight-table mapping (`0.01->0.02`, `0.02->0.77`, `0.77->0.90`, `0.90->0.91`, `0.91->0.97`, `0.97->0.98`) + zero-iteration bounds, short-stock monotonic `on_progress` + reusing existing `@heavy` `TestSyntheticToolpathsFullTarget` fixture for real-target `on_progress`, `JobCancelled` abort + `_GEN_SEMAPHORE` release, deterministic `_start_job_worker` + `_stub_toolpath_result` lifecycle (`202 -> 409 while running -> done -> GET /result` twice `-> DELETE -> 404`), `120 s` TTL expiry, 4-job FIFO eviction + active-job protection, `DELETE` `202` `cancelling -> cancelled`, `90 s` abandon-on-silence, `429` on both sync & async when `_GEN_SEMAPHORE` held, immediate `422` on `tool_cfg` + job-time `422` `detail` parity, and `500` safe message
- [ ] 1.2 Scaffold failing Node lint assertions in `tests/test_xp_ui_lint.mjs` for `#processing-overlay`, `#progress-bar`, `#progress-fill.xp-progress-fill`, `aria-valuenow`, `aria-live`, `prefers-reduced-motion`, `pagehide` `keepalive: true`, `visibilitychange`, and zero Unicode emojis
- [ ] 1.3 Run `scripts/safe-test.sh tests/test_carver_sim.py` and `scripts/safe-test.sh --node` and confirm new tests fail
- [ ] 2.1 Add `JobCancelled` and local `[0.0, 1.0]` `on_progress(local_fraction, message)` callbacks (emitting `0.0` start and `1.0` end even on 0 iterations) to `resample_path` (throttled every `N` segments), `detect_gouges_detailed`, `build_roughing`, `build_finishing`, and the post-gouge `feed_class` loop in `toolpath_sim.py`, mapped through the single measured weight table in `generate_synthetic_carve_path`
- [ ] 2.2 Update `server.py` (documenting `--workers 1`): add `_GEN_SEMAPHORE = threading.Semaphore(1)` (non-blocking `429` on both sync and async endpoints, always released in `finally`), `_start_job_worker` seam, pre-flight `tool_cfg` `422` before semaphore acquisition, `_JOBS` (`running | cancelling | cancelled | done | error`, `_MAX_RETAINED_JOBS = 4` finished jobs FIFO, `120 s` TTL from completion, lock-free `100 ms` pre-check throttling, `90 s` abandon-on-silence), `POST /api/sculpt-and-sim/jobs`, `GET .../jobs/{id}`, retry-safe `GET .../jobs/{id}/result` (`409` while running), `DELETE .../jobs/{id}` (`202` `cancelling`), and structured `422`/`500` error mapping
- [ ] 3.1 Add `#processing-overlay` markup (`#progress-label` `aria-live="polite"`, `#progress-bar` `role="progressbar"` `aria-valuenow`, `<div class="xp-progress-fill" id="progress-fill">`, `#progress-pct`, `#progress-elapsed`, emoji-free) inside `.inset-well.viewport-well` in `static/index.html`
- [ ] 3.2 Style `.processing-progress-box`, `.xp-progress-track`, `.xp-progress-fill` (segmented `#70c040`), and `@media (prefers-reduced-motion: reduce)` in `static/xp.css` (reusing PR #3's `.processing-overlay` and `[hidden]` rules)
- [ ] 3.3 Update `sculptAndSimulate()` in `static/app.js` to handle non-202 POSTs (`422`, `429` `"Previous generation is stopping..."`, `500`), poll `GET .../jobs/{id}` every `500 ms` (3 transient retries, `404` recovery, immediate poll on `visibilitychange`), fetch `/result`, send `DELETE` ack (plus `pagehide` `fetch(..., { method: "DELETE", keepalive: true })`), update `#progress-label` on phase change only + `aria-valuenow` on every tick, and always hide `#processing-overlay` in `finally`
- [ ] 4.1 Run `scripts/safe-test.sh` (default tier) and `scripts/safe-test.sh --node` and verify clean passes within budget
- [ ] 4.2 Strictly validate OpenSpec artifacts (`openspec validate toolpath-loading-bar --strict --json`)
- [ ] 4.3 Populate `verification.md` with Requirement Adherence Matrix and verbatim `safe-test.sh` summary lines

## 7. Post-Implementation & Verification Obligations
When `spec-coder-sub` finishes:
1. Verify all checkboxes in `tasks.md` are marked `- [x]`. Only tick boxes that genuinely ran and passed.
2. Ensure `openspec/changes/toolpath-loading-bar/verification.md` is populated with Requirement Adherence Audit Matrix, Resolved Assumptions, and verbatim `scripts/safe-test.sh` summary lines.
3. Automatically run verification via `openspec-verify-change`.
4. **Open a Pull Request**: Once implementation is complete and `verification.md` is written and verified with zero critical issues:
   - Ensure your work is on a dedicated feature branch (`feat/toolpath-loading-bar`).
   - Stage and commit all implementation code and every artifact within `openspec/changes/toolpath-loading-bar`, push (`git push -u origin HEAD`), open a Pull Request using `gh pr create --fill`, and report the PR URL.

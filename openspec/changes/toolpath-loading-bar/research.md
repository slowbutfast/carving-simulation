## Source material

- **Measured Phase Timings (`test-memory-scoping` D7 probe on sculpted `base_head` `demo`, `246 s` total)**:
  - `build_roughing`: `0.9 s` (`0.4%`) → `0.01 -> 0.02`
  - `build_finishing`: `184.5 s` (`75.0%`) → `0.02 -> 0.77`
  - `resample_path`: `31.5 s` (`12.8%`) → `0.77 -> 0.90`
  - `build_trajectory + soft_limit_runs`: `1.3 s` (`0.5%`) → `0.90 -> 0.91`
  - `detect_gouges_detailed`: `28.2 s` (`11.4%`) → `0.91 -> 0.97`
  - Post-gouge `feed_class` pass (`tool_model.tool_pose` across ~85k frames) → `0.97 -> 0.98`
  - `server.py` `sculpt` (`0.00 -> 0.01`) & `encode` (`0.98 -> 1.00`)
- **Existing Codebase (`toolpath_sim.py`, `server.py`)**:
  - `toolpath_sim.py`: `resample_path` (`L510`, ~85k segment loop), `detect_gouges_detailed` (`L1215`), `build_roughing` (`L1309`), `build_finishing` (`L1853`, `slices` loop at `L1923`), `generate_synthetic_carve_path` (`L2116`).
  - `server.py`: `sculpt_and_sim` (`L271-L355`), `_validation_error`, `_collision_report`, `_write_collision_log`, `uvicorn` single-worker deployment.
- **XP Luna UI Baseline (merged PR #3 `feat/xp-ui-overhaul`)**:
  - `static/xp.css` (`L810-L850`) already defines `.processing-overlay`, `.processing-overlay[hidden]`, `.processing-box`, and `.processing-spinner`; `static/index.html` has no `#processing-overlay` markup yet.

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| Local Phase Progress | `[0.0, 1.0]` fraction reported by each phase function (`0.0` start, `1.0` end) | Global progress hardcoded inside phase functions |
| Single Weight Table | Mapping table in `generate_synthetic_carve_path` (`0.01->0.02`, `0.02->0.77`, `0.77->0.90`, `0.90->0.91`, `0.91->0.97`, `0.97->0.98`) + `server.py` `sculpt`/`encode` | Arbitrary equal weights |
| Retry-Safe Result | `GET .../jobs/{id}/result` retained until `DELETE` ack or `120 s` TTL | Popping `result` on first `GET` |
| Abandon-on-Silence | Raising `JobCancelled` in `on_progress` if `> 90 s` elapse with no `GET /jobs/{id}` poll (`last_poll_at` initialized at submission) | `15 s` timeout that kills normal background-tab runs |

## Candidate tech

| Option | Decision | Reason |
| :--- | :--- | :--- |
| **Polling (`500 ms` `GET /jobs/{id}` + `GET /jobs/{id}/result`)** | Adopted | Reliable through `cloudflared` tunnels, keeps poll responses tiny, retry-safe for multi-MB payloads |
| **Shared `threading.Semaphore(1)` (`--workers 1`)** | Adopted | Prevents two concurrent ~3.3 GB generations on a 12 GiB box; `ProcessPoolExecutor` would double memory |
| **UI Cancel Button (v1)** | Deferred | Cooperative `JobCancelled` handles `DELETE` + `pagehide` (`keepalive: true`) + `90 s` abandon-on-silence |

## Verified facts

| Claim | Value | How verified | Date |
| :--- | :--- | :--- | :--- |
| `base_head` `demo` phase breakdown | Roughing 0.4%, Finishing 75%, Resample 12.8%, Trajectory 0.5%, Gouges 11.4% | `test-memory-scoping` D7 phase probe (`246 s`) | 2026-11-21 |
| PR #3 `.processing-overlay` CSS exists without HTML markup | `xp.css` L810-L850 | Read `static/xp.css` & `static/index.html` | 2026-11-21 |
| Sync `POST /api/sculpt-and-sim` line range | `L271-L355` in `server.py` | Read `server.py` | 2026-11-21 |

## Unverified assumptions

| Assumption | Confidence | How to verify |
| :--- | :--- | :--- |
| `90 s` abandon-on-silence + `visibilitychange` poll handles Chrome/Safari background tab throttling | High | Verify `500 ms` polling + tab switch + `pagehide` `keepalive` in manual check |

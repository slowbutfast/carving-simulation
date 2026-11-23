## Source material

- **Approved Plan (`toolpath_loading_bar_plan.md`)**:
  - Measured phase timings from `test-memory-scoping` D7 probe on sculpted `base_head` `demo` (`246 s` total): `build_roughing` `0.9 s` (`0.4%`), `build_finishing` `184.5 s` (`75.0%`), `resample_path` `31.5 s` (`12.8%`), `build_trajectory + soft_limit_runs` `1.3 s` (`0.5%`), `detect_gouges_detailed` `28.2 s` (`11.4%`).
- **Existing Codebase (`toolpath_sim.py`, `server.py`)**:
  - `toolpath_sim.py`: `resample_path` (`L510`), `detect_gouges_detailed` (`L1215`), `build_roughing` (`L1309`), `build_finishing` (`L1853`), `generate_synthetic_carve_path` (`L2116`).
  - `server.py`: `sculpt_and_sim` (`L271-L355`), `_validation_error`, `_collision_report`, `_write_collision_log`.
- **XP Luna UI Baseline (PR #3 `feat/xp-ui-overhaul`)**:
  - `xp.css` (`L810-L850`) already defines `.processing-overlay`, `.processing-overlay[hidden]`, `.processing-box`, and `.processing-spinner`; `index.html` lacks `#processing-overlay` markup.

## Glossary

| Term | Means | Does NOT mean |
| :--- | :--- | :--- |
| Local Phase Progress | `[0.0, 1.0]` fraction reported by each phase function (`0.0` start, `1.0` end) | Global progress hardcoded inside phase functions |
| Single Weight Table | Mapping table in `generate_synthetic_carve_path` (`0.01/0.75/0.13/0.01/0.08`) + `encode` (`0.98->1.00`) | Arbitrary equal weights |
| Retry-Safe Result | `GET .../jobs/{id}/result` retained until `DELETE` ack or `120 s` TTL | Popping `result` on first `GET` |
| Abandon-on-Silence | Raising `JobCancelled` in `on_progress` if `> 15 s` elapse with no `GET /jobs/{id}` poll | Leaving a 3.3 GB thread holding `_GEN_SEMAPHORE` |

## Candidate tech

| Option | Decision | Reason |
| :--- | :--- | :--- |
| **Polling (`500 ms` `GET /jobs/{id}` + `GET /jobs/{id}/result`)** | Adopted | Reliable through `cloudflared` tunnels, keeps poll responses tiny, retry-safe for multi-MB payloads |
| **Shared `threading.Semaphore(1)`** | Adopted | Prevents two concurrent ~3.3 GB generations on a 12 GiB box; `ProcessPoolExecutor` would double memory |
| **UI Cancel Button (v1)** | Deferred | Cooperative `JobCancelled` handles `DELETE` + `pagehide` + 15 s abandon-on-silence without UI clutter |

## Verified facts

| Claim | Value | How verified | Date |
| :--- | :--- | :--- | :--- |
| `base_head` `demo` phase breakdown | Roughing 0.4%, Finishing 75%, Resample 12.8%, Trajectory 0.5%, Gouges 11.4% | `test-memory-scoping` D7 phase probe (`246 s`) | 2026-11-21 |
| Sync `POST /api/sculpt-and-sim` line range | `L271-L355` in `server.py` | Read `server.py` | 2026-11-21 |

## Unverified assumptions

| Assumption | Confidence | How to verify |
| :--- | :--- | :--- |
| `15 s` abandon-on-silence timeout is long enough for browser background throttling | Medium–High | Verify `500 ms` polling + 3 retries in manual check |

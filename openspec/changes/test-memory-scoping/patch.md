# Patch Evidence: `test-memory-scoping`

## 2.1 Base_head phase probe (D7)

Run once, through the guarded runner, on the sculpted analytic base head
(`{"nose": 1.0, "chin": 0.6, "brow": 0.4}`, `target_mesh=None`, preset `demo`):

```bash
RUN_PHASE_PROBE=1 SAFE_TEST_AS_KB=6291456 SAFE_TEST_MIN_AVAIL_MB=2048 \
  SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh tests/_phase_probe.py
```

Reference container: cgroup v1, 12 GiB limit, 3 vCPU; 3,094 MiB available by the
runner's page-cache-excluded formula at start.

| Phase | Wall (s) | RSS before (MiB) | RSS after (MiB) | Peak RSS (MiB) |
|---|---:|---:|---:|---:|
| `build_roughing` | 0.89 | 85.3 | 91.6 | 175.6 |
| `build_finishing` | **184.49** | 91.6 | 272.8 | **3,313.1** |
| `resample_path` | 31.49 | 266.0 | 266.0 | 3,313.1 |
| `build_trajectory` | 1.21 | 266.0 | 266.0 | 3,313.1 |
| `soft_limit_runs` | 0.07 | 266.0 | 266.0 | 3,313.1 |
| `detect_gouges_detailed` | 28.15 | 266.0 | 294.4 | 3,313.1 |

Verbose summary line:

```text
safe-test: status=0 peak_rss_mb=3313 wall_s=247 tier=default
```

Raw JSON: `phase-probe.json` (written by the probe).

**D7 decision:** the multi-GB peak is a **transient allocation inside
`build_finishing`**: RSS is 91.6 MiB before the phase and 272.8 MiB after it, so
the path state itself is small (about 180 MiB), while the phase peaks at
3,313 MiB. Roughing, resampling, trajectory building and the gouge scan all stay
at or below 294 MiB. No single O(N·M) array with an obviously safe O(M)
replacement was found by inspection; the phi-candidate batches feed
`tool_model.body_penetrates`, and any change there risks changing the pinned
finishing output. Per the D7 rule, the spike is **recorded for the
`toolpath-memory` follow-up change** (`openspec/changes/toolpath-memory/`)
instead of being fixed here. The heavy tier still runs under the 8 GiB cap and
fails cleanly with `MemoryError` if it cannot finish, never by an uncapped
allocation.

## 2.3 Short-stock fixture

`tests/_fixtures.py` builds a 40 mm stock (`H_stock_mm = 40`, plinth at 10 mm,
1 mm top clearance) and sculpts the analytic head at its natural height, then
scales it uniformly (factor 0.3625 for the demo sliders) and seats it on the
plinth. Bounds: `x [-12.32, 11.46]`, `y [-9.42, 9.42]`,
`z [10.00, 39.00]`; watertight.

One `demo` generation on that fixture: **36,415 frames**, **26.4 s**,
**159 MiB** peak RSS in-process; the class run through the runner reports:

```text
Ran 2 tests in 25.598s
safe-test: status=0 peak_rss_mb=179 wall_s=26 tier=default
```

Both are inside the 2.3 target of under 200 MB and under 30 s. Invariants hold:
every one of the 36 azimuth bins has cutting frames, there are negative-`r_s`
frames, and roughing/finishing/rapid stages are all populated.

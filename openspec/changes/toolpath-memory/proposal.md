## Why

The D7 phase probe recorded for `test-memory-scoping` (2026-11-21) shows the
full-size sculpted base_head `demo` peaking at **3,313 MiB** inside
`toolpath_sim.build_finishing`, while the retained RSS after that phase is only
**273 MiB**. Roughing peaks at 176 MiB, resampling at 273 MiB, trajectory
building at 266 MiB and the gouge scan at 294 MiB. The spike is therefore a
transient allocation inside finishing, not accumulated state, and it is what
pushes the heavy tier towards the container limit.

`test-memory-scoping` deliberately did not change `build_finishing`: the phase
takes 184 s, the output is pinned by many invariant tests, and no single O(N·M)
array with an obviously safe O(M) replacement was identified during the capped
probe.

## What Changes

- Profile `build_finishing`'s phi search and `tool_model.body_penetrates`
  batches to locate the transient multi-GB allocation.
- Bound that allocation without changing the emitted joints: the same path,
  rapid flags, stages and diagnostics, with a peak-RSS assertion in a regression
  test.
- Keep the heavy tier's real-target run green under the 8 GiB address-space cap
  afterwards.

## Impact

- **Production:** `toolpath_sim.build_finishing`, possibly
  `tool_model.body_penetrates` / `_head_points` (sampling density or batching).
- **Tests:** one new memory-asserting test on the sculpted base_head fixture,
  kept in the heavy tier.
- **Evidence:** `openspec/changes/test-memory-scoping/phase-probe.json` and
  `patch.md`.

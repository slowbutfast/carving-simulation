## ADDED Requirements

### Requirement: Finishing peak memory is bounded

`toolpath_sim.build_finishing` SHALL NOT exceed a documented transient peak RSS
budget on the sculpted base_head `demo` while emitting byte-identical joints,
rapid flags, stages and diagnostics. The budget SHALL be set from the profiling
task, below the 3,313 MiB measured on 2026-11-21.

#### Scenario: The sculpted baseline stays inside the budget

- **WHEN** finishing runs on the sculpted base_head `demo` with
  `{"nose": 1.0, "chin": 0.6, "brow": 0.4}`
- **THEN** its peak RSS is at most the documented budget
- **AND** the emitted path, rapid flags, stages and diagnostics are identical to
  the pre-change output

#### Scenario: The heavy tier still completes

- **WHEN** the heavy tier runs with `RUN_HEAVY_TESTS=1` under the 8 GiB
  address-space cap
- **THEN** the full-size `demo` and `standard` generations either pass or fail
  with a clean `MemoryError`, never by a container-wide OOM kill

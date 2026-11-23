## 1. Profile

- [ ] 1.1 Re-run the capped phase probe from `test-memory-scoping` with
  line-level sampling inside `build_finishing` (the phi-candidate batches and
  `tool_model.body_penetrates`), recording the allocation that reaches the
  multi-GB peak.

## 2. Bound the transient

- [ ] 2.1 Reduce or batch the identified allocation without changing the emitted
  joints, rapid flags, stages or diagnostics.
- [ ] 2.2 Add a heavy-tier regression test that asserts the finishing peak RSS
  stays under the documented budget on the sculpted base_head `demo`.

## 3. Verify

- [ ] 3.1 Confirm the heavy tier passes (or fails with a clean `MemoryError`)
  under `RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608`.

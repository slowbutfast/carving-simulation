# Agent Test Policy

Every test run in this repository goes through `scripts/safe-test.sh`. The
runner serialises runs across all worktrees, refuses to start when the container
has less than 4.5 GiB available, caps Python's address space and reports peak
RSS. Do not run tests any other way.

## During implementation

Run only the files you touched, in the foreground:

```bash
scripts/safe-test.sh tests/test_carver_sim.py
scripts/safe-test.sh tests/test_tool_model.py tests/test_machine_cad.py
```

`tests/<file>.py` targets become dotted module names; dotted
`module.Class.test` names pass through.

## Before opening a pull request

Run the default tier once. It must pass with `peak_rss_mb <= 1536` and
`wall_s <= 600`:

```bash
scripts/safe-test.sh
```

Node tests (V8 cannot start under `ulimit -v`, so they run without the cap but
under the same lock):

```bash
scripts/safe-test.sh --node
```

## Verification only

The heavy tier does full-scale generation on the real targets. Run it once,
serialised, during verification:

```bash
RUN_HEAVY_TESTS=1 SAFE_TEST_AS_KB=8388608 SAFE_TEST_MIN_AVAIL_MB=9216 \
  SAFE_TEST_BUDGET_MB=8192 scripts/safe-test.sh
```

## Never

- `python -m unittest discover -s tests` or any raw `unittest` invocation.
- Backgrounded, `nohup`, `setsid` or `&` test runs.
- Raw `npm run test:node` (it skips the lock and the memory floor).
- Lowering `SAFE_TEST_MIN_AVAIL_MB` below the cap-coupled floor
  (`max(MIN_AVAIL_MB, AS_KB / 1024 + 512)`).

Exit status `4` means the peak-RSS budget was exceeded; `75` means the lock or
the memory floor said "come back later", not that a test failed.

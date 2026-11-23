"""Python half of ``scripts/safe-test.sh``.

Converts ``tests/<file>.py`` targets into dotted module names, runs ``unittest``
in this process (so ``ru_maxrss`` is the real peak), prints the one-line summary
and exits 4 when the peak-RSS budget is exceeded.
"""

from __future__ import annotations

import os
import resource
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def target_to_name(target: str) -> str:
    """``tests/test_tool_model.py`` -> ``test_tool_model``; dotted names pass."""

    if not target.endswith(".py"):
        return target
    path = Path(target).with_suffix("")
    parts = list(path.parts)
    if parts and parts[0] == "tests":
        parts = parts[1:]
    return ".".join(parts)


def main(argv: list[str]) -> int:
    started = time.perf_counter()
    names = [target_to_name(argument) for argument in argv]
    unittest_argv = ["unittest"]
    if names:
        unittest_argv.extend(names)
    else:
        unittest_argv.extend(["discover", "-s", "tests", "-t", "tests"])

    program = unittest.main(
        module=None, argv=unittest_argv, exit=False, verbosity=2
    )
    status = 0 if program.result.wasSuccessful() else 1

    self_usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak_mb = max(self_usage, child_usage) // 1024
    wall_s = int(round(time.perf_counter() - started))
    tier = "heavy" if os.environ.get("RUN_HEAVY_TESTS") == "1" else "default"
    print(
        f"safe-test: status={status} peak_rss_mb={peak_mb} "
        f"wall_s={wall_s} tier={tier}",
        flush=True,
    )

    budget_mb = int(os.environ.get("SAFE_TEST_BUDGET_MB", "1536"))
    if peak_mb > budget_mb:
        print(
            f"safe-test: BUDGET EXCEEDED peak_rss_mb={peak_mb} "
            f"budget_mb={budget_mb}",
            file=sys.stderr,
            flush=True,
        )
        return 4
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

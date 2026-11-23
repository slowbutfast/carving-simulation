#!/usr/bin/env bash
# Serialised, memory-guarded test runner.
#
#   scripts/safe-test.sh [tests/<file>.py | module.Class.test ...]
#   scripts/safe-test.sh --node
#
# One exclusive flock is shared by every worktree in the container. After the
# lock the runner checks available memory (cgroup v1 -> v2 -> MemAvailable,
# page cache excluded), caps Python's address space, and reports peak RSS.
# Exit codes: the tests' status; 4 budget exceeded; 75 no lock / low memory.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

LOCK="${SAFE_TEST_LOCK:-/tmp/carving-sim-test.lock}"
WAIT_S="${SAFE_TEST_LOCK_WAIT_S:-3600}"
MIN_AVAIL_MB="${SAFE_TEST_MIN_AVAIL_MB:-4608}"
AS_KB="${SAFE_TEST_AS_KB:-4194304}"
BUDGET_MB="${SAFE_TEST_BUDGET_MB:-1536}"
CGROUP_ROOT="${SAFE_TEST_CGROUP_ROOT:-/sys/fs/cgroup}"
MEMINFO="${SAFE_TEST_MEMINFO:-/proc/meminfo}"
export SAFE_TEST_BUDGET_MB="$BUDGET_MB"

TIER=default
if [ "${RUN_HEAVY_TESTS:-0}" = "1" ]; then
    TIER=heavy
fi

node_mode=0
targets=()
for argument in "$@"; do
    case "$argument" in
        --node) node_mode=1 ;;
        *) targets+=("$argument") ;;
    esac
done

if [ ! -x .venv/bin/python ]; then
    echo "safe-test: .venv/bin/python is missing or not executable; create the virtualenv first" >&2
    exit 1
fi

if ! [[ "$AS_KB" =~ ^[0-9]+$ && "$MIN_AVAIL_MB" =~ ^[0-9]+$ ]]; then
    echo "safe-test: SAFE_TEST_AS_KB and SAFE_TEST_MIN_AVAIL_MB must be integers" >&2
    exit 1
fi

# A run may not start with less headroom than its own address-space cap (plus
# a small margin for the interpreter and fixtures), however low
# SAFE_TEST_MIN_AVAIL_MB is set.
CAP_FLOOR_MB=$(( AS_KB / 1024 + 512 ))
EFFECTIVE_FLOOR_MB=$MIN_AVAIL_MB
if [ "$CAP_FLOOR_MB" -gt "$EFFECTIVE_FLOOR_MB" ]; then
    EFFECTIVE_FLOOR_MB=$CAP_FLOOR_MB
fi

if ! exec 9>"$LOCK"; then
    echo "safe-test: cannot open lock $LOCK" >&2
    exit 75
fi

if ! flock -n 9; then
    echo "safe-test: waiting for $LOCK" >&2
    if ! flock -w "$WAIT_S" 9; then
        echo "safe-test: no lock on $LOCK after ${WAIT_S}s" >&2
        exit 75
    fi
fi

AVAIL_MB="$(
    SAFE_TEST_CGROUP_ROOT="$CGROUP_ROOT" SAFE_TEST_MEMINFO="$MEMINFO" \
        .venv/bin/python - <<'PY'
import os
import re
from pathlib import Path

root = Path(os.environ.get("SAFE_TEST_CGROUP_ROOT", "/sys/fs/cgroup"))


def read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def stat_value(path: Path, key: str) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    match = re.search(rf"^{key}\s+(\d+)$", text, re.MULTILINE)
    return int(match.group(1)) if match else 0


available = None
if (root / "memory" / "memory.limit_in_bytes").exists():
    limit = read_int(root / "memory" / "memory.limit_in_bytes")
    usage = read_int(root / "memory" / "memory.usage_in_bytes")
    inactive = stat_value(root / "memory" / "memory.stat", "total_inactive_file")
    if limit is not None and usage is not None:
        available = limit - max(0, usage - inactive)
elif (root / "memory.max").exists():
    raw_limit = (root / "memory.max").read_text(encoding="utf-8").strip()
    if raw_limit != "max":
        limit = int(raw_limit)
        usage = read_int(root / "memory.current") or 0
        inactive = stat_value(root / "memory.stat", "inactive_file")
        available = limit - max(0, usage - inactive)

meminfo = Path(os.environ.get("SAFE_TEST_MEMINFO", "/proc/meminfo"))
try:
    match = re.search(
        r"^MemAvailable:\s+(\d+) kB", meminfo.read_text(encoding="utf-8"), re.MULTILINE
    )
except OSError:
    match = None
mem_available = int(match.group(1)) * 1024 if match else None

if available is None:
    available = mem_available
elif mem_available is not None:
    available = min(available, mem_available)
if available is None:
    available = 0
print(max(0, available // (1024 * 1024)))
PY
)"

if ! [[ "$AVAIL_MB" =~ ^[0-9]+$ ]]; then
    echo "safe-test: cannot compute available memory" >&2
    exit 75
fi

echo "safe-test: available_mb=${AVAIL_MB} threshold_mb=${EFFECTIVE_FLOOR_MB}"
if [ "$AVAIL_MB" -lt "$EFFECTIVE_FLOOR_MB" ]; then
    echo "safe-test: only ${AVAIL_MB} MiB available (< ${EFFECTIVE_FLOOR_MB} MiB); refusing to run" >&2
    exit 75
fi

if [ "$node_mode" -eq 1 ]; then
    # V8 reserves many GB of virtual address space. The cap is only for Python,
    # so lift it even when this run was started from a capped parent.
    ulimit -v unlimited 2>/dev/null || true
    export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--max-old-space-size=2048"
    summary_file="$(mktemp)"
    trap 'rm -f "$summary_file"' EXIT
    .venv/bin/python - "$summary_file" <<'PY'
import resource
import subprocess
import sys
import time

started = time.perf_counter()
status = subprocess.call(["npm", "run", "test:node"])
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    stream.write(
        f"{status} {usage.ru_maxrss // 1024} {int(round(time.perf_counter() - started))}\n"
    )
PY
    read -r node_status node_peak node_wall <"$summary_file"
    echo "safe-test: status=${node_status:-1} peak_rss_mb=${node_peak:-0} wall_s=${node_wall:-0} tier=${TIER}"
    exit "${node_status:-1}"
fi

(
    # Soft limit only, so a nested `--node` run can lift it back to unlimited
    # for V8 without needing a privileged process.
    ulimit -S -v "$AS_KB" 2>/dev/null || {
        echo "safe-test: cannot set ulimit -v $AS_KB" >&2
        exit 75
    }
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2 \
        .venv/bin/python tests/_run.py "${targets[@]}"
)
status=$?
exit "$status"

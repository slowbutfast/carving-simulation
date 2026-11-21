"""One-shot phase probe for the sculpted base_head `demo` spike (D7 / task 2.1).

Tooling, not a test: it is excluded from discovery and skipped unless
``RUN_PHASE_PROBE=1``. It runs the same phase sequence as
``generate_synthetic_carve_path`` and writes per-phase wall time and peak RSS to
``PHASE_PROBE_OUT`` (JSON) plus stdout.

Contain it with an explicit cap (the runner only accepts ``tests/`` targets):

    ( ulimit -S -v 6291456; RUN_PHASE_PROBE=1 \
        .venv/bin/python scripts/probe_phase.py )

``scripts/safe-test.sh`` was used for the recorded 2.1 evidence while the probe
lived under ``tests/``; the numbers are in ``patch.md``.
"""

from __future__ import annotations

import gc
import json
import os
import resource
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kinematics  # noqa: E402
import face_sculpt  # noqa: E402
import toolpath_sim  # noqa: E402

OUT = Path(
    os.environ.get(
        "PHASE_PROBE_OUT",
        ROOT / "openspec" / "changes" / "test-memory-scoping" / "phase-probe.json",
    )
)
SLIDERS = {"nose": 1.0, "chin": 0.6, "brow": 0.4}
PRESET = "demo"


def rss_mb() -> float:
    with open("/proc/self/statm", encoding="ascii") as stream:
        pages = int(stream.read().split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)


def peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


@unittest.skipUnless(
    os.environ.get("RUN_PHASE_PROBE") == "1", "set RUN_PHASE_PROBE=1"
)
class PhaseProbe(unittest.TestCase):
    def test_phase_probe(self):
        config = kinematics.load_config()
        config["target_mesh"] = None
        config = kinematics.load_config(config)
        params = dict(config["toolpath"])
        params.update(config["presets"][PRESET])
        params["rapid_clearance_mm"] = float(
            config["stock"].get(
                "retract_clearance_mm", params.get("rapid_clearance_mm", 6.0)
            )
        )

        gc.collect()
        mesh = face_sculpt.load_base_head(config)
        sculpt = face_sculpt.apply_facial_modifications(mesh, SLIDERS, config).mesh
        assert sculpt is not None

        phases: list[dict[str, float | str]] = []
        collector = kinematics.DiagnosticCollector()
        unreachable_samples: list[dict] = []

        def measure(name, function):
            gc.collect()
            before = rss_mb()
            started = time.perf_counter()
            value = function()
            elapsed = time.perf_counter() - started
            phases.append(
                {
                    "phase": name,
                    "wall_s": round(elapsed, 2),
                    "rss_before_mb": round(before, 1),
                    "rss_after_mb": round(rss_mb(), 1),
                    "peak_mb": round(peak_mb(), 1),
                }
            )
            return value

        rough = measure(
            "build_roughing",
            lambda: toolpath_sim.build_roughing(sculpt, config, params, collector),
        )
        rough_joints, rough_rapid, rough_stage, rough_last = rough

        finishing = measure(
            "build_finishing",
            lambda: toolpath_sim.build_finishing(
                sculpt,
                config,
                params,
                collector,
                rough_last,
                unreachable_samples,
            ),
        )
        finish_joints, finish_rapid, finish_stage, _points, unreachable = finishing

        joints = rough_joints + finish_joints
        rapid = rough_rapid + finish_rapid
        stages = rough_stage + finish_stage
        del rough, finishing

        resampled = measure(
            "resample_path",
            lambda: toolpath_sim.resample_path(joints, rapid, stages, config),
        )
        joints, rapid, stages = resampled
        del resampled

        built = measure(
            "build_trajectory",
            lambda: kinematics.build_trajectory(joints, rapid, config),
        )
        frames, _diagnostics = built
        for frame, stage in zip(frames, stages):
            frame["stage"] = stage
        del built, joints, rapid

        measure("soft_limit_runs", lambda: toolpath_sim.soft_limit_runs(frames, config))

        gouges = measure(
            "detect_gouges_detailed",
            lambda: toolpath_sim.detect_gouges_detailed(
                sculpt, frames, stages, config
            ),
        )

        payload = {
            "mesh": "presets/base_head.stl (sculpted)",
            "sliders": SLIDERS,
            "preset": PRESET,
            "frames": len(frames),
            "unreachable_percent": unreachable,
            "gouge_events": len(gouges.events),
            "phases": phases,
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        print(f"\nphase probe -> {OUT}")
        print(f"{'phase':<24}{'wall_s':>8}{'rss_before_mb':>15}{'rss_after_mb':>14}{'peak_mb':>10}")
        for phase in phases:
            print(
                f"{phase['phase']:<24}{phase['wall_s']:>8}"
                f"{phase['rss_before_mb']:>15}{phase['rss_after_mb']:>14}"
                f"{phase['peak_mb']:>10}"
            )


if __name__ == "__main__":
    unittest.main()

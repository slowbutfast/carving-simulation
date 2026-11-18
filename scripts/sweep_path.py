"""Dump a generated trajectory for `tests/sweep_path.mjs` (PATCH-10c sweep).

Usage:
    .venv/bin/python scripts/sweep_path.py --preset demo --out /tmp/demo.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import face_sculpt  # noqa: E402
import kinematics  # noqa: E402
import toolpath_sim  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="demo", choices=["demo", "standard"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--grid", type=int, default=128)
    parser.add_argument("--sliders", default='{"nose": 1.0, "chin": 0.6, "brow": 0.4}')
    args = parser.parse_args()

    config = kinematics.load_config()
    base = face_sculpt.load_base_head(config)
    sliders = json.loads(args.sliders)
    sculpt = face_sculpt.apply_facial_modifications(base, sliders, config)
    if sculpt.mesh is None or any(d.severity == "error" for d in sculpt.diagnostics):
        for diag in sculpt.diagnostics:
            print(diag.as_dict(), file=sys.stderr)
        return 2

    result = toolpath_sim.generate_synthetic_carve_path(sculpt.mesh, config, preset=args.preset)
    poses: list[float] = []
    rapid: list[int] = []
    for frame in result.frames:
        tip = frame["tip_xyz_wax"]
        axis = frame["tool_axis_wax"]
        poses.extend([float(tip[0]), float(tip[1]), float(tip[2])])
        poses.extend([float(axis[0]), float(axis[1]), float(axis[2])])
        rapid.append(1 if frame["is_rapid"] else 0)

    tool = config["tool"]
    payload = {
        "preset": args.preset,
        "gridN": args.grid,
        "count": len(result.frames),
        "poses": poses,
        "rapid": rapid,
        "tool": {
            "tip_radius_mm": tool["tip_radius_mm"],
            "cone_half_angle_deg": tool["cone_half_angle_deg"],
            "engaged_length_mm": tool["engaged_length_mm"],
            "melt_kerf_mm": tool["melt_kerf_mm"],
            "shank_radius_mm": tool["shank_radius_mm"],
            "shank_length_mm": tool["shank_length_mm"],
        },
        "stock": {
            "R_stock_mm": config["stock"]["R_stock_mm"],
            "H_stock_mm": config["stock"]["H_stock_mm"],
        },
    }
    Path(args.out).write_text(json.dumps(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "preset": args.preset,
                "frames": len(result.frames),
                "roughing": result.roughing_frames,
                "finishing": result.finishing_frames,
                "rapid": result.rapid_frames,
                "unreachable_percent": round(result.unreachable_percent, 3),
                "diagnostics": [d.code for d in result.diagnostics],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

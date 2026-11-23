"""Small default-tier fixtures.

The default tier must not generate a toolpath on a full-size target. These
helpers build a 40 mm-tall stock and a sculpted analytic head scaled and seated
to fit it, so the toolpath invariants run on the same shape at a fraction of the
cost.

They are plain functions, not a module-level cache: a process-wide fixture would
bring back the "never freed" problem this change removes.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import trimesh

import face_sculpt
import kinematics

SHORT_STOCK_H_MM = 40.0
#: Keep the scaled crown below the stock top so no cutter pose clips it.
SHORT_STOCK_TOP_CLEARANCE_MM = 1.0
#: The analytic base head's natural seating height (used while sculpting only).
_NATURAL_STOCK_H_MM = 120.0


def short_stock_config(**overrides: Any) -> dict[str, Any]:
    """The analytic head in a 40 mm stock, with optional dotted overrides."""

    config = kinematics.load_config()
    config["target_mesh"] = None
    config["stock"]["H_stock_mm"] = SHORT_STOCK_H_MM
    for dotted, value in overrides.items():
        node = config
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return kinematics.load_config(config)


def short_stock_target(
    config: Mapping[str, Any],
    sliders: Mapping[str, float] | None = None,
) -> trimesh.Trimesh:
    """Sculpt the analytic head, then scale and seat it inside ``config``'s stock."""

    # Sculpt at the natural height so the landmark centres and the stock bounds
    # check both refer to the un-scaled head.
    sculpt_config = kinematics.load_config(dict(config))
    sculpt_config["stock"]["H_stock_mm"] = _NATURAL_STOCK_H_MM

    base = face_sculpt.build_base_head(sculpt_config)
    if sliders:
        sculpted = face_sculpt.apply_facial_modifications(
            base, dict(sliders), sculpt_config
        ).mesh
    else:
        sculpted = base
    assert sculpted is not None

    vertices = np.asarray(sculpted.vertices, dtype=np.float64).copy()
    stock = config["stock"]
    z_plinth = float(stock["z_plinth_mm"])
    radial_limit = float(stock["R_stock_mm"]) - float(stock["finish_allowance_mm"])
    height_limit = (
        float(stock["H_stock_mm"]) - z_plinth - SHORT_STOCK_TOP_CLEARANCE_MM
    )

    bottom = float(vertices[:, 2].min())
    height = float(vertices[:, 2].max()) - bottom
    radius = float(np.linalg.norm(vertices[:, :2], axis=1).max())
    scale = min(height_limit / height, radial_limit / radius)

    vertices[:, :2] *= scale
    vertices[:, 2] = (vertices[:, 2] - bottom) * scale + z_plinth
    return trimesh.Trimesh(
        vertices=vertices, faces=np.asarray(sculpted.faces).copy(), process=False
    )

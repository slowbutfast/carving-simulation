"""The single runtime definition of the T12-K blade tool.

Constants come from ``machine_geometry.json`` (CAD-derived) merged under
``machine_config.json``; ``toolpath_sim.py`` and the web worker must not carry
their own tool geometry. The wax SDF mirror in ``static/wax_sdf_core.js`` reads
the same numbers and is pinned by ``tests/fixtures/heated_sdf_parity.json``.

Sign conventions, stated once here because mixing them cost two PATCH-10
rounds:

* this module's :func:`heated_sdf` is **negative inside** the heated region;
* ``trimesh.proximity`` signed distance and ``trimesh.contains`` are
  **positive inside** a watertight mesh.

Geometry at the CAD reference pose (theta = 0, phi = 0):
``u = -Z`` points from the pivot toward the tool reference point,
``a_w = +Y`` is the blade width, and ``a_n = -X`` is the blade thickness.
The ordered frame ``(a_n, a_w, u)`` is right-handed with ``a_n x a_w = u``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class ToolPose:
    """A tool reference point and its right-handed frame in the wax frame."""

    tip_xyz: np.ndarray
    a_n: np.ndarray
    a_w: np.ndarray
    u: np.ndarray


def load_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the merged machine configuration (lazy import avoids cycles)."""

    if config is not None:
        return dict(config)
    import kinematics

    return kinematics.load_config()


def tool_pose(
    tip_xyz: Sequence[float],
    theta: float,
    phi: float,
    config: Mapping[str, Any] | None = None,
) -> ToolPose:
    """Build the tool frame at an orbit angle and wrist pitch."""

    del config  # the frame is purely geometric; kept for a uniform signature
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    e_r = np.array([cos_t, sin_t, 0.0])
    e_theta = np.array([-sin_t, cos_t, 0.0])
    u = -sin_p * e_r - cos_p * np.array([0.0, 0.0, 1.0])
    a_w = e_theta
    a_n = np.cross(a_w, u)
    return ToolPose(
        tip_xyz=np.asarray(tip_xyz, dtype=np.float64),
        a_n=a_n / np.linalg.norm(a_n),
        a_w=a_w,
        u=u / np.linalg.norm(u),
    )


def _tool(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return load_config(config)["tool"]


def _heated_params(config: Mapping[str, Any] | None) -> tuple[float, float, float, float]:
    tool = _tool(config)
    kerf = float(tool["melt_kerf_mm"])
    length = float(tool.get("heated_length_mm", tool["blade_length_mm"]))
    return float(tool["blade_thickness_mm"]), float(tool["blade_width_mm"]), length, kerf


def heated_sdf(
    points: np.ndarray | Sequence[Sequence[float]],
    pose: ToolPose,
    config: Mapping[str, Any] | None = None,
) -> np.ndarray:
    """Exact signed distance to the kerf-inflated blade prism.

    The heated region is the blade box (``blade_thickness`` x ``blade_width`` x
    ``heated_length``) inflated by ``melt_kerf_mm``: a rounded box. Local ``s``
    runs along ``-u`` from the reference point, so the box spans ``s`` in
    ``[0, heated_length]``. Distances are negative inside.
    """

    thickness, width, length, kerf = _heated_params(config)
    pts = np.atleast_2d(np.asarray(points, dtype=np.float64))
    delta = pts - pose.tip_xyz
    local = np.stack(
        [
            delta @ pose.a_n,
            delta @ pose.a_w,
            delta @ (-pose.u) - 0.5 * length,
        ],
        axis=1,
    )
    half = np.array([0.5 * thickness, 0.5 * width, 0.5 * length])
    q = np.abs(local) - half
    outside = np.linalg.norm(np.maximum(q, 0.0), axis=1)
    inside = np.minimum(np.max(q, axis=1), 0.0)
    return outside + inside - kerf


def _support_point(pose: ToolPose, direction: np.ndarray, config: Mapping[str, Any] | None) -> np.ndarray:
    """Support point of the un-inflated prism relative to the reference point."""

    thickness, width, length, _ = _heated_params(config)
    centre_offset = 0.5 * length * (-pose.u)
    axes = (pose.a_n, pose.a_w, -pose.u)
    half = (0.5 * thickness, 0.5 * width, 0.5 * length)
    point = centre_offset.copy()
    for axis, extent in zip(axes, half):
        component = float(direction @ axis)
        # A tie is a face or edge: use its centroid (sign 0) so placement is
        # deterministic instead of picking an arbitrary corner.
        sign = 0.0 if abs(component) < 1e-12 else math.copysign(1.0, component)
        point = point + extent * sign * axis
    return point


def place_on_contact(
    cc: Sequence[float],
    n: Sequence[float],
    pose_axes: ToolPose,
    config: Mapping[str, Any] | None = None,
) -> np.ndarray:
    """Reference point that puts the heated region tangent at ``cc``.

    ``cl = cc + kerf*n - s0(-n)`` where ``s0`` is the support point of the
    un-inflated prism. This is exact for any convex tool and any normal, and it
    is not a scalar offset along ``n``.
    """

    _, _, _, kerf = _heated_params(config)
    normal = np.asarray(n, dtype=np.float64)
    magnitude = float(np.linalg.norm(normal))
    if magnitude == 0.0:
        raise ValueError("contact normal must be nonzero")
    normal = normal / magnitude
    support = _support_point(pose_axes, -normal, config)
    return np.asarray(cc, dtype=np.float64) + kerf * normal - support


def _ring_points(
    pose: ToolPose,
    stations: np.ndarray,
    radius: float,
    angles: np.ndarray,
) -> np.ndarray:
    base = pose.tip_xyz[None, :] - stations[:, None] * pose.u[None, :]
    offsets = (
        np.cos(angles)[None, :, None] * pose.a_n[None, None, :]
        + np.sin(angles)[None, :, None] * pose.a_w[None, None, :]
    )
    return (base[:, None, :] + radius * offsets).reshape(-1, 3)


def _head_points(pose: ToolPose, envelope: Mapping[str, Any], pitch: float) -> np.ndarray:
    """Sample the explicit head box surface at axial pitch and 8 perimeter lines."""

    centre = np.asarray(envelope["center_mm"], dtype=np.float64)
    half = np.asarray(envelope["half_extents_mm"], dtype=np.float64)
    s_lo = max(centre[2] - half[2], 0.0)
    s_hi = centre[2] + half[2]
    count = max(2, int(math.ceil((s_hi - s_lo) / pitch)) + 1)
    stations = np.linspace(s_lo, s_hi, count)
    # 9 points across the rectangular cross-section: corners, edge mids and
    # centre. Including the centre catches a body engulfed by wax, not just one
    # crossing a face.
    perimeter = np.array(
        [(n, w) for n in (-1.0, 0.0, 1.0) for w in (-1.0, 0.0, 1.0)]
    )
    local_n = centre[0] + half[0] * perimeter[:, 0]
    local_w = centre[1] + half[1] * perimeter[:, 1]
    points = (
        pose.tip_xyz[None, None, :]
        + local_n[None, :, None] * pose.a_n[None, None, :]
        + local_w[None, :, None] * pose.a_w[None, None, :]
        - stations[:, None, None] * pose.u[None, None, :]
    )
    return points.reshape(-1, 3)


def _pose_body_points(
    pose: ToolPose,
    tool: Mapping[str, Any],
    pitch: float = 0.5,
) -> np.ndarray:
    angles = np.arange(12) * (math.pi / 6.0)
    blocks = []
    for span_key, radius_key in (("shaft_span_mm", "shaft_radius_mm"), ("body_span_mm", "body_radius_mm")):
        span = tool.get(span_key)
        radius = tool.get(radius_key)
        if not span or radius is None:
            continue
        lo, hi = float(span[0]), float(span[1])
        count = max(2, int(math.ceil((hi - lo) / pitch)) + 1)
        stations = np.linspace(lo, hi, count)
        blocks.append(_ring_points(pose, stations, float(radius), angles))
    if blocks:
        return np.concatenate(blocks, axis=0)
    return np.zeros((0, 3))


def body_penetrates(
    mesh: Any,
    poses: Sequence[ToolPose],
    config: Mapping[str, Any] | None = None,
) -> np.ndarray:
    """Per pose: does any unheated tool body enter the mesh?

    Bodies: the shaft cylinder, the cartridge body cylinder, and the explicit
    tilt-head box recorded in ``machine_geometry.json``. Axial stations are
    measured from the reference point along ``-u``, sampled at <= 0.5 mm and 12
    points (30 degrees) around each ring. ``mesh.contains`` is the authority and
    it is positive inside, matching trimesh's signed-distance convention.
    """

    if len(poses) == 0:
        return np.zeros(0, dtype=bool)
    cfg = load_config(config)
    tool = cfg["tool"]
    envelope = tool.get("head_envelope")
    mesh_bounds = np.asarray(mesh.bounds, dtype=np.float64)

    points: list[np.ndarray] = []
    owners: list[int] = []
    for index, pose in enumerate(poses):
        body = _pose_body_points(pose, tool)
        points.append(body)
        owners.append(index)
        if envelope is not None:
            corners = _head_points(pose, envelope, pitch=10.0)
            low = corners.min(axis=0)
            high = corners.max(axis=0)
            if np.all(low <= mesh_bounds[1]) and np.all(high >= mesh_bounds[0]):
                points.append(_head_points(pose, envelope, pitch=0.5))
                owners.append(index)

    if not points:
        return np.zeros(len(poses), dtype=bool)
    all_points = np.concatenate(points, axis=0)
    # Points outside the mesh AABB cannot be inside it. Culling them before the
    # ray cast is exact and removes most of the long shaft/cartridge samples
    # above the stock, which dominate the cost.
    low = mesh_bounds[0] - 1e-6
    high = mesh_bounds[1] + 1e-6
    relevant = np.all(all_points >= low, axis=1) & np.all(all_points <= high, axis=1)
    inside = np.zeros(len(all_points), dtype=bool)
    if relevant.any():
        inside[relevant] = np.asarray(
            mesh.contains(all_points[relevant]), dtype=bool
        )
    result = np.zeros(len(poses), dtype=bool)
    cursor = 0
    for block, owner in zip(points, owners):
        size = len(block)
        if inside[cursor : cursor + size].any():
            result[owner] = True
        cursor += size
    return result


def feed_class(
    direction: Sequence[float],
    pose_axes: ToolPose,
    config: Mapping[str, Any] | None = None,
) -> str:
    """Classify a cutting direction as ``broadside``, ``slice`` or ``plunge``.

    Broadside means the move pushes the 6 mm blade face through wax:
    ``|d . a_n| > cos(broadside_threshold_deg)``. Otherwise the largest
    component along ``a_w`` is a slice and along ``u`` a plunge.
    """

    cfg = load_config(config)
    threshold = math.cos(
        math.radians(float(cfg.get("toolpath", {}).get("broadside_threshold_deg", 45.0)))
    )
    d = np.asarray(direction, dtype=np.float64)
    magnitude = float(np.linalg.norm(d))
    if magnitude == 0.0:
        raise ValueError("feed direction must be nonzero")
    d = d / magnitude
    axial = abs(float(d @ pose_axes.a_n))
    if axial > threshold:
        return "broadside"
    if abs(float(d @ pose_axes.a_w)) >= abs(float(d @ pose_axes.u)):
        return "slice"
    return "plunge"


def heated_corners(
    pose: ToolPose, config: Mapping[str, Any] | None = None
) -> np.ndarray:
    """The eight corners of the un-inflated heated blade in the wax frame."""

    thickness, width, length, _ = _heated_params(config)
    points = []
    for n in (-0.5 * thickness, 0.5 * thickness):
        for w in (-0.5 * width, 0.5 * width):
            for s in (0.0, length):
                points.append(
                    pose.tip_xyz + n * pose.a_n + w * pose.a_w - s * pose.u
                )
    return np.asarray(points)


def radial_support_extent(phi: float, config: Mapping[str, Any] | None = None) -> float:
    """Maximum radial reach of the heated region at a wrist pitch.

    Used for rapid clearance: retract until the tool axis is outside
    ``R_stock + clearance + extent`` so no part of the heated region can graze
    the stock while traversing.
    """

    thickness, _, length, kerf = _heated_params(config)
    return (
        abs(length * math.sin(phi))
        + 0.5 * thickness * abs(math.cos(phi))
        + kerf
    )

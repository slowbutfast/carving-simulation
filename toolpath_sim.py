"""Synthetic 4-DOF roughing and undercut-capable finishing trajectory generator.

Stage 1 - shadow-aware cylindrical roughing (phi = 0):
    Z-level terracing from H_stock down to z_plinth.  At every level each
    azimuth's material is removed from the stock radius inward to the top-down
    shadow ``max_{z' >= z} r_target(theta, z') + finish_allowance`` so the
    vertical shank can never collide with an overhang above the cut.

Stage 2 - r-Z slice undercut finishing:
    The target mesh is cut with true planar sections
    (``plane_normal = e_theta``), so every contour point lies exactly on the
    slice azimuth with its own radius (multi-valued overhangs included).  The
    Contact-Point is offset to the Tip Apex by (tip_radius + melt_kerf), the
    wrist pitch lays the conical flank on the surface, unreachable overhangs
    are reported, and gouges are detected against the target mesh.

Every segment is resampled so the maximum displacement of any point on the
engaged heated cone is <= 0.5 * tip_width.  Approaches and retracts are split
into three safe moves (body retract at constant phi, reorient phi, then rapid)
and all rapids retract outside the stock before traversing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import trimesh
from trimesh import intersections as trimesh_intersections

import kinematics
from kinematics import Diagnostic, DiagnosticCollector

TAU = 2.0 * math.pi
EPS = 1e-9


class FrameCapExceededError(RuntimeError):
    """Raised when a generated path would exceed ``api.max_frames``."""

    def __init__(self, frames: int, max_frames: int) -> None:
        super().__init__(
            f"trajectory needs {frames} frames which exceeds max_frames={max_frames}; "
            "choose a coarser preset or raise api.max_frames"
        )
        self.frames = int(frames)
        self.max_frames = int(max_frames)

    def diagnostic(self) -> Diagnostic:
        return Diagnostic(
            code="FRAME_CAP_EXCEEDED",
            severity="error",
            message=str(self),
            value=float(self.frames),
        )


@dataclass
class ToolpathResult:
    frames: list[dict[str, Any]]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    preset: str = "demo"
    roughing_frames: int = 0
    finishing_frames: int = 0
    unreachable_percent: float = 0.0
    rapid_frames: int = 0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _wrap_angle(angle: float) -> float:
    wrapped = math.fmod(angle + math.pi, TAU)
    if wrapped < 0.0:
        wrapped += TAU
    return wrapped - math.pi


def _theta_grid(step_deg: float) -> list[float]:
    count = max(4, int(round(360.0 / step_deg)))
    return [TAU * index / count for index in range(count)]


def _joint(
    rs: float,
    theta: float,
    zs: float,
    phi: float,
    config: Mapping[str, Any],
    collector: DiagnosticCollector | None = None,
) -> dict[str, float]:
    """Joint tuple for a desired wax-frame tip apex pose.

    Every generated joint is validated against the soft travel limits so an
    out-of-bounds stock/config surfaces ``SOFT_LIMIT_EXCEEDED`` instead of
    silently producing impossible machine coordinates.
    """

    x = float(config["arm_radial_offset_mm"])
    h2 = float(config["arm_to_pivot_z_mm"])
    p = float(config["pivot_to_tip_mm"])
    joint = {
        "r": rs + x + p * math.sin(phi),
        "theta": theta,
        "h": zs + p * math.cos(phi) + h2,
        "phi": phi,
    }
    if collector is not None:
        collector.extend(validate_joint(collector, joint, config))
    return joint


def validate_joint(
    collector: DiagnosticCollector,
    joint: Mapping[str, float],
    config: Mapping[str, Any],
) -> list[Diagnostic]:
    """Return ``SOFT_LIMIT_EXCEEDED`` diagnostics for an out-of-bounds joint."""

    raw = kinematics.validate_joints(
        float(joint["r"]), float(joint["theta"]), float(joint["h"]), float(joint["phi"]), config
    )
    out: list[Diagnostic] = []
    for diag in raw:
        out.append(
            Diagnostic(
                code=diag.code,
                severity=diag.severity,
                message=diag.message,
                axis=diag.axis,
                value=diag.value,
            )
        )
    return out


def _fk_frame(frame: Mapping[str, Any], config: Mapping[str, Any]) -> kinematics.ForwardKinematics:
    return kinematics.forward_kinematics(
        float(frame["r"]),
        float(frame["theta"]),
        float(frame["h"]),
        float(frame["phi"]),
        config,
    )


def max_engaged_displacement(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    engaged_length_mm: float,
    config: Mapping[str, Any],
) -> float:
    """Exact maximum displacement over the engaged cone (convex in s).

    Body points are ``P(s) = tip - s * axis`` for ``s in [0, L_tip]``.  The
    difference ``d(s) = d_tip - s * d_axis`` is affine, so its norm is convex
    and attains its maximum at an endpoint.
    """

    a = _fk_frame(first, config)
    b = _fk_frame(second, config)
    dtip = np.asarray(b.tip_xyz_wax) - np.asarray(a.tip_xyz_wax)
    daxis = np.asarray(b.tool_axis_wax) - np.asarray(a.tool_axis_wax)
    at_tip = float(np.linalg.norm(dtip))
    at_base = float(np.linalg.norm(dtip - engaged_length_mm * daxis))
    return max(at_tip, at_base)


def sweep_length(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    engaged_length_mm: float,
    config: Mapping[str, Any],
) -> float:
    """Conservative swept path length for a segment (bounds every cone point).

    Unlike the endpoint chord, this includes the angular arc ``r_s * dtheta``
    and the tool-axis rotation contribution ``L_tip * |d_axis|``, so a
    combined radial+angular move cannot hide behind a short chord.
    """

    a = _fk_frame(first, config)
    b = _fk_frame(second, config)
    dtheta = float(second["theta"]) - float(first["theta"])
    r_scale = max(abs(a.r_s), abs(b.r_s))
    path = math.sqrt(
        (b.r_s - a.r_s) ** 2
        + (r_scale * dtheta) ** 2
        + (b.z_s - a.z_s) ** 2
    )
    axis_delta = np.linalg.norm(
        np.asarray(b.tool_axis_wax) - np.asarray(a.tool_axis_wax)
    )
    return float(path + engaged_length_mm * axis_delta)


def _interpolate_joint(
    first: Mapping[str, float], second: Mapping[str, float], u: float
) -> dict[str, float]:
    return {
        key: float(first[key]) + u * (float(second[key]) - float(first[key]))
        for key in ("r", "theta", "h", "phi")
    }


def _subdivide_segment(
    first: Mapping[str, float],
    second: Mapping[str, float],
    depth: int,
    limit: float,
    engaged: float,
    config: Mapping[str, Any],
    out: list[dict[str, float]],
) -> None:
    displacement = max_engaged_displacement(first, second, engaged, config)
    if displacement <= limit or depth >= 11:
        out.append(dict(second))
        return
    midpoint = _interpolate_joint(first, second, 0.5)
    _subdivide_segment(first, midpoint, depth + 1, limit, engaged, config, out)
    _subdivide_segment(midpoint, second, depth + 1, limit, engaged, config, out)


def resample_path(
    joints: Sequence[Mapping[str, float]],
    rapid_flags: Sequence[bool],
    stages: Sequence[str],
    config: Mapping[str, Any],
) -> tuple[list[dict[str, float]], list[bool], list[str]]:
    """Adaptively subdivide until the engaged-cone sweep bound is satisfied."""

    if not joints:
        return [], [], []
    tip_width = float(config["tool"]["tip_width_mm"])
    engaged = float(config["tool"]["engaged_length_mm"])
    limit = 0.5 * tip_width

    out_joints: list[dict[str, float]] = [dict(joints[0])]
    out_rapid: list[bool] = [False]
    out_stage: list[str] = [stages[0]]

    for index in range(1, len(joints)):
        pieces: list[dict[str, float]] = []
        _subdivide_segment(
            joints[index - 1], joints[index], 0, limit, engaged, config, pieces
        )
        for piece in pieces:
            out_joints.append(piece)
            out_rapid.append(bool(rapid_flags[index]))
            out_stage.append(stages[index])
    return out_joints, out_rapid, out_stage


# ---------------------------------------------------------------------------
# Target surface sampling
# ---------------------------------------------------------------------------


def radial_profiles(
    mesh: trimesh.Trimesh,
    thetas: Sequence[float],
    z_probes: Sequence[float],
) -> np.ndarray:
    """Outer target radius for every (theta, z) probe via axial rays."""

    origins = []
    directions = []
    for theta in thetas:
        e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
        for z in z_probes:
            origins.append([0.0, 0.0, float(z)])
            directions.append(e_r)
    origins_arr = np.asarray(origins)
    directions_arr = np.asarray(directions)
    profile = np.zeros(len(origins), dtype=np.float64)
    if len(mesh.faces) == 0:
        return profile.reshape(len(thetas), len(z_probes))
    locations, index_ray, _ = mesh.ray.intersects_location(
        origins_arr, directions_arr, multiple_hits=True
    )
    for point, ray_index in zip(locations, index_ray):
        radius = float(math.hypot(point[0], point[1]))
        profile[int(ray_index)] = max(profile[int(ray_index)], radius)
    return profile.reshape(len(thetas), len(z_probes))


def shadow_radius(
    profile: np.ndarray, theta_index: int, z_probe_index: int, allowance: float
) -> float:
    """Top-down shadow ``max_{z' >= z} (r_target + allowance)``."""

    above = profile[theta_index, z_probe_index:]
    if above.size == 0:
        return 0.0
    return float(np.max(above) + allowance)


def _vkey(point: Sequence[float]) -> tuple[int, int, int]:
    return (int(round(point[0] * 1e6)), int(round(point[1] * 1e6)), int(round(point[2] * 1e6)))


def section_contour(
    mesh: trimesh.Trimesh,
    theta: float,
    z_min: float,
    z_max: float,
    sample_step_mm: float = 2.0,
) -> list[dict[str, Any]]:
    """Planar ``r-Z`` contour used to *find* candidate cut points.

    The plane has normal ``e_theta = (-sin θ, cos θ, 0)`` through the platter
    axis, so every sample lies exactly on ``theta`` with its own radius
    (multi-valued overhangs are preserved).  It is called with ``z_min =
    z_plinth`` so the seating datum and its footprint are never carve targets.

    Only the near half of the slice is returned (``radius >= 0``): points with a
    negative radius lie on the ``theta + pi`` side of the plane, which the
    platter reaches by rotating the other way.

    ``n_r`` / ``n_z`` are the outward face normals of the intersected triangles
    expanded in ``(e_theta, e_r, e_z)``.  ``mesh_plane`` already returns them
    outward-facing, so they feed :func:`finishing_phi` directly.
    """

    _ = sample_step_mm  # kept for API compatibility with profiled callers
    source = mesh
    extents = float(np.max(source.extents))
    step = max(0.5, extents / 300.0)

    normal = np.array([-math.sin(theta), math.cos(theta), 0.0])
    segments, faces = trimesh_intersections.mesh_plane(
        mesh=source, plane_normal=normal, plane_origin=[0.0, 0.0, 0.0], return_faces=True
    )
    if segments is None or len(segments) == 0:
        return []
    segments = np.asarray(segments, dtype=np.float64).reshape(-1, 2, 3)
    faces = np.asarray(faces).reshape(-1)

    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    a = segments[:, 0]
    b = segments[:, 1]
    ra = a @ e_r
    za = a[:, 2]
    rb = b @ e_r
    zb = b[:, 2]
    dr = rb - ra
    dz = zb - za
    length = np.maximum(np.hypot(dr, dz), 1e-12)

    # Outward normal is the face normal of the intersected triangle, expanded in
    # the local (e_theta, e_r, e_z) basis: that is exactly the surface normal the
    # wrist-pitch policy needs, and overhang flanks keep their inward tilt.
    face_normals = np.asarray(mesh.face_normals, dtype=np.float64)[faces]
    n_r = face_normals @ e_r
    n_z = face_normals[:, 2]
    planar = np.hypot(n_r, n_z)
    tangential = planar < 0.1
    n_r = np.where(tangential, -dz / length, n_r / np.where(tangential, 1.0, planar))
    n_z = np.where(tangential, dr / length, n_z / np.where(tangential, 1.0, planar))

    points: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for index in range(len(segments)):
        count = max(1, int(math.ceil(float(length[index]) / step)))
        for k in range(count + 1):
            t = k / count
            point_r = ra[index] + t * dr[index]
            point_z = za[index] + t * dz[index]
            if point_z < z_min - 1e-9 or point_z > z_max + 1e-9:
                continue
            if point_r < 0.0:
                # Opposite side of the slice (theta + pi); not this azimuth.
                continue
            key = (int(round(point_r / 0.6)), int(round(point_z / 0.6)))
            if key in seen:
                continue
            seen.add(key)
            points.append(
                {
                    "point": np.array([point_r * e_r[0], point_r * e_r[1], point_z]),
                    "radius": float(point_r),
                    "z": float(point_z),
                    "n_r": float(n_r[index]),
                    "n_z": float(n_z[index]),
                }
            )
    points.sort(key=lambda item: (item["z"], item["radius"]))
    return points


def finishing_phi(n_r: float, n_z: float, config: Mapping[str, Any]) -> tuple[float, bool]:
    """Wrist pitch that lays the conical flank on the surface.

    ``beta = atan2(n_r, n_z)`` is the surface angle from +Z and ``alpha`` the
    conical-bevel half angle.  The bevel flank removes material within
    ``alpha`` of the tool axis, so the apex may touch the surface while the
    flank clears it whenever ``|beta - phi| <= 90° - alpha``.  The requested
    pitch is ``beta - alpha`` (clamped to the configured ``phi`` limits when the
    preferred orientation is out of range); only a surface steeper than that
    clearance band is genuinely unreachable.  Returns ``(phi_rad, reachable)``.
    """

    alpha = math.radians(float(config["tool"]["cone_half_angle_deg"]))
    phi_lo, phi_hi = (math.radians(float(v)) for v in config["limits"]["phi_limits_deg"])
    if n_z <= 0.2:
        # Nearly tangential / steeply overhanging faces: the wrist sweeps from
        # vertical all the way to the far limit, which also covers surfaces
        # the +phi side cannot reach.
        beta_positive = math.atan2(n_r, max(n_z, 0.0))
        phi_forward = min(max(beta_positive - alpha, phi_lo), phi_hi)
        if abs(beta_positive - phi_forward) <= (math.pi / 2 - alpha) + EPS:
            return phi_forward, True
        return phi_hi, False
    beta = math.atan2(n_r, n_z)
    preferred = beta - alpha
    phi = min(max(preferred, phi_lo), phi_hi)
    reachable = abs(beta - phi) <= (math.pi / 2 - alpha) + EPS
    return phi, reachable


def _melt_kerf_offset(config: Mapping[str, Any]) -> float:
    """Contact-Point -> Tip-Apex standoff: ``tip_radius + melt_kerf``."""

    tool = config["tool"]
    return float(tool["tip_radius_mm"]) + float(tool["melt_kerf_mm"])


def detect_gouges(
    mesh: trimesh.Trimesh,
    poses: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[Diagnostic]:
    """Flag cutting poses whose heated body penetrates the target mesh.

    Stations are walked along the tool axis from the apex back toward the wrist.
    At station ``t`` the conical flank has radius
    ``tip_radius + melt_kerf + t * tan(alpha)``; the flank is a gouge when the
    material reaches past that radius, i.e. when the signed distance of the axis
    point is closer to the surface than the flank radius.

    ``trimesh.nearest.signed_distance`` is **positive inside** a watertight mesh
    and negative outside, so "material reaches past the flank" is
    ``signed_distance(axis_point) > -(tip_r + kerf + t * tan(alpha))``.
    """

    tool = config["tool"]
    engaged = float(tool["engaged_length_mm"])
    tip_radius = float(tool["tip_radius_mm"])
    kerf = float(tool["melt_kerf_mm"])
    alpha = math.radians(float(tool["cone_half_angle_deg"]))
    collector = DiagnosticCollector()
    stations = [engaged * fraction for fraction in (0.25, 0.5, 0.75, 1.0)]
    for pose in poses:
        apex = np.asarray(pose["tip_xyz_wax"], dtype=np.float64)
        axis = np.asarray(pose["tool_axis_wax"], dtype=np.float64)
        length = float(np.linalg.norm(axis)) or 1.0
        axis = axis / length
        points = np.asarray([apex - axis * t for t in stations], dtype=np.float64)
        signed = np.asarray(mesh.nearest.signed_distance(points), dtype=np.float64)
        for station, offset, point in zip(stations, signed, points):
            flank = tip_radius + kerf + station * math.tan(alpha)
            if float(offset) > -flank:
                collector.add(
                    "GOUGE",
                    "warning",
                    f"tool flank penetrates the target at {np.round(point, 3).tolist()}",
                    value=float(flank + float(offset)),
                )
                break
    return collector.as_list()


# ---------------------------------------------------------------------------
# Stage 1: shadow-aware roughing
# ---------------------------------------------------------------------------


def build_roughing(
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any],
    params: Mapping[str, Any],
    collector: DiagnosticCollector | None = None,
) -> tuple[list[dict[str, float]], list[bool], list[str], float]:
    """Returns joints, rapid flags, stages, and the final unwrapped theta."""

    diagnostics = collector if collector is not None else DiagnosticCollector()
    stock = config["stock"]
    radius_stock = float(stock["R_stock_mm"])
    height_stock = float(stock["H_stock_mm"])
    z_plinth = float(stock["z_plinth_mm"])
    allowance = float(stock["finish_allowance_mm"])
    clearance = float(params["rapid_clearance_mm"])
    engaged = float(config["tool"]["engaged_length_mm"])
    # The cone only removes material over the engaged length above the apex, so
    # clamp the stepdown and start one cone-length below the top to face it off.
    stepdown = min(float(params["rough_stepdown_mm"]), max(1.0, engaged * 0.75))
    stepover = max(float(params["rough_stepover_mm"]), 0.25)
    theta_grid = _theta_grid(float(params["theta_step_deg"]))

    z_probes = np.arange(z_plinth, height_stock + 1e-6, 1.0)
    if z_probes.size == 0 or z_probes[-1] < height_stock - 1e-6:
        z_probes = np.append(z_probes, height_stock)
    # Sample the shadow at a much finer azimuth than the cutting pass so a
    # chord between two coarse angles can never clip a localized nose/brow.
    shadow_theta_deg = min(5.0, float(params["theta_step_deg"]) / 3.0)
    shadow_thetas = _theta_grid(shadow_theta_deg)
    shadow_profile = radial_profiles(mesh, shadow_thetas, z_probes)
    fine_per_coarse = max(1, len(shadow_thetas) // len(theta_grid))
    fine_step = TAU / len(shadow_thetas)
    # Precompute a circular wedge max around every fine azimuth so a chord
    # between two sampled cutting angles cannot clip a localized feature.
    span = fine_per_coarse + 2
    wedge_profile = np.empty_like(shadow_profile)
    for center in range(len(shadow_thetas)):
        columns = [
            shadow_profile[(center + offset) % len(shadow_thetas)]
            for offset in range(-span, span + 1)
        ]
        wedge_profile[center] = np.maximum.reduce(columns)
    theta_count = len(theta_grid)

    top_level = min(height_stock, height_stock - engaged + stepdown)
    levels = list(np.arange(top_level, z_plinth - 1e-6, -stepdown))
    if not levels or abs(levels[-1] - z_plinth) > 1e-6:
        levels.append(z_plinth)
    if levels[0] > z_plinth and levels[0] < height_stock:
        levels.insert(0, height_stock)

    joints: list[dict[str, float]] = []
    rapid: list[bool] = []
    stages: list[str] = []
    theta_base = 0.0
    last_theta = 0.0

    # Establish a safe home outside the stock.
    joints.append(_joint(radius_stock + clearance, 0.0, height_stock, 0.0, config, diagnostics))
    rapid.append(True)
    stages.append("roughing")

    for level_index, level in enumerate(levels):
        level = float(level)
        if level_index > 0:
            # Rapid at clearance to the next terrace before plunging in.
            joints.append(
                _joint(radius_stock + clearance, last_theta, level, 0.0, config, diagnostics)
            )
            rapid.append(True)
            stages.append("roughing")
        probe_index = int(np.argmin(np.abs(z_probes - level)))
        level_shadow_by_center = (
            np.max(wedge_profile[:, probe_index:], axis=1) + allowance + 0.3
        )
        lowest = max(0.0, float(np.min(level_shadow_by_center)))
        radii = list(np.arange(radius_stock, lowest - 1e-6, -stepover))
        if not radii or radii[-1] > lowest + 1e-6:
            radii.append(lowest)
        radii = [min(radius_stock, max(0.0, float(r))) for r in radii]

        for radius in radii:
            # Unwrapped theta never wraps: each ring continues from the last.
            ring_thetas = [
                theta_base + theta_grid[index] for index in range(len(theta_grid))
            ]
            ring_shadows = []
            for theta_value in ring_thetas:
                center = int(round((theta_value % TAU) / fine_step)) % len(shadow_thetas)
                ring_shadows.append(float(level_shadow_by_center[center]))
            active = [
                theta_index
                for theta_index, shadow in enumerate(ring_shadows)
                if radius >= shadow - 1e-6
            ]
            if not active:
                continue
            # Split active angles into contiguous runs.  A chord across an
            # inactive gap would sweep past an overhang that needs a larger
            # radius, so each run gets a safe clearance approach.
            runs: list[list[int]] = []
            for theta_index in active:
                if runs and theta_index == runs[-1][-1] + 1:
                    runs[-1].append(theta_index)
                else:
                    runs.append([theta_index])

            for run in runs:
                start_theta = ring_thetas[run[0]]
                if abs(start_theta - last_theta) > 1e-9:
                    # Cut radially out, rapid at clearance across the gap, then
                    # plunge back in at the run start.
                    joints.append(
                        _joint(radius_stock + clearance, last_theta, level, 0.0, config, diagnostics)
                    )
                    rapid.append(False)
                    stages.append("roughing")
                    joints.append(
                        _joint(radius_stock + clearance, start_theta, level, 0.0, config, diagnostics)
                    )
                    rapid.append(True)
                    stages.append("roughing")
                for theta_index in run:
                    theta_value = ring_thetas[theta_index]
                    joints.append(_joint(radius, theta_value, level, 0.0, config, diagnostics))
                    rapid.append(False)
                    stages.append("roughing")
                    last_theta = theta_value
            theta_base = last_theta

        # Cut radially out at the current azimuth, then rapid to the next level.
        joints.append(_joint(radius_stock + clearance, last_theta, level, 0.0, config, diagnostics))
        rapid.append(False)
        stages.append("roughing")

    theta_base = last_theta
    return joints, rapid, stages, float(theta_base)


# ---------------------------------------------------------------------------
# Stage 2: r-Z undercut finishing
# ---------------------------------------------------------------------------


def _tool_body_clearance(config: Mapping[str, Any]) -> float:
    """Radial standoff where the *body* (not the apex) is fully clear."""

    tool = config["tool"]
    alpha = math.radians(float(tool["cone_half_angle_deg"]))
    engaged = float(tool["engaged_length_mm"])
    reach = float(tool["tip_radius_mm"]) + float(tool["melt_kerf_mm"])
    return reach + engaged * math.tan(alpha)


def safe_retract_moves(
    joint: Mapping[str, float],
    config: Mapping[str, Any],
    clearance_target: float,
    diagnostics: DiagnosticCollector | None = None,
) -> list[dict[str, float]]:
    """Pull the tool clear at constant phi, then reorient phi to vertical.

    Sliding the body along ``-u`` keeps the wrist pitch fixed, so the heated
    cone never sweeps sideways into stock it has not cut.  Only once the whole
    body is outside ``clearance_target`` may ``phi`` rotate back to 0.
    """

    fk = _fk_frame(joint, config)
    apex = np.asarray(fk.tip_xyz_wax, dtype=np.float64)
    axis = np.asarray(fk.tool_axis_wax, dtype=np.float64)
    p = float(config["pivot_to_tip_mm"])
    engaged = float(config["tool"]["engaged_length_mm"])
    theta = float(joint["theta"])
    phi = float(joint["phi"])

    station = 0.0
    while station <= engaged + EPS:
        clear = True
        for s in (0.0, station):
            point = apex - axis * s
            if float(math.hypot(point[0], point[1])) + s * (1.0 - axis[2]) < clearance_target:
                clear = False
                break
        if clear:
            break
        station += 0.5
    if station > engaged:
        station = float(np.linalg.norm(apex)) + _tool_body_clearance(config)

    tip = apex - axis * station
    r_clear = max(float(math.hypot(tip[0], tip[1])), clearance_target)
    z_clear = float(tip[2])
    out = [_joint(r_clear, theta, z_clear, phi, config, diagnostics)]
    if abs(phi) > 1e-9:
        # Reorient in free space: the apex rises by p(1 - cos phi).
        out.append(
            _joint(
                r_clear,
                theta,
                z_clear + p * (1.0 - math.cos(phi)),
                0.0,
                config,
                diagnostics,
            )
        )
    return out


def safe_approach_moves(
    theta: float,
    target_rs: float,
    target_zs: float,
    target_phi: float,
    config: Mapping[str, Any],
    clearance_target: float,
    diagnostics: DiagnosticCollector | None = None,
) -> list[dict[str, float]]:
    """Three-step approach: drop to cut height clear, pitch, then slide in.

    1. Descend at ``r_s = R_stock + clearance`` (outside the stock) to the cut
       height, still vertical.
    2. Pitch the wrist to ``target_phi`` at that height, still outside the stock
       and still above the surface.
    3. Slide along ``-u`` (constant ``phi``) onto the Contact-Point apex.  The
       slide starts ``p * sin(phi)`` outboard of the apex, which is exactly the
       pose a retract walks back to.
    """

    p = float(config["pivot_to_tip_mm"])
    descend = _joint(clearance_target, theta, target_zs, 0.0, config, diagnostics)
    pitched = _joint(clearance_target, theta, target_zs, target_phi, config, diagnostics)
    # Step 3 is a *cutting* move from the clear pose onto the Contact-Point
    # apex: the apex travels inward along -u by ``clearance_target - target_rs``
    # and down by ``p(1 - cos phi)``.  The slide must therefore use the real
    # apex pose, not a re-derived one that would add a further ``p sin(phi)``.
    slide = _joint(target_rs, theta, target_zs, target_phi, config, diagnostics)
    return [descend, pitched, slide]


def _flank_clearance(
    mesh: trimesh.Trimesh,
    apex: np.ndarray,
    normal: np.ndarray,
    config: Mapping[str, Any],
) -> float:
    """How far the pitched flank clears the material (mm; <= 0 means gouge).

    Walks stations back along the tool axis from the apex and returns the
    minimum of ``signed_distance - flank_radius``.  Because
    ``signed_distance`` is positive inside the mesh, a positive result means
    every station sits outside the flank envelope.
    """

    tool = config["tool"]
    engaged = float(tool["engaged_length_mm"])
    tip_radius = float(tool["tip_radius_mm"])
    kerf = float(tool["melt_kerf_mm"])
    alpha = math.radians(float(tool["cone_half_angle_deg"]))
    # The body runs from the apex back toward the wrist, i.e. along -normal.
    axis = -np.asarray(normal, dtype=np.float64)
    length = float(np.linalg.norm(axis)) or 1.0
    axis = axis / length
    clearance = math.inf
    for station in (engaged * 0.5, engaged, engaged * 1.5, engaged * 2.0):
        # ``apex + axis * station`` walks *forward* along -normal, which is away
        # from the tool body, so step back instead.
        point = apex - axis * station
        flank = tip_radius + kerf + station * math.tan(alpha)
        offset = float(
            np.asarray(mesh.nearest.signed_distance([point]), dtype=np.float64)[0]
        )
        # Positive offset = inside the mesh.  Clearance is how far the flank
        # radius exceeds the (negative) distance to the material.
        clearance = min(clearance, flank + offset)
    return clearance


def build_finishing(
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any],
    params: Mapping[str, Any],
    diagnostics: DiagnosticCollector,
    theta_start: float,
) -> tuple[list[dict[str, float]], list[bool], list[str], int, float]:
    stock = config["stock"]
    radius_stock = float(stock["R_stock_mm"])
    z_plinth = float(stock["z_plinth_mm"])
    height_stock = float(stock["H_stock_mm"])
    clearance = float(params["rapid_clearance_mm"])
    theta_grid = _theta_grid(float(params["theta_step_deg"]))
    theta_step = TAU / len(theta_grid)
    offset = _melt_kerf_offset(config)
    clearance_target = radius_stock + clearance
    safe_zs = height_stock + clearance

    joints: list[dict[str, float]] = []
    rapid: list[bool] = []
    stages: list[str] = []
    total_points = 0
    unreachable_points = 0
    last_theta = float(theta_start)

    joints.append(_joint(clearance_target, last_theta, safe_zs, 0.0, config, diagnostics))
    rapid.append(True)
    stages.append("finishing")

    for slice_index in range(len(theta_grid)):
        theta_emit = theta_start + slice_index * theta_step
        current_theta = theta_emit % TAU
        # ``radius >= 0`` keeps only this azimuth; the far half of the plane is
        # theta + pi and is reached on another slice.
        contour = section_contour(mesh, current_theta, z_plinth, height_stock)
        if not contour:
            continue
        if slice_index % 2 == 1:
            contour = list(reversed(contour))
        e_r = np.array([math.cos(current_theta), math.sin(current_theta), 0.0])
        unit_z = np.array([0.0, 0.0, 1.0])

        cut_points: list[dict[str, Any]] = []
        for point in contour:
            if point["z"] < z_plinth + 1.5:
                # Plinth foot is seating geometry; finishing starts above it.
                continue
            total_points += 1
            n_r_value = float(point["n_r"])
            n_z_value = float(point["n_z"])
            if n_z_value < -0.2:
                # The pointed conical tip cannot finish a surface that faces
                # down: reaching it would need stock removal below the datum.
                # Report it rather than driving the flank through the body.
                unreachable_points += 1
                continue
            phi, reachable = finishing_phi(n_r_value, n_z_value, config)
            if not reachable:
                unreachable_points += 1
                continue
            # Contact-Point -> Tip-Apex standoff along the local normal.  A
            # purely radial offset is used for near-vertical flanks because the
            # apex must sit outboard of the wall, not above it.
            if abs(n_z_value) > abs(n_r_value):
                normal = unit_z * n_z_value
            else:
                normal = e_r * (1.0 if n_r_value >= 0.0 else -1.0)
            apex = np.asarray(point["point"], dtype=np.float64) + normal * offset
            if apex[2] < z_plinth - EPS:
                unreachable_points += 1
                continue
            # Conservative flank clearance: the pitched cone body must clear the
            # material directly below the apex, otherwise a cut into a steeper
            # flank below buries the flank further up.
            if _flank_clearance(mesh, apex, normal, config) <= 0.0:
                unreachable_points += 1
                continue
            cut_points.append(
                {
                    "rs": float(math.hypot(apex[0], apex[1])),
                    "zs": float(apex[2]),
                    "theta": theta_emit,
                    "phi": phi,
                }
            )
        if not cut_points:
            continue

        first = cut_points[0]
        joints.append(_joint(clearance_target, first["theta"], safe_zs, 0.0, config, diagnostics))
        rapid.append(True)
        stages.append("finishing")
        for move in safe_approach_moves(
            first["theta"],
            first["rs"],
            first["zs"],
            first["phi"],
            config,
            clearance_target,
            diagnostics,
        ):
            joints.append(move)
            rapid.append(False)
            stages.append("finishing")
        last_theta = first["theta"]

        for cut in cut_points[1:]:
            joints.append(
                _joint(cut["rs"], cut["theta"], cut["zs"], cut["phi"], config, diagnostics)
            )
            rapid.append(False)
            stages.append("finishing")

        last_cut = cut_points[-1]
        if slice_index + 1 < len(theta_grid):
            last_joint = _joint(
                last_cut["rs"],
                last_cut["theta"],
                last_cut["zs"],
                last_cut["phi"],
                config,
                diagnostics,
            )
            for move in safe_retract_moves(
                last_joint, config, clearance_target, diagnostics
            ):
                joints.append(move)
                rapid.append(False)
                stages.append("finishing")
            joints.append(
                _joint(clearance_target, last_cut["theta"], safe_zs, 0.0, config, diagnostics)
            )
            rapid.append(True)
            stages.append("finishing")

    percentage = 0.0 if total_points == 0 else 100.0 * unreachable_points / total_points
    return joints, rapid, stages, total_points, percentage


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_synthetic_carve_path(
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any] | None = None,
    preset: str = "demo",
) -> ToolpathResult:
    """Generate the full two-stage synthetic toolpath and its diagnostics."""

    cfg = kinematics.load_config(config) if config is not None else kinematics.load_config()
    if preset not in cfg["presets"]:
        raise ValueError(f"unknown preset {preset!r}; expected one of {list(cfg['presets'])}")

    params = dict(cfg["toolpath"])
    params.update(cfg["presets"][preset])
    params["rapid_clearance_mm"] = float(
        cfg["stock"].get("retract_clearance_mm", params.get("rapid_clearance_mm", 6.0))
    )

    collector = DiagnosticCollector()

    rough_joints, rough_rapid, rough_stage, rough_last_theta = build_roughing(
        mesh, cfg, params, collector
    )
    (
        finish_joints,
        finish_rapid,
        finish_stage,
        _finish_points,
        unreachable_percent,
    ) = build_finishing(mesh, cfg, params, collector, rough_last_theta)

    joints = rough_joints + finish_joints
    rapid_flags = rough_rapid + finish_rapid
    stages = rough_stage + finish_stage

    joints, rapid_flags, stages = resample_path(joints, rapid_flags, stages, cfg)

    max_frames = int(cfg.get("api", {}).get("max_frames", 250_000))
    if len(joints) > max_frames:
        # Fail loudly instead of truncating mid-stock with the tool buried.
        raise FrameCapExceededError(len(joints), max_frames)

    frames, trajectory_diagnostics = kinematics.build_trajectory(joints, rapid_flags, cfg)
    for frame, stage in zip(frames, stages):
        frame["stage"] = stage

    collector.extend(trajectory_diagnostics)

    if unreachable_percent > 0.0:
        collector.add(
            "UNREACHABLE_UNDERCUT_AREA",
            "warning",
            (
                f"{unreachable_percent:.2f}% of target surface points require a wrist "
                f"pitch outside the configured limits"
            ),
            value=unreachable_percent,
        )

    # Gouge checks run over every finishing cut pose, derived from the FK of
    # the frames actually emitted (not from pre-resampling target points).
    cutting_poses = [
        {
            "tip_xyz_wax": frame["tip_xyz_wax"],
            "tool_axis_wax": frame["tool_axis_wax"],
        }
        for frame, stage in zip(frames, stages)
        if stage == "finishing" and not frame["is_rapid"]
    ]
    for diag in detect_gouges(mesh, cutting_poses, cfg):
        collector.extend([diag])

    rough_count = sum(1 for stage in stages if stage == "roughing")
    finish_count = sum(1 for stage in stages if stage == "finishing")
    return ToolpathResult(
        frames=frames,
        diagnostics=collector.as_list(),
        preset=preset,
        roughing_frames=rough_count,
        finishing_frames=finish_count,
        unreachable_percent=unreachable_percent,
        rapid_frames=sum(1 for flag in rapid_flags if flag),
    )

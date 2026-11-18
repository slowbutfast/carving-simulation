"""Synthetic 4-DOF roughing and undercut-capable finishing trajectory generator.

Stage 1 - shadow-aware cylindrical roughing (phi = 0):
    Z-level terracing from H_stock down to z_plinth.  At every level each
    azimuth's material is removed from the stock radius inward to the top-down
    shadow ``max_{z' >= z} r_target(theta, z') + finish_allowance`` so the
    vertical shank can never collide with an overhang above the cut.

Stage 2 - r-Z slice undercut finishing:
    The target mesh vertices are binned into narrow theta wedges.  Each wedge
    is a 2D r-Z cross-section (multi-valued overhangs included), normals are
    projected into the local (e_r, e_z) plane, the wrist pitch is chosen to
    align the conical flank with the surface, the Contact-Point is offset to
    the Tip Apex by (tip_radius + melt_kerf), unreachable overhangs are
    reported, and gouges are detected against the target mesh.

Every segment is resampled so the maximum displacement of any point on the
engaged heated cone is <= 0.5 * tip_width, and all rapids retract outside the
stock before traversing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import trimesh

import kinematics
from kinematics import Diagnostic, DiagnosticCollector

TAU = 2.0 * math.pi
EPS = 1e-9


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


def _joint(rs: float, theta: float, zs: float, phi: float, config: Mapping[str, Any]) -> dict[str, float]:
    """Joint tuple for a desired wax-frame tip apex pose (no limit checking)."""

    x = float(config["arm_radial_offset_mm"])
    h2 = float(config["arm_to_pivot_z_mm"])
    p = float(config["pivot_to_tip_mm"])
    return {
        "r": rs + x + p * math.sin(phi),
        "theta": theta,
        "h": zs + p * math.cos(phi) + h2,
        "phi": phi,
    }


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
        origins_arr, directions_arr, multiple_hits=False
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


def surface_slice_points(
    mesh: trimesh.Trimesh,
    theta: float,
    half_width: float,
    z_step: float,
    z_min: float,
    z_max: float,
) -> list[dict[str, Any]]:
    """Target points whose azimuth falls inside one wedge (multi-valued r-Z)."""

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    normals = np.asarray(mesh.vertex_normals, dtype=np.float64)
    azimuth = np.arctan2(vertices[:, 1], vertices[:, 0])
    delta = np.abs([_wrap_angle(a - theta) for a in azimuth])
    mask = (delta <= half_width) & (vertices[:, 2] >= z_min) & (vertices[:, 2] <= z_max)
    if not np.any(mask):
        return []

    selected = vertices[mask]
    selected_normals = normals[mask]
    radii = np.linalg.norm(selected[:, :2], axis=1)
    z_values = selected[:, 2]

    # Preserve multi-valued r for a given z bin (undercuts), dedupe near-dupes.
    bins: dict[tuple[int, int], dict[str, Any]] = {}
    for point, normal, radius, z in zip(selected, selected_normals, radii, z_values):
        z_bin = int(round(float(z) / max(z_step, 0.25)))
        r_bin = int(round(float(radius) / 0.75))
        key = (z_bin, r_bin)
        if key in bins:
            continue
        e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
        n_r = float(np.dot(normal, e_r))
        n_z = float(normal[2])
        norm = math.hypot(n_r, n_z)
        if norm < 1e-6:
            n_r, n_z = 0.0, 1.0
            norm = 1.0
        bins[key] = {
            "point": np.array(point, dtype=np.float64),
            "radius": float(radius),
            "z": float(z),
            "n_r": n_r / norm,
            "n_z": n_z / norm,
        }
    return sorted(bins.values(), key=lambda item: (item["z"], item["radius"]))


def finishing_phi(n_r: float, n_z: float, config: Mapping[str, Any]) -> tuple[float, bool]:
    """Wrist pitch that lays the conical flank on the surface.

    ``beta = atan2(n_r, n_z)`` is the surface angle from +Z.  The bevel half
    angle lets the flank cut surfaces within ``alpha`` of the axis, so the
    required wrist pitch is ``beta - alpha`` (signed for inward/outward
    facing normals).  Flat tops use phi = 0.  Returns ``(phi_rad, reachable)``.
    """

    alpha = math.radians(float(config["tool"]["cone_half_angle_deg"]))
    phi_lo, phi_hi = (math.radians(float(v)) for v in config["limits"]["phi_limits_deg"])
    beta = math.atan2(n_r, n_z)
    if beta >= 0.0:
        phi = max(0.0, beta - alpha)
    else:
        phi = min(0.0, beta + alpha)
    reachable = (phi_lo - EPS) <= phi <= (phi_hi + EPS)
    return phi, reachable


def detect_gouges(
    mesh: trimesh.Trimesh,
    poses: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[Diagnostic]:
    """Flag tool-body points that penetrate the target mesh."""

    engaged = float(config["tool"]["engaged_length_mm"])
    collector = DiagnosticCollector()
    for pose in poses:
        apex = np.asarray(pose["tip_xyz_wax"], dtype=np.float64)
        axis = np.asarray(pose["tool_axis_wax"], dtype=np.float64)
        for fraction in (0.25, 0.5, 0.75):
            probe = apex - axis * (engaged * fraction)
            if bool(mesh.contains([probe])[0]):
                collector.add(
                    "GOUGE",
                    "warning",
                    f"tool body penetrates the target at {np.round(probe, 3).tolist()}",
                    value=float(fraction),
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
) -> tuple[list[dict[str, float]], list[bool], list[str], float]:
    """Returns joints, rapid flags, stages, and the final unwrapped theta."""

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
    joints.append(_joint(radius_stock + clearance, 0.0, height_stock, 0.0, config))
    rapid.append(True)
    stages.append("roughing")

    for level_index, level in enumerate(levels):
        level = float(level)
        if level_index > 0:
            # Rapid at clearance to the next terrace before plunging in.
            joints.append(
                _joint(radius_stock + clearance, last_theta, level, 0.0, config)
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
                        _joint(radius_stock + clearance, last_theta, level, 0.0, config)
                    )
                    rapid.append(False)
                    stages.append("roughing")
                    joints.append(
                        _joint(radius_stock + clearance, start_theta, level, 0.0, config)
                    )
                    rapid.append(True)
                    stages.append("roughing")
                for theta_index in run:
                    theta_value = ring_thetas[theta_index]
                    joints.append(_joint(radius, theta_value, level, 0.0, config))
                    rapid.append(False)
                    stages.append("roughing")
                    last_theta = theta_value
            theta_base = last_theta

        # Cut radially out at the current azimuth, then rapid to the next level.
        joints.append(_joint(radius_stock + clearance, last_theta, level, 0.0, config))
        rapid.append(False)
        stages.append("roughing")

    theta_base = last_theta
    return joints, rapid, stages, float(theta_base)


# ---------------------------------------------------------------------------
# Stage 2: r-Z undercut finishing
# ---------------------------------------------------------------------------


def build_finishing(
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any],
    params: Mapping[str, Any],
    diagnostics: DiagnosticCollector,
    theta_start: float,
) -> tuple[list[dict[str, float]], list[bool], list[str], list[dict[str, Any]], float]:
    stock = config["stock"]
    radius_stock = float(stock["R_stock_mm"])
    z_plinth = float(stock["z_plinth_mm"])
    height_stock = float(stock["H_stock_mm"])
    clearance = float(params["rapid_clearance_mm"])
    theta_grid = _theta_grid(float(params["theta_step_deg"]))
    theta_step = TAU / len(theta_grid)
    half_width = theta_step * 0.55
    z_step = float(params["finish_z_step_mm"])
    offset = float(config["tool"]["tip_radius_mm"]) + float(config["tool"]["melt_kerf_mm"])

    joints: list[dict[str, float]] = []
    rapid: list[bool] = []
    stages: list[str] = []
    cl_poses: list[dict[str, Any]] = []
    total_points = 0
    unreachable_points = 0

    # Start outside the stock at the first slice's top height.
    joints.append(_joint(radius_stock + clearance, theta_start, height_stock, 0.0, config))
    rapid.append(True)
    stages.append("finishing")
    previous_cut_zs: float | None = None
    previous_cut_theta = theta_start

    for slice_index in range(len(theta_grid)):
        theta_emit = theta_start + slice_index * theta_step
        theta_geom = theta_emit % TAU
        points = surface_slice_points(
            mesh, theta_geom, half_width, z_step, z_plinth, height_stock
        )
        if not points:
            continue
        if slice_index % 2 == 1:
            points = list(reversed(points))

        cut_points: list[dict[str, Any]] = []
        for point in points:
            total_points += 1
            phi, reachable = finishing_phi(point["n_r"], point["n_z"], config)
            if not reachable:
                unreachable_points += 1
                continue
            e_r = np.array([math.cos(theta_geom), math.sin(theta_geom), 0.0])
            n_out = point["n_r"] * e_r + point["n_z"] * np.array([0.0, 0.0, 1.0])
            apex = point["point"] + n_out * offset
            cut_points.append(
                {
                    "rs": float(math.hypot(apex[0], apex[1])),
                    "zs": float(apex[2]),
                    "theta": theta_emit,
                    "phi": phi,
                    "apex": apex,
                }
            )

        if not cut_points:
            continue

        # Rapid to the first cut point's quadrant at clearance, then cut in.
        first = cut_points[0]
        if previous_cut_zs is not None:
            # Retract radially at the previous cut's z/theta (a cutting move, as
            # the surrounding stock may still carry roughing ridges).
            joints.append(
                _joint(
                    radius_stock + clearance,
                    previous_cut_theta,
                    previous_cut_zs,
                    0.0,
                    config,
                )
            )
            rapid.append(False)
            stages.append("finishing")
        joints.append(_joint(radius_stock + clearance, first["theta"], first["zs"], 0.0, config))
        rapid.append(True)
        stages.append("finishing")
        joints.append(_joint(first["rs"], first["theta"], first["zs"], first["phi"], config))
        rapid.append(False)
        stages.append("finishing")
        cl_poses.append(
            {
                "tip_xyz_wax": first["apex"],
                "tool_axis_wax": _fk_frame(joints[-1], config).tool_axis_wax,
            }
        )

        for cut in cut_points[1:]:
            joints.append(
                _joint(cut["rs"], cut["theta"], cut["zs"], cut["phi"], config)
            )
            rapid.append(False)
            stages.append("finishing")
            cl_poses.append(
                {
                    "tip_xyz_wax": cut["apex"],
                    "tool_axis_wax": _fk_frame(joints[-1], config).tool_axis_wax,
                }
            )
        previous_cut_zs = cut_points[-1]["zs"]
        previous_cut_theta = theta_emit

    if previous_cut_zs is not None:
        joints.append(
            _joint(
                radius_stock + clearance,
                previous_cut_theta,
                previous_cut_zs,
                0.0,
                config,
            )
        )
        rapid.append(False)
        stages.append("finishing")

    percentage = 0.0 if total_points == 0 else 100.0 * unreachable_points / total_points
    return joints, rapid, stages, cl_poses, percentage


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
        mesh, cfg, params
    )
    finish_joints, finish_rapid, finish_stage, cl_poses, unreachable_percent = build_finishing(
        mesh, cfg, params, collector, rough_last_theta
    )

    joints = rough_joints + finish_joints
    rapid_flags = rough_rapid + finish_rapid
    stages = rough_stage + finish_stage

    joints, rapid_flags, stages = resample_path(joints, rapid_flags, stages, cfg)

    max_frames = int(cfg.get("api", {}).get("max_frames", 250_000))
    if len(joints) > max_frames:
        collector.add(
            "FRAME_CAP_EXCEEDED",
            "warning",
            f"trajectory truncated from {len(joints)} to {max_frames} frames",
            value=float(len(joints)),
        )
        joints = joints[:max_frames]
        rapid_flags = rapid_flags[:max_frames]
        stages = stages[:max_frames]

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

    for diag in detect_gouges(mesh, cl_poses[:: max(1, len(cl_poses) // 60)], cfg):
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

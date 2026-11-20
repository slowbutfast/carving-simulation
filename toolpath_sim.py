"""Synthetic 4-DOF roughing and undercut-capable finishing trajectory generator.

Stage 1 - shadow-aware cylindrical roughing (phi = 0):
    Z-level terracing from H_stock down to z_plinth. At every level each
    azimuth's material is removed from the stock radius inward to the top-down
    shadow ``max_{z' >= z} r_target(theta, z') + finish_allowance`` so the
    unheated shaft can never collide with an overhang above the cut. Passes run
    along theta at constant r; the blade's radial support extent is added to
    the shadow so the heated region cannot enter it.

Stage 2 - r-Z slice undercut finishing:
    The target mesh is cut with true planar sections
    (``plane_normal = e_theta``), so every contour point lies exactly on the
    slice azimuth with its own radius (multi-valued overhangs included). The
    contact point is placed with ``tool_model.place_on_contact`` (support
    function, including the melt kerf); the wrist pitch comes from the IK
    policy and is searched outward from phi_ideal until the unheated bodies
    clear the target. Points with no clear pitch are reported as
    ``UNREACHABLE_UNDERCUT_AREA``; heated-region burial is a ``GOUGE``.

Every segment is resampled so the maximum displacement of any heated-region
corner is <= 0.5 * (blade_thickness + 2 * kerf). Approaches and retracts are
split into safe moves and all rapids retract outside the stock by the
retract clearance plus the tool's radial support extent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import trimesh
from trimesh import intersections as trimesh_intersections

import kinematics
import tool_model
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


def _reachable_floor(config: Mapping[str, Any]) -> float:
    """Lowest reference-point height the machine can actually reach.

    The stock's seating plinth may sit below the CAD Z-travel minimum; with
    ``phi = 0`` the reference point is ``p`` below the pivot, so the reachable
    floor is ``h_min - p``. Never cut where the machine cannot go.
    """

    stock_floor = float(config["stock"]["z_plinth_mm"])
    h_min = float(config["limits"]["h_limits_mm"][0])
    p = float(config["pivot_to_tip_mm"])
    h2 = float(config["arm_to_pivot_z_mm"])
    return max(stock_floor, h_min - p - h2 + 0.01)


def _theta_grid(step_deg: float, config: Mapping[str, Any] | None = None) -> list[float]:
    """Orbit angles from the configured stop range, at approximately step_deg.

    The upper stop is included: the first implementation used ``range(count)``
    and stopped one step short of ``hi``.
    """

    if config is not None and config.get("limits", {}).get("theta_limits_deg"):
        lo_deg, hi_deg = (float(v) for v in config["limits"]["theta_limits_deg"])
    else:
        lo_deg, hi_deg = -180.0, 180.0
    span = max(1e-6, hi_deg - lo_deg)
    count = max(4, int(round(span / float(step_deg))))
    step = span / count
    return [math.radians(lo_deg + index * step) for index in range(count + 1)]


def _azimuth_passes(
    step_deg: float, config: Mapping[str, Any]
) -> list[tuple[float, float, float]]:
    """Every azimuth around the wax, as ``(azimuth, ring theta, r-sign)``.

    The ring is bounded by the stop block, so azimuths in
    ``(theta_hi, theta_lo + 360)`` cannot be reached with positive ``r_s``.
    They are reached on the far side of the axis: ``theta = azimuth - 180``
    and ``r_s < 0``.
    """

    theta_grid = _theta_grid(step_deg, config)
    passes: list[tuple[float, float, float]] = [
        (theta, theta, 1.0) for theta in theta_grid
    ]
    limits = config.get("limits", {}).get("theta_limits_deg")
    if not limits:
        return passes
    lo_deg, hi_deg = (float(v) for v in limits)
    back_span = (lo_deg + 360.0) - hi_deg
    if back_span <= 1e-9:
        return passes
    count = max(1, int(round(back_span / float(step_deg))))
    step = back_span / count
    for index in range(1, count + 1):
        azimuth_deg = hi_deg + index * step
        if azimuth_deg >= lo_deg + 360.0 - 1e-9:
            continue  # duplicate of the lower stop
        passes.append(
            (
                math.radians(azimuth_deg),
                math.radians(azimuth_deg - 180.0),
                -1.0,
            )
        )
    return passes


def _joint(
    rs: float,
    theta: float,
    zs: float,
    phi: float,
    config: Mapping[str, Any],
    collector: DiagnosticCollector | None = None,
) -> dict[str, float]:
    """Joint tuple for a desired wax-frame tip tip pose.

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


def _frame_pose(frame: Mapping[str, Any], config: Mapping[str, Any]) -> tool_model.ToolPose:
    fk = _fk_frame(frame, config)
    return tool_model.tool_pose(
        fk.tip_xyz_wax, float(frame["theta"]), float(frame["phi"]), config
    )


def max_engaged_displacement(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    config: Mapping[str, Any],
) -> float:
    """Exact max displacement over the eight heated-region corners.

    The corners are fixed in the tool frame, so comparing corresponding corners
    between the two poses bounds every point of the blade under the linear
    joint interpolation.
    """

    a = tool_model.heated_corners(_frame_pose(first, config), config)
    b = tool_model.heated_corners(_frame_pose(second, config), config)
    return float(np.max(np.linalg.norm(b - a, axis=1)))


def sweep_length(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    config: Mapping[str, Any],
) -> float:
    """Conservative swept path length for a segment (bounds every blade point)."""

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
    thickness = float(tool_model._tool(config)["blade_thickness_mm"])
    return float(path + thickness * axis_delta)


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
    config: Mapping[str, Any],
    out: list[dict[str, float]],
) -> None:
    displacement = max_engaged_displacement(first, second, config)
    if displacement <= limit or depth >= 11:
        out.append(dict(second))
        return
    midpoint = _interpolate_joint(first, second, 0.5)
    _subdivide_segment(first, midpoint, depth + 1, limit, config, out)
    _subdivide_segment(midpoint, second, depth + 1, limit, config, out)


def resample_path(
    joints: Sequence[Mapping[str, float]],
    rapid_flags: Sequence[bool],
    stages: Sequence[str],
    config: Mapping[str, Any],
) -> tuple[list[dict[str, float]], list[bool], list[str]]:
    """Adaptively subdivide until the heated-region corner bound is satisfied."""

    if not joints:
        return [], [], []
    tool = config["tool"]
    limit = 0.5 * (
        float(tool["blade_thickness_mm"]) + 2.0 * float(tool["melt_kerf_mm"])
    )

    out_joints: list[dict[str, float]] = [dict(joints[0])]
    out_rapid: list[bool] = [False]
    out_stage: list[str] = [stages[0]]

    for index in range(1, len(joints)):
        pieces: list[dict[str, float]] = []
        _subdivide_segment(joints[index - 1], joints[index], 0, limit, config, pieces)
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

def _vkey(point: Sequence[float], quantum: float = 1e-6) -> tuple[int, int, int]:
    """Hash a slice endpoint; ``mesh_plane`` returns shared vertices exactly."""

    return (
        int(round(float(point[0]) / quantum)),
        int(round(float(point[1]) / quantum)),
        int(round(float(point[2]) / quantum)),
    )


def _chain_loops(
    segments: np.ndarray,
    normals: list[tuple[float, float]],
) -> list[tuple[list[np.ndarray], list[tuple[float, float]], bool]]:
    """Chain slice segments into runs by shared endpoints.

    Returns ``(points, point_normals, closed)`` per run, where ``point_normals``
    is the intersected face's planar normal carried per vertex (outward, from
    the face normal).  A run that returns to its start is closed; its start
    point is not repeated.
    """

    records: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for first, second in segments:
        key_a, key_b = _vkey(first), _vkey(second)
        if key_a != key_b:
            records.append((key_a, key_b))
    if not records:
        return []

    adjacency: dict[tuple[int, int, int], list[int]] = {}
    for segment_id, (key_a, key_b) in enumerate(records):
        adjacency.setdefault(key_a, []).append(segment_id)
        adjacency.setdefault(key_b, []).append(segment_id)

    visited: set[int] = set()

    def walk(start_key: tuple[int, int, int], first: int) -> tuple[
        list[np.ndarray], list[tuple[float, float]], bool
    ]:
        points: list[np.ndarray] = [np.asarray(segments[first, 0], dtype=np.float64)]
        carried: list[tuple[float, float]] = [normals[first]]
        key = start_key
        segment_id: int | None = first
        closed = False
        while segment_id is not None and segment_id not in visited:
            visited.add(segment_id)
            key_a, key_b = records[segment_id]
            exit_key = key_b if key_a == key else key_a
            point = np.asarray(
                segments[segment_id, 1] if key_a == key else segments[segment_id, 0],
                dtype=np.float64,
            )
            if exit_key == start_key:
                closed = True
                break
            points.append(point)
            carried.append(normals[segment_id])
            key = exit_key
            following = [s for s in adjacency.get(key, []) if s not in visited]
            segment_id = following[0] if following else None
        return points, carried, closed

    loops = []
    for key in sorted(k for k, ids in adjacency.items() if len(ids) == 1):
        for segment_id in adjacency[key]:
            if segment_id not in visited:
                loops.append(walk(key, segment_id))
    for segment_id in range(len(records)):
        if segment_id not in visited:
            loops.append(walk(records[segment_id][0], segment_id))
    return loops


def _clip_band(
    points: list[np.ndarray],
    normals: list[tuple[float, float]],
    z_lo: float,
    z_hi: float,
) -> list[tuple[list[np.ndarray], list[tuple[float, float]]]]:
    """Clip ``(r, z)`` points to ``r >= 0`` and ``z in [z_lo, z_hi]``.

    Implements the half-plane clip: each segment is trimmed to the band and
    every crossing is interpolated (its normal too), so no output sample lies
    outside the band - neither the plinth foot at ``z < z_lo`` nor the
    ``theta + pi`` half at ``r < 0``.  Returns open pieces; a closed input is
    returned whole only when it never leaves the band.
    """

    def inside(value: np.ndarray) -> bool:
        return float(value[0]) >= 0.0 and z_lo - 1e-9 <= float(value[1]) <= z_hi + 1e-9

    def crossing_parameters(first: np.ndarray, second: np.ndarray) -> list[float]:
        delta = second - first
        parameters = []
        # Radius (axis 0) can only be bounded by r = 0; z (axis 1) only by the
        # band.  Crossing every axis with every bound is wrong: it fabricates a
        # crossing at r = z_lo on any horizontal segment (e.g. a top face).
        for axis, bounds in ((0, (0.0,)), (1, (z_lo, z_hi))):
            if abs(float(delta[axis])) <= EPS:
                continue
            for bound in bounds:
                t = (bound - float(first[axis])) / float(delta[axis])
                if 0.0 < t < 1.0:
                    parameters.append(t)
        return sorted(parameters)

    def mix_normal(first: tuple[float, float], second: tuple[float, float], t: float):
        return (
            first[0] + t * (second[0] - first[0]),
            first[1] + t * (second[1] - first[1]),
        )

    pieces: list[tuple[list[np.ndarray], list[tuple[float, float]]]] = []
    current_points: list[np.ndarray] = []
    current_normals: list[tuple[float, float]] = []

    def push(value: np.ndarray, normal: tuple[float, float]) -> None:
        if current_points and float(np.linalg.norm(current_points[-1] - value)) <= 1e-9:
            current_points[-1] = value
            current_normals[-1] = normal
            return
        current_points.append(value)
        current_normals.append(normal)

    def close() -> None:
        nonlocal current_points, current_normals
        if len(current_points) >= 2:
            pieces.append((current_points, current_normals))
        current_points, current_normals = [], []

    order = list(range(len(points)))
    for index, next_index in zip(order, order[1:]):
        first, second = points[index], points[next_index]
        first_normal, second_normal = normals[index], normals[next_index]
        parameters = crossing_parameters(first, second)
        # Split the segment into sub-stretches at every band crossing and keep
        # those whose midpoint is inside: each kept stretch starts and ends on
        # an interpolated boundary point, never on an out-of-band sample.
        stops = [0.0, *parameters, 1.0]
        for t_start, t_end in zip(stops, stops[1:]):
            middle = first + 0.5 * (t_start + t_end) * (second - first)
            if not inside(middle):
                continue
            start_value = first + t_start * (second - first)
            end_value = first + t_end * (second - first)
            if not current_points:
                push(start_value, mix_normal(first_normal, second_normal, t_start))
            push(end_value, mix_normal(first_normal, second_normal, t_end))
            if t_end < 1.0 or not inside(second):
                close()
    close()
    return pieces


def _split_closed_loop(points: list[np.ndarray]) -> list[list[int]]:
    """Index runs for the two bottom-to-top halves of a closed loop.

    The loop is cut at a lowest and a highest vertex (outermost on ties), but
    which tied vertex is chosen is *measured*, not assumed: both arcs are
    walked and the pair with the fewest strict descents wins.  A flat cut plane
    that climbs toward the axis (a top face, ``r 15 -> 0``) is a tie rather
    than a descent, and only one arc of each flat plane remains, so the closing
    edge is never cut twice.  Both halves share the split vertices.
    """

    if len(points) < 3:
        return []
    lowest = min(float(point[1]) for point in points)
    highest = max(float(point[1]) for point in points)
    if highest - lowest <= 1e-9:
        return []
    souths = [i for i, p in enumerate(points) if float(p[1]) <= lowest + 1e-9]
    norths = [i for i, p in enumerate(points) if float(p[1]) >= highest - 1e-9]

    def arc(start: int, stop: int) -> list[int]:
        run = [start]
        index = start
        while index != stop:
            index = (index + 1) % len(points)
            run.append(index)
        return run

    def descents(run: list[int]) -> int:
        return sum(
            1
            for first, second in zip(run, run[1:])
            if float(points[second][1]) < float(points[first][1]) - 1e-9
        )

    best: tuple[int, int, list[int], list[int]] | None = None
    for south in souths:
        for north in norths:
            if south == north:
                continue
            first, second = arc(south, north), arc(north, south)
            # Worst-case descent count, then prefer the longer short arc so a
            # degenerate one-vertex leg is never chosen.
            score = (max(descents(first), descents(second)), -min(len(first), len(second)))
            if best is None or score < (best[0], best[1]):
                best = (score[0], score[1], first, second)
    if best is None:
        return []
    return [run for run in (best[2], best[3]) if len(run) >= 2]


def _resample(
    points: list[np.ndarray],
    normals: list[tuple[float, float]],
    step: float,
    e_r: np.ndarray,
) -> list[dict[str, Any]]:
    """Resample a 2D ``(r, z)`` polyline at arc-length ``step``."""

    def sample(value: np.ndarray, normal: tuple[float, float]) -> dict[str, Any]:
        radius = float(value[0])
        return {
            "point": radius * e_r + np.array([0.0, 0.0, float(value[1])]),
            "radius": radius,
            "z": float(value[1]),
            "n_r": float(normal[0]),
            "n_z": float(normal[1]),
        }

    out = [sample(points[0], normals[0])]
    carry = 0.0
    for index, (first, second) in enumerate(zip(points, points[1:])):
        length = float(np.linalg.norm(second - first))
        if length <= EPS:
            continue
        travelled = step - carry
        while travelled < length - EPS:
            t = travelled / length
            normal = (
                normals[index][0] + t * (normals[index + 1][0] - normals[index][0]),
                normals[index][1] + t * (normals[index + 1][1] - normals[index][1]),
            )
            # A linear blend between two face normals shortens the vector; keep
            # every emitted normal unit length.
            magnitude = math.hypot(normal[0], normal[1]) or 1.0
            out.append(
                sample(first + t * (second - first), (normal[0] / magnitude, normal[1] / magnitude))
            )
            travelled += step
        carry = max(0.0, length - (travelled - step))
    out.append(sample(points[-1], normals[-1]))
    return out


def section_polylines(
    mesh: trimesh.Trimesh,
    theta: float,
    z_min: float,
    z_max: float,
    step: float = 2.0,
) -> list[list[dict[str, Any]]]:
    """Ordered ``r-Z`` contour polylines on the half-plane at ``theta``.

    The plane normal is ``e_theta = (-sin theta, cos theta, 0)`` through the
    platter axis, so every point lies exactly on ``theta`` with its own radius
    (multi-valued overhangs are preserved).

    ``mesh_plane`` segments are chained into loops by shared endpoints.  Each
    loop becomes ``(r, z)`` with ``r = p . e_r`` and is clipped to ``r >= 0``
    (the ``theta + pi`` half belongs to another slice) and to
    ``z in [z_min + 1.5, z_max]`` (the plinth foot is seating geometry),
    interpolating at every crossing.  A closed loop is split at its lowest and
    highest points, so every returned polyline runs bottom-to-top; each is then
    resampled at arc-length ``step``.

    Each point carries ``point`` (wax XYZ), ``radius``, ``z`` and
    ``n_r``/``n_z`` - the intersected triangle's outward normal expanded in
    ``(e_r, e_z)`` and re-normalised, which feeds :func:`finishing_phi`.
    Splitting into cut runs (and rejecting unreachable points) belongs to
    :func:`build_finishing`, not to this helper.
    """

    normal = np.array([-math.sin(theta), math.cos(theta), 0.0])
    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    segments, faces = trimesh_intersections.mesh_plane(
        mesh=mesh,
        plane_normal=normal,
        plane_origin=[0.0, 0.0, 0.0],
        return_faces=True,
    )
    if segments is None or len(segments) == 0:
        return []
    segments = np.asarray(segments, dtype=np.float64).reshape(-1, 2, 3)
    faces = np.asarray(faces, dtype=np.int64).reshape(-1)
    step = max(float(step), 0.1)
    z_lo = float(z_min) + 1.5
    z_hi = float(z_max)

    face_normals = np.asarray(mesh.face_normals, dtype=np.float64)
    planar_normals: list[tuple[float, float]] = []
    for index in range(len(segments)):
        raw_r = float(face_normals[int(faces[index])] @ e_r) if index < len(faces) else 0.0
        raw_z = float(face_normals[int(faces[index])][2]) if index < len(faces) else 1.0
        magnitude = math.hypot(raw_r, raw_z)
        if magnitude < 1e-6:
            delta = segments[index, 1] - segments[index, 0]
            radial = float(delta @ e_r)
            axial = float(delta[2])
            magnitude = max(math.hypot(radial, axial), EPS)
            raw_r, raw_z = -axial, radial
        planar_normals.append((raw_r / magnitude, raw_z / magnitude))

    polylines: list[list[dict[str, Any]]] = []
    for loop, carried, closed in _chain_loops(segments, planar_normals):
        flat = [np.array([float(point @ e_r), float(point[2])]) for point in loop]
        inside = [
            float(value[0]) >= 0.0 and z_lo - 1e-9 <= float(value[1]) <= z_hi + 1e-9
            for value in flat
        ]
        pieces: list[tuple[list[np.ndarray], list[tuple[float, float]]]] = []
        if closed and all(inside):
            # An untouched island (e.g. the needle): both halves run
            # bottom-to-top, so split it at its low and high points.
            for half in _split_closed_loop(flat) or [list(range(len(flat)))]:
                if len(half) >= 2:
                    pieces.append(
                        ([flat[index] for index in half], [carried[index] for index in half])
                    )
        elif closed:
            # A loop that crosses a boundary is clipped, never split, so the
            # discarded r < 0 / z < z_lo half cannot influence the result.
            # Start the walk at an outside vertex so the in-band arc is kept
            # whole instead of being cut at the chain's arbitrary start.
            first_outside = inside.index(False)
            rotated = list(range(first_outside, len(flat))) + list(range(0, first_outside + 1))
            points = [flat[index] for index in rotated]
            normals = [carried[index] for index in rotated]
            pieces = _clip_band(points, normals, z_lo, z_hi)
        else:
            pieces = _clip_band(flat, carried, z_lo, z_hi)
        for piece, piece_normals in pieces:
            if len(piece) < 2:
                continue
            if float(piece[-1][1]) < float(piece[0][1]):
                piece = list(reversed(piece))
                piece_normals = list(reversed(piece_normals))
            polylines.append(_resample(piece, piece_normals, step, e_r))

    polylines.sort(key=lambda line: (line[0]["z"], line[0]["radius"]))
    return polylines


def section_contour(
    mesh: trimesh.Trimesh,
    theta: float,
    z_min: float,
    z_max: float,
    sample_step_mm: float = 2.0,
) -> list[dict[str, Any]]:
    """Flat view of :func:`section_polylines` for callers that want one list.

    Kept for API compatibility (tests and profiling import it).  Finishing uses
    the ordered polylines directly, because a flat list loses which points may
    be joined by a cut.
    """

    return [
        point
        for line in section_polylines(mesh, theta, z_min, z_max, sample_step_mm)
        for point in line
    ]


def finishing_phi(n_r: float, n_z: float, config: Mapping[str, Any]) -> tuple[float, bool]:
    """Wrist-pitch preference for a section normal, from the IK policy.

    There is no cone half-angle any more: the blade's flank does not define a
    reachability band. The pitch is ``atan2(n_r, n_z)`` projected into the
    configured phi limits, and reachability is decided later by the
    body-collision search over candidate pitches. Always returns ``True`` for
    the policy step (the tuple is kept for callers that distinguish a
    tangential normal).
    """

    magnitude = math.hypot(float(n_r), float(n_z))
    if magnitude < 1e-3:
        return 0.0, True
    n_r = float(n_r) / magnitude
    n_z = float(n_z) / magnitude
    phi_lo, phi_hi = (math.radians(float(v)) for v in config["limits"]["phi_limits_deg"])
    phi = min(max(math.atan2(n_r, n_z), phi_lo), phi_hi)
    return phi, True


def _melt_kerf(config: Mapping[str, Any]) -> float:
    return float(config["tool"]["melt_kerf_mm"])


def cutter_location(
    point_xyz: Sequence[float],
    n_r: float,
    n_z: float,
    theta: float,
    config: Mapping[str, Any],
) -> np.ndarray:
    """Reference point for a contact point, via the blade support function.

    The section normal is ``n_r e_r + n_z e_z`` (planar slices carry no
    tangential component). ``tool_model.place_on_contact`` replaces the old
    ``(rho + kerf) * n`` offset, which was wrong by up to half the blade
    thickness on tangential normals.
    """

    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    normal = float(n_r) * e_r + float(n_z) * np.array([0.0, 0.0, 1.0])
    magnitude = float(np.linalg.norm(normal)) or 1.0
    normal = normal / magnitude
    phi, _ = finishing_phi(n_r, n_z, config)
    axes = tool_model.tool_pose(point_xyz, theta, phi, config)
    return tool_model.place_on_contact(point_xyz, normal, axes, config)


def _pose_for_axis(
    tip: Sequence[float],
    axis: Sequence[float],
    theta: float,
    config: Mapping[str, Any],
) -> tool_model.ToolPose:
    """Rebuild the tool frame from a reference point, axis and azimuth."""

    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    u = np.asarray(axis, dtype=np.float64)
    u = u / (float(np.linalg.norm(u)) or 1.0)
    phi = math.atan2(-float(u @ e_r), -float(u[2]))
    return tool_model.tool_pose(tip, theta, phi, config)


def tool_body_penetrates(
    mesh: trimesh.Trimesh,
    tips: Sequence[Sequence[float]],
    axes: Sequence[Sequence[float]],
    config: Mapping[str, Any],
    thetas: Sequence[float] | None = None,
) -> np.ndarray:
    """Vectorised test: does an unheated tool body intersect the mesh?

    Sign convention: ``trimesh.contains`` is POSITIVE inside the mesh. The wax
    SDF used by the worker is the opposite and states it separately.
    """

    tips = np.atleast_2d(np.asarray(tips, dtype=np.float64))
    axes = np.atleast_2d(np.asarray(axes, dtype=np.float64))
    if len(tips) == 0:
        return np.zeros(0, dtype=bool)
    poses = []
    for index, (tip, axis) in enumerate(zip(tips, axes)):
        theta = float(thetas[index]) if thetas is not None else 0.0
        poses.append(_pose_for_axis(tip, axis, theta, config))
    return tool_model.body_penetrates(mesh, poses, config)


def detect_gouges(
    mesh: trimesh.Trimesh,
    poses: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[Diagnostic]:
    """Flag cutting poses where the heated region is buried in the target.

    Samples the blade corners and centreline, takes the mesh's inside-positive
    signed distance, and reports a GOUGE when the deepest sample exceeds
    ``finish_allowance_mm``. A tangent pose sits at distance ~0.
    """

    allowance = float(config["stock"].get("finish_allowance_mm", 1.5))
    tool = config["tool"]
    thickness = float(tool["blade_thickness_mm"])
    width = float(tool["blade_width_mm"])
    length = float(tool.get("heated_length_mm", tool["blade_length_mm"]))
    collector = DiagnosticCollector()
    for pose in poses:
        tip = np.asarray(pose["tip_xyz_wax"], dtype=np.float64)
        axis = np.asarray(pose["tool_axis_wax"], dtype=np.float64)
        theta = float(pose.get("theta", 0.0))
        frame = _pose_for_axis(tip, axis, theta, config)
        samples = tool_model.heated_corners(frame, config)
        # Add the centreline so a fully engulfed blade cannot hide between
        # corners.
        centreline = np.asarray(
            [tip - frame.u * (length * fraction) for fraction in (0.25, 0.5, 0.75)]
        )
        points = np.concatenate([samples, centreline], axis=0)
        signed = np.asarray(mesh.nearest.signed_distance(points), dtype=np.float64)
        index = int(np.argmax(signed))
        if float(signed[index]) > allowance:
            collector.add(
                "GOUGE",
                "warning",
                f"heated blade is {float(signed[index]):.3f} mm inside the target "
                f"(allowance {allowance:.3f} mm) near {np.round(points[index], 3).tolist()}",
                value=float(signed[index]),
            )
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
    """Returns joints, rapid flags, stages, and the final unwrapped theta.

    Passes run along theta at constant r. The blade's radial support extent is
    added to the shadow, so the heated region (not just the reference point)
    stays outside the material. Radial repositioning moves are
    ``roughing_link`` transitions, not cuts, so the cutting moves themselves are
    all slice-direction theta passes.
    """

    diagnostics = collector if collector is not None else DiagnosticCollector()
    stock = config["stock"]
    radius_stock = float(stock["R_stock_mm"])
    height_stock = float(stock["H_stock_mm"])
    z_plinth = _reachable_floor(config)
    allowance = float(stock["finish_allowance_mm"])
    clearance = float(params["rapid_clearance_mm"])
    reach = tool_model.radial_support_extent(0.0, config)
    clearance_radius = radius_stock + clearance + reach
    stepdown = max(1.0, float(params["rough_stepdown_mm"]))
    stepover = max(float(params["rough_stepover_mm"]), 0.25)
    passes = _azimuth_passes(float(params["theta_step_deg"]), config)

    z_probes = np.arange(z_plinth, height_stock + 1e-6, 1.0)
    if z_probes.size == 0 or z_probes[-1] < height_stock - 1e-6:
        z_probes = np.append(z_probes, height_stock)
    # Sample the shadow at a much finer azimuth than the cutting pass so a
    # chord between two coarse angles can never clip a localized nose/brow.
    shadow_theta_deg = min(5.0, float(params["theta_step_deg"]) / 3.0)
    shadow_thetas = _theta_grid(shadow_theta_deg)
    shadow_profile = radial_profiles(mesh, shadow_thetas, z_probes)
    fine_per_coarse = max(
        1,
        (len(shadow_thetas) - 1)
        // max(1, len(_theta_grid(float(params["theta_step_deg"]), config)) - 1),
    )
    shadow_count = len(shadow_thetas) - 1  # the grid repeats its endpoints
    fine_step = TAU / shadow_count
    span = fine_per_coarse + 2
    wedge_profile = np.empty_like(shadow_profile)
    for center in range(len(shadow_thetas)):
        columns = [
            shadow_profile[(center + offset) % len(shadow_thetas)]
            for offset in range(-span, span + 1)
        ]
        wedge_profile[center] = np.maximum.reduce(columns)

    top_level = height_stock - stepdown
    levels = list(np.arange(top_level, z_plinth - 1e-6, -stepdown))
    if not levels:
        levels = [height_stock]
    if abs(levels[-1] - z_plinth) > 1e-6:
        levels.append(z_plinth)

    joints: list[dict[str, float]] = []
    rapid: list[bool] = []
    stages: list[str] = []
    theta_base = 0.0
    last_theta = 0.0

    # Establish a safe home outside the stock and the blade's radial extent.
    joints.append(_joint(clearance_radius, 0.0, height_stock, 0.0, config, diagnostics))
    rapid.append(True)
    stages.append("roughing_link")

    for level_index, level in enumerate(levels):
        level = float(level)
        if level_index > 0:
            joints.append(
                _joint(clearance_radius, last_theta, level, 0.0, config, diagnostics)
            )
            rapid.append(True)
            stages.append("roughing_link")
        probe_index = int(np.searchsorted(z_probes, level, side="right")) - 1
        probe_index = max(0, min(probe_index, len(z_probes) - 1))
        level_shadow_by_center = (
            np.max(wedge_profile[:, probe_index:], axis=1) + allowance + 0.3
        )
        lowest_shadow = float(np.min(level_shadow_by_center))
        lowest = max(0.0, lowest_shadow + reach)
        radii = list(np.arange(radius_stock + reach, lowest - 1e-6, -stepover))
        if not radii or radii[-1] > lowest + 1e-6:
            radii.append(lowest)
        radii = [float(r) for r in radii]

        for radius_index, radius in enumerate(radii):
            # Serpentine: alternate the sweep direction so the next (smaller)
            # radius starts where the previous one ended. Without this, every
            # radius pays a 340-degree traverse back to the arc start, which
            # dominates the frame count.
            ordered = passes if radius_index % 2 == 0 else list(reversed(passes))
            ring_shadows = []
            shadow_lo = shadow_thetas[0]
            for azimuth, _theta, _sign in ordered:
                center = int(
                    round(((azimuth - shadow_lo) % TAU) / fine_step)
                ) % shadow_count
                ring_shadows.append(float(level_shadow_by_center[center]))
            active = [
                index
                for index, shadow in enumerate(ring_shadows)
                if radius >= shadow + reach - 1e-6
            ]
            if not active:
                continue
            runs: list[list[int]] = []
            for index in active:
                same_branch = (
                    runs
                    and index == runs[-1][-1] + 1
                    and ordered[index][2] == ordered[runs[-1][-1]][2]
                )
                if same_branch:
                    runs[-1].append(index)
                else:
                    runs.append([index])

            for run in runs:
                start_theta = ordered[run[0]][1]
                if abs(start_theta - last_theta) > 1e-9:
                    # Link out to the clearance radius, traverse at clearance,
                    # then link back in. Neither link is a cutting move.
                    joints.append(
                        _joint(clearance_radius, last_theta, level, 0.0, config, diagnostics)
                    )
                    rapid.append(False)
                    stages.append("roughing_link")
                    joints.append(
                        _joint(clearance_radius, start_theta, level, 0.0, config, diagnostics)
                    )
                    rapid.append(True)
                    stages.append("roughing_link")
                    joints.append(
                        _joint(
                            ordered[run[0]][2] * radius,
                            start_theta,
                            level,
                            0.0,
                            config,
                            diagnostics,
                        )
                    )
                    rapid.append(False)
                    stages.append("roughing_link")
                for index in run:
                    _azimuth, theta_value, sign = ordered[index]
                    joints.append(
                        _joint(
                            sign * radius,
                            theta_value,
                            level,
                            0.0,
                            config,
                            diagnostics,
                        )
                    )
                    rapid.append(False)
                    stages.append("roughing")
                    last_theta = theta_value
            theta_base = last_theta

        # Link out at the current azimuth before the next level descends.
        joints.append(
            _joint(clearance_radius, last_theta, level, 0.0, config, diagnostics)
        )
        rapid.append(False)
        stages.append("roughing_link")

    return joints, rapid, stages, float(last_theta)


# ---------------------------------------------------------------------------
# Stage 2: r-Z undercut finishing
# ---------------------------------------------------------------------------


def _safe_radius(config: Mapping[str, Any], sign: float, phi: float) -> float:
    """Radial standoff that clears the stock on the requested side of the axis.

    On the negative-r side the CAD travel ends at ``r_min`` (about -51 mm), so
    the generic ``R + clearance + extent`` radius can exceed what the machine
    can reach. Clamp it to the travel while keeping the stock+retract minimum.
    """

    stock = config["stock"]
    minimum = float(stock["R_stock_mm"]) + float(
        stock.get("retract_clearance_mm", 6.0)
    )
    target = minimum + tool_model.radial_support_extent(phi, config)
    if sign >= 0.0:
        return target
    r_min = float(config["limits"]["r_limits_mm"][0])
    return max(minimum, min(target, abs(r_min) - 1.0))


def _tool_body_clearance(config: Mapping[str, Any], phi: float = 0.0) -> float:
    """Radial standoff added to the stock so the heated region is clear."""

    return tool_model.radial_support_extent(phi, config)


def _body_clear(
    mesh: trimesh.Trimesh,
    tips: Sequence[np.ndarray],
    axes: Sequence[np.ndarray],
    config: Mapping[str, Any],
    theta: float = 0.0,
) -> bool:
    """True when every sampled pose in the batch clears the mesh."""

    if len(tips) == 0:
        return True
    return not bool(
        np.asarray(
            tool_body_penetrates(mesh, tips, axes, config, [theta] * len(tips))
        ).any()
    )


def _sample_poses(
    tips: list[np.ndarray],
    axis: np.ndarray,
) -> list[np.ndarray]:
    """Sample a list of tips every 1 mm, keeping the pitch (axis) constant."""

    samples: list[np.ndarray] = []
    for first, second in zip(tips, tips[1:]):
        steps = max(1, int(math.ceil(float(np.linalg.norm(second - first)))))
        for index in range(steps):
            samples.append(first + (second - first) * (index / steps))
    if tips:
        samples.append(tips[-1])
    return samples


def _clear_line(length: float, start: np.ndarray, direction: np.ndarray) -> list[np.ndarray]:
    """A straight line of ``length`` mm from ``start`` along ``direction``."""

    return [start + direction * s for s in np.arange(0.0, max(length, 0.0) + 1e-9, 1.0)]


def exit_moves(
    tip: np.ndarray | Sequence[float],
    phi: float,
    theta: float,
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any],
    clearance_target: float,
    collector: DiagnosticCollector,
) -> list[dict[str, float]]:
    """Non-rapid exit from a pitched cut: clear the body, re-pitch, then rise.

    With ``u = -sin(phi) e_r - cos(phi) e_z`` a slide along ``-u`` moves the
    tip ``+s sin(phi)`` radially and ``+s cos(phi)`` upward, so candidate A
    reaches ``clearance_target`` at ``s = (clear - r_tip) / sin(phi)`` when
    ``sin(phi) > 0.05``.  Otherwise (or if A is still buried) candidate B lifts
    to ``H_stock + clearance`` and pulls straight out.

    The first candidate whose poses, sampled every 1 mm, all clear the mesh
    under :func:`tool_body_penetrates` wins.  If neither is clear the point is
    genuinely unreachable: an ``UNREACHABLE_UNDERCUT_AREA`` rejection is
    counted and ``[]`` is returned, so ``build_finishing`` drops the point and
    retries with the previous one.

    The moves are non-rapid links (stage ``finishing_link``) ending vertical
    at the clearance radius and then at the safe plane.
    """

    tip = np.asarray(tip, dtype=np.float64)
    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    signed_rs = float(tip[0] * e_r[0] + tip[1] * e_r[1])
    sign = 1.0 if signed_rs >= 0.0 else -1.0
    outward = e_r if signed_rs >= 0.0 else -e_r
    safe_phi = _safe_radius(config, sign, phi)
    safe_zero = _safe_radius(config, sign, 0.0)
    # Tool axis wrist -> tip.  As in kinematics.forward_kinematics (u(phi) =
    # -sin(phi) e_r - cos(phi) e_z), +phi tilts the tip *inward*, so with a
    # negative phi the axis leans outboard and the body runs inboard.
    axis = -math.sin(phi) * e_r - np.array([0.0, 0.0, math.cos(phi)])
    height_stock = float(config["stock"]["H_stock_mm"])
    clearance = float(config["stock"].get("retract_clearance_mm", 6.0))
    safe_z = height_stock + clearance
    p = float(config["pivot_to_tip_mm"])
    r_tip = float(math.hypot(tip[0], tip[1]))

    # The tip of a CL pose sits ``tip_r + kerf`` off the surface, i.e. its
    # *heater* is already in contact: a cone flank opens back towards the wrist
    # and lies on the face by construction.  Both candidates therefore skip the
    # first millimetre (that cut has just been made) and must clear from there.
    candidates: list[list[np.ndarray]] = []
    # Candidate 0: horizontal +e_r at constant phi.  Under a wide overhang
    # both the -u slide and a vertical lift rise into the slab, but pulling
    # straight out at the cut height stays under it.  This is tried first.
    if safe_phi > r_tip:
        candidates.append(
            _clear_line(
                safe_phi - r_tip,
                tip + outward * min(1.0, safe_phi - r_tip),
                outward,
            )
        )
    if math.sin(phi) > 0.05:
        # Leaving the cut is -u; with u = -sin(phi) e_r - cos(phi) e_z the
        # radius of the tip and of every body point grows by s sin(phi).
        length = max(0.0, (safe_phi - r_tip) / math.sin(phi))
        candidates.append(_clear_line(length, tip - axis * min(1.0, length), -axis))
    lift = max(0.0, safe_z - float(tip[2]))
    start = tip + np.array([0.0, 0.0, min(1.0, lift)])
    top = tip + np.array([0.0, 0.0, lift])
    radial = max(0.0, safe_zero - float(math.hypot(top[0], top[1])))
    candidates.append(
        _clear_line(max(0.0, lift - 1.0), start, np.array([0.0, 0.0, 1.0]))
        + _clear_line(radial, top, outward)[1:]
    )

    # Candidate A ends pitched at the clearance radius; it re-pitches to
    # vertical there, sinking by ``p (1 - cos phi)``, so that drop must stay
    # clear.  If it buries, candidate B (which ends on the safe plane, clear of
    # everything) is used instead.
    upright = np.array([0.0, 0.0, -1.0])
    for candidate in candidates:
        samples = _sample_poses(candidate, axis)
        if not _body_clear(mesh, samples, [axis] * len(samples), config, theta):
            continue
        clear = candidate[-1]
        r_clear = max(float(math.hypot(clear[0], clear[1])), safe_phi)
        z_clear = float(clear[2])
        # Check the pitched clearance pose against the joint travel before
        # emitting it; at_clear keeps the cut's pitch and is the worst case.
        p = float(config["pivot_to_tip_mm"])
        r_at_clear = sign * r_clear + p * math.sin(phi)
        r_lo, r_hi = (float(v) for v in config["limits"]["r_limits_mm"])
        if not (r_lo - 1e-9 <= r_at_clear <= r_hi + 1e-9):
            continue
        reorient_z = z_clear + p * (1.0 - math.cos(phi))
        reorient = [
            outward * r_clear + np.array([0.0, 0.0, z])
            for z in np.linspace(z_clear, reorient_z, 8)
        ]
        if not _body_clear(mesh, reorient, [upright] * len(reorient), config, theta):
            continue
        # Wax tip poses, not joint radii: _joint would add p sin(phi).
        at_clear = outward * r_clear + np.array([0.0, 0.0, z_clear])
        at_reorient = outward * r_clear + np.array([0.0, 0.0, reorient_z])
        at_safe = outward * safe_zero + np.array([0.0, 0.0, safe_z])
        return [
            _tip_joint(at_clear, phi, theta, config, collector),
            _tip_joint(at_reorient, 0.0, theta, config, collector),
            _tip_joint(at_safe, 0.0, theta, config, collector),
        ]
    collector.add(
        "UNREACHABLE_UNDERCUT_AREA",
        "warning",
        f"no clear exit from the pitched cut at {np.round(tip, 3).tolist()}",
        value=0.0,
    )
    return []


def entry_moves(
    first: Mapping[str, float],
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any],
    clearance_target: float,
    collector: DiagnosticCollector,
) -> list[dict[str, float]]:
    """Approach a run's first cut: descend vertical, pitch in free space, plunge.

    The reverse of :func:`exit_moves`: from the safe plane at the clearance
    radius, descend, pitch to the cut's ``phi`` outside the stock, then slide
    along ``-u`` onto the Contact-Point tip.  All non-rapid links.
    """

    _ = mesh
    theta = float(first["theta"])
    rs = float(first["rs"])
    zs = float(first["zs"])
    phi = float(first["phi"])
    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    # Build in wax coordinates, then convert to joints.  ``_joint`` adds
    # ``p sin(phi)`` to r and ``p cos(phi)`` to h, so passing a wax radius
    # straight in would swing the arm out by p sin(phi) (r = 120 for a 75 deg
    # pitch at r = 46) and pitch the tool at the wrong place.
    height_stock = float(config["stock"]["H_stock_mm"])
    clearance = float(config["stock"].get("retract_clearance_mm", 6.0))
    p = float(config["pivot_to_tip_mm"])
    h_min = float(config["limits"]["h_limits_mm"][0])
    tip = np.array([rs * math.cos(theta), rs * math.sin(theta), zs])
    sign = 1.0 if rs >= 0.0 else -1.0
    outward = e_r if rs >= 0.0 else -e_r
    # Pitching about the pivot at the cut height can drop the pivot below the
    # CAD Z-travel minimum (h = z + p cos(phi)). Pitch at the lowest height
    # that keeps h valid, then slide down to the contact.
    pitch_z = max(zs, h_min - p * math.cos(phi) + 1.0)
    pitch_z = min(pitch_z, height_stock + clearance)
    # Pitch outside the stock: the reference point sits at the clearance radius
    # while the wrist rotates, then the tool slides onto the contact point.
    ref = outward * _safe_radius(config, sign, phi) + np.array([0.0, 0.0, pitch_z])
    pitched = _tip_joint(ref, phi, theta, config, collector)
    return [
        _tip_joint(
            outward * _safe_radius(config, sign, 0.0)
            + np.array([0.0, 0.0, height_stock + clearance]),
            0.0,
            theta,
            config,
            collector,
        ),
        _tip_joint(ref, 0.0, theta, config, collector),
        pitched,
        _tip_joint(tip, phi, theta, config, collector),
    ]


def _tip_joint(
    tip: np.ndarray,
    phi: float,
    theta: float,
    config: Mapping[str, Any],
    collector: DiagnosticCollector | None = None,
) -> dict[str, float]:
    """Joint for a wax-frame tip tip pose (inverse of the FK translation)."""

    x = float(config["arm_radial_offset_mm"])
    h2 = float(config["arm_to_pivot_z_mm"])
    p = float(config["pivot_to_tip_mm"])
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    rs = float(tip[0]) * cos_t + float(tip[1]) * sin_t
    return _joint_body(rs, theta, float(tip[2]), phi, x, h2, p, config, collector)


def _joint_body(
    rs: float,
    theta: float,
    zs: float,
    phi: float,
    x: float,
    h2: float,
    p: float,
    config: Mapping[str, Any],
    collector: DiagnosticCollector | None,
) -> dict[str, float]:
    """Raw joint from a wax tip pose (shared by _joint and _tip_joint)."""

    joint = {
        "r": rs + x + p * math.sin(phi),
        "theta": theta,
        "h": zs + p * math.cos(phi) + h2,
        "phi": phi,
    }
    if collector is not None:
        collector.extend(validate_joint(collector, joint, config))
    return joint


def build_finishing(
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any],
    params: Mapping[str, Any],
    diagnostics: DiagnosticCollector,
    theta_start: float,
) -> tuple[list[dict[str, float]], list[bool], list[str], int, float]:
    """Undercut-capable finishing, composed from the unit-tested helpers.

    Per slice: :func:`section_polylines` -> batch ``finishing_phi`` +
    :func:`cutter_location` + FK axis -> one :func:`tool_body_penetrates`
    pre-filter -> split each polyline into runs of *consecutive accepted*
    points.  A rejected point ends a run and is never bridged: every run gets
    its own :func:`entry_moves`, its cuts and its :func:`exit_moves`.
    Rejected points are counted into ``UNREACHABLE_UNDERCUT_AREA``.
    """

    stock = config["stock"]
    radius_stock = float(stock["R_stock_mm"])
    z_plinth = _reachable_floor(config)
    height_stock = float(stock["H_stock_mm"])
    clearance = float(params["rapid_clearance_mm"])
    # Rapid clearance must cover the heated region at any wrist pitch, so use
    # the largest support extent over the configured phi range.
    phi_lo, phi_hi = (math.radians(float(v)) for v in config["limits"]["phi_limits_deg"])
    extent = max(
        tool_model.radial_support_extent(phi_lo, config),
        tool_model.radial_support_extent(phi_hi, config),
        tool_model.radial_support_extent(0.0, config),
    )
    clearance_target = radius_stock + clearance + extent
    safe_zs = height_stock + clearance
    # The polyline step honours the preset (never the azimuth grid).
    step = float(params["finish_z_step_mm"])
    search_step = math.radians(float(params.get("finish_phi_search_step_deg", 5.0)))
    max_candidates = int(math.ceil((phi_hi - phi_lo) / search_step)) + 1
    offsets = [0]
    for index in range(1, max_candidates + 1):
        offsets.extend((index, -index))

    joints: list[dict[str, float]] = []
    rapid: list[bool] = []
    stages: list[str] = []
    total_points = 0
    unreachable_points = 0

    def link(move: Mapping[str, float]) -> None:
        joints.append(dict(move))
        rapid.append(False)
        stages.append("finishing_link")

    slices = _azimuth_passes(float(params["theta_step_deg"]), config)
    joints.append(
        _joint(clearance_target, slices[0][1], safe_zs, 0.0, config, diagnostics)
    )
    rapid.append(True)
    stages.append("finishing")

    for azimuth, theta_emit, branch in slices:
        e_r_tool = np.array([math.cos(theta_emit), math.sin(theta_emit), 0.0])
        polylines = section_polylines(mesh, azimuth % TAU, z_plinth, height_stock, step)
        if not polylines:
            continue

        # 1. Contact points and their phi_ideal placement.
        pose_of: dict[int, dict[str, Any]] = {}
        flat: list[dict[str, Any]] = []

        def place(item: dict[str, Any], phi: float) -> None:
            point = item["point"]
            normal = item["normal"]
            tip = tool_model.place_on_contact(
                point["point"],
                normal,
                tool_model.tool_pose(point["point"], theta_emit, phi, config),
                config,
            )
            item["phi"] = phi
            item["tip"] = tip
            item["axis"] = np.array(
                [
                    -math.sin(phi) * math.cos(theta_emit),
                    -math.sin(phi) * math.sin(theta_emit),
                    -math.cos(phi),
                ]
            )
            item["rs"] = float(tip[0] * e_r_tool[0] + tip[1] * e_r_tool[1])
            item["zs"] = float(tip[2])
            # A contact whose support-function CL lands on the far side of the
            # axis does not belong to this slice's branch. Emitting it at this
            # theta would place the tool on the wrong side of the axis; reject
            # it instead of searching every pitch for it.
            if item["rs"] * branch < 0.0:
                item["valid"] = False
                return
            p = float(config["pivot_to_tip_mm"])
            joint_diags = kinematics.validate_joints(
                item["rs"] + p * math.sin(phi),
                theta_emit,
                item["zs"] + p * math.cos(phi),
                phi,
                config,
            )
            item["valid"] = not any(d.severity == "error" for d in joint_diags)
            # The approach/reorient happens at the clearance radius with the
            # same pitch. A cut whose pitch cannot also be held at clearance is
            # not reachable by this machine, so reject it here instead of
            # emitting an out-of-travel link. Use the tip's actual side: a
            # near-axis CL can cross the axis even on a positive-azimuth slice.
            sign_actual = 1.0 if item["rs"] >= 0.0 else -1.0
            r_clear = (
                sign_actual * _safe_radius(config, sign_actual, phi)
                + p * math.sin(phi)
            )
            r_min, r_max = (float(v) for v in config["limits"]["r_limits_mm"])
            if not (r_min - 1e-9 <= r_clear <= r_max + 1e-9):
                item["valid"] = False

        for line in polylines:
            for point in line:
                total_points += 1
                n_r_azimuth = float(point["n_r"])
                n_z = float(point["n_z"])
                # The world normal is the same whichever side of the axis the
                # tool sits on; only its projection into the tool's own e_r
                # changes sign for the negative-r branch.
                e_r_azimuth = np.array(
                    [math.cos(azimuth), math.sin(azimuth), 0.0]
                )
                normal = n_r_azimuth * e_r_azimuth + n_z * np.array([0.0, 0.0, 1.0])
                magnitude = float(np.linalg.norm(normal)) or 1.0
                n_r_tool = branch * n_r_azimuth
                phi_ideal, _ = finishing_phi(n_r_tool, n_z, config)
                item: dict[str, Any] = {
                    "point": point,
                    "normal": normal / magnitude,
                    "phi_ideal": phi_ideal,
                    "accepted": False,
                }
                item["floor"] = float(point["point"][2]) < z_plinth - EPS
                pose_of[id(point)] = item
                flat.append(item)

        # 2. Search phi candidates ordered from phi_ideal, with early exit:
        #    batch every still-blocked point at one candidate, keep the first
        #    candidate that clears each point.
        pending = [item for item in flat if not item["floor"]]
        for offset in offsets:
            if not pending:
                break
            batch: list[dict[str, Any]] = []
            for item in pending:
                phi = min(max(item["phi_ideal"] + offset * search_step, phi_lo), phi_hi)
                if offset and abs(phi - item["phi_ideal"]) < 1e-12:
                    continue  # clamped: this candidate adds nothing
                place(item, phi)
                if float(item["tip"][2]) < z_plinth - EPS or not item["valid"]:
                    continue
                batch.append(item)
            if not batch:
                continue
            penetrated = np.asarray(
                tool_body_penetrates(
                    mesh,
                    [item["tip"] for item in batch],
                    [item["axis"] for item in batch],
                    config,
                    [theta_emit] * len(batch),
                ),
                dtype=bool,
            )
            for item, blocked in zip(batch, penetrated):
                if not blocked:
                    item["accepted"] = True
            pending = [item for item in pending if not item["accepted"]]
        unreachable_points += sum(1 for item in flat if not item["accepted"])

        # 3. Runs of consecutive accepted points, per polyline.  A rejected
        #    point ends a run; runs are never bridged by a straight cut.
        for line in polylines:
            runs: list[list[dict[str, Any]]] = []
            current: list[dict[str, Any]] = []
            for point in line:
                item = pose_of[id(point)]
                if not item["accepted"]:
                    if current:
                        runs.append(current)
                        current = []
                    continue
                current.append(item)
            if current:
                runs.append(current)

            for run in runs:
                first = run[0]
                entry = entry_moves(
                    {"theta": theta_emit, "rs": first["rs"], "zs": first["zs"], "phi": first["phi"]},
                    mesh,
                    config,
                    clearance_target,
                    diagnostics,
                )
                if not entry:
                    unreachable_points += len(run)
                    continue
                for move in entry:
                    link(move)
                for item in run:
                    joints.append(
                        _joint(item["rs"], theta_emit, item["zs"], item["phi"], config, diagnostics)
                    )
                    rapid.append(False)
                    stages.append("finishing")
                last = run[-1]
                exit_ = exit_moves(
                    last["tip"], last["phi"], theta_emit, mesh, config, clearance_target, diagnostics
                )
                if not exit_:
                    # The run cannot be left safely; drop its end point (counted
                    # unreachable) rather than driving the body back through.
                    joints.pop()
                    rapid.pop()
                    stages.pop()
                    unreachable_points += 1
                    continue
                for move in exit_:
                    link(move)

        # Reposition to the positive clearance plane as a link, not a rapid:
        # after a negative-r_s slice this segment crosses the axis, and a rapid
        # that starts on the far-side clearance radius would momentarily pass
        # inside the required radial clearance.
        joints.append(_joint(clearance_target, theta_emit, safe_zs, 0.0, config, diagnostics))
        rapid.append(False)
        stages.append("finishing_link")

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

    if any(diag.severity == "error" for diag in collector.as_list()):
        # An out-of-bounds joint or stock already makes the path unproducible;
        # don't spend minutes resampling (and trip the frame cap) to say so.
        return ToolpathResult(
            frames=[],
            diagnostics=collector.as_list(),
            preset=preset,
            unreachable_percent=unreachable_percent,
        )

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
            "theta": frame["theta_s"],
        }
        for frame, stage in zip(frames, stages)
        if stage == "finishing" and not frame["is_rapid"]
    ]
    for diag in detect_gouges(mesh, cutting_poses, cfg):
        collector.extend([diag])

    # Feed-direction diagnostics over every cutting segment (roughing theta
    # passes and finishing cuts). Link moves and rapids are not cuts.
    broadside_length = 0.0
    cutting_length = 0.0
    first_offending: int | None = None
    for index in range(1, len(frames)):
        current = frames[index]
        if current["is_rapid"] or current["stage"] not in ("roughing", "finishing"):
            continue
        previous = frames[index - 1]
        direction = np.asarray(current["tip_xyz_wax"]) - np.asarray(
            previous["tip_xyz_wax"]
        )
        length = float(np.linalg.norm(direction))
        if length <= 1e-12:
            continue
        pose = tool_model.tool_pose(
            current["tip_xyz_wax"], current["theta_s"], current["phi"], cfg
        )
        kind = tool_model.feed_class(direction, pose, cfg)
        cutting_length += length
        if kind == "broadside":
            broadside_length += length
            if first_offending is None:
                first_offending = index
    if broadside_length > 0.0 and cutting_length > 0.0:
        fraction = broadside_length / cutting_length
        collector.add(
            "BLADE_BROADSIDE_FEED",
            "warning",
            (
                f"{100.0 * fraction:.2f}% of cutting path length feeds the 6 mm "
                f"blade face broadside; first offending frame {first_offending}"
            ),
            value=100.0 * fraction,
            frame=first_offending,
        )

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

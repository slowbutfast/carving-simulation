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
    beta = math.atan2(n_r, n_z)
    # A face whose outward normal turns away from the cut (+n_r) wants the flank
    # leaning forward; one that faces the other way (an undercut) wants it
    # leaning back, and is never clamped across zero.  There is no separate
    # branch for downward faces: beta < 0 covers them and is judged by the same
    # clearance band, so a reachable overhang is not thrown away.
    if beta >= 0.0:
        preferred = max(0.0, beta - alpha)
    else:
        preferred = min(0.0, beta + alpha)
    phi = min(max(preferred, phi_lo), phi_hi)
    reachable = abs(beta - phi) <= (math.pi / 2 - alpha) + EPS
    return phi, reachable


def _melt_kerf_offset(config: Mapping[str, Any]) -> float:
    """Contact-Point -> Tip-Apex standoff: ``tip_radius + melt_kerf``."""

    tool = config["tool"]
    return float(tool["tip_radius_mm"]) + float(tool["melt_kerf_mm"])


def cutter_location(
    point_xyz: Sequence[float],
    n_r: float,
    n_z: float,
    theta: float,
    config: Mapping[str, Any],
) -> np.ndarray:
    """Tip apex for a Contact-Point on the surface at ``theta``.

    The apex sits one standoff (``tip_radius + melt_kerf``) out along the
    *true* outward normal ``n_r e_r + n_z e_z``.  The normal is never snapped
    to pure radial or vertical: on a slope that would place the apex off the
    CL, and the cut would no longer follow the section contour.
    """

    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    normal = n_r * e_r + n_z * np.array([0.0, 0.0, 1.0])
    return np.asarray(point_xyz, dtype=np.float64) + normal * _melt_kerf_offset(config)


def tool_body_penetrates(
    mesh: trimesh.Trimesh,
    apexes: Sequence[Sequence[float]],
    axes: Sequence[Sequence[float]],
    config: Mapping[str, Any],
) -> np.ndarray:
    """Vectorised test: does the heated tool body intersect the mesh?

    Stations ``t in {0.25, 0.5, 0.75, 1.0} * engaged`` are walked back from each
    apex along its axis.  At station ``t`` the flank point is the axis point
    plus eight ring points at radius ``tip_radius + t * tan(alpha)`` in the
    plane perpendicular to the axis (the melt kerf is deliberately omitted: it
    is cut tolerance, not tool steel).

    "Penetrates" is ``mesh.contains(...)`` for any of those points, which is the
    one inside/outside authority here (``trimesh.nearest.signed_distance`` is
    positive inside and agrees).  All points for all poses go through a single
    ``contains`` call, so the caller can batch a whole slice.
    """

    apexes = np.atleast_2d(np.asarray(apexes, dtype=np.float64))
    axes = np.atleast_2d(np.asarray(axes, dtype=np.float64))
    if len(apexes) == 0:
        return np.zeros(0, dtype=bool)
    lengths = np.linalg.norm(axes, axis=1)
    axes = axes / np.where(lengths == 0.0, 1.0, lengths)[:, None]

    tool = config["tool"]
    engaged = float(tool["engaged_length_mm"])
    tip_radius = float(tool["tip_radius_mm"])
    tan_alpha = math.tan(math.radians(float(tool["cone_half_angle_deg"])))
    fractions = (0.25, 0.5, 0.75, 1.0)
    angles = np.arange(8) * (math.pi / 4.0)

    # A stable perpendicular basis per pose (never parallel to the axis).
    helper = np.tile(np.array([0.0, 0.0, 1.0]), (len(axes), 1))
    almost_parallel = np.abs(axes @ np.array([0.0, 0.0, 1.0])) > 0.9
    helper[almost_parallel] = np.array([1.0, 0.0, 0.0])
    e1 = np.cross(axes, helper)
    e1 /= np.linalg.norm(e1, axis=1)[:, None]
    e2 = np.cross(axes, e1)

    points: list[np.ndarray] = [apexes]
    for fraction in fractions:
        station = engaged * fraction
        radius = tip_radius + station * tan_alpha
        base = apexes - axes * station
        for angle in angles:
            points.append(base + radius * (math.cos(angle) * e1 + math.sin(angle) * e2))
    # Each block is (poses, 3); stacking gives one row per (sample, pose).
    inside = np.asarray(mesh.contains(np.concatenate(points, axis=0)), dtype=bool)
    return inside.reshape(len(points), len(apexes)).any(axis=0)


def detect_gouges(
    mesh: trimesh.Trimesh,
    poses: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[Diagnostic]:
    """Flag cutting poses whose heated body penetrates the target mesh.

    Delegates the geometry to :func:`tool_body_penetrates`, so the pre-filter in
    ``build_finishing`` and the reported diagnostic cannot disagree.  The text
    keeps the offending station and the margin by which the flank is buried.
    """

    tool = config["tool"]
    engaged = float(tool["engaged_length_mm"])
    tip_radius = float(tool["tip_radius_mm"])
    tan_alpha = math.tan(math.radians(float(tool["cone_half_angle_deg"])))
    stations = [engaged * fraction for fraction in (0.25, 0.5, 0.75, 1.0)]
    collector = DiagnosticCollector()
    for pose in poses:
        apex = np.asarray(pose["tip_xyz_wax"], dtype=np.float64)
        axis = np.asarray(pose["tool_axis_wax"], dtype=np.float64)
        if not bool(tool_body_penetrates(mesh, [apex], [axis], config)[0]):
            continue
        # Locate the worst station for the message (signed distance is positive
        # inside, so the deepest burial is the largest positive value).
        lengths = float(np.linalg.norm(axis)) or 1.0
        unit = axis / lengths
        signed = np.asarray(
            mesh.nearest.signed_distance(
                np.asarray([apex - unit * t for t in stations], dtype=np.float64)
            ),
            dtype=np.float64,
        )
        index = int(np.argmax(signed))
        flank = tip_radius + stations[index] * tan_alpha
        collector.add(
            "GOUGE",
            "warning",
            f"tool flank penetrates the target at {np.round(apex - unit * stations[index], 3).tolist()}",
            value=float(flank + float(signed[index])),
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


def _body_clear(
    mesh: trimesh.Trimesh,
    apexes: Sequence[np.ndarray],
    axes: Sequence[np.ndarray],
    config: Mapping[str, Any],
) -> bool:
    """True when every sampled pose in the batch clears the mesh."""

    if len(apexes) == 0:
        return True
    return not bool(np.asarray(tool_body_penetrates(mesh, apexes, axes, config)).any())


def _sample_poses(
    apexes: list[np.ndarray],
    axis: np.ndarray,
) -> list[np.ndarray]:
    """Sample a list of apexes every 1 mm, keeping the pitch (axis) constant."""

    samples: list[np.ndarray] = []
    for first, second in zip(apexes, apexes[1:]):
        steps = max(1, int(math.ceil(float(np.linalg.norm(second - first)))))
        for index in range(steps):
            samples.append(first + (second - first) * (index / steps))
    if apexes:
        samples.append(apexes[-1])
    return samples


def _clear_line(length: float, start: np.ndarray, direction: np.ndarray) -> list[np.ndarray]:
    """A straight line of ``length`` mm from ``start`` along ``direction``."""

    return [start + direction * s for s in np.arange(0.0, max(length, 0.0) + 1e-9, 1.0)]


def exit_moves(
    apex: np.ndarray | Sequence[float],
    phi: float,
    theta: float,
    mesh: trimesh.Trimesh,
    config: Mapping[str, Any],
    clearance_target: float,
    collector: DiagnosticCollector,
) -> list[dict[str, float]]:
    """Non-rapid exit from a pitched cut: clear the body, re-pitch, then rise.

    With ``u = -sin(phi) e_r - cos(phi) e_z`` a slide along ``-u`` moves the
    apex ``+s sin(phi)`` radially and ``+s cos(phi)`` upward, so candidate A
    reaches ``clearance_target`` at ``s = (clear - r_apex) / sin(phi)`` when
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

    apex = np.asarray(apex, dtype=np.float64)
    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    # Tool axis wrist -> apex.  As in kinematics.forward_kinematics (u(phi) =
    # -sin(phi) e_r - cos(phi) e_z), +phi tilts the tip *inward*, so with a
    # negative phi the axis leans outboard and the body runs inboard.
    axis = -math.sin(phi) * e_r - np.array([0.0, 0.0, math.cos(phi)])
    height_stock = float(config["stock"]["H_stock_mm"])
    clearance = float(config["stock"].get("retract_clearance_mm", 6.0))
    safe_z = height_stock + clearance
    p = float(config["pivot_to_tip_mm"])
    r_apex = float(math.hypot(apex[0], apex[1]))

    # The apex of a CL pose sits ``tip_r + kerf`` off the surface, i.e. its
    # *heater* is already in contact: a cone flank opens back towards the wrist
    # and lies on the face by construction.  Both candidates therefore skip the
    # first millimetre (that cut has just been made) and must clear from there.
    candidates: list[list[np.ndarray]] = []
    # Candidate 0: horizontal +e_r at constant phi.  Under a wide overhang
    # both the -u slide and a vertical lift rise into the slab, but pulling
    # straight out at the cut height stays under it.  This is tried first.
    if clearance_target > r_apex:
        candidates.append(
            _clear_line(
                clearance_target - r_apex,
                apex + e_r * min(1.0, clearance_target - r_apex),
                e_r,
            )
        )
    if math.sin(phi) > 0.05:
        # Leaving the cut is -u; with u = -sin(phi) e_r - cos(phi) e_z the
        # radius of the apex and of every body point grows by s sin(phi).
        length = max(0.0, (clearance_target - r_apex) / math.sin(phi))
        candidates.append(_clear_line(length, apex - axis * min(1.0, length), -axis))
    lift = max(0.0, safe_z - float(apex[2]))
    start = apex + np.array([0.0, 0.0, min(1.0, lift)])
    top = apex + np.array([0.0, 0.0, lift])
    radial = max(0.0, clearance_target - float(math.hypot(top[0], top[1])))
    candidates.append(
        _clear_line(max(0.0, lift - 1.0), start, np.array([0.0, 0.0, 1.0]))
        + _clear_line(radial, top, e_r)[1:]
    )

    # Candidate A ends pitched at the clearance radius; it re-pitches to
    # vertical there, sinking by ``p (1 - cos phi)``, so that drop must stay
    # clear.  If it buries, candidate B (which ends on the safe plane, clear of
    # everything) is used instead.
    upright = np.array([0.0, 0.0, -1.0])
    for candidate in candidates:
        samples = _sample_poses(candidate, axis)
        if not _body_clear(mesh, samples, [axis] * len(samples), config):
            continue
        clear = candidate[-1]
        r_clear = max(float(math.hypot(clear[0], clear[1])), clearance_target)
        z_clear = float(clear[2])
        reorient_z = z_clear + p * (1.0 - math.cos(phi))
        reorient = [
            e_r * r_clear + np.array([0.0, 0.0, z])
            for z in np.linspace(z_clear, reorient_z, 8)
        ]
        if not _body_clear(mesh, reorient, [upright] * len(reorient), config):
            continue
        return [
            _joint(r_clear, theta, z_clear, phi, config, collector),
            _joint(r_clear, theta, reorient_z, 0.0, config, collector),
            _joint(clearance_target, theta, safe_z, 0.0, config, collector),
        ]
    collector.add(
        "UNREACHABLE_UNDERCUT_AREA",
        "warning",
        f"no clear exit from the pitched cut at {np.round(apex, 3).tolist()}",
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
    along ``-u`` onto the Contact-Point apex.  All non-rapid links.
    """

    _ = mesh
    theta = float(first["theta"])
    rs = float(first["rs"])
    zs = float(first["zs"])
    phi = float(first["phi"])
    height_stock = float(config["stock"]["H_stock_mm"])
    clearance = float(config["stock"].get("retract_clearance_mm", 6.0))
    safe_z = height_stock + clearance
    p = float(config["pivot_to_tip_mm"])
    descend_z = zs + p * (1.0 - math.cos(phi))
    return [
        _joint(clearance_target, theta, safe_z, 0.0, config, collector),
        _joint(clearance_target, theta, descend_z, 0.0, config, collector),
        _joint(clearance_target, theta, descend_z, phi, config, collector),
        _joint(rs, theta, zs, phi, config, collector),
    ]


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

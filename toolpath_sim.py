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

def _vkey(point: Sequence[float], quantum: float = 1e-5) -> tuple[int, int, int]:
    """Hash a slice endpoint; ``mesh_plane`` reuses vertex positions exactly."""

    return (
        int(round(float(point[0]) / quantum)),
        int(round(float(point[1]) / quantum)),
        int(round(float(point[2]) / quantum)),
    )


def _sample_between(first: dict[str, Any], second: dict[str, Any], t: float) -> dict[str, Any]:
    """Linear interpolation of one polyline sample (``t`` in ``[0, 1]``)."""

    keys = ("radius", "z", "n_r", "n_z")
    values = {key: first[key] + t * (second[key] - first[key]) for key in keys}
    return {
        "point": np.asarray(first["point"] + t * (second["point"] - first["point"])),
        "radius": float(values["radius"]),
        "z": float(values["z"]),
        "n_r": float(values["n_r"]),
        "n_z": float(values["n_z"]),
    }


def _resample_piece(
    piece: list[dict[str, Any]], step: float, clip_floor: float | None = None
) -> list[dict[str, Any]]:
    """Resample one connected piece at arc-length ``step`` (mm).

    Endpoints are kept as-is so neighbouring slices stay aligned, and every
    inserted point interpolates ``radius``/``z``/normal along its source segment,
    so a resampled sample never leaves the section plane.
    """

    out: list[dict[str, Any]] = [dict(piece[0])]
    carry = 0.0
    for first, second in zip(piece, piece[1:]):
        length = math.hypot(second["radius"] - first["radius"], second["z"] - first["z"])
        if length <= EPS:
            continue
        # ``carry`` is the distance already covered since the last sample.
        travelled = step - carry
        while travelled < length - EPS:
            out.append(_sample_between(first, second, travelled / length))
            travelled += step
        carry = max(0.0, length - (travelled - step))
        if carry >= step - EPS:
            carry -= step
    tail = dict(piece[-1])
    ends_at_clip = clip_floor is not None and abs(tail["z"] - clip_floor) <= 1e-6
    if len(out) > 1 and ends_at_clip:
        gap = math.hypot(
            tail["radius"] - out[-1]["radius"], tail["z"] - out[-1]["z"]
        )
        if gap < 0.5 * step:
            # A stub shorter than half a step only exists because the clip cut
            # the chain there; keep it only if it carries a real length.
            out.pop()
    out.append(tail)
    return out


def _ordered_segment_ids(
    records: list[dict[str, Any]],
) -> list[list[int]]:
    """Chain mesh_plane segments into connected runs by shared endpoints.

    Plain dict adjacency keyed by :func:`_vkey`; no networkx.  Open chains start
    at a degree-1 endpoint (all real slices are open), and whatever is left is
    walked from an arbitrary endpoint so closed loops are not dropped.
    """

    adjacency: dict[tuple[int, int, int], list[int]] = {}
    for segment_id, record in enumerate(records):
        adjacency.setdefault(record["ka"], []).append(segment_id)
        adjacency.setdefault(record["kb"], []).append(segment_id)

    visited: set[int] = set()

    def walk(start_key: tuple[int, int, int], first: int) -> list[int]:
        order: list[int] = []
        key = start_key
        segment_id: int | None = first
        while segment_id is not None and segment_id not in visited:
            visited.add(segment_id)
            order.append(segment_id)
            record = records[segment_id]
            key = record["kb"] if record["ka"] == key else record["ka"]
            following = [s for s in adjacency.get(key, []) if s not in visited]
            segment_id = following[0] if following else None
        return order

    chains: list[list[int]] = []
    for key in sorted(k for k, ids in adjacency.items() if len(ids) == 1):
        for segment_id in adjacency[key]:
            if segment_id not in visited:
                chains.append(walk(key, segment_id))
    for segment_id, record in enumerate(records):
        if segment_id not in visited:
            chains.append(walk(record["ka"], segment_id))
    return chains


def _is_proper_chain(records: list[dict[str, Any]], order: list[int]) -> bool:
    """True when every interior vertex of the run joins exactly two segments."""

    keys = [records[order[0]]["ka"]]
    for segment_id in order:
        record = records[segment_id]
        keys.append(record["kb"] if record["ka"] == keys[-1] else record["ka"])
    counts: dict[tuple[int, int, int], int] = {}
    for segment_id in order:
        for key in (records[segment_id]["ka"], records[segment_id]["kb"]):
            counts[key] = counts.get(key, 0) + 1
    return all(counts[key] == 2 for key in keys[1:-1])


def _chain_model(
    segments: list[tuple[np.ndarray, np.ndarray]],
    quantum: float = 1e-4,
) -> list[list[tuple[int, int, int]]]:
    """Chain 2D segments by shared endpoints, merging vertices within ``quantum``.

    This is the fallback for a slice that lands on a coplanar face and meets
    itself: coplanar records are collapsed onto the section plane, collinear
    overlaps are rendered as isolated segments, and the merged keys reconnect
    them so a proper contour is recovered.
    """

    keys: dict[tuple[int, int], int] = {}
    flat: list[list[int]] = []
    merged: list[np.ndarray] = []
    for point_a, point_b in segments:
        pair = []
        for point in (point_a, point_b):
            key = (int(round(float(point[0]) / quantum)), int(round(float(point[1]) / quantum)))
            if key not in keys:
                keys[key] = len(merged)
                merged.append(np.asarray(point, dtype=np.float64))
            pair.append(keys[key])
        if pair[0] != pair[1]:
            flat.append(pair)

    adjacency: dict[int, list[int]] = {}
    for segment_id, pair in enumerate(flat):
        for key in pair:
            adjacency.setdefault(key, []).append(segment_id)
    visited: set[int] = set()

    def walk(start: int, first: int) -> list[tuple[int, int, int]]:
        # Each step is (segment id, entry key, exit key); ties are emitted at
        # the *exact* merged position whenever a key is first stored.
        order: list[tuple[int, int, int]] = []
        key = start
        segment_id: int | None = first
        while segment_id is not None and segment_id not in visited:
            visited.add(segment_id)
            first_key, second_key = flat[segment_id]
            exit_key = second_key if first_key == key else first_key
            order.append((segment_id, key, exit_key))
            key = exit_key
            following = [s for s in adjacency.get(key, []) if s not in visited]
            segment_id = following[0] if following else None
        return order

    _ = merged

    chains: list[list[tuple[int, int, int]]] = []
    for key in sorted(k for k, ids in adjacency.items() if len(ids) == 1):
        for segment_id in adjacency[key]:
            if segment_id not in visited:
                chains.append(walk(key, segment_id))
    for segment_id in range(len(flat)):
        if segment_id not in visited:
            chains.append(walk(flat[segment_id][0], segment_id))
    return chains


def _chain_points(records: list[dict[str, Any]], order: list[int]) -> list[dict[str, Any]]:
    """Vertex list for one ordered run of segments, carrying its face normal."""

    points: list[dict[str, Any]] = []
    for position, segment_id in enumerate(order):
        record = records[segment_id]
        if position == 0:
            first, second = record["a"], record["b"]
            point_key = record["kb"]
        elif record["ka"] == point_key:
            first, second = record["a"], record["b"]
            point_key = record["kb"]
        else:
            first, second = record["b"], record["a"]
            point_key = record["ka"]
        normal = {"n_r": record["n_r"], "n_z": record["n_z"]}
        if position == 0:
            points.append({"point": np.asarray(first, dtype=np.float64), **normal})
        points.append({"point": np.asarray(second, dtype=np.float64), **normal})
    return points


def _clip_polyline(
    points: list[dict[str, Any]], z_lo: float, z_hi: float
) -> list[list[dict[str, Any]]]:
    """Clip to ``radius >= 0`` and ``z in [z_lo, z_hi]``, splitting at the edge.

    Walking is done in *section order*, not in ``(z, radius)`` order, so an
    overhang between two accepted points is never bridged by a chord.
    """

    def inside(value: dict[str, Any]) -> bool:
        x, y, z = (float(component) for component in value["point"][:3])
        return x * x + y * y >= 0.0 and z_lo - 1e-9 <= z <= z_hi + 1e-9

    pieces: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for value in points:
        if inside(value):
            current.append(value)
            continue
        # Leaving the band: close the piece on this boundary sample.
        if current:
            current.append(value)
            pieces.append(current)
            current = []
    if current:
        pieces.append(current)
    return [piece for piece in pieces if len(piece) >= 2]


def _split_by_normal(piece: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split a chain wherever the intersected face's normal changes.

    A resampled sample interpolates one face's normal, so a cut never carries
    a blended normal across a sharp edge (a box corner, a wall-to-top fillet).
    The corner is snapped to the *next* face exactly and re-normalised, because
    the next cut's Contact-Point offset (and ``finishing_phi``) are computed from
    that point's normal.  Returns ``(island, run)`` lists: a new island starts
    at a segment whose two faces are mutually perpendicular (a real edge), while
    a change within a smooth band stays in the same island.
    """

    if not piece:
        return []
    islands: list[list[list[dict[str, Any]]]] = [[[dict(piece[0])]]]
    for value in piece[1:]:
        previous = islands[-1][-1][-1]
        d_r = value["n_r"] - previous["n_r"]
        d_z = value["n_z"] - previous["n_z"]
        if abs(d_r) <= 1e-6 and abs(d_z) <= 1e-6:
            islands[-1][-1].append(dict(value))
            continue
        corner = dict(value)
        is_edge = (
            abs(d_r) > 0.35 or abs(d_z) > 0.35
        )
        if is_edge:
            islands[-1][-1][-1] = dict(corner)
            islands.append([[corner, dict(corner)]])
        else:
            islands[-1][-1][-1] = dict(corner)
            islands[-1].append([corner, dict(corner)])
    return [run for island in islands for run in island]


def _drop_reversals(piece: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split a chain wherever it steps back along its own face.

    Trimesh can meet a triangle twice on the slice plane, which makes the chain
    double back over a face.  On a run whose points share one face, ``radius``
    is not monotone along any contour, so a step *back* in ``z`` on that face
    (the top face's ``r=15 -> r=0`` tail, or the far wall's ``z=50 -> z=30``
    leg) is that overlap, not a real second pass.  Returns the ascending runs.
    """

    if not piece:
        return []
    runs: list[list[dict[str, Any]]] = [[dict(piece[0])]]
    for value in piece[1:]:
        if float(value["point"][2]) < float(runs[-1][-1]["point"][2]) - 1e-9:
            runs.append([dict(value)])
        else:
            runs[-1].append(dict(value))
    return [run for run in runs if len(run) >= 2]


def _height_in_slice(piece: list[dict[str, Any]], normal: np.ndarray) -> float:
    """Mean in-plane ``z``: the normal's z component discriminates a cut plane."""

    return float(normal[2]) * sum(float(v["point"][2]) for v in piece) / len(piece)


def _same_contact(run: list[dict[str, Any]], runs: list[list[dict[str, Any]]]) -> bool:
    """True when ``run`` is the same contacts as one already queued.

    Every point's ``(radius, z, n_r, n_z)`` must match some earlier run, so a
    duplicate face walk (the coplanar-face tie) is skipped while a genuinely
    new face is kept.
    """

    signature = {
        (
            round(float(math.hypot(v["point"][0], v["point"][1])), 3),
            round(float(v["point"][2]), 3),
            round(v["n_r"], 3),
            round(v["n_z"], 3),
        )
        for v in run
    }
    if not signature:
        return True
    for earlier in runs:
        other = {
            (
                round(float(math.hypot(v["point"][0], v["point"][1])), 3),
                round(float(v["point"][2]), 3),
                round(v["n_r"], 3),
                round(v["n_z"], 3),
            )
            for v in earlier
        }
        if signature <= other:
            return True
    return False


def _monotone_runs(piece: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split a chain into stretches where ``z`` never decreases.

    Returns one piece when the chain is already monotone; otherwise one piece
    per climb, each starting on the point where the previous one peaked.
    """

    pieces: list[list[dict[str, Any]]] = [[piece[0]]]
    for value in piece[1:]:
        if float(value["point"][2]) >= float(pieces[-1][-1]["point"][2]) - 1e-9:
            pieces[-1].append(value)
        else:
            pieces.append([pieces[-1][-1], value])
    return [run for run in pieces if len(run) >= 2]


def _orient_bottom_to_top(piece: list[dict[str, Any]], normal: np.ndarray) -> list[dict[str, Any]]:
    """Orient a contour so its *cut plane* runs bottom-to-top.

    For a cut plane (``abs(n_z) > 0.5``, e.g. the top face) the walk direction
    must make ``z`` non-decreasing.  Perpendicular planes contain the axial
    direction, so their chains are reversed only if they run downward overall;
    a contour that legitimately tops out on the far wall is left alone.
    """

    signs = [
        float(piece[k + 1]["point"][2] - piece[k]["point"][2])
        for k in range(len(piece) - 1)
    ]
    if abs(float(normal[2])) > 0.5:
        descending = sum(1 for s in signs if s < -1e-9)
        ascending = sum(1 for s in signs if s > 1e-9)
        if descending > ascending:
            piece.reverse()
    elif float(piece[-1]["point"][2]) < float(piece[0]["point"][2]):
        piece.reverse()
    return piece


def _section_records(
    segments: np.ndarray,
    faces: np.ndarray,
    mesh: trimesh.Trimesh,
    e_r: np.ndarray,
) -> list[dict[str, Any]]:
    """One record per ``mesh_plane`` segment: endpoints, keys and planar normal."""

    face_normals = np.asarray(mesh.face_normals, dtype=np.float64)
    records: list[dict[str, Any]] = []
    for index in range(len(segments)):
        point_a = segments[index, 0]
        point_b = segments[index, 1]
        key_a, key_b = _vkey(point_a), _vkey(point_b)
        if key_a == key_b:
            continue
        if index < len(faces):
            face_normal = face_normals[int(faces[index])]
            raw_r = float(face_normal @ e_r)
            raw_z = float(face_normal[2])
            planar = math.hypot(raw_r, raw_z)
            if planar < 1e-6:
                # Tangential face: no planar normal, use the section tangent.
                delta_r = float(point_b @ e_r - point_a @ e_r)
                delta_z = float(point_b[2] - point_a[2])
                planar = max(math.hypot(delta_r, delta_z), EPS)
                raw_r, raw_z = -delta_z, delta_r
            n_r, n_z = raw_r / planar, raw_z / planar
        else:  # pragma: no cover - mesh_plane always pairs segments and faces
            n_r, n_z = 0.0, 1.0
        records.append(
            {"a": point_a, "b": point_b, "ka": key_a, "kb": key_b, "n_r": n_r, "n_z": n_z}
        )
    return records


def _chain_runs(records: list[dict[str, Any]], e_r: np.ndarray) -> list[list[dict[str, Any]]]:
    """Chain records into vertex runs, falling back to a merged 2D model.

    A slice that lies on a coplanar face meets itself, so plain endpoint
    matching cannot always stitch it.  Those runs are re-chained from their 2D
    image with vertices merged within a quantum (:func:`_chain_model`).
    """

    runs: list[list[dict[str, Any]]] = []
    for order in _ordered_segment_ids(records):
        if _is_proper_chain(records, order):
            runs.append(_chain_points(records, order))
            continue
        flat = [
            (
                np.array([float(records[s]["a"] @ e_r), float(records[s]["a"][2])]),
                np.array([float(records[s]["b"] @ e_r), float(records[s]["b"][2])]),
            )
            for s in order
        ]
        for flat_order in _chain_model(flat):
            points: list[dict[str, Any]] = []
            for position, entry, exit_ in flat_order:
                record = records[order[position]]
                # ``flat[position][0]`` is the near endpoint when entry is its
                # stored key, otherwise it is the far endpoint.
                near = flat[position][0]
                far = flat[position][1]
                entering = near if _pair_key(near) == entry else far
                leaving = near if _pair_key(near) == exit_ else far
                points.append(
                    {
                        "point": np.array(
                            [entering[0] * e_r[0], entering[0] * e_r[1], entering[1]]
                        ),
                        "n_r": record["n_r"],
                        "n_z": record["n_z"],
                    }
                )
                points.append(
                    {
                        "point": np.array(
                            [leaving[0] * e_r[0], leaving[0] * e_r[1], leaving[1]]
                        ),
                        "n_r": record["n_r"],
                        "n_z": record["n_z"],
                    }
                )
            runs.append(points)
    return runs


def _pair_key(point: np.ndarray, quantum: float = 1e-4) -> tuple[int, int]:
    return (int(round(float(point[0]) / quantum)), int(round(float(point[1]) / quantum)))


def _normal_runs(run: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split a run where a new face starts after a change of normal.

    A resampled sample interpolates one face's normal, so a cut never carries a
    blended normal across a sharp edge.  The corner is snapped to the *next*
    face exactly and re-normalised, because the next cut's Contact-Point offset
    and ``finishing_phi`` are computed from that point's normal.
    """

    if not run:
        return []
    pieces: list[list[dict[str, Any]]] = [[dict(run[0])]]
    for value in run[1:]:
        previous = pieces[-1][-1]
        if abs(previous["n_r"] - value["n_r"]) <= 1e-3 and abs(previous["n_z"] - value["n_z"]) <= 1e-3:
            pieces[-1].append(dict(value))
            continue
        pieces[-1][-1] = dict(value)
        pieces.append([dict(value)])
    return pieces


def _axially_monotone(piece: list[dict[str, Any]]) -> bool:
    """True when ``z`` never decreases along the run (within 1e-9)."""

    return all(
        float(second["point"][2]) >= float(first["point"][2]) - 1e-9
        for first, second in zip(piece, piece[1:])
    )


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
    (multi-valued overhangs are preserved); points with ``radius < 0`` are the
    ``theta + pi`` half and are dropped.

    ``mesh_plane`` segments are chained by shared endpoints into connected
    polylines and clipped to ``z in [z_min + 1.5, z_max]`` (the plinth foot is
    seating geometry).  A polyline is a run of consecutive points that are
    axially monotone *and* share the same intersected face, so consecutive
    points of one polyline may always be joined by a cut.  At a sharp edge the
    first face's run ends on the corner and the next face's run starts there
    with its own normal - the two runs must not be bridged except through an
    explicit link move.

    Returns polylines oriented bottom-to-top and resampled at arc-length
    ``step``.  Each point carries ``point`` (wax XYZ), ``radius``, ``z`` and
    ``n_r``/``n_z`` - the intersected triangle's outward normal expanded in
    ``(e_r, e_z)`` and re-normalised, which feeds :func:`finishing_phi`
    directly.
    """

    normal = np.array([-math.sin(theta), math.cos(theta), 0.0])
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
    e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
    e_theta = np.array([-math.sin(theta), math.cos(theta), 0.0])
    step = max(float(step), 0.1)
    z_lo = float(z_min) + 1.5
    # ``mesh_plane`` returns each segment inside its triangle, which sits a few
    # microns off the exact plane (the face normal is not exactly e_theta), so
    # reproject every point onto the half-plane: radius and z are unchanged and
    # the contour lies exactly on the slice azimuth.
    def on_plane(point: np.ndarray) -> np.ndarray:
        point = np.asarray(point, dtype=np.float64)
        radial = float(point[0]) * e_r[0] + float(point[1]) * e_r[1]
        return radial * e_r + np.array([0.0, 0.0, float(point[2])])

    for index in range(len(segments)):
        segments[index, 0] = on_plane(segments[index, 0])
        segments[index, 1] = on_plane(segments[index, 1])

    records = _section_records(segments, faces, mesh, e_r)
    if not records:
        return []

    runs: list[list[dict[str, Any]]] = []
    for raw in _chain_runs(records, e_r):
        for piece in _clip_polyline(raw, z_lo, float(z_max)):
            if len(piece) < 2:
                continue
            # A cut plane (the top face) is walked with non-decreasing z; a
            # flank that contains the axis is oriented by its overall rise.
            if abs(float(piece[0]["n_z"])) > 0.5:
                piece = _orient_bottom_to_top(
                    piece, np.array([0.0, 0.0, float(piece[0]["n_z"])])
                )
            elif float(piece[-1]["point"][2]) < float(piece[0]["point"][2]):
                piece = list(reversed(piece))
            if max(float(v["point"][2]) for v in piece) <= z_lo:
                continue
            for face_run in _normal_runs(piece):
                for run in _drop_reversals(face_run):
                    if len(run) < 2:
                        continue
                    # A run that ends where another run begins, descending
                    # along the same face, is the same contact seen twice (the
                    # top face re-walked toward the axis, or the far wall's
                    # back leg).  One pass per distinct contact.
                    start = run[0]
                    duplicate = any(
                        abs(earlier[-1]["point"][0] - start["point"][0]) < 1e-6
                        and abs(earlier[-1]["point"][2] - start["point"][2]) < 1e-6
                        and abs(earlier[-1]["n_r"] - start["n_r"]) < 1e-3
                        and abs(earlier[-1]["n_z"] - start["n_z"]) < 1e-3
                        for earlier in runs
                    )
                    if duplicate or _same_contact(run, runs):
                        continue
                    runs.append(run)

    finished: list[list[dict[str, Any]]] = []
    for run in runs:
        for value in run:
            point = np.asarray(value["point"], dtype=np.float64)
            value["point"] = point
            value["radius"] = float(math.hypot(point[0], point[1]))
            value["z"] = float(point[2])
        finished.append(_resample_piece(run, step, z_lo))

    finished.sort(key=lambda line: (line[0]["z"], line[0]["radius"]))
    return finished


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

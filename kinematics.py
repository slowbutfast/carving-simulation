"""Single-source-of-truth 4-DOF kinematics for the thermal wax carver.

Machine frame (right-handed, ``mm``, ``+Z`` up):
    origin (0, 0, 0) at the center of the rotary platter top surface
    theta = 0 points along +X toward the Z-column / radial gantry

Wax frame:
    theta_s = theta = theta_ring - theta_platter (default single platter:
    theta_ring = 0 -> theta = -theta_platter); the tool azimuth is theta_s.

Joint symbols:
    r      radial carriage datum (mm) measured outward from the platter axis
    theta  rotary coordinate (rad)
    h      arm datum height above the platter top (mm)
    phi    wrist pitch (rad), +phi tilts the tip inward toward -r

All trigonometric work for the viewer lives here. ``tip_xyz_wax`` and
``tool_axis_wax`` are emitted per frame so the Three.js rig performs none.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

MM = 1.0
DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi

CONFIG_PATH = Path(__file__).resolve().with_name("machine_config.json")


# ---------------------------------------------------------------------------
# Structured diagnostics
# ---------------------------------------------------------------------------


@dataclass
class Diagnostic:
    """Structured, machine-readable diagnostic shared by every backend stage."""

    code: str
    severity: str
    message: str
    axis: str | None = None
    value: float | None = None
    frame: int | None = None
    count: int = 1

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "count": self.count,
        }
        if self.axis is not None:
            payload["axis"] = self.axis
        if self.value is not None:
            payload["value"] = float(self.value)
        if self.frame is not None:
            payload["frame"] = int(self.frame)
        return payload


class DiagnosticCollector:
    """Deduplicates repeated diagnostics while keeping occurrence counts."""

    def __init__(self) -> None:
        self._items: dict[str, Diagnostic] = {}
        self._order: list[str] = []

    def add(
        self,
        code: str,
        severity: str,
        message: str,
        *,
        axis: str | None = None,
        value: float | None = None,
        frame: int | None = None,
    ) -> Diagnostic:
        key = f"{code}:{axis or ''}"
        existing = self._items.get(key)
        if existing is None:
            diag = Diagnostic(
                code=code,
                severity=severity,
                message=message,
                axis=axis,
                value=value,
                frame=frame,
                count=1,
            )
            self._items[key] = diag
            self._order.append(key)
            return diag
        existing.count += 1
        if existing.frame is None and frame is not None:
            existing.frame = frame
        if existing.value is None and value is not None:
            existing.value = value
        return existing

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        for diag in diagnostics:
            stored = self.add(
                diag.code,
                diag.severity,
                diag.message,
                axis=diag.axis,
                value=diag.value,
                frame=diag.frame,
            )
            stored.count += max(0, diag.count - 1)

    def as_list(self) -> list[Diagnostic]:
        return [self._items[key] for key in self._order]

    def has(self, code: str) -> bool:
        return any(item.code == code for item in self._items.values())

    def has_error(self) -> bool:
        return any(item.severity == "error" for item in self._items.values())


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config(path: str | Path | Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load the machine configuration (or deep-copy an already loaded mapping)."""

    if isinstance(path, Mapping):
        return json.loads(json.dumps(path))
    config_path = Path(path) if path is not None else CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


# ---------------------------------------------------------------------------
# Forward kinematics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForwardKinematics:
    theta_s: float
    r_s: float
    z_s: float
    tip_xyz_wax: tuple[float, float, float]
    tool_axis_wax: tuple[float, float, float]


@dataclass
class InverseKinematics:
    r: float
    theta: float
    h: float
    phi: float
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def forward_kinematics(
    r: float,
    theta: float,
    h: float,
    phi: float,
    config: Mapping[str, Any],
) -> ForwardKinematics:
    """Evaluate conical-bevel tip apex pose in the wax frame.

    ``r``/``h`` are millimetres, ``theta``/``phi`` radians. ``+phi`` rotates
    about the local azimuthal axis ``+e_theta`` and tilts the tip inward.
    """

    r = _finite(r, "r")
    theta = _finite(theta, "theta")
    h = _finite(h, "h")
    phi = _finite(phi, "phi")

    x = float(config["arm_radial_offset_mm"])
    h2 = float(config["arm_to_pivot_z_mm"])
    p = float(config["pivot_to_tip_mm"])

    theta_s = theta
    r_s = r - x - p * math.sin(phi)
    z_s = h - p * math.cos(phi) - h2

    cos_t = math.cos(theta_s)
    sin_t = math.sin(theta_s)
    cos_p = math.cos(phi)
    sin_p = math.sin(phi)

    tip = (r_s * cos_t, r_s * sin_t, z_s)
    # Tool axis points from the wrist pivot toward the tip apex.
    # u(phi) = -sin(phi) * e_r - cos(phi) * e_z
    axis = (-sin_p * cos_t, -sin_p * sin_t, -cos_p)
    return ForwardKinematics(
        theta_s=theta_s,
        r_s=r_s,
        z_s=z_s,
        tip_xyz_wax=tip,
        tool_axis_wax=axis,
    )


# ---------------------------------------------------------------------------
# Soft limits and inverse kinematics
# ---------------------------------------------------------------------------


def _wrap_deg(angle_deg: float) -> float:
    wrapped = math.fmod(angle_deg + 180.0, 360.0)
    if wrapped < 0.0:
        wrapped += 360.0
    return wrapped - 180.0


def validate_joints(
    r: float,
    theta: float,
    h: float,
    phi: float,
    config: Mapping[str, Any],
) -> list[Diagnostic]:
    """Reject out-of-bounds joints instead of silently clamping them."""

    limits = config["limits"]
    diagnostics: list[Diagnostic] = []

    r_lo, r_hi = (float(v) for v in limits["r_limits_mm"])
    if not (r_lo - 1e-9 <= r <= r_hi + 1e-9):
        diagnostics.append(
            Diagnostic(
                code="SOFT_LIMIT_EXCEEDED",
                severity="error",
                message=f"radial joint r={r:.3f} mm outside [{r_lo}, {r_hi}] mm",
                axis="r",
                value=r,
            )
        )

    h_lo, h_hi = (float(v) for v in limits["h_limits_mm"])
    if not (h_lo - 1e-9 <= h <= h_hi + 1e-9):
        diagnostics.append(
            Diagnostic(
                code="SOFT_LIMIT_EXCEEDED",
                severity="error",
                message=f"vertical joint h={h:.3f} mm outside [{h_lo}, {h_hi}] mm",
                axis="h",
                value=h,
            )
        )

    phi_lo, phi_hi = (float(v) for v in limits["phi_limits_deg"])
    phi_deg = phi * RAD2DEG
    if not (phi_lo - 1e-9 <= phi_deg <= phi_hi + 1e-9):
        diagnostics.append(
            Diagnostic(
                code="SOFT_LIMIT_EXCEEDED",
                severity="error",
                message=(
                    f"wrist joint phi={phi_deg:.3f} deg outside "
                    f"[{phi_lo}, {phi_hi}] deg"
                ),
                axis="phi",
                value=phi_deg,
            )
        )

    theta_limits = limits.get("theta_limits_deg")
    if theta_limits is not None:
        t_lo, t_hi = (float(v) for v in theta_limits)
        theta_deg = _wrap_deg(theta * RAD2DEG)
        if not (t_lo - 1e-9 <= theta_deg <= t_hi + 1e-9):
            diagnostics.append(
                Diagnostic(
                    code="SOFT_LIMIT_EXCEEDED",
                    severity="error",
                    message=(
                        f"rotary joint theta={theta_deg:.3f} deg outside "
                        f"[{t_lo}, {t_hi}] deg"
                    ),
                    axis="theta",
                    value=theta_deg,
                )
            )

    return diagnostics


def _project_normal(
    normal: Sequence[float] | None, theta: float
) -> tuple[float, float]:
    """Project a wax-frame normal into the local (e_r, e_z) plane."""

    if normal is None:
        return (0.0, 1.0)
    values = [float(v) for v in normal]
    if len(values) == 2:
        return (values[0], values[1])
    if len(values) != 3:
        raise ValueError("normal must have 2 or 3 components")
    nx, ny, nz = values
    n_r = nx * math.cos(theta) + ny * math.sin(theta)
    return (n_r, nz)


def phi_selection_policy(
    normal: Sequence[float] | None,
    theta: float,
    config: Mapping[str, Any],
) -> tuple[float, list[Diagnostic]]:
    """Choose the wrist pitch that aligns the tool with the surface normal.

    The tool approaches the surface along ``-n`` so ``u = -n``.  With
    ``u = -sin(phi) e_r - cos(phi) e_z`` this gives ``phi = atan2(n_r, n_z)``.
    Tangential normals (no radial/vertical component) fall back to phi = 0.
    """

    n_r, n_z = _project_normal(normal, theta)
    if math.hypot(n_r, n_z) < 1e-3:
        return 0.0, []

    phi_ideal = math.atan2(n_r, n_z)
    phi_lo, phi_hi = (float(v) * DEG2RAD for v in config["limits"]["phi_limits_deg"])
    phi = min(max(phi_ideal, phi_lo), phi_hi)

    diagnostics: list[Diagnostic] = []
    if abs(phi - phi_ideal) > 1e-12:
        diagnostics.append(
            Diagnostic(
                code="PHI_POLICY_CLAMPED",
                severity="info",
                message=(
                    f"phi policy {phi_ideal * RAD2DEG:.2f} deg clamped to "
                    f"{phi * RAD2DEG:.2f} deg"
                ),
                axis="phi",
                value=phi * RAD2DEG,
            )
        )
    return phi, diagnostics


def inverse_kinematics_with_policy(
    target: Sequence[float] | Mapping[str, float],
    normal: Sequence[float] | None,
    config: Mapping[str, Any],
    *,
    phi_preference_rad: float | None = None,
) -> InverseKinematics:
    """Solve ``(r, theta, h, phi)`` for a tip-apex target and optional normal."""

    if isinstance(target, Mapping):
        r_s = _finite(target["r_s"], "r_s")
        theta_s = _finite(target["theta_s"], "theta_s")
        z_s = _finite(target["z_s"], "z_s")
    else:
        r_s, theta_s, z_s = (_finite(v, "target") for v in target)

    diagnostics: list[Diagnostic] = []
    if phi_preference_rad is None:
        phi, policy_diags = phi_selection_policy(normal, theta_s, config)
        diagnostics.extend(policy_diags)
    else:
        phi = _finite(phi_preference_rad, "phi_preference_rad")

    x = float(config["arm_radial_offset_mm"])
    h2 = float(config["arm_to_pivot_z_mm"])
    p = float(config["pivot_to_tip_mm"])

    theta = theta_s
    r = r_s + x + p * math.sin(phi)
    h = z_s + p * math.cos(phi) + h2

    diagnostics.extend(validate_joints(r, theta, h, phi, config))
    return InverseKinematics(r=r, theta=theta, h=h, phi=phi, diagnostics=diagnostics)


# ---------------------------------------------------------------------------
# Timing, relative tip speed, singularity
# ---------------------------------------------------------------------------


def _frame_fk(frame: Mapping[str, Any], config: Mapping[str, Any]) -> ForwardKinematics:
    if "tip_xyz_wax" in frame and "r_s" in frame:
        return ForwardKinematics(
            theta_s=float(frame["theta_s"]),
            r_s=float(frame["r_s"]),
            z_s=float(frame["z_s"]),
            tip_xyz_wax=tuple(float(v) for v in frame["tip_xyz_wax"]),  # type: ignore[arg-type]
            tool_axis_wax=tuple(float(v) for v in frame["tool_axis_wax"]),  # type: ignore[arg-type]
        )
    return forward_kinematics(
        float(frame["r"]),
        float(frame["theta"]),
        float(frame["h"]),
        float(frame["phi"]),
        config,
    )


def segment_timing(
    prev_frame: Mapping[str, Any],
    curr_frame: Mapping[str, Any],
    is_rapid: bool,
    config: Mapping[str, Any],
) -> tuple[float, float]:
    """Return ``(dt, v_tip)`` for one sampled segment.

    ``dt = max(ds / feed, max_i |dq_i| / v_max,i)`` and ``v_tip`` is the
    relative wax-frame tip speed including the platter term ``r_s * theta_dot``.
    """

    prev_fk = _frame_fk(prev_frame, config)
    curr_fk = _frame_fk(curr_frame, config)

    dr = float(curr_frame["r"]) - float(prev_frame["r"])
    dtheta = float(curr_frame["theta"]) - float(prev_frame["theta"])
    dh = float(curr_frame["h"]) - float(prev_frame["h"])
    dphi = float(curr_frame["phi"]) - float(prev_frame["phi"])

    drs = curr_fk.r_s - prev_fk.r_s
    dzs = curr_fk.z_s - prev_fk.z_s
    r_mean = 0.5 * (prev_fk.r_s + curr_fk.r_s)
    ds = math.sqrt(
        drs * drs + (r_mean * dtheta) * (r_mean * dtheta) + dzs * dzs
    )

    feeds = config["feeds"]
    feed = float(feeds["feed_rapid_mm_s"] if is_rapid else feeds["feed_cut_mm_s"])
    v_max = config["v_max"]
    v_r = float(v_max["r_mm_s"])
    v_theta = float(v_max["theta_rad_s"])
    v_h = float(v_max["h_mm_s"])
    v_phi = float(v_max["phi_deg_s"]) * DEG2RAD

    dt = max(
        ds / feed if feed > 0 else 0.0,
        abs(dr) / v_r if v_r > 0 else 0.0,
        abs(dtheta) / v_theta if v_theta > 0 else 0.0,
        abs(dh) / v_h if v_h > 0 else 0.0,
        abs(dphi) / v_phi if v_phi > 0 else 0.0,
    )
    if dt <= 1e-12:
        dt = 1e-12

    theta_dot = dtheta / dt
    v_tip = math.sqrt(
        (drs / dt) ** 2 + (r_mean * theta_dot) ** 2 + (dzs / dt) ** 2
    )
    return dt, v_tip


def build_trajectory(
    joint_path: Sequence[Mapping[str, float]],
    rapid_flags: Sequence[bool],
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[Diagnostic]]:
    """Attach timestamps, wax-frame vectors, tip speed, and diagnostics."""

    if len(joint_path) != len(rapid_flags):
        raise ValueError("joint_path and rapid_flags must have equal length")
    if not joint_path:
        return [], []

    collector = DiagnosticCollector()
    frames: list[dict[str, Any]] = []
    singularity = config["singularity"]
    r_s_min = float(singularity["r_s_min_mm"])
    theta_warn = float(singularity["theta_dot_warn_rad_s"])

    t = 0.0
    first = joint_path[0]
    first_fk = forward_kinematics(
        float(first["r"]), float(first["theta"]), float(first["h"]), float(first["phi"]), config
    )
    frames.append(
        {
            "t": 0.0,
            "r": float(first["r"]),
            "theta": float(first["theta"]),
            "h": float(first["h"]),
            "phi": float(first["phi"]),
            "r_s": first_fk.r_s,
            "theta_s": first_fk.theta_s,
            "z_s": first_fk.z_s,
            "v_tip": 0.0,
            "is_rapid": False,
            "tip_xyz_wax": first_fk.tip_xyz_wax,
            "tool_axis_wax": first_fk.tool_axis_wax,
        }
    )

    for index in range(1, len(joint_path)):
        prev = joint_path[index - 1]
        curr = joint_path[index]
        rapid = bool(rapid_flags[index])
        dt, v_tip = segment_timing(prev, curr, rapid, config)
        t += dt
        fk = forward_kinematics(
            float(curr["r"]), float(curr["theta"]), float(curr["h"]), float(curr["phi"]), config
        )
        prev_fk = forward_kinematics(
            float(prev["r"]), float(prev["theta"]), float(prev["h"]), float(prev["phi"]), config
        )
        theta_dot = (float(curr["theta"]) - float(prev["theta"])) / dt
        if min(prev_fk.r_s, fk.r_s) < r_s_min and abs(theta_dot) > theta_warn:
            collector.add(
                "SINGULARITY_HIGH_THETA_DOT",
                "warning",
                (
                    f"r_s={fk.r_s:.3f} mm < {r_s_min} mm with "
                    f"theta_dot={theta_dot:.3f} rad/s > {theta_warn} rad/s"
                ),
                value=fk.r_s,
                frame=index,
            )
        frames.append(
            {
                "t": t,
                "r": float(curr["r"]),
                "theta": float(curr["theta"]),
                "h": float(curr["h"]),
                "phi": float(curr["phi"]),
                "r_s": fk.r_s,
                "theta_s": fk.theta_s,
                "z_s": fk.z_s,
                "v_tip": v_tip,
                "is_rapid": rapid,
                "tip_xyz_wax": fk.tip_xyz_wax,
                "tool_axis_wax": fk.tool_axis_wax,
            }
        )

    return frames, collector.as_list()

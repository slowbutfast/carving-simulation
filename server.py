"""FastAPI service for the 4-DOF thermal wax carver simulation.

``GET /api/health``
    Liveness probe.

``POST /api/sculpt-and-sim``
    Applies facial sliders, generates a synthetic roughing + undercut
    finishing trajectory, and returns the target mesh, machine configuration,
    structured diagnostics, and **columnar base64** ``Float32Array`` /
    ``Uint8Array`` buffers (capped at ``api.max_frames``).

Static files are served from ``static/`` (Three.js modules are mounted from
``node_modules/three`` when installed).
"""

from __future__ import annotations

import base64
import copy
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import face_sculpt
import kinematics
import toolpath_sim

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
THREE_DIR = ROOT / "node_modules" / "three"
PRESET_DIR = ROOT / "presets"
SERVICE_NAME = "carver-sim"
VERSION = "0.1.0"

app = FastAPI(title="Carving Studio API", version=VERSION)


class StockCfg(BaseModel):
    """Optional stock overrides; every length must be positive."""

    model_config = ConfigDict(extra="forbid")

    R_stock_mm: float | None = Field(default=None, gt=0.0)
    H_stock_mm: float | None = Field(default=None, gt=0.0)
    z_plinth_mm: float | None = Field(default=None, ge=0.0)
    finish_allowance_mm: float | None = Field(default=None, ge=0.0)
    retract_clearance_mm: float | None = Field(default=None, ge=0.0)


class ToolCfg(BaseModel):
    """Optional tool overrides. Blade dimensions are CAD-derived, not client
    overridable; removed cone keys are rejected with 422 naming the key."""

    model_config = ConfigDict(extra="forbid")

    melt_kerf_mm: float | None = Field(default=None, ge=0.0)
    heated_length_mm: float | None = Field(default=None, gt=0.0)


class SimulationRequest(BaseModel):
    sliders: dict[str, float] = Field(default_factory=dict)
    stock_cfg: StockCfg | None = None
    tool_cfg: ToolCfg | None = None
    preset: Literal["demo", "standard"] = "demo"
    #: Optional target mesh, resolved inside ``presets/`` (HTTP 422 on traversal).
    mesh_path: str | None = None


def _overrides(model: BaseModel | None) -> dict[str, Any]:
    """Only the fields the client actually sent (``None`` means unchanged)."""

    if model is None:
        return {}
    return {key: value for key, value in model.model_dump().items() if value is not None}


def _error_detail(
    diagnostics: list[dict[str, Any]],
    *,
    collision_log: dict[str, Any] | None = None,
    sliders_enabled: bool | None = None,
) -> dict[str, Any]:
    """The single shape of every error response body.

    ``collision_log`` is always present so a client can tell "not built because
    there is no trajectory" (``None``) from "built and attached".
    """

    detail: dict[str, Any] = {
        "status": "error",
        "diagnostics": diagnostics,
        "collision_log": collision_log,
    }
    if sliders_enabled is not None:
        detail["sliders_enabled"] = bool(sliders_enabled)
    return detail


def _validation_error(
    diagnostics: list[dict[str, Any]],
    *,
    collision_log: dict[str, Any] | None = None,
    sliders_enabled: bool | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=_error_detail(
            diagnostics, collision_log=collision_log, sliders_enabled=sliders_enabled
        ),
    )


def _resolve_preset_mesh(mesh_path: str) -> str:
    """Resolve a client ``mesh_path`` inside ``presets/`` or raise HTTP 422."""

    presets = PRESET_DIR.resolve()
    try:
        candidate = (presets / mesh_path).resolve()
    except (OSError, RuntimeError):
        candidate = presets
    if not candidate.is_relative_to(presets) or candidate == presets:
        raise _validation_error(
            [
                {
                    "code": "MESH_PATH_INVALID",
                    "severity": "error",
                    "message": (
                        f"mesh_path {mesh_path!r} must name a file inside presets/"
                    ),
                    "count": 1,
                }
            ]
        )
    return candidate.relative_to(ROOT).as_posix()


def _collision_log_target(config: dict[str, Any]) -> Path | None:
    configured = (config.get("logging") or {}).get("collision_log_path")
    if not configured:
        return None
    path = Path(str(configured))
    return path if path.is_absolute() else ROOT / path


def _collision_report(
    path: toolpath_sim.ToolpathResult, *, status: str, preset: str
) -> dict[str, Any]:
    """The collision report returned to the client and written to disk."""

    report: dict[str, Any] = {
        "status": status,
        "service": SERVICE_NAME,
        "version": VERSION,
        "preset": preset,
        "frames": len(path.frames),
        "diagnostics": [d.as_dict() for d in path.diagnostics],
    }
    report.update(copy.deepcopy(path.collision_log or {}))
    return report


def _write_collision_log(
    config: dict[str, Any], report: dict[str, Any]
) -> Path | None:
    """Write ``report`` atomically (temp file + ``os.replace``) and return it."""

    target = _collision_log_target(config)
    if target is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _column(array: np.ndarray, dtype: str) -> dict[str, Any]:
    cast = np.asarray(array, dtype=dtype)
    return {
        "b64": base64.b64encode(cast.tobytes(order="C")).decode("ascii"),
        "dtype": np.dtype(dtype).name,
        "length": int(cast.size),
    }


def _encode_trajectory(frames: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(frames)

    def scalar(name: str) -> np.ndarray:
        return np.asarray([float(frame[name]) for frame in frames], dtype=np.float32)

    def vectors(name: str) -> np.ndarray:
        return np.asarray([frame[name] for frame in frames], dtype=np.float32).reshape(-1)

    columns = {
        "t": _column(scalar("t"), "float32"),
        "r": _column(scalar("r"), "float32"),
        "theta": _column(scalar("theta"), "float32"),
        "h": _column(scalar("h"), "float32"),
        "phi": _column(scalar("phi"), "float32"),
        "r_s": _column(scalar("r_s"), "float32"),
        "theta_s": _column(scalar("theta_s"), "float32"),
        "z_s": _column(scalar("z_s"), "float32"),
        "v_tip": _column(scalar("v_tip"), "float32"),
        "is_rapid": _column(
            np.asarray([1 if frame["is_rapid"] else 0 for frame in frames], dtype=np.uint8),
            "uint8",
        ),
        "tip_xyz_wax": _column(vectors("tip_xyz_wax"), "float32"),
        "tool_axis_wax": _column(vectors("tool_axis_wax"), "float32"),
    }
    return {
        "frame_count": count,
        "columns": columns,
        "vector_columns": ["tip_xyz_wax", "tool_axis_wax"],
    }


def _encode_mesh(mesh: Any) -> dict[str, Any]:
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    return {
        "vertices_b64": base64.b64encode(vertices.tobytes(order="C")).decode("ascii"),
        "faces_b64": base64.b64encode(faces.tobytes(order="C")).decode("ascii"),
        "vertex_count": int(vertices.shape[0]),
        "face_count": int(faces.shape[0]),
        "vertices_dtype": "float32",
        "faces_dtype": "uint32",
        "bounds": np.asarray(mesh.bounds, dtype=np.float32).tolist(),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "max_frames": kinematics.load_config()["api"]["max_frames"],
    }


@app.post("/api/sculpt-and-sim")
def sculpt_and_sim(request: SimulationRequest) -> dict[str, Any]:
    started = time.perf_counter()
    config = kinematics.load_config()
    if request.mesh_path is not None:
        _deep_merge(config, {"target_mesh": {"path": _resolve_preset_mesh(request.mesh_path)}})
    stock_overrides = _overrides(request.stock_cfg)
    tool_overrides = _overrides(request.tool_cfg)
    if stock_overrides:
        _deep_merge(config, {"stock": stock_overrides})
    if tool_overrides:
        _deep_merge(config, {"tool": tool_overrides})
        blade_length = float(config["tool"]["blade_length_mm"])
        heated_length = float(config["tool"]["heated_length_mm"])
        if heated_length > blade_length + 1e-9:
            raise _validation_error(
                [
                    {
                        "code": "TOOL_CFG_INVALID",
                        "severity": "error",
                        "message": (
                            f"tool_cfg.heated_length_mm={heated_length} exceeds "
                            f"the CAD blade length {blade_length} mm"
                        ),
                        "axis": "heated_length_mm",
                        "value": heated_length,
                    }
                ]
            )

    base_mesh = face_sculpt.load_base_head(config)
    sliders_enabled = face_sculpt.sliders_enabled(config)
    sculpt = face_sculpt.apply_facial_modifications(base_mesh, request.sliders, config)
    fatal = [d for d in sculpt.diagnostics if d.severity == "error"]
    if fatal:
        raise _validation_error(
            [d.as_dict() for d in sculpt.diagnostics], sliders_enabled=sliders_enabled
        )

    assert sculpt.mesh is not None
    try:
        path = toolpath_sim.generate_synthetic_carve_path(
            sculpt.mesh, config, preset=request.preset
        )
    except toolpath_sim.FrameCapExceededError as error:
        # No trajectory was produced, so there is nothing to log.
        raise _validation_error([error.diagnostic().as_dict()]) from error

    errors = [d for d in path.diagnostics if d.severity == "error"]
    if errors:
        # SOFT_LIMIT_EXCEEDED and friends: the trajectory is not producible, but
        # the collision log is the artefact a debugger needs, so build and write
        # it *before* raising.
        collision_log = _collision_report(path, status="error", preset=request.preset)
        _write_collision_log(config, collision_log)
        raise _validation_error(
            [d.as_dict() for d in path.diagnostics],
            collision_log=collision_log,
            sliders_enabled=sliders_enabled,
        )

    collision_log = _collision_report(path, status="ok", preset=request.preset)
    _write_collision_log(config, collision_log)

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "preset": request.preset,
        "sliders_enabled": sliders_enabled,
        "config": copy.deepcopy(config),
        "target_mesh": _encode_mesh(sculpt.mesh),
        "trajectory": _encode_trajectory(path.frames),
        "diagnostics": [d.as_dict() for d in path.diagnostics],
        "collision_log": collision_log,
        "summary": {
            "generation_ms": round(elapsed_ms, 2),
            "roughing_frames": path.roughing_frames,
            "finishing_frames": path.finishing_frames,
            "rapid_frames": path.rapid_frames,
            "unreachable_percent": round(path.unreachable_percent, 4),
            "sculpt_max_displacement_mm": round(sculpt.max_displacement_mm, 4),
        },
    }


if THREE_DIR.exists():
    app.mount("/vendor", StaticFiles(directory=THREE_DIR), name="three")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

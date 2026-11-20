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
import time
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import face_sculpt
import kinematics
import toolpath_sim

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
THREE_DIR = ROOT / "node_modules" / "three"
PRESETS_DIR = ROOT / "presets"
SERVICE_NAME = "carver-sim"
VERSION = "0.1.0"

# Upload limits advertised to static/upload.js through GET /api/health.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ACCEPTED_FORMATS = [".stl", ".obj", ".3mf"]
PRESET_LABELS = {"base_head": "Base Head"}

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


def _overrides(model: BaseModel | None) -> dict[str, Any]:
    """Only the fields the client actually sent (``None`` means unchanged)."""

    if model is None:
        return {}
    return {key: value for key, value in model.model_dump().items() if value is not None}


def _validation_error(diagnostics: list[dict[str, Any]]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"status": "error", "diagnostics": diagnostics},
    )


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
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "accepted_formats": list(ACCEPTED_FORMATS),
    }


@app.get("/api/presets")
def presets() -> dict[str, Any]:
    """Bundled model presets discovered from ``presets/*.stl``.

    The static entry keeps ``#preset-select`` usable even when the directory is
    absent (for example in a trimmed deployment).
    """

    entries: list[dict[str, Any]] = []
    if PRESETS_DIR.exists():
        for path in sorted(PRESETS_DIR.glob("*.stl")):
            slug = path.stem
            entries.append(
                {
                    "id": slug,
                    "slug": slug,
                    "label": PRESET_LABELS.get(slug, slug.replace("_", " ").title()),
                    "path": f"/presets/{path.name}",
                }
            )
    if not entries:
        entries.append(
            {
                "id": "base_head",
                "slug": "base_head",
                "label": "Base Head",
                "path": "/presets/base_head.stl",
            }
        )
    return {"presets": entries}


@app.post("/api/sculpt-and-sim")
def sculpt_and_sim(request: SimulationRequest) -> dict[str, Any]:
    started = time.perf_counter()
    config = kinematics.load_config()
    stock_overrides = _overrides(request.stock_cfg)
    tool_overrides = _overrides(request.tool_cfg)
    if stock_overrides:
        _deep_merge(config, {"stock": stock_overrides})
    if tool_overrides:
        _deep_merge(config, {"tool": tool_overrides})
        blade_length = float(config["tool"]["blade_length_mm"])
        heated_length = float(config["tool"]["heated_length_mm"])
        if heated_length > blade_length + 1e-9:
            raise HTTPException(
                status_code=422,
                detail={
                    "status": "error",
                    "diagnostics": [
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
                    ],
                },
            )

    base_mesh = face_sculpt.load_base_head(config)
    sculpt = face_sculpt.apply_facial_modifications(base_mesh, request.sliders, config)
    fatal = [d for d in sculpt.diagnostics if d.severity == "error"]
    if fatal:
        raise HTTPException(
            status_code=422,
            detail={
                "status": "error",
                "diagnostics": [d.as_dict() for d in sculpt.diagnostics],
            },
        )

    assert sculpt.mesh is not None
    try:
        path = toolpath_sim.generate_synthetic_carve_path(
            sculpt.mesh, config, preset=request.preset
        )
    except toolpath_sim.FrameCapExceededError as error:
        raise _validation_error([error.diagnostic().as_dict()]) from error

    errors = [d for d in path.diagnostics if d.severity == "error"]
    if errors:
        # SOFT_LIMIT_EXCEEDED and friends: the trajectory is not producible.
        raise _validation_error([d.as_dict() for d in path.diagnostics])

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "preset": request.preset,
        "config": copy.deepcopy(config),
        "target_mesh": _encode_mesh(sculpt.mesh),
        "trajectory": _encode_trajectory(path.frames),
        "diagnostics": [d.as_dict() for d in path.diagnostics],
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

if PRESETS_DIR.exists():
    app.mount("/presets", StaticFiles(directory=PRESETS_DIR), name="presets")

if STATIC_DIR.exists():
    # Keep the legacy /static prefix for compatibility, then serve the XP shell
    # from the root last so /api/* and /vendor keep priority.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="spa")

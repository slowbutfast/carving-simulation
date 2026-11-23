"""FastAPI service for the 4-DOF thermal wax carver simulation.

``GET /api/health``
    Liveness probe.

``POST /api/sculpt-and-sim``
    Applies facial sliders, generates a synthetic roughing + undercut
    finishing trajectory, and returns the target mesh, machine configuration,
    structured diagnostics, and **columnar base64** ``Float32Array`` /
    ``Uint8Array`` buffers (capped at ``api.max_frames``).

``POST /api/sculpt-and-sim/jobs``
    Same generation on a worker thread: ``202`` with a ``job_id``, then
    ``GET .../jobs/{job_id}`` for progress and ``GET .../jobs/{job_id}/result``
    for the payload once ``status`` is ``done``.

Static files are served from ``static/`` (Three.js modules are mounted from
``node_modules/three`` when installed).

Deployment: run ``uvicorn server:app --workers 1``. The job store and the
single-flight generation guard are per-process in-memory state: with several
workers a poll can land on a process that has never seen the job (``404``), and
each worker would allow one concurrent generation.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

import face_sculpt
import kinematics
import toolpath_sim

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
THREE_DIR = ROOT / "node_modules" / "three"
PRESET_DIR = ROOT / "presets"
PRESETS_DIR = PRESET_DIR
SERVICE_NAME = "carver-sim"
VERSION = "0.1.0"

LOGGER = logging.getLogger(SERVICE_NAME)

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


# ---------------------------------------------------------------------------
# Generation pipeline (shared by the sync and job endpoints)
# ---------------------------------------------------------------------------


def _preflight(request: SimulationRequest) -> dict[str, Any]:
    """Load and merge the config, rejecting a bad ``tool_cfg`` or ``mesh_path``.

    Runs before ``_GEN_SEMAPHORE`` is acquired so an invalid request returns an
    immediate ``422`` instead of waiting for the running generation.
    """

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
    return config


def _run_sculpt_and_sim(
    request: SimulationRequest,
    on_progress: Callable[[str, float, str], None] | None = None,
) -> dict[str, Any]:
    """Sculpt, generate and encode one response payload.

    ``on_progress(phase, global_fraction, message)`` receives ``sculpt``
    (0.00 -> 0.01) and ``encode`` (0.98 -> <1.00) here; the pipeline phases in
    between are weighted inside :func:`toolpath_sim.generate_synthetic_carve_path`.
    ``1.00`` is only ever reported by the job status once the payload is stored.
    """

    started = time.perf_counter()
    config = _preflight(request)

    def emit(phase: str, fraction: float, message: str) -> None:
        if on_progress is not None:
            on_progress(phase, fraction, message)

    emit("sculpt", 0.0, "Sculpting")
    base_mesh = face_sculpt.load_base_head(config)
    sliders_enabled = face_sculpt.sliders_enabled(config)
    sculpt = face_sculpt.apply_facial_modifications(base_mesh, request.sliders, config)
    fatal = [d for d in sculpt.diagnostics if d.severity == "error"]
    if fatal:
        raise _validation_error(
            [d.as_dict() for d in sculpt.diagnostics], sliders_enabled=sliders_enabled
        )
    emit("sculpt", 0.01, "Sculpting")

    assert sculpt.mesh is not None
    try:
        path = toolpath_sim.generate_synthetic_carve_path(
            sculpt.mesh, config, preset=request.preset, on_progress=on_progress
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

    emit("encode", 0.98, "Encoding")
    target_mesh = _encode_mesh(sculpt.mesh)
    trajectory = _encode_trajectory(path.frames)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    payload = {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "preset": request.preset,
        "sliders_enabled": sliders_enabled,
        "config": copy.deepcopy(config),
        "target_mesh": target_mesh,
        "trajectory": trajectory,
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
    # Deliberately < 1.00: the bar reaches 100% only when the job is `done`.
    emit("encode", 0.99, "Encoding")
    return payload


# ---------------------------------------------------------------------------
# Single-flight guard, job store and worker
# ---------------------------------------------------------------------------

#: One generation at a time: two concurrent runs peak at ~3.3 GB each on a
#: 12 GiB container. Acquired non-blocking, so a busy server answers ``429``
#: instead of parking a FastAPI threadpool worker.
_GEN_SEMAPHORE = threading.Semaphore(1)

_JOBS_LOCK = threading.Lock()
#: ``job_id -> job record``; per-process, hence ``--workers 1``.
_JOBS: dict[str, dict[str, Any]] = {}

#: Finished jobs kept for result retries; the oldest by ``completed_at`` goes.
_MAX_RETAINED_JOBS = 4
#: A finished job disappears this long after it completed.
_JOB_TTL_S = 120.0
#: A job nobody polls for this long is abandoned at its next callback.
_SILENCE_S = 90.0
#: Progress writes closer together than this are dropped before taking a lock.
_PROGRESS_MIN_INTERVAL_S = 0.1

_ACTIVE_STATUSES = ("running", "cancelling")
_FINISHED_STATUSES = ("done", "error", "cancelled")


def _monotonic() -> float:
    """Clock seam for the TTL and silence windows (tests replace this)."""

    return time.monotonic()


def _new_job(job_id: str, now: float) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "status": "running",
        "phase": "sculpt",
        "progress": 0.0,
        "message": "Sculpting",
        "created_at": now,
        "completed_at": None,
        "last_poll_at": now,
        "cancel_event": threading.Event(),
        "result": None,
        "error_kind": None,
        "http_status": None,
        "detail": None,
        "_last_write": now - _PROGRESS_MIN_INTERVAL_S,
        "_last_phase": None,
    }


def _prune_jobs() -> None:
    """Expire finished jobs, then keep only the newest ``_MAX_RETAINED_JOBS``.

    Caller holds ``_JOBS_LOCK``. A ``running`` or ``cancelling`` job is never
    dropped: it still owns the semaphore and a worker may still read it.
    """

    now = _monotonic()
    for job_id, job in list(_JOBS.items()):
        completed_at = job["completed_at"]
        if (
            job["status"] in _FINISHED_STATUSES
            and completed_at is not None
            and now - float(completed_at) > _JOB_TTL_S
        ):
            del _JOBS[job_id]

    finished = sorted(
        (job for job in _JOBS.values() if job["status"] in _FINISHED_STATUSES),
        key=lambda job: float(job["completed_at"] or 0.0),
    )
    for job in finished[: max(0, len(finished) - _MAX_RETAINED_JOBS)]:
        del _JOBS[job["job_id"]]


def _finish_job(
    job: dict[str, Any],
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error_kind: str | None = None,
    http_status: int | None = None,
    detail: Any = None,
) -> None:
    """Move a job to a terminal status (the caller holds no lock)."""

    with _JOBS_LOCK:
        job["status"] = status
        job["completed_at"] = _monotonic()
        if status == "done":
            job["phase"] = "done"
            job["progress"] = 1.0
            job["message"] = "Done"
            job["result"] = result
        elif status == "cancelled":
            job["message"] = "Cancelled"
        else:
            job["message"] = "Failed"
            job["error_kind"] = error_kind
            job["http_status"] = http_status
            job["detail"] = detail


def _job_progress(job: dict[str, Any]) -> Callable[[str, float, str], None]:
    """Cooperative cancellation and throttled status writes for one job."""

    def on_progress(phase: str, fraction: float, message: str) -> None:
        # Both checks read fields that are replaced (never mutated in place),
        # so this pre-check needs no lock and a 500 ms poll never queues behind
        # a progress write.
        if job["cancel_event"].is_set():
            raise toolpath_sim.JobCancelled("cancelled by DELETE")
        if _monotonic() - float(job["last_poll_at"]) > _SILENCE_S:
            raise toolpath_sim.JobCancelled("no status poll within 90 s")
        now = _monotonic()
        if (
            now - float(job["_last_write"]) < _PROGRESS_MIN_INTERVAL_S
            and phase == job["_last_phase"]
        ):
            return
        with _JOBS_LOCK:
            job["phase"] = phase
            job["progress"] = fraction
            job["message"] = message
            job["_last_write"] = now
            job["_last_phase"] = phase

    return on_progress


def _run_job(job_id: str, request: SimulationRequest) -> None:
    """Generate one job's payload and always hand the semaphore back."""

    job = _JOBS.get(job_id)
    if job is None:  # deleted while queued; nobody is waiting for the result
        _GEN_SEMAPHORE.release()
        return
    try:
        try:
            result = _run_sculpt_and_sim(request, _job_progress(job))
        except toolpath_sim.JobCancelled:
            _finish_job(job, "cancelled")
        except HTTPException as error:
            _finish_job(
                job,
                "error",
                error_kind="validation",
                http_status=error.status_code,
                detail=error.detail,
            )
        except Exception:
            LOGGER.exception("sculpt-and-sim job %s failed", job_id)
            _finish_job(
                job,
                "error",
                error_kind="internal",
                http_status=500,
                detail={
                    "status": "error",
                    "message": "generation failed; see the server log",
                },
            )
        else:
            _finish_job(job, "done", result=result)
    finally:
        _GEN_SEMAPHORE.release()


def _start_job_worker(job_id: str, request: SimulationRequest) -> None:
    """Start the worker for one job.

    Split out (rather than inlined into the endpoint) so tests can capture the
    call and run :func:`_run_job` inline instead of racing a thread.
    """

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, request),
        name=f"sculpt-sim-{job_id}",
        daemon=True,
    )
    thread.start()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/sculpt-and-sim")
def sculpt_and_sim(request: SimulationRequest) -> dict[str, Any]:
    # Pre-flight validation runs before the guard: an invalid request must not
    # wait behind (or block) a real generation.
    _preflight(request)
    if not _GEN_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="a generation is already running; try again in a moment",
        )
    try:
        return _run_sculpt_and_sim(request)
    finally:
        _GEN_SEMAPHORE.release()


@app.post("/api/sculpt-and-sim/jobs", status_code=202)
def sculpt_and_sim_job(request: SimulationRequest) -> dict[str, Any]:
    """Start one generation on a worker thread and return its ``job_id``."""

    _preflight(request)
    if not _GEN_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="a generation is already running; try again in a moment",
        )
    now = _monotonic()
    job_id = uuid.uuid4().hex
    job = _new_job(job_id, now)
    with _JOBS_LOCK:
        _JOBS[job_id] = job
        _prune_jobs()
    try:
        _start_job_worker(job_id, request)
    except BaseException:
        with _JOBS_LOCK:
            _JOBS.pop(job_id, None)
        _GEN_SEMAPHORE.release()
        raise
    return {"job_id": job_id, "status": "running"}


@app.get("/api/sculpt-and-sim/jobs/{job_id}")
def sculpt_and_sim_job_status(job_id: str) -> dict[str, Any]:
    """Lightweight status poll; also the liveness signal for ``last_poll_at``."""

    with _JOBS_LOCK:
        _prune_jobs()
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown or expired job")
        now = _monotonic()
        job["last_poll_at"] = now
        payload: dict[str, Any] = {
            "job_id": job_id,
            "status": job["status"],
            "phase": job["phase"],
            "progress": job["progress"],
            "message": job["message"],
            "elapsed_ms": round((now - float(job["created_at"])) * 1000.0, 2),
        }
        if job["status"] == "error":
            payload["error_kind"] = job["error_kind"]
            payload["http_status"] = job["http_status"]
            payload["detail"] = job["detail"]
        return payload


@app.get("/api/sculpt-and-sim/jobs/{job_id}/result")
def sculpt_and_sim_job_result(job_id: str) -> dict[str, Any]:
    """The full payload, retry-safe until ``DELETE`` ack or the ``120 s`` TTL."""

    with _JOBS_LOCK:
        _prune_jobs()
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown or expired job")
        if job["status"] in _ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail=f"job is {job['status']}")
        if job["status"] != "done" or job["result"] is None:
            raise HTTPException(status_code=404, detail="job produced no result")
        return job["result"]


@app.delete("/api/sculpt-and-sim/jobs/{job_id}")
def sculpt_and_sim_job_cancel(job_id: str, response: Response) -> dict[str, Any]:
    """Cancel an active job (``202``) or drop a finished one (``200``)."""

    with _JOBS_LOCK:
        _prune_jobs()
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown or expired job")
        if job["status"] in _ACTIVE_STATUSES:
            # Cooperative: the worker raises `JobCancelled` at its next
            # callback and releases `_GEN_SEMAPHORE` on the way out.
            job["cancel_event"].set()
            job["status"] = "cancelling"
            response.status_code = 202
            return {"job_id": job_id, "status": "cancelling"}
        del _JOBS[job_id]
        return {"job_id": job_id, "status": "deleted"}


if THREE_DIR.exists():
    app.mount("/vendor", StaticFiles(directory=THREE_DIR), name="three")

if PRESETS_DIR.exists():
    app.mount("/presets", StaticFiles(directory=PRESETS_DIR), name="presets")

if STATIC_DIR.exists():
    # Keep the legacy /static prefix for compatibility, then serve the XP shell
    # from the root last so /api/* and /vendor keep priority.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="spa")

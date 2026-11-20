"""Procedural base head + smooth parametric facial deformation.

The base head is a watertight icosphere-based ellipsoid facing +X at theta = 0
and seated on the cylindrical plinth (bottom at ``z_plinth_mm``). Facial
features are displaced along vertex normals with a Gaussian RBF weighted by a
``cKDTree`` radius query. A displacement-gradient fold guard prevents
self-intersection, and a cylindrical stock containment check returns a
structured ``STOCK_BOUNDS_EXCEEDED`` error instead of clipping the face.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import trimesh
from scipy.spatial import cKDTree

import kinematics
from kinematics import Diagnostic, DiagnosticCollector

ROOT = Path(__file__).resolve().parent
PRESET_DIR = ROOT / "presets"
BASE_STL = PRESET_DIR / "base_head.stl"
LANDMARKS_JSON = PRESET_DIR / "base_head_landmarks.json"

# Base ellipsoid: 30 x 26 x 40 mm, seated with its bottom at z = 10 mm.
BASE_CENTER = (-4.0, 0.0, 50.0)
BASE_RADII = (30.0, 26.0, 40.0)
ICOSPHERE_SUBDIVISIONS = 4


@dataclass
class SculptResult:
    mesh: trimesh.Trimesh | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    self_intersection_free: bool = True
    max_displacement_mm: float = 0.0

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


# ---------------------------------------------------------------------------
# Procedural base head and landmarks
# ---------------------------------------------------------------------------


def build_base_head(config: Mapping[str, Any] | None = None) -> trimesh.Trimesh:
    """Build the watertight base head seated on the plinth datum."""

    cfg = kinematics.load_config(config) if config is not None else kinematics.load_config()
    z_plinth = float(cfg["stock"]["z_plinth_mm"])
    mesh = trimesh.creation.icosphere(subdivisions=ICOSPHERE_SUBDIVISIONS)
    mesh.vertices = np.asarray(mesh.vertices, dtype=np.float64) * np.asarray(
        BASE_RADII, dtype=np.float64
    )
    mesh.vertices[:, 0] += BASE_CENTER[0]
    mesh.vertices[:, 1] += BASE_CENTER[1]
    mesh.vertices[:, 2] += BASE_CENTER[2]
    # Seat the lowest vertex on the plinth regardless of exact pole geometry.
    min_z = float(mesh.vertices[:, 2].min())
    mesh.vertices[:, 2] += z_plinth - min_z
    mesh.fix_normals()
    return mesh


def build_landmarks() -> dict[str, dict[str, Any]]:
    """Landmark centres, RBF radii, and displacement guards."""

    return {
        "nose": {
            "centers": [[23.0, 0.0, 50.0]],
            "radius_mm": 9.0,
            "max_displacement_mm": 5.0,
            "label": "Nose bridge and tip",
        },
        "brow": {
            "centers": [[21.0, 0.0, 61.0]],
            "radius_mm": 12.5,
            "max_displacement_mm": 3.5,
            "label": "Brow ridge",
        },
        "cheeks": {
            "centers": [[18.0, 14.0, 46.0], [18.0, -14.0, 46.0]],
            "radius_mm": 11.0,
            "max_displacement_mm": 3.0,
            "label": "Cheekbones",
        },
        "jaw": {
            "centers": [[15.0, 11.0, 31.0], [15.0, -11.0, 31.0]],
            "radius_mm": 10.0,
            "max_displacement_mm": 2.5,
            "label": "Jaw line",
        },
        "chin": {
            "centers": [[18.0, 0.0, 22.0]],
            "radius_mm": 9.0,
            "max_displacement_mm": 4.5,
            "label": "Chin",
        },
    }


def generate_presets(force: bool = False) -> tuple[Path, Path]:
    """Generate ``presets/base_head.stl`` and its landmark JSON."""

    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    mesh = build_base_head()
    if force or not BASE_STL.exists():
        mesh.export(BASE_STL)
    if force or not LANDMARKS_JSON.exists():
        payload = {
            "mesh": "base_head.stl",
            "facing": "+X at theta=0",
            "stock_frame": "mm, +Z up, origin at platter top center",
            "facial_features": build_landmarks(),
        }
        LANDMARKS_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return BASE_STL, LANDMARKS_JSON


def resolve_mesh_path(config: Mapping[str, Any] | None = None) -> Path:
    """The active target mesh for ``config``.

    ``config["target_mesh"]["path"]`` wins when it is configured; the analytic
    ellipsoid preset is used only when ``target_mesh`` is ``None`` or omitted
    (which is what the ellipsoid unit tests pin themselves to).
    """

    target = config.get("target_mesh") if isinstance(config, Mapping) else None
    configured = target.get("path") if isinstance(target, Mapping) else None
    if not configured:
        return BASE_STL
    candidate = Path(str(configured))
    return candidate if candidate.is_absolute() else ROOT / candidate


def landmarks_path(
    config: Mapping[str, Any] | None = None,
    mesh_path: str | Path | None = None,
) -> Path:
    """``presets/<stem>_landmarks.json`` for the active mesh (may not exist)."""

    mesh = Path(mesh_path) if mesh_path is not None else resolve_mesh_path(config)
    return mesh.with_name(f"{mesh.stem}_landmarks.json")


def sliders_enabled(config: Mapping[str, Any] | None = None) -> bool:
    """True when the active mesh carries a landmark sidecar to deform."""

    return landmarks_path(config).exists()


def load_base_head(config: Mapping[str, Any] | None = None) -> trimesh.Trimesh:
    """Load the configured target mesh, generating the preset if it is missing."""

    path = resolve_mesh_path(config)
    if path == BASE_STL and not path.exists():
        generate_presets()
    if not path.exists():
        raise FileNotFoundError(
            f"target mesh {path} is missing; run scripts/import_head_mesh.py "
            f"or clear config.target_mesh"
        )
    mesh = trimesh.load(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):  # pragma: no cover - defensive
        raise TypeError(f"{path.name} did not load as a single Trimesh")
    return mesh


def load_landmarks(
    config: Mapping[str, Any] | None = None,
    mesh_path: str | Path | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Facial landmarks for the active mesh, or ``None`` without a sidecar.

    The sidecar is resolved from the mesh path (``presets/<stem>_landmarks.json``),
    not from a fixed file name, so swapping the target mesh cannot silently apply
    another mesh's landmarks.
    """

    sidecar = landmarks_path(config, mesh_path)
    if sidecar == LANDMARKS_JSON and not sidecar.exists():
        generate_presets()
    if not sidecar.exists():
        return None
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    return payload["facial_features"]


# ---------------------------------------------------------------------------
# Deformation guards
# ---------------------------------------------------------------------------


def displacement_fold_violations(
    mesh: trimesh.Trimesh, new_vertices: np.ndarray, *, max_gradient: float = 0.85
) -> int:
    """Count edges whose normal displacement gradient risks a fold.

    A smooth displacement whose magnitude changes by less than ``max_gradient``
    per unit edge length cannot invert the local surface orientation, which is
    a conservative sufficient guard against self-intersection.
    """

    base_vertices = np.asarray(mesh.vertices, dtype=np.float64)
    displacement = new_vertices - base_vertices
    edges = np.asarray(mesh.edges_unique, dtype=np.int64)
    if edges.size == 0:
        return 0
    delta = np.linalg.norm(displacement[edges[:, 0]] - displacement[edges[:, 1]], axis=1)
    lengths = np.linalg.norm(base_vertices[edges[:, 0]] - base_vertices[edges[:, 1]], axis=1)
    lengths = np.maximum(lengths, 1e-9)
    gradient = delta / lengths
    return int(np.count_nonzero(gradient > max_gradient))


def mesh_integrity(mesh: trimesh.Trimesh) -> tuple[bool, list[str]]:
    """Watertightness / volume / orientation integrity guard."""

    problems: list[str] = []
    if not mesh.is_watertight:
        problems.append("mesh is not watertight")
    if not mesh.is_winding_consistent:
        problems.append("mesh winding is inconsistent")
    if mesh.volume <= 0.0:
        problems.append("mesh volume is not positive")
    if not np.all(np.isfinite(mesh.vertices)):
        problems.append("mesh has non-finite vertices")
    if len(mesh.faces) and float(np.min(mesh.area_faces)) <= 1e-12:
        problems.append("mesh has degenerate faces")
    return (not problems), problems


def stock_violations(
    mesh: trimesh.Trimesh, config: Mapping[str, Any]
) -> list[Diagnostic]:
    stock = config["stock"]
    r_limit = float(stock["R_stock_mm"]) - float(stock["finish_allowance_mm"])
    z_limit = float(stock["H_stock_mm"])
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    radial = np.linalg.norm(vertices[:, :2], axis=1)
    diagnostics: list[Diagnostic] = []
    max_r = float(radial.max()) if len(radial) else 0.0
    if max_r > r_limit + 1e-6:
        diagnostics.append(
            Diagnostic(
                code="STOCK_BOUNDS_EXCEEDED",
                severity="error",
                message=(
                    f"sculpted mesh radius {max_r:.3f} mm exceeds "
                    f"R_stock - finish_allowance = {r_limit:.3f} mm"
                ),
                axis="r",
                value=max_r,
            )
        )
    max_z = float(vertices[:, 2].max()) if len(vertices) else 0.0
    min_z = float(vertices[:, 2].min()) if len(vertices) else 0.0
    if max_z > z_limit + 1e-6 or min_z < -1e-6:
        diagnostics.append(
            Diagnostic(
                code="STOCK_BOUNDS_EXCEEDED",
                severity="error",
                message=(
                    f"sculpted mesh z range [{min_z:.3f}, {max_z:.3f}] mm exceeds "
                    f"stock [0, {z_limit:.3f}] mm"
                ),
                axis="z",
                value=max_z,
            )
        )
    return diagnostics


# ---------------------------------------------------------------------------
# Facial modification
# ---------------------------------------------------------------------------


def _feature_centers(landmark: Mapping[str, Any]) -> np.ndarray:
    centers = landmark.get("centers") or [landmark.get("center")]
    return np.asarray(centers, dtype=np.float64)


def apply_facial_modifications(
    base_mesh: trimesh.Trimesh,
    parameters: Mapping[str, float] | None,
    config: Mapping[str, Any] | None = None,
) -> SculptResult:
    """Apply smooth RBF normal deformations to the five facial landmarks.

    A mesh without a ``<stem>_landmarks.json`` sidecar (the imported ``head_2``)
    cannot be deformed: the pass is skipped with zero displacement and, if any
    slider is non-zero, an info ``SCULPT_SLIDERS_IGNORED`` diagnostic is emitted
    instead of failing the request.
    """

    cfg = kinematics.load_config(config) if config is not None else kinematics.load_config()
    params = dict(parameters or {})
    landmarks = load_landmarks(cfg)

    mesh = trimesh.Trimesh(
        vertices=np.array(base_mesh.vertices, dtype=np.float64, copy=True),
        faces=np.array(base_mesh.faces, dtype=np.int64, copy=True),
        process=False,
    )
    mesh.fix_normals()
    base_vertices = np.array(mesh.vertices, copy=True)

    collector = DiagnosticCollector()
    if landmarks is None:
        active = sorted(
            name for name, value in params.items() if abs(float(value)) > 1e-12
        )
        if active:
            collector.add(
                "SCULPT_SLIDERS_IGNORED",
                "info",
                (
                    f"{resolve_mesh_path(cfg).stem} has no landmark sidecar "
                    f"({landmarks_path(cfg).name}); ignoring facial sliders "
                    f"({', '.join(active)})"
                ),
            )
        displacement = np.zeros(len(base_vertices), dtype=np.float64)
        new_vertices = base_vertices
    else:
        normals = np.asarray(mesh.vertex_normals, dtype=np.float64)
        displacement = np.zeros(len(base_vertices), dtype=np.float64)
        for name, landmark in landmarks.items():
            amplitude = float(params.get(name, 0.0))
            if abs(amplitude) < 1e-12:
                continue
            amplitude = float(np.clip(amplitude, -1.5, 1.5))
            radius = float(landmark["radius_mm"])
            max_disp = float(landmark["max_displacement_mm"])
            centers = _feature_centers(landmark)
            # cKDTree over this feature's landmark centres gives each vertex the
            # distance to the nearest RBF kernel centre (supports mirrored pairs).
            feature_tree = cKDTree(centers)
            nearest, _ = feature_tree.query(base_vertices, k=1)
            weight = np.exp(-0.5 * (nearest / radius) ** 2)
            weight[nearest > 2.75 * radius] = 0.0
            displacement += amplitude * max_disp * weight

        new_vertices = base_vertices + normals * displacement[:, None]
        mesh.vertices = new_vertices

    fold_violations = displacement_fold_violations(base_mesh, new_vertices)
    self_free = fold_violations == 0
    if not self_free:
        collector.add(
            "SELF_INTERSECTION_GUARD",
            "error",
            f"{fold_violations} edges exceed the normal-displacement fold guard",
            value=float(fold_violations),
        )

    integrity_ok, problems = mesh_integrity(mesh)
    if not integrity_ok:
        collector.add(
            "MESH_INTEGRITY_FAILED",
            "error",
            "; ".join(problems),
        )

    for diag in stock_violations(mesh, cfg):
        collector.add(
            diag.code,
            diag.severity,
            diag.message,
            axis=diag.axis,
            value=diag.value,
        )

    return SculptResult(
        mesh=mesh,
        diagnostics=collector.as_list(),
        self_intersection_free=self_free and integrity_ok,
        max_displacement_mm=float(np.max(np.abs(displacement))) if len(displacement) else 0.0,
    )


if __name__ == "__main__":  # pragma: no cover - asset generation entry point
    stl_path, landmarks_path = generate_presets(force=True)
    print(f"wrote {stl_path}")
    print(f"wrote {landmarks_path}")

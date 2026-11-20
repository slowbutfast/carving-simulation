"""Convert a downloaded Sketchfab head scan into the preset target mesh.

The simulator's default target is a pre-normalized, watertight head seated on
the stock plinth, committed as ``presets/head_2.stl`` so local runs and CI carve
the same geometry.  The raw download is a glTF photogrammetry scan: an open
surface whose three boundary loops (the neck cut plus the two ear canals) are
capped here.

Usage::

    .venv/bin/python scripts/import_head_mesh.py assets/head_2.zip

The archive is read entirely in memory (``zipfile`` plus a trimesh
``ZipResolver`` over the archive's members); nothing is ever extracted to disk.
Outputs, all in ``presets/``: the STL, the archive's ``license.txt`` as
``<stem>_license.txt``, and a ``<stem>.json`` sidecar recording the source
SHA-256 and every transform parameter, so the conversion is reproducible.

Geometry pipeline:

1. Load the single glTF mesh and ``merge_vertices()`` (glTF splits vertices per
   attribute seam, so the raw mesh is not even topologically open in the right
   places).
2. Chain the boundary half-edges into loops; refuse a boundary vertex of degree
   > 2, which would mean a non-manifold hole.
3. Plain fan-cap the ear holes.
4. Extrude the neck loop (the loop with the most edges) straight down with a
   quad wall to a flat bottom cap.
5. Rotate ``(Z_gltf, X_gltf, Y_gltf)`` -> ``(+X forward, +Z up)`` (det = +1, so
   the winding is preserved).
6. Center the XY footprint on the minimum enclosing circle
   (``trimesh.nsphere.minimum_nsphere`` over the XY points - no new dependency).
7. Scale uniformly so the footprint radius is ``max_radius_mm``.
8. Seat the flat base at ``z_plinth_mm``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
PRESET_DIR = ROOT / "presets"

#: ``det = +1`` axis permutation glTF -> wax frame: the model looks down -Z in
#: glTF, so the wax frame is ``(x, y, z)_wax = (z, x, y)_gltf``.
ROTATION_AXES = ("Z", "X", "Y")
MAX_RADIUS_MM = 32.0
Z_PLINTH_MM = 10.0
#: Height of the extruded neck wall below the lowest point of the neck rim.
#: Without it the wall's lowest quad is zero-height, i.e. a degenerate
#: (zero-area) face, which fails ``face_sculpt.mesh_integrity``.
WALL_MARGIN_MM = 0.5

MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024


# ---------------------------------------------------------------------------
# Archive / mesh loading
# ---------------------------------------------------------------------------


def read_archive(path: Path) -> dict[str, bytes]:
    """Read every member of ``path`` into memory with sane size caps."""

    if not path.is_file():
        raise FileNotFoundError(f"archive not found: {path}")
    members: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.file_size > MAX_ENTRY_BYTES:
                raise ValueError(
                    f"{info.filename} is {info.file_size} bytes, over the "
                    f"{MAX_ENTRY_BYTES} byte per-entry limit"
                )
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"archive expands to more than {MAX_UNCOMPRESSED_BYTES} bytes"
                )
            members[info.filename] = archive.read(info.filename)
    return members


def load_scene_mesh(members: dict[str, bytes]) -> tuple[trimesh.Trimesh, str]:
    """Load the archive's single glTF/glb mesh (buffers resolved in memory)."""

    entries = sorted(
        name for name in members if name.lower().endswith((".gltf", ".glb"))
    )
    if len(entries) != 1:
        raise ValueError(
            "expected exactly one glTF entry in the archive, found "
            f"{entries or 'none'}"
        )
    entry = entries[0]
    loaded = trimesh.load(
        io.BytesIO(members[entry]),
        file_type=Path(entry).suffix.lstrip(".").lower(),
        resolver=trimesh.visual.resolvers.ZipResolver(members),
    )
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.to_mesh()
    mesh = trimesh.Trimesh(
        vertices=np.asarray(loaded.vertices, dtype=np.float64),
        faces=np.asarray(loaded.faces, dtype=np.int64),
        process=False,
    )
    mesh.merge_vertices()
    return mesh, entry


# ---------------------------------------------------------------------------
# Boundary loops, caps, and winding
# ---------------------------------------------------------------------------


def boundary_loops(mesh: trimesh.Trimesh) -> list[list[int]]:
    """Ordered vertex loops of every open boundary of ``mesh``.

    An undirected edge used by exactly one face is a boundary edge; it is kept
    as the directed half-edge ``(start, end)`` of the face that owns it, so
    walking ``start -> end`` traverses the hole in the direction its neighbours
    run.  A boundary vertex with more than two incident boundary edges is a
    non-manifold hole and is refused.
    """

    directed = {
        (int(a), int(b))
        for face in np.asarray(mesh.faces, dtype=np.int64)
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0]))
    }
    boundary = sorted(edge for edge in directed if (edge[1], edge[0]) not in directed)
    outgoing: dict[int, list[int]] = {}
    for start, end in boundary:
        outgoing.setdefault(start, []).append(end)
    for vertex, targets in outgoing.items():
        if len(targets) > 2:
            raise ValueError(
                f"boundary vertex {vertex} has degree {len(targets)} (max 2): "
                "the hole is not a simple loop"
            )

    loops: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for start, end in boundary:
        if (start, end) in seen:
            continue
        loop = [start]
        current = (start, end)
        while True:
            seen.add(current)
            if current[1] == loop[0]:
                break
            loop.append(current[1])
            targets = outgoing.get(current[1], [])
            if len(targets) != 1:
                raise ValueError(
                    f"boundary vertex {current[1]} has degree {len(targets)}; "
                    "cannot chain a closed boundary loop"
                )
            current = (current[1], targets[0])
        loops.append(loop)
    return loops


def _append_fan(
    vertices: np.ndarray, faces: list[list[int]], loop: Sequence[int]
) -> np.ndarray:
    """Cap ``loop`` with a triangle fan around its centroid.

    The new triangles reuse each boundary half-edge reversed, which is what
    keeps the cap's winding consistent with the faces around the hole.
    """

    centroid = np.asarray(vertices, dtype=np.float64)[list(loop)].mean(axis=0)
    centre = len(vertices)
    vertices = np.vstack([vertices, centroid])
    for index, vertex in enumerate(loop):
        nxt = loop[(index + 1) % len(loop)]
        faces.append([int(nxt), int(vertex), int(centre)])
    return vertices


def extrude_loop(
    vertices: np.ndarray,
    faces: list[list[int]],
    loop: Sequence[int],
    z_bottom: float,
) -> np.ndarray:
    """Drop a quad wall from ``loop`` to ``z_bottom`` and cap it flat."""

    bottom: list[int] = []
    for vertex in loop:
        bottom.append(len(vertices))
        vertices = np.vstack(
            [vertices, [vertices[vertex][0], vertices[vertex][1], float(z_bottom)]]
        )
    for index, vertex in enumerate(loop):
        nxt = loop[(index + 1) % len(loop)]
        lower = bottom[index]
        lower_next = bottom[(index + 1) % len(loop)]
        faces.append([int(vertex), lower, lower_next])
        faces.append([int(vertex), lower_next, int(nxt)])
    return _append_fan(vertices, faces, bottom)


def _edge_face_pairs(
    faces: np.ndarray,
) -> dict[tuple[int, int], list[tuple[int, bool]]]:
    """Map each undirected edge to ``(face index, local direction)``.

    ``local direction`` is True when the face walks the edge low -> high index.
    """

    pairs: dict[tuple[int, int], list[tuple[int, bool]]] = {}
    for face_index, face in enumerate(np.asarray(faces, dtype=np.int64)):
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (int(min(a, b)), int(max(a, b)))
            pairs.setdefault(key, []).append((int(face_index), bool(a < b)))
    return pairs


def orient_outward(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Make the winding consistent across shared edges and face outward.

    ``trimesh.repair.fix_normals`` imports ``networkx``, which this project does
    not depend on (``mesh_formats`` is dependency-free for the same reason), so
    the two passes it performs are done here: propagate a consistent winding
    through face adjacency, then flip the result if the enclosed volume is
    negative.
    """

    pairs = _edge_face_pairs(mesh.faces)
    faces = np.array(mesh.faces, dtype=np.int64, copy=True)
    flip = np.zeros(len(faces), dtype=bool)
    visited = np.zeros(len(faces), dtype=bool)

    def edges_of(face: np.ndarray):
        return (
            (face[0], face[1]),
            (face[1], face[2]),
            (face[2], face[0]),
        )

    for seed in range(len(faces)):
        if visited[seed]:
            continue
        visited[seed] = True
        stack = [seed]
        while stack:
            current = stack.pop()
            for a, b in edges_of(faces[current]):
                key = (int(min(a, b)), int(max(a, b)))
                local_current = bool(a < b) != bool(flip[current])
                for other, local_other in pairs[key]:
                    if other == current or visited[other]:
                        continue
                    # Neighbours must traverse a shared edge in opposite
                    # directions, so `other` flips unless its local direction
                    # already differs from this face's effective one.
                    flip[other] = bool(flip[current]) == (local_current != local_other)
                    visited[other] = True
                    stack.append(other)

    flipped = faces[flip]
    faces[flip] = flipped[:, ::-1]
    mesh.faces = faces
    if float(mesh.volume) < 0.0:
        mesh.invert()
    return mesh


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize(
    mesh: trimesh.Trimesh,
    *,
    max_radius_mm: float = MAX_RADIUS_MM,
    z_plinth_mm: float = Z_PLINTH_MM,
    wall_margin_mm: float = WALL_MARGIN_MM,
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Cap the three holes and place the head on the plinth datum."""

    loops = boundary_loops(mesh)
    if len(loops) != 3:
        raise ValueError(
            "expected three open boundary loops (the neck cut and the two ear "
            f"canals), found {len(loops)}: {[len(loop) for loop in loops]}"
        )
    neck = max(loops, key=len)
    ears = [loop for loop in loops if loop is not neck]
    if len(neck) <= max(len(loop) for loop in ears):
        raise ValueError("cannot tell the neck loop from the ear holes by edge count")

    vertices = np.array(mesh.vertices, dtype=np.float64, copy=True)
    faces = [[int(index) for index in face] for face in np.asarray(mesh.faces)]
    for loop in ears:
        vertices = _append_fan(vertices, faces, loop)

    # (Z, X, Y): +X forward, +Z up, det = +1 so the winding still holds.
    vertices = vertices[:, [2, 0, 1]]
    centre_xy = np.asarray(
        trimesh.nsphere.minimum_nsphere(vertices[:, :2])[0], dtype=np.float64
    )
    vertices[:, :2] -= centre_xy
    footprint = float(np.max(np.hypot(vertices[:, 0], vertices[:, 1])))
    if footprint <= 0.0:
        raise ValueError("mesh has no XY footprint to scale")
    scale = float(max_radius_mm) / footprint
    vertices = vertices * scale

    # Seat the neck rim so the extruded wall lands on the plinth datum.
    rim_min = float(np.min(vertices[neck][:, 2]))
    vertices[:, 2] += float(z_plinth_mm) + float(wall_margin_mm) - rim_min
    vertices = extrude_loop(vertices, faces, neck, float(z_plinth_mm))

    capped = trimesh.Trimesh(
        vertices=vertices, faces=np.asarray(faces, dtype=np.int64), process=False
    )
    capped = orient_outward(capped)
    transform = {
        "rotation": list(ROTATION_AXES),
        "center_xy_mm": [float(value) for value in centre_xy],
        "scale": scale,
        "footprint_radius_mm": footprint,
        "max_radius_mm": float(max_radius_mm),
        "z_plinth_mm": float(z_plinth_mm),
        "wall_margin_mm": float(wall_margin_mm),
        "neck_loop_edges": len(neck),
        "ear_loop_edges": [len(loop) for loop in ears],
    }
    return capped, transform


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def import_head(
    archive_path: Path,
    out_dir: Path = PRESET_DIR,
    *,
    max_radius_mm: float = MAX_RADIUS_MM,
    z_plinth_mm: float = Z_PLINTH_MM,
) -> tuple[Path, Path, Path]:
    """Convert ``archive_path`` and write the STL, licence, and sidecar."""

    members = read_archive(archive_path)
    raw, entry = load_scene_mesh(members)
    mesh, transform = normalize(
        raw, max_radius_mm=max_radius_mm, z_plinth_mm=z_plinth_mm
    )
    if not mesh.is_watertight:
        raise ValueError("capped mesh is not watertight")
    if not mesh.is_winding_consistent:
        raise ValueError("capped mesh winding is inconsistent")
    if float(mesh.volume) <= 0.0:
        raise ValueError("capped mesh has non-positive volume")

    stem = archive_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    stl_path = out_dir / f"{stem}.stl"
    mesh.export(stl_path)

    credit = members.get("license.txt")
    if credit is None:
        raise ValueError("archive has no license.txt to carry the model credit")
    license_path = out_dir / f"{stem}_license.txt"
    license_path.write_bytes(credit)

    sidecar = {
        "mesh": stl_path.name,
        "source": {
            "archive": archive_path.name,
            "entry": entry,
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        },
        "transform": transform,
        "geometry": {
            "vertices": int(len(mesh.vertices)),
            "faces": int(len(mesh.faces)),
            "volume_mm3": round(float(mesh.volume), 6),
            "bounds_mm": [[round(float(v), 6) for v in row] for row in mesh.bounds],
            "watertight": bool(mesh.is_watertight),
            "winding_consistent": bool(mesh.is_winding_consistent),
        },
    }
    sidecar_path = out_dir / f"{stem}.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return stl_path, license_path, sidecar_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip_path", type=Path, help="downloaded head_*.zip")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PRESET_DIR,
        help="output directory (default: presets/)",
    )
    parser.add_argument("--max-radius-mm", type=float, default=MAX_RADIUS_MM)
    parser.add_argument("--z-plinth-mm", type=float, default=Z_PLINTH_MM)
    args = parser.parse_args(argv)
    stl_path, license_path, sidecar_path = import_head(
        args.zip_path,
        args.out_dir,
        max_radius_mm=args.max_radius_mm,
        z_plinth_mm=args.z_plinth_mm,
    )
    for path in (stl_path, license_path, sidecar_path):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - asset generation entry point
    raise SystemExit(main())

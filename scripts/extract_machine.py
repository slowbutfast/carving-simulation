"""Offline STEP -> machine geometry extraction for the Wax Face Carver v2.

Dev-only: needs ``cadquery-ocp`` from ``requirements-cad.txt``. No runtime
module imports this file or OCP.

Reads ``assets/Wax+Face+Carver+v2.stp`` through XCAF, converts centimetres to
millimetres, transforms the Y-up CAD frame into the Z-up machine frame

    (x, y, z)_cad -> (x, -z, y - seat_y_cad)

and writes two committed artifact sets:

* ``machine_geometry.json`` - constants, travel evidence, link roles, tool
  geometry and provenance, sorted and rounded so repeated runs are identical.
* ``static/models/{static,orbit,z,radial,tilt,unassigned}.glb`` - one mesh per
  link at the CAD reference pose, node names equal to the CAD occurrence names.

Usage::

    .venv-cad/bin/python scripts/extract_machine.py
    .venv-cad/bin/python scripts/extract_machine.py --check   # non-zero if stale
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
STEP_PATH = ROOT / "assets" / "Wax+Face+Carver+v2.stp"
ROLES_PATH = ROOT / "cad_part_roles.json"
GEOMETRY_PATH = ROOT / "machine_geometry.json"
MODELS_DIR = ROOT / "static" / "models"

LINKS = ("static", "orbit", "z", "radial", "tilt")
ALL_LINKS = LINKS + ("unassigned", "stock_placeholder")

# Per-link linear deflection, mm. The cartridge is pinned by the spec at
# <= 0.02 mm; the rest trade fidelity for the 8 MiB total budget.
DEFLECTION_MM = {
    "static": 1.0,
    "orbit": 1.0,
    "z": 0.5,
    "radial": 0.3,
    "tilt": 0.1,
    "unassigned": 1.0,
}
CARTRIDGE_DEFLECTION_MM = 0.02

# Verified CAD measurements that are section studies rather than bbox reads.
# They are recorded with provenance in the output; see research.md.
BLADE_DIMS_MM = (1.2, 6.0, 14.0)  # thickness (CAD X), width (CAD Z), length (CAD Y)
SHAFT_RADIUS_MM = 2.5
SHAFT_SPAN_MM = (14.0, 75.0)
BODY_RADIUS_MM = 3.5
BODY_SPAN_MM = (75.0, 140.0)

ROUND = 4


# ---------------------------------------------------------------------------
# OCP imports are deliberately local to this module (never a runtime import)
# ---------------------------------------------------------------------------


def _ocp() -> dict[str, Any]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_ChildIterator
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.collections import Sequence_TDF_Label

    return {
        "Bnd_Box": Bnd_Box,
        "BRep_Tool": BRep_Tool,
        "BRepBndLib": BRepBndLib,
        "BRepMesh_IncrementalMesh": BRepMesh_IncrementalMesh,
        "IFSelect_ReturnStatus": IFSelect_ReturnStatus,
        "Interface_Static": Interface_Static,
        "STEPCAFControl_Reader": STEPCAFControl_Reader,
        "TCollection_ExtendedString": TCollection_ExtendedString,
        "TDataStd_Name": TDataStd_Name,
        "TDF_ChildIterator": TDF_ChildIterator,
        "TDocStd_Document": TDocStd_Document,
        "TopAbs_FACE": TopAbs_FACE,
        "TopAbs_REVERSED": TopAbs_REVERSED,
        "TopExp_Explorer": TopExp_Explorer,
        "TopLoc_Location": TopLoc_Location,
        "TopoDS": TopoDS,
        "XCAFDoc_DocumentTool": XCAFDoc_DocumentTool,
        "Sequence_TDF_Label": Sequence_TDF_Label,
    }


def ocp_version() -> str:
    for name in ("cadquery-ocp", "cadquery_ocp", "OCP"):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "unknown"


def step_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_length_unit(path: Path) -> str:
    """Read the declared length unit from the STEP header text."""

    head = path.read_bytes().decode("latin-1", errors="replace")
    match = re.search(
        r"SI_UNIT\s*\(\s*(?:\.([A-Z]+)\.\s*)?,\s*\.METRE\.\s*\)", head
    )
    if not match:
        return "unknown"
    prefix = (match.group(1) or "").upper()
    return {
        "MILLI": "mm",
        "CENTI": "cm",
        "DECI": "dm",
        "MICRO": "um",
        "KILO": "km",
        "": "m",
    }.get(prefix, "unknown")


# ---------------------------------------------------------------------------
# XCAF walk
# ---------------------------------------------------------------------------


def load_occurrences(step_path: Path) -> list[dict[str, Any]]:
    """Return every leaf occurrence with its CAD-frame bbox, sorted by name."""

    ocp = _ocp()
    ocp["Interface_Static"].SetCVal_s("xstep.cascade.unit", "MM")
    doc = ocp["TDocStd_Document"](ocp["TCollection_ExtendedString"]("doc"))
    reader = ocp["STEPCAFControl_Reader"]()
    reader.SetNameMode(True)
    reader.SetColorMode(False)
    status = reader.ReadFile(str(step_path))
    if status != ocp["IFSelect_ReturnStatus"].IFSelect_RetDone:
        raise RuntimeError(f"STEP read failed for {step_path}: {status}")
    if not reader.Transfer(doc):
        raise RuntimeError(f"STEP transfer failed for {step_path}")

    shape_tool = ocp["XCAFDoc_DocumentTool"].ShapeTool_s(doc.Main())
    name_cls = ocp["TDataStd_Name"]
    topo = ocp["TopoDS"]

    def name_of(label) -> str | None:
        attr = name_cls()
        if label.FindAttribute(name_cls.GetID_s(), attr):
            return attr.Get().ToExtString()
        return None

    def bbox(shape) -> list[float]:
        box = ocp["Bnd_Box"]()
        ocp["BRepBndLib"].Add_s(shape, box)
        lo, hi = box.CornerMin(), box.CornerMax()
        return [lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()]

    occurrences: list[dict[str, Any]] = []

    def walk(label) -> None:
        if shape_tool.IsComponent_s(label) or shape_tool.IsSimpleShape_s(label):
            shape = shape_tool.GetShape_s(label)
            if shape is None or shape.IsNull():
                return
            name = name_of(label) or "unnamed"
            occurrences.append(
                {
                    "name": name,
                    "bbox_cad": bbox(shape),
                    "solid": shape.ShapeType().name == "TopAbs_SOLID",
                }
            )
            return
        count = shape_tool.NbComponents_s(label)
        if count:
            components = ocp["Sequence_TDF_Label"]()
            shape_tool.GetComponents_s(label, components, False)
            for index in range(1, components.Length() + 1):
                walk(components.Value(index))

    free = ocp["Sequence_TDF_Label"]()
    shape_tool.GetFreeShapes(free)
    for index in range(1, free.Length() + 1):
        walk(free.Value(index))

    occurrences.sort(key=lambda item: item["name"])
    return occurrences


def occurrences_by_shape(step_path: Path) -> dict[str, Any]:
    """Second pass: shape handles by occurrence name, for tessellation."""

    ocp = _ocp()
    ocp["Interface_Static"].SetCVal_s("xstep.cascade.unit", "MM")
    doc = ocp["TDocStd_Document"](ocp["TCollection_ExtendedString"]("doc"))
    reader = ocp["STEPCAFControl_Reader"]()
    reader.SetNameMode(True)
    reader.ReadFile(str(step_path))
    reader.Transfer(doc)
    shape_tool = ocp["XCAFDoc_DocumentTool"].ShapeTool_s(doc.Main())
    name_cls = ocp["TDataStd_Name"]

    def name_of(label) -> str | None:
        attr = name_cls()
        if label.FindAttribute(name_cls.GetID_s(), attr):
            return attr.Get().ToExtString()
        return None

    shapes: dict[str, Any] = {}

    def walk(label) -> None:
        if shape_tool.IsComponent_s(label) or shape_tool.IsSimpleShape_s(label):
            name = name_of(label) or "unnamed"
            shapes.setdefault(name, shape_tool.GetShape_s(label))
            return
        count = shape_tool.NbComponents_s(label)
        if count:
            components = ocp["Sequence_TDF_Label"]()
            shape_tool.GetComponents_s(label, components, False)
            for index in range(1, components.Length() + 1):
                walk(components.Value(index))

    free = ocp["Sequence_TDF_Label"]()
    shape_tool.GetFreeShapes(free)
    for index in range(1, free.Length() + 1):
        walk(free.Value(index))
    return shapes


# ---------------------------------------------------------------------------
# Frames and roles
# ---------------------------------------------------------------------------


def cad_to_machine(point: Iterable[float], seat_y_cad: float) -> list[float]:
    x, y, z = (float(v) for v in point)
    return [x, -z, y - seat_y_cad]


def transform_matrix(seat_y_cad: float) -> list[list[float]]:
    # (x, y, z) -> (x, -z, y - seat_y_cad); last row is homogeneous.
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, 0.0],
        [0.0, 1.0, 0.0, -float(seat_y_cad)],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _prefix_link(name: str, rules: Sequence) -> str | None:
    for rule in rules:
        if name.startswith(rule["prefix"]):
            return rule["link"]
    return None


def _bbox_distance_sq(a: Sequence[float], b: Sequence[float]) -> float:
    total = 0.0
    for index in range(3):
        lo_a, hi_a = a[index], a[index + 3]
        lo_b, hi_b = b[index], b[index + 3]
        if hi_a < lo_b:
            delta = lo_b - hi_a
        elif hi_b < lo_a:
            delta = lo_a - hi_b
        else:
            delta = 0.0
        total += delta * delta
    return total


def assign_roles(
    occurrences: list[dict[str, Any]], roles: dict[str, Any]
) -> dict[str, list[str]]:
    """Map every occurrence name to exactly one link.

    Non-fasteners use the ordered prefix rules. ``FST_*`` fasteners are
    resolved by proximity to the nearest already-assigned part bbox. This is
    the only geometric inference, it applies only to fasteners, and ties break
    on the part name so the result is deterministic.
    """

    rules = roles["rules"]
    fastener = roles.get("fastener_rule", {})
    fastener_prefix = fastener.get("prefix", "FST_")
    assignments: dict[str, str] = {}
    pending: list[dict[str, Any]] = []

    for item in occurrences:
        link = _prefix_link(item["name"], rules)
        if link is None and item["name"].startswith(fastener_prefix):
            pending.append(item)
        else:
            assignments[item["name"]] = link or "unassigned"

    anchors = [
        (item["name"], assignments[item["name"]], item["bbox_cad"])
        for item in occurrences
        if item["name"] in assignments
        and assignments[item["name"]] not in ("unassigned", "stock_placeholder")
    ]
    for item in pending:
        best: tuple[float, str, str] | None = None
        for name, link, bbox in anchors:
            key = (_bbox_distance_sq(item["bbox_cad"], bbox), name, link)
            if best is None or key < best:
                best = key
        assignments[item["name"]] = best[2] if best else fastener.get("default", "unassigned")

    by_link: dict[str, list[str]] = {link: [] for link in ALL_LINKS}
    for name in sorted(assignments):
        by_link[assignments[name]].append(name)
    return by_link


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _bbox_of(names: Iterable[str], occ: dict[str, dict[str, Any]]) -> list[float] | None:
    boxes = [occ[name]["bbox_cad"] for name in names if name in occ]
    if not boxes:
        return None
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        max(b[4] for b in boxes),
        max(b[5] for b in boxes),
    ]


def _name_starting(prefix: str, occ: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name in occ if name.startswith(prefix)]


def compute_constants(by_link: dict[str, list[str]], occ: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Measure the kinematic constants from the CAD bboxes.

    The verified tolerances in the change stop rule are checked by the tests;
    this function never invents a value. Anything not measured is ``None`` with
    a reason.
    """

    seat_y_cad = 3.0  # placeholder block bottom face; the stock seat plane
    reasons: dict[str, str] = {}

    horn_names = _name_starting("Servo_Horn", occ)
    horn_box = _bbox_of(horn_names, occ)
    if horn_box is None:
        raise RuntimeError("Servo_Horn missing: cannot locate the tilt pivot")
    horn_centre_cad = [
        (horn_box[0] + horn_box[3]) / 2.0,
        (horn_box[1] + horn_box[4]) / 2.0,
        (horn_box[2] + horn_box[5]) / 2.0,
    ]
    # The horn plate is the thin Z face of the servo; its axis is CAD Z.
    pivot_machine = cad_to_machine([horn_centre_cad[0], horn_centre_cad[1], 0.0], seat_y_cad)
    pivot_point = [pivot_machine[0], pivot_machine[1], pivot_machine[2]]
    # Project the tangential CAD-Z offset out: the axis is parallel to CAD Z,
    # so any point on the line is equivalent. The machine-frame pivot point is
    # placed on the tool's radial plane.
    pivot_point = [0.0, 0.0, pivot_machine[2]]
    pivot_axis = [0.0, -1.0, 0.0]  # CAD +Z -> machine -Y = -e_theta at theta=0

    dowel_names = _name_starting("Dowel_3x37", occ)
    dowel_box = _bbox_of(dowel_names, occ)
    pivot_candidates = [
        {
            "name": "servo_horn_axis",
            "point_mm": _round_list(pivot_point),
            "axis_mm": pivot_axis,
            "provenance": "Servo_Horn plate centre, thin axis CAD Z (MG90D-270 output shaft)",
        }
    ]
    if dowel_box is not None:
        dowel_centre = [
            (dowel_box[0] + dowel_box[3]) / 2.0,
            (dowel_box[1] + dowel_box[4]) / 2.0,
            (dowel_box[2] + dowel_box[5]) / 2.0,
        ]
        dowel_point = [dowel_centre[0], 0.0, dowel_centre[1] - seat_y_cad]
        pivot_candidates.append(
            {
                "name": "dowel_3x37_axis",
                "point_mm": _round_list(dowel_point),
                "axis_mm": pivot_axis,
                "provenance": "Dowel_3x37 long axis CAD Z at x=14.03, y=153.99 (unverified alternative)",
            }
        )

    cartridge_names = _name_starting("T12_K_Cartridge", occ)
    cartridge_box = _bbox_of(cartridge_names, occ)
    if cartridge_box is None:
        raise RuntimeError("T12_K_Cartridge missing: cannot locate the tool reference point")
    ref_cad = [
        0.5 * (cartridge_box[0] + cartridge_box[3]),
        cartridge_box[1],
        0.5 * (cartridge_box[2] + cartridge_box[5]),
    ]
    ref_machine = cad_to_machine(ref_cad, seat_y_cad)
    reference_point = [0.0, 0.0, ref_machine[2]]

    pivot_to_tip = float(pivot_point[2] - reference_point[2])

    # Radial stop faces minus the carriage half-length (MGN12C).
    stops = _name_starting("Radial_Stop", occ)
    carriage = _bbox_of(_name_starting("Radial_Carriage", occ), occ)
    if len(stops) >= 2 and carriage is not None:
        stop_boxes = sorted((occ[name]["bbox_cad"] for name in stops), key=lambda b: b[0])
        half_length = 0.5 * (carriage[3] - carriage[0])
        inner_face = stop_boxes[0][3]  # +X face of the inner stop
        outer_face = stop_boxes[-1][0]  # -X face of the outer stop
        r_travel = [inner_face + half_length, outer_face - half_length]
    else:
        r_travel = None
        reasons["r_travel_mm"] = "radial stops or carriage not found in the CAD"

    # Z travel from the carriage bearings against the stop hardware. The
    # Z_Carriage plate reaches up to the arm mount, so the linear bearings are
    # the moving reference that actually approaches the stops.
    z_moving = _bbox_of(_name_starting("Z_Bushing", occ), occ) or _bbox_of(
        _name_starting("Z_Carriage", occ), occ
    )
    z_bottom = _bbox_of(_name_starting("Z_Bottom_Switch", occ), occ)
    z_top = _bbox_of(_name_starting("Z_Top_Stops", occ), occ)
    if z_moving is not None and z_bottom is not None and z_top is not None:
        down = z_moving[1] - z_bottom[4]  # bearing bottom to clamp top
        up = z_top[1] - z_moving[4]  # top stop bottom to bearing top
        h_travel = [pivot_point[2] - down, pivot_point[2] + up]
    else:
        h_travel = None
        reasons["h_travel_mm"] = "Z stops or Z carriage bearings not found in the CAD"

    theta_travel = None
    reasons["theta_travel_deg"] = (
        "The orbit stop block bounds rotation, but the contact angle depends on the "
        "arm's swept envelope and is not unambiguously measurable from placed bboxes; "
        "configuration must supply a labelled conservative fallback."
    )

    # Head envelope: the tilt link minus the cartridge, in the tool-local frame
    #   s = along -u (toward the pivot, +CAD Y), n = a_n (-CAD X), w = a_w (-CAD Z)
    # The scalar head clearance also accounts for the lowest radial-link head
    # part (the tilt bracket), which is why it is slightly smaller than s_min.
    head_names = [
        name for name in by_link["tilt"] if not name.startswith("T12_K_Cartridge")
    ]
    head_box = _bbox_of(head_names, occ)
    clearance_names = (
        [name for name in by_link["radial"] if name.startswith(("Tilt_Bracket", "Tilt_Servo"))]
        + head_names
    )
    clearance_box = _bbox_of(clearance_names, occ)
    head_envelope = None
    head_clearance = None
    if clearance_box is not None:
        head_clearance = float(clearance_box[1] - ref_cad[1])
    if head_box is not None:
        s_min = head_box[1] - ref_cad[1]
        s_max = head_box[4] - ref_cad[1]
        n_min, n_max = -head_box[3], -head_box[0]
        w_min, w_max = -head_box[5], -head_box[2]
        if head_clearance is None:
            head_clearance = float(s_min)
        head_envelope = {
            "shape": "box",
            "frame": "tool_local (n=a_n, w=a_w, s along -u)",
            "center_mm": _round_list(
                [
                    0.5 * (n_min + n_max),
                    0.5 * (w_min + w_max),
                    0.5 * (s_min + s_max),
                ]
            ),
            "half_extents_mm": _round_list(
                [
                    0.5 * (n_max - n_min),
                    0.5 * (w_max - w_min),
                    0.5 * (s_max - s_min),
                ]
            ),
            "provenance": (
                "Bbox of the tilt link minus T12_K_Cartridge, tool-local, at the "
                "CAD reference pose"
            ),
        }

    base_plate = _bbox_of(_name_starting("Base_Plate", occ), occ)
    base_diameter = None
    if base_plate is not None:
        base_diameter = max(base_plate[3] - base_plate[0], base_plate[5] - base_plate[2])

    provenance = {
        "pivot_point_mm": "Servo_Horn plate centre; axis parallel to CAD Z (see pivot_candidates)",
        "pivot_to_tip_mm": "Servo_Horn axis height minus T12_K_Cartridge lowest face",
        "pivot_radial_offset_mm": "Tilt pivot x minus cartridge tool-axis x (both 0.0)",
        "tangential_tool_offset_mm": "Cartridge centre CAD z minus the radial line through the orbit axis (0.0)",
        "r_travel_mm": "Radial_Stop_M_PLA faces minus Radial_Carriage_MGN12C half-length",
        "h_travel_mm": "Z_Bushing_Q_PETG extremes against Z_Bottom_Switch_Clamp_U_PLA and Z_Top_Stops_TPU",
        "cad_reference_pose": "Cartridge/pivot bboxes at the as-exported CAD pose; theta=0, phi=0",
        "tool.blade": "Section study of T12_K_Cartridge (research.md Verified facts)",
        "tool.shaft_body": "Section study of T12_K_Cartridge (research.md Verified facts)",
        "tool.head_envelope": "Bbox of the tilt link minus T12_K_Cartridge, tool-local; head_clearance also includes the lowest radial head part (tilt bracket)",
        "base_plate_diameter_mm": "Base_Plate_6061 placed bounding box",
    }

    return {
        "seat_y_cad": seat_y_cad,
        "pivot_point_mm": pivot_point,
        "pivot_axis_mm": pivot_axis,
        "tool_reference_point_mm": reference_point,
        "pivot_to_tip_mm": pivot_to_tip,
        "pivot_radial_offset_mm": 0.0,
        "tangential_tool_offset_mm": 0.0,
        "r_travel_mm": r_travel,
        "h_travel_mm": h_travel,
        "theta_travel_deg": theta_travel,
        "cad_reference_pose": {
            "r": 0.0,
            "theta_deg": 0.0,
            "h": float(pivot_point[2]),
            "phi_deg": 0.0,
        },
        "home_pose": None,
        "pivot_candidates": pivot_candidates,
        "head_clearance_mm": head_clearance,
        "head_envelope": head_envelope,
        "base_plate_diameter_mm": base_diameter,
        "provenance": provenance,
        "reasons": reasons,
        "reasons_for": list(reasons),
    }


# ---------------------------------------------------------------------------
# Tessellation and GLB export
# ---------------------------------------------------------------------------


def tessellate(shape, deflection: float) -> tuple[Any, Any]:
    import numpy as np

    ocp = _ocp()
    mesher = ocp["BRepMesh_IncrementalMesh"](shape, float(deflection), False, 0.5, True)
    mesher.Perform()
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    explorer = ocp["TopExp_Explorer"](shape, ocp["TopAbs_FACE"])
    topo = ocp["TopoDS"]
    while explorer.More():
        face = topo.Face(explorer.Current())
        location = ocp["TopLoc_Location"]()
        triangulation = ocp["BRep_Tool"].Triangulation_s(face, location)
        if triangulation is not None:
            transform = location.Transformation()
            offset = len(vertices)
            for index in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(index).Transformed(transform)
                vertices.append((point.X(), point.Y(), point.Z()))
            reversed_face = face.Orientation() == ocp["TopAbs_REVERSED"]
            for index in range(1, triangulation.NbTriangles() + 1):
                triangle = triangulation.Triangle(index)
                a, b, c = triangle.Value(1), triangle.Value(2), triangle.Value(3)
                if reversed_face:
                    b, c = c, b
                faces.append((offset + a - 1, offset + b - 1, offset + c - 1))
        explorer.Next()
    return (
        np.asarray(vertices, dtype=np.float64).reshape(-1, 3),
        np.asarray(faces, dtype=np.int32).reshape(-1, 3),
    )


def export_link_glbs(
    by_link: dict[str, list[str]],
    occ: dict[str, dict[str, Any]],
    seat_y_cad: float,
    models_dir: Path,
) -> dict[str, Any]:
    import numpy as np
    import trimesh

    shapes = occurrences_by_shape(STEP_PATH)
    models_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {}
    for link in ALL_LINKS:
        names = by_link.get(link, [])
        if link == "stock_placeholder":
            # Rendered never: the simulated stock is the configurable cylinder.
            summary[link] = {"occurrences": len(names), "bytes": 0, "skipped": True}
            continue
        scene = trimesh.Scene()
        deflection = DEFLECTION_MM.get(link, 1.0)
        for name in names:
            shape = shapes.get(name)
            if shape is None:
                continue
            part_deflection = (
                CARTRIDGE_DEFLECTION_MM if name.startswith("T12_K_Cartridge") else deflection
            )
            vertices, faces = tessellate(shape, part_deflection)
            if len(vertices) == 0 or len(faces) == 0:
                continue
            # CAD (x, y, z) -> machine (x, -z, y - seat).
            machine = np.empty_like(vertices)
            machine[:, 0] = vertices[:, 0]
            machine[:, 1] = -vertices[:, 2]
            machine[:, 2] = vertices[:, 1] - seat_y_cad
            mesh = trimesh.Trimesh(vertices=machine, faces=faces, process=False)
            scene.add_geometry(mesh, geom_name=name, node_name=name)
        path = models_dir / f"{link}.glb"
        if len(scene.geometry) == 0:
            summary[link] = {"occurrences": len(names), "bytes": 0, "skipped": True}
            continue
        scene.export(path)
        summary[link] = {
            "occurrences": len(names),
            "meshes": len(scene.geometry),
            "bytes": path.stat().st_size,
            "deflection_mm": deflection,
        }
    return summary


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _round(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        rounded = round(value, ROUND)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, list):
        return [_round(item) for item in value]
    if isinstance(value, dict):
        return {key: _round(item) for key, item in value.items()}
    return value


def _round_list(values: Iterable[float]) -> list[float]:
    return [round(float(value), ROUND) for value in values]


def build_geometry(
    step_path: Path = STEP_PATH,
    roles_path: Path = ROLES_PATH,
    models_dir: Path | None = MODELS_DIR,
) -> dict[str, Any]:
    occurrences = load_occurrences(step_path)
    occ = {item["name"]: item for item in occurrences}
    roles = json.loads(roles_path.read_text(encoding="utf-8"))
    by_link = assign_roles(occurrences, roles)
    constants = compute_constants(by_link, occ)

    occurrences_total = sum(len(names) for names in by_link.values())
    if occurrences_total != len(occurrences):
        raise RuntimeError(
            f"role coverage {occurrences_total} != {len(occurrences)} leaf occurrences"
        )

    geometry: dict[str, Any] = {
        "schema_version": 1,
        "step_path": str(step_path.relative_to(ROOT)) if step_path.is_relative_to(ROOT) else step_path.name,
        "step_sha256": step_sha256(step_path),
        "ocp_version": ocp_version(),
        "source_length_unit": source_length_unit(step_path),
        "parts_count": len(occurrences),
        "transform": {
            "description": "(x, y, z)_cad -> (x, -z, y - seat_y_cad)",
            "matrix": transform_matrix(constants["seat_y_cad"]),
            "rotation_det": 1.0,
            "seat_y_cad": constants["seat_y_cad"],
        },
        "frame": {
            "machine": "right-handed, +Z up, origin on the orbit axis at the stock seat plane",
            "cad": "Y up, orbit axis on CAD Y through the origin, column toward +X",
        },
        "orbit_axis_mm": [0.0, 0.0],
        "base_plate_diameter_mm": constants["base_plate_diameter_mm"],
        "pivot_point_mm": constants["pivot_point_mm"],
        "pivot_axis_mm": constants["pivot_axis_mm"],
        "tool_reference_point_mm": constants["tool_reference_point_mm"],
        "pivot_to_tip_mm": constants["pivot_to_tip_mm"],
        "pivot_radial_offset_mm": constants["pivot_radial_offset_mm"],
        "tangential_tool_offset_mm": constants["tangential_tool_offset_mm"],
        "r_travel_mm": constants["r_travel_mm"],
        "h_travel_mm": constants["h_travel_mm"],
        "theta_travel_deg": constants["theta_travel_deg"],
        "cad_reference_pose": constants["cad_reference_pose"],
        "home_pose": constants["home_pose"],
        "pivot_candidates": constants["pivot_candidates"],
        "tool": {
            "blade_thickness_mm": BLADE_DIMS_MM[0],
            "blade_width_mm": BLADE_DIMS_MM[1],
            "blade_length_mm": BLADE_DIMS_MM[2],
            "shaft_radius_mm": SHAFT_RADIUS_MM,
            "shaft_span_mm": list(SHAFT_SPAN_MM),
            "body_radius_mm": BODY_RADIUS_MM,
            "body_span_mm": list(BODY_SPAN_MM),
            "head_clearance_mm": constants["head_clearance_mm"],
            "head_envelope": constants["head_envelope"],
        },
        "links": {link: by_link.get(link, []) for link in ALL_LINKS},
        "link_counts": {link: len(by_link.get(link, [])) for link in ALL_LINKS},
        "unassigned_parts": by_link.get("unassigned", []),
        "stock_placeholder_parts": by_link.get("stock_placeholder", []),
        "provenance": constants["provenance"],
        "reasons": constants["reasons"],
    }

    if models_dir is not None:
        geometry["models"] = export_link_glbs(
            by_link, occ, constants["seat_y_cad"], Path(models_dir)
        )
    return _round(geometry)


def dumps(geometry: dict[str, Any]) -> str:
    return json.dumps(geometry, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if committed artifacts are stale")
    parser.add_argument("--no-models", action="store_true", help="skip GLB export")
    args = parser.parse_args(argv)

    models = None if args.no_models else MODELS_DIR
    geometry = build_geometry(models_dir=models)
    text = dumps(geometry)
    if args.check:
        committed = GEOMETRY_PATH.read_text(encoding="utf-8") if GEOMETRY_PATH.exists() else ""
        if committed != text:
            print("machine_geometry.json is stale; run scripts/extract_machine.py", file=sys.stderr)
            return 1
        print("machine_geometry.json is current")
        return 0

    GEOMETRY_PATH.write_text(text, encoding="utf-8")
    total = sum(
        entry.get("bytes", 0) for entry in geometry.get("models", {}).values()
    )
    print(f"wrote {GEOMETRY_PATH.name}: {len(geometry['links'])} links, {geometry['parts_count']} parts")
    print(f"GLB total: {total / (1024 * 1024):.2f} MiB")
    print(f"unassigned: {geometry['unassigned_parts']}")
    print(f"stock_placeholder: {geometry['stock_placeholder_parts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Runtime-side tests for the CAD-derived machine artifacts.

These read the committed ``machine_geometry.json`` and ``static/models/*.glb``.
They must not need OCP: the runtime never parses the STEP.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = ROOT / "machine_geometry.json"
STEP = ROOT / "assets" / "Wax+Face+Carver+v2.stp"
MODELS = ROOT / "static" / "models"

RUNTIME_MODULES = ("server.py", "kinematics.py", "toolpath_sim.py", "tool_model.py")

try:  # noqa: E402
    from tests._tiers import ReleasesClassFixtures
except ImportError:  # direct `python tests/test_machine_cad.py`
    from _tiers import ReleasesClassFixtures


def load_geometry() -> dict:
    return json.loads(GEOMETRY.read_text(encoding="utf-8"))


class TestCadArtifact(ReleasesClassFixtures, unittest.TestCase):
    _class_fixtures = ("geometry",)

    @classmethod
    def setUpClass(cls):
        cls.geometry = load_geometry()

    # -- units, frame, orbit axis ------------------------------------------
    def test_source_unit_and_frame_are_recorded(self):
        self.assertEqual(self.geometry["source_length_unit"], "cm")
        transform = self.geometry["transform"]
        self.assertAlmostEqual(float(transform["seat_y_cad"]), 3.0, places=6)
        matrix = np.asarray(transform["matrix"], dtype=float)
        self.assertEqual(matrix.shape, (4, 4))
        rotation = matrix[:3, :3]
        self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=9)

    def test_base_plate_diameter_in_machine_frame(self):
        self.assertAlmostEqual(
            float(self.geometry["base_plate_diameter_mm"]), 700.0, delta=0.1
        )

    def test_orbit_axis_is_the_machine_z_axis_through_the_origin(self):
        self.assertEqual([float(v) for v in self.geometry["orbit_axis_mm"]], [0.0, 0.0])

    def test_cad_to_machine_transform_moves_the_seat_plane_to_z_zero(self):
        # CAD (0, 3, 0) is the stock seat -> machine (0, 0, 0).
        matrix = np.asarray(self.geometry["transform"]["matrix"], dtype=float)
        point = matrix @ np.array([0.0, 3.0, 0.0, 1.0])
        np.testing.assert_allclose(point[:3], [0.0, 0.0, 0.0], atol=1e-9)

    # -- provenance and staleness -----------------------------------------
    def test_step_sha256_matches_the_committed_step(self):
        digest = hashlib.sha256(STEP.read_bytes()).hexdigest()
        self.assertEqual(self.geometry["step_sha256"], digest)
        self.assertTrue(self.geometry["ocp_version"])

    def test_parts_count_matches_occurrences(self):
        self.assertEqual(int(self.geometry["parts_count"]), 295)

    # -- role coverage -----------------------------------------------------
    def test_link_counts_sum_to_295(self):
        counts = self.geometry["link_counts"]
        self.assertEqual(sum(int(v) for v in counts.values()), 295)
        listed = sum(len(v) for v in self.geometry["links"].values())
        self.assertEqual(listed, 295)

    def test_unknown_and_placeholder_parts_are_reported_by_name(self):
        self.assertIn("Cold_Tool_6mm_Shank:1", self.geometry["unassigned_parts"])
        self.assertIn(
            "Wax_Block_Cast_120x100x56:1", self.geometry["stock_placeholder_parts"]
        )

    def test_unassigned_and_placeholder_parts_do_not_join_a_link(self):
        links = self.geometry["links"]
        for name in self.geometry["unassigned_parts"]:
            self.assertIn(name, links["unassigned"])
            for link in ("static", "orbit", "z", "radial", "tilt"):
                self.assertNotIn(name, links[link])
        for name in self.geometry["stock_placeholder_parts"]:
            self.assertIn(name, links["stock_placeholder"])
        self.assertFalse((MODELS / "stock_placeholder.glb").exists())

    def test_every_link_name_is_unique(self):
        seen: dict[str, str] = {}
        for link, names in self.geometry["links"].items():
            for name in names:
                self.assertNotIn(name, seen, f"{name} in {link} and {seen.get(name)}")
                seen[name] = link

    # -- kinematic constants ----------------------------------------------
    def test_constants_match_the_verified_cad_measurements(self):
        self.assertAlmostEqual(float(self.geometry["pivot_to_tip_mm"]), 60.0, delta=0.05)
        self.assertAlmostEqual(
            float(self.geometry["pivot_radial_offset_mm"]), 0.0, delta=0.05
        )
        self.assertAlmostEqual(
            float(self.geometry["tangential_tool_offset_mm"]), 0.0, delta=0.05
        )
        r_travel = [float(v) for v in self.geometry["r_travel_mm"]]
        self.assertAlmostEqual(r_travel[0], -51.0, delta=0.5)
        self.assertAlmostEqual(r_travel[1], 135.0, delta=0.5)
        reference = [float(v) for v in self.geometry["tool_reference_point_mm"]]
        np.testing.assert_allclose(reference, [0.0, 0.0, 91.0], atol=0.05)

    def test_cad_reference_pose_matches_the_pivot_height(self):
        pose = self.geometry["cad_reference_pose"]
        self.assertAlmostEqual(float(pose["r"]), 0.0, delta=0.05)
        self.assertAlmostEqual(float(pose["theta_deg"]), 0.0, delta=0.05)
        self.assertAlmostEqual(float(pose["phi_deg"]), 0.0, delta=0.05)
        self.assertAlmostEqual(float(pose["h"]), 151.0, delta=0.05)

    def test_null_constants_carry_a_reason(self):
        reasons = self.geometry.get("reasons", {})
        for key in ("r_travel_mm", "h_travel_mm", "theta_travel_deg"):
            if self.geometry.get(key) is None:
                self.assertTrue(reasons.get(key), f"{key} is null without a reason")

    def test_home_pose_is_never_inferred(self):
        self.assertIsNone(self.geometry["home_pose"])

    def test_pivot_candidates_record_the_dowel_alternative(self):
        names = {candidate["name"] for candidate in self.geometry["pivot_candidates"]}
        self.assertIn("servo_horn_axis", names)
        self.assertIn("dowel_3x37_axis", names)

    def test_tool_block_matches_the_blade(self):
        tool = self.geometry["tool"]
        self.assertAlmostEqual(float(tool["blade_thickness_mm"]), 1.2, places=6)
        self.assertAlmostEqual(float(tool["blade_width_mm"]), 6.0, places=6)
        self.assertAlmostEqual(float(tool["blade_length_mm"]), 14.0, places=6)
        self.assertAlmostEqual(float(tool["shaft_radius_mm"]), 2.5, places=6)
        self.assertAlmostEqual(float(tool["body_radius_mm"]), 3.5, places=6)
        self.assertAlmostEqual(float(tool["head_clearance_mm"]), 46.6, delta=0.5)
        envelope = tool["head_envelope"]
        self.assertIn(envelope["shape"], ("box", "capsule"))
        self.assertEqual(len(envelope["half_extents_mm"]), 3)


class TestLinkMeshes(ReleasesClassFixtures, unittest.TestCase):
    _class_fixtures = ("trimesh", "geometry", "paths", "scenes")

    @classmethod
    def setUpClass(cls):
        import trimesh

        cls.trimesh = trimesh
        cls.geometry = load_geometry()
        cls.paths = sorted(MODELS.glob("*.glb"))
        cls.scenes = {path.stem: trimesh.load(path) for path in cls.paths}

    def test_glb_total_stays_within_budget(self):
        total = sum(path.stat().st_size for path in self.paths)
        self.assertLessEqual(total, 8 * 1024 * 1024)
        self.assertGreater(total, 0)

    def test_all_expected_links_exist(self):
        self.assertEqual(
            {path.stem for path in self.paths},
            {"static", "orbit", "z", "radial", "tilt", "unassigned"},
        )

    def test_mesh_node_names_match_cad_occurrences(self):
        for link, scene in self.scenes.items():
            expected = set(self.geometry["links"][link])
            self.assertTrue(set(scene.geometry).issubset(expected), link)
            for name in scene.geometry:
                self.assertIn(name, expected)

    def test_tilt_glb_cartridge_lowest_vertex_is_the_reference_point(self):
        scene = self.scenes["tilt"]
        names = [name for name in scene.geometry if name.startswith("T12_K_Cartridge")]
        self.assertEqual(len(names), 1)
        mesh = scene.geometry[names[0]]
        reference = float(self.geometry["tool_reference_point_mm"][2])
        self.assertAlmostEqual(float(mesh.bounds[0][2]), reference, delta=0.05)
        # The cartridge continues above the 14 mm blade, so it must reach at
        # least the blade top at the CAD reference pose.
        self.assertGreaterEqual(float(mesh.bounds[1][2]), reference + 14.0 - 1e-6)


class TestRuntimeNeverDependsOnOcp(unittest.TestCase):
    def test_runtime_modules_do_not_import_ocp(self):
        for name in RUNTIME_MODULES:
            path = ROOT / name
            self.assertTrue(path.exists(), f"{name} is missing")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name.split(".")[0] == "OCP", name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(node.module.split(".")[0] == "OCP", name)

    def test_static_js_does_not_reference_the_step_file(self):
        for path in (ROOT / "static").glob("*.js"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(".stp", text, path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

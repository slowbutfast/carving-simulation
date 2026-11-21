"""Tests for the single runtime tool definition (blade-tool-model)."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kinematics  # noqa: E402
import tool_model  # noqa: E402

try:  # noqa: E402
    from tests._tiers import ReleasesClassFixtures
except ImportError:  # direct `python tests/test_tool_model.py`
    from _tiers import ReleasesClassFixtures

X = np.array([1.0, 0.0, 0.0])
Y = np.array([0.0, 1.0, 0.0])
Z = np.array([0.0, 0.0, 1.0])


class TestToolFrame(ReleasesClassFixtures, unittest.TestCase):
    _class_fixtures = ("config",)

    @classmethod
    def setUpClass(cls):
        cls.config = kinematics.load_config()

    def test_radial_support_extent_covers_the_unheated_shaft(self):
        # Rapid clearance must keep the 2.5 mm shaft out of the stock too, not
        # only the ~1 mm heated blade reach at phi = 0.
        extent = tool_model.radial_support_extent(0.0, self.config)
        self.assertGreaterEqual(
            extent, float(self.config["tool"]["shaft_radius_mm"])
        )

    def test_frame_at_zero_is_the_cad_blade_orientation(self):
        pose = tool_model.tool_pose([0.0, 0.0, 0.0], 0.0, 0.0, self.config)
        np.testing.assert_allclose(pose.a_n, -X, atol=1e-12)
        np.testing.assert_allclose(pose.a_w, Y, atol=1e-12)
        np.testing.assert_allclose(pose.u, -Z, atol=1e-12)
        np.testing.assert_allclose(np.cross(pose.a_n, pose.a_w), pose.u, atol=1e-12)

    def test_frame_is_right_handed_orthonormal_across_the_grid(self):
        for phi_deg in (-60.0, 0.0, 45.0, 75.0):
            for theta_deg in (0.0, 90.0, 225.0):
                theta = math.radians(theta_deg)
                phi = math.radians(phi_deg)
                pose = tool_model.tool_pose([0.0, 0.0, 0.0], theta, phi, self.config)
                e_theta = np.array([-math.sin(theta), math.cos(theta), 0.0])
                np.testing.assert_allclose(pose.a_w, e_theta, atol=1e-12)
                np.testing.assert_allclose(np.linalg.norm(pose.a_n), 1.0, atol=1e-12)
                np.testing.assert_allclose(np.linalg.norm(pose.a_w), 1.0, atol=1e-12)
                np.testing.assert_allclose(np.linalg.norm(pose.u), 1.0, atol=1e-12)
                np.testing.assert_allclose(np.dot(pose.a_n, pose.a_w), 0.0, atol=1e-12)
                np.testing.assert_allclose(np.dot(pose.a_n, pose.u), 0.0, atol=1e-12)
                np.testing.assert_allclose(np.dot(pose.a_w, pose.u), 0.0, atol=1e-12)
                np.testing.assert_allclose(
                    np.cross(pose.a_n, pose.a_w), pose.u, atol=1e-12
                )


class TestHeatedSdf(ReleasesClassFixtures, unittest.TestCase):
    """All distances are negative inside the heated region."""

    _class_fixtures = ("config", "kerf", "length", "pose")

    @classmethod
    def setUpClass(cls):
        cls.config = kinematics.load_config()
        cls.kerf = float(cls.config["tool"]["melt_kerf_mm"])
        cls.length = float(cls.config["tool"]["heated_length_mm"])
        cls.pose = tool_model.tool_pose([0.0, 0.0, 0.0], 0.0, 0.0, cls.config)

    def sdf(self, points):
        return tool_model.heated_sdf(np.asarray(points, dtype=float), self.pose, self.config)

    def test_analytic_probes_from_the_spec(self):
        kerf = self.kerf
        mid = self.length / 2.0
        self.assertAlmostEqual(float(self.sdf([[0.0, 0.0, 0.0]])[0]), -kerf, places=9)
        self.assertAlmostEqual(
            float(self.sdf([[0.6 + kerf, 0.0, mid]])[0]), 0.0, places=9
        )
        self.assertAlmostEqual(
            float(self.sdf([[0.0, 3.0 + kerf + 1.0, mid]])[0]), 1.0, places=9
        )
        self.assertAlmostEqual(
            float(self.sdf([[0.0, 0.0, -kerf - 2.0]])[0]), 2.0, places=9
        )

    def test_inside_is_negative_and_outside_positive(self):
        values = self.sdf([[0.0, 0.0, self.length / 2], [5.0, 0.0, self.length / 2]])
        self.assertLess(values[0], 0.0)
        self.assertGreater(values[1], 0.0)


class TestSupportPlacement(ReleasesClassFixtures, unittest.TestCase):
    _class_fixtures = (
        "config",
        "tool",
        "kerf",
        "length",
        "half_thickness",
        "half_width",
    )

    @classmethod
    def setUpClass(cls):
        cls.config = kinematics.load_config()
        cls.tool = cls.config["tool"]
        cls.kerf = float(cls.tool["melt_kerf_mm"])
        cls.length = float(cls.tool["heated_length_mm"])
        cls.half_thickness = 0.5 * float(cls.tool["blade_thickness_mm"])
        cls.half_width = 0.5 * float(cls.tool["blade_width_mm"])

    def corners(self, pose):
        """Un-inflated prism corners relative to the reference point."""
        values = []
        for n in (-self.half_thickness, self.half_thickness):
            for w in (-self.half_width, self.half_width):
                for s in (0.0, self.length):
                    values.append(n * pose.a_n + w * pose.a_w - s * pose.u)
        return np.asarray(values)

    def test_placement_is_tangent_for_arbitrary_normals(self):
        rng = np.random.default_rng(20261119)
        for _ in range(500):
            normal = rng.normal(size=3)
            normal /= np.linalg.norm(normal)
            theta = rng.uniform(-math.pi, math.pi)
            phi = rng.uniform(math.radians(-60.0), math.radians(75.0))
            cc = rng.uniform(-20.0, 20.0, size=3)
            axes = tool_model.tool_pose(cc, theta, phi, self.config)
            cl = tool_model.place_on_contact(cc, normal, axes, self.config)
            pose = tool_model.tool_pose(cl, theta, phi, self.config)
            value = float(tool_model.heated_sdf([cc], pose, self.config)[0])
            self.assertAlmostEqual(value, 0.0, places=9)
            # The tangent plane touches the rounded inflated box at cc: one
            # micron to the wax side is outside, one micron to the tool side is
            # inside. That is the half-space property without sampling corners
            # of an over-approximating per-axis box.
            wax_side = float(
                tool_model.heated_sdf([cc - 1e-6 * normal], pose, self.config)[0]
            )
            tool_side = float(
                tool_model.heated_sdf([cc + 1e-6 * normal], pose, self.config)[0]
            )
            self.assertAlmostEqual(wax_side, 1e-6, places=9)
            self.assertAlmostEqual(tool_side, -1e-6, places=9)

    def test_flat_top_contact_offsets_by_the_kerf_only(self):
        cc = np.array([3.0, -2.0, 40.0])
        axes = tool_model.tool_pose(cc, 0.0, 0.0, self.config)
        cl = tool_model.place_on_contact(cc, Z, axes, self.config)
        np.testing.assert_allclose(cl, cc + self.kerf * Z, atol=1e-12)

    def test_tangential_normal_is_not_a_scalar_radial_offset(self):
        cc = np.array([10.0, 0.0, 40.0])
        axes = tool_model.tool_pose(cc, 0.0, 0.0, self.config)
        cl = tool_model.place_on_contact(cc, Y, axes, self.config)
        naive = cc + (self.half_thickness + self.kerf) * Y
        self.assertGreater(float(np.linalg.norm(cl - naive)), 1.0)


class TestBodyCollision(ReleasesClassFixtures, unittest.TestCase):
    """trimesh's signed distance / contains is POSITIVE inside a mesh.

    The wax SDF is the opposite (negative inside). Every addition that touches
    both conventions must state which one it is using.
    """

    _class_fixtures = ("config",)

    @classmethod
    def setUpClass(cls):
        cls.config = kinematics.load_config()

    def wall(self, face_offset: float) -> trimesh.Trimesh:
        # Face normal -X (the a_n direction at theta=0, phi=0). The wall spans
        # 20-40 mm above the reference point along -u (+Z here).
        box = trimesh.creation.box(extents=(10.0, 20.0, 20.0))
        # x face toward the tool at x = -face_offset
        box.apply_translation([-face_offset - 5.0, 0.0, 30.0])
        return box

    def test_shaft_wall_at_two_mm_penetrates_at_three_does_not(self):
        pose = tool_model.tool_pose([0.0, 0.0, 0.0], 0.0, 0.0, self.config)
        self.assertTrue(bool(tool_model.body_penetrates(self.wall(2.0), [pose], self.config)[0]))
        self.assertFalse(bool(tool_model.body_penetrates(self.wall(3.0), [pose], self.config)[0]))

    def test_head_envelope_is_read_from_the_geometry(self):
        geometry = self.config["geometry"]["tool"]
        envelope = geometry["head_envelope"]
        centre = np.asarray(envelope["center_mm"], dtype=float)
        half = np.asarray(envelope["half_extents_mm"], dtype=float)
        pose = tool_model.tool_pose([0.0, 0.0, 0.0], 0.0, 0.0, self.config)
        # A point well inside the recorded head box.
        local = centre + np.array([0.0, 0.0, -half[2] * 0.5])
        world = pose.tip_xyz + local[0] * pose.a_n + local[1] * pose.a_w - local[2] * pose.u
        slab = trimesh.creation.box(extents=(6.0, 6.0, 6.0))
        slab.apply_translation(world)
        self.assertTrue(bool(tool_model.body_penetrates(slab, [pose], self.config)[0]))


class TestFeedClass(ReleasesClassFixtures, unittest.TestCase):
    _class_fixtures = ("config",)

    @classmethod
    def setUpClass(cls):
        cls.config = kinematics.load_config()

    def test_radial_feed_is_broadside_and_tangential_is_slice(self):
        pose = tool_model.tool_pose([0.0, 0.0, 0.0], 0.0, 0.0, self.config)
        self.assertEqual(tool_model.feed_class(X, pose, self.config), "broadside")
        self.assertEqual(tool_model.feed_class(Y, pose, self.config), "slice")
        self.assertEqual(tool_model.feed_class(-Z, pose, self.config), "plunge")

    def test_threshold_comes_from_config(self):
        pose = tool_model.tool_pose([0.0, 0.0, 0.0], 0.0, 0.0, self.config)
        angle = math.radians(30.0)
        direction = math.cos(angle) * (-X) + math.sin(angle) * Y
        self.assertEqual(tool_model.feed_class(direction, pose, self.config), "broadside")
        narrow = {
            **self.config,
            "toolpath": {**self.config["toolpath"], "broadside_threshold_deg": 20.0},
        }
        self.assertNotEqual(tool_model.feed_class(direction, pose, narrow), "broadside")


if __name__ == "__main__":
    unittest.main(verbosity=2)

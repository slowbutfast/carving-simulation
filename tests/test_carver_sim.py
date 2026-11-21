"""Automated tests for the 4-DOF thermal wax carver simulation MVP.

Covers the Python single-source-of-truth for kinematics, facial sculpting,
synthetic toolpaths, and the columnar FastAPI payload contract.
"""

from __future__ import annotations

import base64
import copy
import json
import math
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kinematics  # noqa: E402
import face_sculpt  # noqa: E402
import tool_model  # noqa: E402
import toolpath_sim  # noqa: E402
from server import app  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

CONFIG_PATH = ROOT / "machine_config.json"
HW_FIXTURE = ROOT / "tests" / "fixtures" / "hardware_poses.json"


def load_config(**overrides):
    cfg = kinematics.load_config()
    for dotted, value in overrides.items():
        node = cfg
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return cfg


def fk_frame(r, theta, h, phi, config):
    """Build the flat frame dict consumed by the timing helpers."""
    fk = kinematics.forward_kinematics(r, theta, h, phi, config)
    return {
        "r": r,
        "theta": theta,
        "h": h,
        "phi": phi,
        "r_s": fk.r_s,
        "theta_s": fk.theta_s,
        "z_s": fk.z_s,
        "tip_xyz_wax": fk.tip_xyz_wax,
        "tool_axis_wax": fk.tool_axis_wax,
    }


def engaged_cone_displacement(a, b, length_mm, samples=17):
    """Independent dense-sample check of the full heated blade sweep."""
    tip_a = np.asarray(a["tip_xyz_wax"], dtype=float)
    tip_b = np.asarray(b["tip_xyz_wax"], dtype=float)
    axis_a = np.asarray(a["tool_axis_wax"], dtype=float)
    axis_b = np.asarray(b["tool_axis_wax"], dtype=float)
    worst = 0.0
    for s in np.linspace(0.0, length_mm, samples):
        pa = tip_a - axis_a * s
        pb = tip_b - axis_b * s
        worst = max(worst, float(np.linalg.norm(pb - pa)))
    return worst


class TestConfigAndForwardKinematics(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.x = self.config["arm_radial_offset_mm"]
        self.h2 = self.config["arm_to_pivot_z_mm"]
        self.p = self.config["pivot_to_tip_mm"]

    def test_config_declares_datums_tool_and_limits(self):
        self.assertAlmostEqual(self.p, 60.0, delta=0.05)
        self.assertAlmostEqual(self.x, 0.0, delta=0.05)
        self.assertAlmostEqual(self.h2, 0.0, delta=0.05)
        self.assertEqual(self.config["stock"]["R_stock_mm"], 40.0)
        self.assertEqual(self.config["stock"]["H_stock_mm"], 120.0)
        self.assertEqual(self.config["stock"]["z_plinth_mm"], 10.0)
        self.assertEqual(self.config["stock"]["finish_allowance_mm"], 1.5)
        self.assertEqual(self.config["singularity"]["r_s_min_mm"], 2.0)
        self.assertEqual(self.config["singularity"]["theta_dot_warn_rad_s"], 3.0)
        self.assertLessEqual(self.config["v_max"]["theta_rad_s"], 1.0)
        for key in (
            "blade_thickness_mm",
            "blade_width_mm",
            "blade_length_mm",
            "melt_kerf_mm",
            "heated_length_mm",
        ):
            self.assertIn(key, self.config["tool"])
        for key in (
            "tip_radius_mm",
            "cone_half_angle_deg",
            "engaged_length_mm",
            "tip_width_mm",
            "shank_radius_mm",
            "shank_length_mm",
        ):
            self.assertNotIn(key, self.config["tool"])

    def test_toolpath_module_has_no_cone_geometry(self):
        text = Path(toolpath_sim.__file__).read_text(encoding="utf-8")
        for token in (
            "cone_half_angle_deg",
            "tip_radius_mm",
            "engaged_length_mm",
            "tip_width_mm",
            "shank_radius_mm",
            "shank_length_mm",
        ):
            self.assertNotIn(token, text, f"toolpath_sim still references {token}")

    def test_cad_reference_pose_reproduces_the_cad_reference_point(self):
        pose = self.config["cad_reference_pose"]
        fk = kinematics.forward_kinematics(
            float(pose["r"]),
            math.radians(float(pose["theta_deg"])),
            float(pose["h"]),
            math.radians(float(pose["phi_deg"])),
            self.config,
        )
        np.testing.assert_allclose(fk.tip_xyz_wax, [0.0, 0.0, 91.0], atol=0.05)

    def test_fk_phi_zero(self):
        r, theta, h, phi = 60.0, 0.30, 80.0, 0.0
        fk = kinematics.forward_kinematics(r, theta, h, phi, self.config)
        self.assertAlmostEqual(fk.theta_s, theta, places=8)
        self.assertAlmostEqual(fk.r_s, r - self.x, places=8)
        self.assertAlmostEqual(fk.z_s, h - self.p - self.h2, places=8)
        tip = np.asarray(fk.tip_xyz_wax)
        np.testing.assert_allclose(
            tip,
            [fk.r_s * math.cos(theta), fk.r_s * math.sin(theta), fk.z_s],
            atol=1e-9,
        )
        np.testing.assert_allclose(
            np.asarray(fk.tool_axis_wax), [0.0, 0.0, -1.0], atol=1e-9
        )

    def test_fk_phi_ninety_degrees(self):
        r, theta, h = 60.0, 0.4, 80.0
        fk = kinematics.forward_kinematics(r, theta, h, math.pi / 2, self.config)
        self.assertAlmostEqual(fk.r_s, r - self.x - self.p, places=8)
        self.assertAlmostEqual(fk.z_s, h - self.h2, places=8)
        # +phi tilts the tip inward (decreasing r_s).
        lower = kinematics.forward_kinematics(r, theta, h, 0.2, self.config)
        higher = kinematics.forward_kinematics(r, theta, h, 0.8, self.config)
        self.assertLess(higher.r_s, lower.r_s)

    def test_fk_arbitrary_phi_vectors(self):
        r, theta, h, phi = 55.0, -0.9, 72.0, 0.37
        fk = kinematics.forward_kinematics(r, theta, h, phi, self.config)
        self.assertAlmostEqual(
            fk.r_s, r - self.x - self.p * math.sin(phi), places=8
        )
        self.assertAlmostEqual(
            fk.z_s, h - self.p * math.cos(phi) - self.h2, places=8
        )
        axis = np.asarray(fk.tool_axis_wax)
        expected = np.asarray(
            [
                -math.sin(phi) * math.cos(theta),
                -math.sin(phi) * math.sin(theta),
                -math.cos(phi),
            ]
        )
        np.testing.assert_allclose(axis, expected, atol=1e-9)
        self.assertAlmostEqual(float(np.linalg.norm(axis)), 1.0, places=9)

    @unittest.skipUnless(
        HW_FIXTURE.exists(),
        "pending physical hardware pose measurements (fixture not recorded yet)",
    )
    def test_hardware_calibration_fixture_within_one_mm(self):
        fixture = json.loads(HW_FIXTURE.read_text(encoding="utf-8"))
        for pose in fixture["poses"]:
            fk = kinematics.forward_kinematics(
                pose["r"], pose["theta"], pose["h"], math.radians(pose["phi_deg"]),
                self.config,
            )
            measured = pose["measured"]
            self.assertAlmostEqual(fk.r_s, measured["r_s"], delta=1.0)
            self.assertAlmostEqual(fk.theta_s, measured["theta_s"], delta=1.0)
            self.assertAlmostEqual(fk.z_s, measured["z_s"], delta=1.0)


class TestInverseKinematicsAndLimits(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_ik_round_trip_with_phi_policy(self):
        theta = 0.5
        phi = 0.31
        r, h = 64.0, 96.0
        fk = kinematics.forward_kinematics(r, theta, h, phi, self.config)
        normal = (
            math.sin(phi) * math.cos(theta),
            math.sin(phi) * math.sin(theta),
            math.cos(phi),
        )
        ik = kinematics.inverse_kinematics_with_policy(
            (fk.r_s, fk.theta_s, fk.z_s), normal, self.config
        )
        self.assertTrue(ik.ok, ik.diagnostics)
        self.assertAlmostEqual(ik.phi, phi, places=6)
        rt = kinematics.forward_kinematics(ik.r, ik.theta, ik.h, ik.phi, self.config)
        self.assertAlmostEqual(rt.r_s, fk.r_s, places=6)
        self.assertAlmostEqual(rt.theta_s, fk.theta_s, places=6)
        self.assertAlmostEqual(rt.z_s, fk.z_s, places=6)

    def test_phi_policy_clamped_is_informational(self):
        config = copy.deepcopy(self.config)
        config["limits"]["phi_limits_deg"] = [-45.0, 60.0]
        phi_ideal = math.radians(80.0)
        normal = (math.sin(phi_ideal), 0.0, math.cos(phi_ideal))
        ik = kinematics.inverse_kinematics_with_policy(
            (20.0, 0.0, 45.0), normal, config
        )
        codes = {d.code for d in ik.diagnostics}
        self.assertIn("PHI_POLICY_CLAMPED", codes)
        self.assertAlmostEqual(ik.phi, math.radians(60.0), places=6)
        self.assertTrue(ik.ok)
        clamped = next(d for d in ik.diagnostics if d.code == "PHI_POLICY_CLAMPED")
        self.assertEqual(clamped.severity, "info")
        # Clamping the policy must never silently clamp a joint past soft limits.
        self.assertNotIn("SOFT_LIMIT_EXCEEDED", codes)

    def test_tangential_normal_falls_back_to_zero_phi(self):
        theta = 0.8
        normal = (-math.sin(theta), math.cos(theta), 0.0)
        ik = kinematics.inverse_kinematics_with_policy(
            (18.0, theta, 40.0), normal, self.config
        )
        self.assertTrue(ik.ok)
        self.assertAlmostEqual(ik.phi, 0.0, places=9)
        rt = kinematics.forward_kinematics(ik.r, ik.theta, ik.h, ik.phi, self.config)
        self.assertAlmostEqual(rt.r_s, 18.0, places=6)
        self.assertAlmostEqual(rt.z_s, 40.0, places=6)

    def test_out_of_bounds_joint_is_rejected_with_axis(self):
        ik = kinematics.inverse_kinematics_with_policy(
            (200.0, 0.0, 40.0), None, self.config
        )
        self.assertFalse(ik.ok)
        err = next(d for d in ik.diagnostics if d.code == "SOFT_LIMIT_EXCEEDED")
        self.assertEqual(err.severity, "error")
        self.assertEqual(err.axis, "r")
        self.assertGreater(abs(err.value), self.config["limits"]["r_limits_mm"][1])

    def test_height_limit_is_enforced(self):
        ik = kinematics.inverse_kinematics_with_policy(
            (10.0, 0.0, 400.0), None, self.config
        )
        self.assertFalse(ik.ok)
        codes = {d.code for d in ik.diagnostics}
        self.assertIn("SOFT_LIMIT_EXCEEDED", codes)

    def test_signed_r_solution_avoids_a_configured_orbit_stop(self):
        # Synthetic fixture: it asserts the policy, not that +/-170 deg was
        # measured from the CAD. previous=160 deg, target azimuth=-170 deg.
        config = copy.deepcopy(self.config)
        config["limits"]["theta_limits_deg"] = [-170.0, 170.0]
        previous = math.radians(160.0)
        target_azimuth = math.radians(-170.0)
        target = (20.0, target_azimuth, 40.0)
        ik = kinematics.inverse_kinematics_with_policy(
            target, None, config, previous_theta_rad=previous
        )
        self.assertTrue(ik.ok, ik.diagnostics)
        self.assertLess(ik.r, 0.0)
        self.assertAlmostEqual(math.degrees(ik.theta), 10.0, places=6)
        fk = kinematics.forward_kinematics(ik.r, ik.theta, ik.h, ik.phi, config)
        expected = (
            20.0 * math.cos(target_azimuth),
            20.0 * math.sin(target_azimuth),
            40.0,
        )
        np.testing.assert_allclose(fk.tip_xyz_wax, expected, atol=1e-5)

    def test_unknown_cad_travel_limit_requires_an_explicit_fallback(self):
        geometry = copy.deepcopy(self.config["geometry"])
        geometry["theta_travel_deg"] = None
        raw = copy.deepcopy(self.config)
        raw.pop("geometry", None)
        raw["limits"]["theta_limits_deg"] = None
        raw["limits"].pop("fallbacks", None)
        with self.assertRaises(kinematics.ConfigError):
            kinematics.merge_geometry(raw, geometry)
        # An explicitly labelled fallback is accepted.
        raw["limits"]["theta_limits_deg"] = [-170.0, 170.0]
        raw["limits"]["fallbacks"] = {
            "theta_limits_deg": {"verified": False, "reason": "unmeasured"}
        }
        merged = kinematics.merge_geometry(raw, geometry)
        self.assertEqual(merged["limits"]["theta_limits_deg"], [-170.0, 170.0])
        self.assertIn(
            "theta_limits_deg", merged["geometry_provenance"]["unverified_limits"]
        )

    def test_configuration_may_narrow_but_never_widen_cad_travel(self):
        geometry = self.config["geometry"]
        raw = copy.deepcopy(self.config)
        raw.pop("geometry", None)
        raw["limits"]["r_limits_mm"] = [-1000.0, 1000.0]
        merged = kinematics.merge_geometry(raw, geometry)
        self.assertEqual(merged["limits"]["r_limits_mm"], [-51.0, 135.0])
        raw["limits"]["r_limits_mm"] = [0.0, 100.0]
        narrowed = kinematics.merge_geometry(raw, geometry)
        self.assertEqual(narrowed["limits"]["r_limits_mm"], [0.0, 100.0])

    def test_known_cad_travel_rejects_an_out_of_range_target(self):
        ik = kinematics.inverse_kinematics_with_policy(
            (140.0, 0.0, 40.0), None, self.config
        )
        self.assertFalse(ik.ok)
        err = next(d for d in ik.diagnostics if d.code == "SOFT_LIMIT_EXCEEDED")
        self.assertEqual(err.axis, "r")


class TestTipSpeedTimingAndSingularity(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.x = self.config["arm_radial_offset_mm"]
        self.p = self.config["pivot_to_tip_mm"]
        self.h2 = self.config["arm_to_pivot_z_mm"]
        self.feed = self.config["feeds"]["feed_cut_mm_s"]

    def test_pure_turntable_rotation_reports_relative_tip_speed(self):
        rs = 30.0
        r = rs + self.x
        h = 50.0 + self.p + self.h2
        a = fk_frame(r, 0.0, h, 0.0, self.config)
        b = fk_frame(r, 0.1, h, 0.0, self.config)
        dt, v_tip = kinematics.segment_timing(a, b, False, self.config)
        self.assertAlmostEqual(dt, rs * 0.1 / self.feed, places=6)
        self.assertAlmostEqual(v_tip, rs * 0.1 / dt, places=6)
        self.assertAlmostEqual(v_tip, self.feed, places=6)

    def test_combined_motion_uses_full_relative_tip_speed(self):
        a = fk_frame(58.0, 0.0, 95.0, 0.0, self.config)
        b = fk_frame(61.5, 0.12, 97.5, 0.22, self.config)
        dt, v_tip = kinematics.segment_timing(a, b, False, self.config)
        expected = math.sqrt(
            ((b["r_s"] - a["r_s"]) / dt) ** 2
            + (0.5 * (a["r_s"] + b["r_s"]) * (b["theta_s"] - a["theta_s"]) / dt) ** 2
            + ((b["z_s"] - a["z_s"]) / dt) ** 2
        )
        self.assertAlmostEqual(v_tip, expected, places=6)
        self.assertGreater(v_tip, (b["theta_s"] - a["theta_s"]) * 0.0)  # nonzero

    def test_timing_respects_joint_velocity_limits(self):
        a = fk_frame(70.0, 0.0, 90.0, 0.0, self.config)
        b = fk_frame(70.0, 2.0, 90.0, 0.0, self.config)
        rapid = True
        dt, _ = kinematics.segment_timing(a, b, rapid, self.config)
        vmax = self.config["v_max"]["theta_rad_s"]
        self.assertLessEqual(2.0 / dt, vmax + 1e-9)

    def test_near_axis_fast_rotation_emits_singularity(self):
        config = copy.deepcopy(self.config)
        r = 1.0 + config["arm_radial_offset_mm"]
        h = 40.0 + config["pivot_to_tip_mm"] + config["arm_to_pivot_z_mm"]
        joints = [
            {"r": r, "theta": 0.0, "h": h, "phi": 0.0},
            {"r": r, "theta": 0.5, "h": h, "phi": 0.0},
            {"r": r, "theta": 1.0, "h": h, "phi": 0.0},
        ]
        frames, diagnostics = kinematics.build_trajectory(joints, [False, False, False], config)
        self.assertEqual(len(frames), 3)
        codes = {d.code for d in diagnostics}
        self.assertIn("SINGULARITY_HIGH_THETA_DOT", codes)
        for i in range(1, len(frames)):
            self.assertAlmostEqual(
                frames[i]["theta_s"], frames[i]["theta"], places=9
            )
        # timestamps strictly increase
        self.assertGreater(frames[1]["t"], 0.0)
        self.assertLess(frames[0]["t"], frames[1]["t"])

    def test_axis_crossing_emits_singularity_on_both_sides(self):
        config = copy.deepcopy(self.config)
        h = 40.0 + config["pivot_to_tip_mm"] + config["arm_to_pivot_z_mm"]
        joints = [
            {"r": 1.0, "theta": 0.0, "h": h, "phi": 0.0},
            {"r": -1.0, "theta": 0.5, "h": h, "phi": 0.0},
        ]
        frames, diagnostics = kinematics.build_trajectory(
            joints, [False, False], config
        )
        self.assertEqual(len(frames), 2)
        codes = {d.code for d in diagnostics}
        self.assertIn("SINGULARITY_HIGH_THETA_DOT", codes)
        self.assertLessEqual(config["v_max"]["theta_rad_s"], 1.0)

    def test_unwrapped_theta_has_no_wrap_discontinuity(self):
        r = 20.0 + self.config["arm_radial_offset_mm"]
        h = 60.0 + self.p + self.h2
        joints = [
            {"r": r, "theta": math.radians(deg), "h": h, "phi": 0.0}
            for deg in (0.0, 90.0, 180.0, 270.0, 360.0, 450.0)
        ]
        frames, _ = kinematics.build_trajectory(joints, [False] * 6, self.config)
        self.assertAlmostEqual(frames[-1]["theta_s"], 2.5 * math.pi, places=6)
        for prev, cur in zip(frames, frames[1:]):
            self.assertGreater(cur["theta_s"], prev["theta_s"])


class TestFacialSculpting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Pinned to the analytic ellipsoid preset: `machine_config.json` points
        # `target_mesh.path` at the pre-normalized `head_2`, which has no
        # landmark sidecar (see TestHead2Target).
        cls.config = load_config(target_mesh=None)
        cls.base = face_sculpt.load_base_head(cls.config)
        cls.landmarks = face_sculpt.load_landmarks(cls.config)

    def test_base_head_is_watertight_and_seated(self):
        mesh = self.base
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)
        self.assertGreater(mesh.volume, 0.0)
        z_plinth = self.config["stock"]["z_plinth_mm"]
        self.assertAlmostEqual(float(mesh.bounds[0][2]), z_plinth, delta=0.75)

    def test_landmarks_cover_all_facial_features(self):
        for name in ("nose", "brow", "cheeks", "jaw", "chin"):
            self.assertIn(name, self.landmarks)
            self.assertGreater(self.landmarks[name]["max_displacement_mm"], 0.0)

    def test_positive_sculpt_preserves_watertightness_and_bounds(self):
        params = {"nose": 1.0, "brow": 0.6, "cheeks": 0.4, "jaw": 0.3, "chin": 0.8}
        result = face_sculpt.apply_facial_modifications(self.base, params, self.config)
        self.assertEqual(result.diagnostics, [])
        mesh = result.mesh
        self.assertIsNotNone(mesh)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)
        self.assertGreater(mesh.volume, 0.0)
        self.assertTrue(result.self_intersection_free)
        max_r = float(np.max(np.linalg.norm(mesh.vertices[:, :2], axis=1)))
        allowed_r = (
            self.config["stock"]["R_stock_mm"]
            - self.config["stock"]["finish_allowance_mm"]
        )
        self.assertLessEqual(max_r, allowed_r + 1e-6)
        self.assertGreaterEqual(float(mesh.bounds[0][2]), -1e-6)
        self.assertLessEqual(
            float(mesh.bounds[1][2]), self.config["stock"]["H_stock_mm"] + 1e-6
        )
        moved = np.linalg.norm(mesh.vertices - self.base.vertices, axis=1)
        self.assertGreater(float(np.max(moved)), 0.5)

    def test_sculpting_is_deterministic_and_preserves_topology(self):
        params = {"nose": 0.7, "chin": 0.5}
        a = face_sculpt.apply_facial_modifications(self.base, params, self.config)
        b = face_sculpt.apply_facial_modifications(self.base, params, self.config)
        np.testing.assert_allclose(a.mesh.vertices, b.mesh.vertices, atol=0.0)
        np.testing.assert_array_equal(a.mesh.faces, self.base.faces)

    def test_out_of_stock_deformation_reports_error(self):
        config = copy.deepcopy(self.config)
        config["stock"]["R_stock_mm"] = 24.0
        result = face_sculpt.apply_facial_modifications(
            self.base, {"nose": 1.0}, config
        )
        codes = {d.code for d in result.diagnostics}
        self.assertIn("STOCK_BOUNDS_EXCEEDED", codes)
        err = next(d for d in result.diagnostics if d.code == "STOCK_BOUNDS_EXCEEDED")
        self.assertEqual(err.severity, "error")


class TestSyntheticToolpaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ellipsoid preset again: the committed `head_2` target is exercised by
        # TestHead2Target and by the API tests below, which load the default
        # configuration.
        cls.config = load_config(target_mesh=None)
        cls.mesh = face_sculpt.load_base_head(cls.config)
        cls.sculpt = face_sculpt.apply_facial_modifications(
            cls.mesh, {"nose": 1.0, "chin": 0.6, "brow": 0.4}, cls.config
        ).mesh
        cls.result = toolpath_sim.generate_synthetic_carve_path(
            cls.sculpt, cls.config, preset="demo"
        )

    def test_frames_are_columnar_and_well_formed(self):
        frames = self.result.frames
        self.assertGreater(len(frames), 200)
        required = {
            "t", "r", "theta", "h", "phi", "r_s", "theta_s", "z_s",
            "v_tip", "is_rapid", "tip_xyz_wax", "tool_axis_wax", "stage",
        }
        self.assertTrue(required.issubset(frames[0].keys()))
        for prev, cur in zip(frames, frames[1:]):
            self.assertGreaterEqual(cur["t"], prev["t"] - 1e-12)
            self.assertGreaterEqual(cur["v_tip"], 0.0)

    def test_roughing_is_shadow_clipped_and_phi_zero(self):
        frames = [f for f in self.result.frames if f["stage"] == "roughing" and not f["is_rapid"]]
        self.assertGreater(len(frames), 50)
        for f in frames:
            self.assertAlmostEqual(math.degrees(abs(f["phi"])), 0.0, places=6)
        # Independent shadow check on a deterministic subset of poses. Use the
        # tip's physical azimuth: for a negative-r_s cut theta_s points 180 deg
        # away from the material being cut.
        stock = self.config["stock"]
        allowance = stock["finish_allowance_mm"]
        for f in frames[:: max(1, len(frames) // 12)]:
            theta = math.atan2(f["tip_xyz_wax"][1], f["tip_xyz_wax"][0])
            z = f["z_s"]
            e_r = np.array([math.cos(theta), math.sin(theta), 0.0])
            worst = 0.0
            for z_probe in np.linspace(z, stock["H_stock_mm"], 7):
                origin = np.array([[0.0, 0.0, z_probe]])
                hits, _, _ = self.mesh.ray.intersects_location(
                    origin, e_r[None, :], multiple_hits=True
                )
                if len(hits):
                    worst = max(worst, float(np.max(hits[:, 0] * e_r[0] + hits[:, 1] * e_r[1])))
            required = min(stock["R_stock_mm"], worst + allowance)
            self.assertGreaterEqual(abs(f["r_s"]), required - 1e-3)

    def test_rapids_retract_outside_stock_and_tool_extent(self):
        clearance = self.config["stock"]["retract_clearance_mm"]
        height = self.config["stock"]["H_stock_mm"]
        rapids = [f for f in self.result.frames if f["is_rapid"]]
        self.assertGreater(len(rapids), 0)
        for f in rapids:
            extent = tool_model.radial_support_extent(float(f["phi"]), self.config)
            limit = self.config["stock"]["R_stock_mm"] + clearance + extent
            # Above the stock plane a rapid is clear regardless of radius;
            # cross-axis repositions use that safe plane.
            clear = (
                abs(f["r_s"]) >= limit - 1e-6
                or f["z_s"] >= height + clearance - 1e-6
            )
            self.assertTrue(
                clear,
                f"rapid at r_s={f['r_s']:.3f}, z_s={f['z_s']:.3f} is not clear",
            )

    def test_no_cross_axis_move_below_the_stock_plane(self):
        # Switching the signed-r branch must happen above H_stock, never at a
        # cutting level; otherwise the blade sweeps through the head.
        height = float(self.config["stock"]["H_stock_mm"])
        stages = ("roughing", "finishing", "roughing_link", "finishing_link")
        for prev, cur in zip(self.result.frames, self.result.frames[1:]):
            if cur["is_rapid"] or cur["stage"] not in stages:
                continue
            if float(prev["r_s"]) * float(cur["r_s"]) < -1e-9:
                self.assertGreaterEqual(
                    min(float(prev["z_s"]), float(cur["z_s"])),
                    height - 1e-6,
                    (
                        f"non-rapid {cur['stage']} crosses r_s=0 at "
                        f"z={min(prev['z_s'], cur['z_s']):.2f} < {height}"
                    ),
                )

    def test_finishing_uses_phi_and_reports_unreachable_undercuts(self):
        finishing = [f for f in self.result.frames if f["stage"] == "finishing" and not f["is_rapid"]]
        self.assertGreater(len(finishing), 20)
        self.assertTrue(any(abs(f["phi"]) > 0.05 for f in finishing))
        codes = {d.code for d in self.result.diagnostics}
        self.assertIn("UNREACHABLE_UNDERCUT_AREA", codes)
        diag = next(d for d in self.result.diagnostics if d.code == "UNREACHABLE_UNDERCUT_AREA")
        self.assertEqual(diag.severity, "warning")
        self.assertGreater(diag.value, 0.0)

    def test_heated_blade_resampling_bound(self):
        tool = self.config["tool"]
        limit = 0.5 * (
            float(tool["blade_thickness_mm"]) + 2.0 * float(tool["melt_kerf_mm"])
        )
        frames = self.result.frames
        worst = 0.0
        for prev, cur in zip(frames, frames[1:]):
            if cur["is_rapid"]:
                continue
            a = tool_model.tool_pose(
                prev["tip_xyz_wax"], prev["theta"], prev["phi"], self.config
            )
            b = tool_model.tool_pose(
                cur["tip_xyz_wax"], cur["theta"], cur["phi"], self.config
            )
            corners_a = tool_model.heated_corners(a, self.config)
            corners_b = tool_model.heated_corners(b, self.config)
            worst = max(worst, float(np.max(np.linalg.norm(corners_b - corners_a, axis=1))))
        self.assertLessEqual(worst, limit + 1e-6)

    def test_roughing_passes_slice_and_broadside_is_reported(self):
        frames = self.result.frames
        lengths = {"slice": 0.0, "broadside": 0.0, "plunge": 0.0}
        for prev, cur in zip(frames, frames[1:]):
            if cur["is_rapid"] or cur["stage"] != "roughing":
                continue
            direction = np.asarray(cur["tip_xyz_wax"]) - np.asarray(prev["tip_xyz_wax"])
            if float(np.linalg.norm(direction)) <= 1e-12:
                continue
            pose = tool_model.tool_pose(
                cur["tip_xyz_wax"], cur["theta"], cur["phi"], self.config
            )
            kind = tool_model.feed_class(direction, pose, self.config)
            lengths[kind] += float(np.linalg.norm(direction))
        total = sum(lengths.values())
        self.assertGreater(total, 0.0)
        self.assertGreaterEqual(lengths["slice"] / total, 0.90)
        if lengths["broadside"] > 0.0:
            codes = {d.code for d in self.result.diagnostics}
            self.assertIn("BLADE_BROADSIDE_FEED", codes)

    def test_unwrapped_theta_is_continuous_within_cut_runs(self):
        # The orbit is bounded by the stop block, so a cut run sweeps the
        # configured arc and the rapid between slices may reset theta. Within
        # any non-rapid run the unwrapped angle is continuous.
        frames = self.result.frames
        for prev, cur in zip(frames, frames[1:]):
            if cur["is_rapid"] or cur["stage"] not in ("roughing", "finishing"):
                continue
            delta = float(cur["theta_s"]) - float(prev["theta_s"])
            self.assertGreaterEqual(delta, -0.5)
            self.assertLessEqual(delta, 5.0)

    def test_gouge_detection_flags_tool_inside_target(self):
        # Construct a deliberately bad CL pose that buries the tool in the target.
        cc = np.array([20.0, 0.0, 50.0])
        normal = np.array([1.0, 0.0, 0.0])
        bad_tip = cc - normal * 4.0
        pose = {
            "tip_xyz_wax": tuple(float(v) for v in bad_tip),
            "tool_axis_wax": (1.0, 0.0, 0.0),
            "theta": 0.0,
        }
        diags = toolpath_sim.detect_gouges(self.mesh, [pose], self.config)
        self.assertTrue(any(d.code == "GOUGE" for d in diags))

    def test_every_azimuth_bin_receives_cutting_frames(self):
        # The orbit is bounded, so the azimuths behind the head (170..190 deg)
        # are reached with the signed-r branch (theta = azimuth - 180 deg,
        # r_s < 0). Every 10 degree bin must see at least one cutting frame.
        frames = [
            frame
            for frame in self.result.frames
            if not frame["is_rapid"] and frame["stage"] in ("roughing", "finishing")
        ]
        self.assertGreater(len(frames), 100)
        bins = set()
        for frame in frames:
            x, y, _ = frame["tip_xyz_wax"]
            azimuth = math.degrees(math.atan2(y, x)) % 360.0
            bins.add(int(azimuth // 10.0))
        missing = sorted(set(range(36)) - bins)
        self.assertEqual(missing, [], f"azimuth bins with no cutting frames: {missing}")
        self.assertTrue(
            any(float(frame["r_s"]) < 0.0 for frame in frames),
            "no negative-r_s cutting frames: the back-side azimuths are uncovered",
        )

    def test_standard_preset_produces_denser_path(self):
        standard = toolpath_sim.generate_synthetic_carve_path(
            self.sculpt, self.config, preset="standard"
        )
        self.assertGreater(len(standard.frames), len(self.result.frames))
        self.assertLessEqual(
            len(standard.frames), self.config["api"]["max_frames"]
        )


class TestHead2Target(unittest.TestCase):
    """The committed `presets/head_2.stl` default target mesh.

    `machine_config.json` points `target_mesh.path` at the pre-normalized head,
    so `load_base_head` / `POST /api/sculpt-and-sim` carve it by default.  The
    analytic ellipsoid classes above stay pinned to `target_mesh=None`.
    """

    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.mesh = face_sculpt.load_base_head(cls.config)
        cls.landmarks = face_sculpt.load_landmarks(cls.config)
        cls.result = toolpath_sim.generate_synthetic_carve_path(
            cls.mesh, cls.config, preset="demo"
        )

    # -- geometry ----------------------------------------------------------

    def test_configured_target_mesh_is_head_2(self):
        resolved = face_sculpt.resolve_mesh_path(self.config)
        self.assertEqual(resolved.name, "head_2.stl")
        self.assertEqual(resolved.parent.resolve(), (ROOT / "presets").resolve())
        self.assertNotEqual(
            resolved, face_sculpt.resolve_mesh_path(load_config(target_mesh=None))
        )

    def test_head_2_is_watertight_flat_seated_and_within_stock(self):
        mesh = self.mesh
        delta = 1e-3
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)
        self.assertGreater(float(mesh.volume), 0.0)
        z_plinth = float(self.config["stock"]["z_plinth_mm"])
        self.assertAlmostEqual(float(mesh.bounds[0][2]), z_plinth, delta=delta)
        max_r = float(np.max(np.linalg.norm(mesh.vertices[:, :2], axis=1)))
        self.assertLessEqual(max_r, 32.0 + delta)
        # The flat extruded base is a real face of the mesh, not a clipping
        # artefact: enough vertices sit exactly on the plinth datum.
        on_plinth = np.isclose(mesh.vertices[:, 2], z_plinth, atol=delta)
        self.assertGreaterEqual(int(np.count_nonzero(on_plinth)), 7)

    def test_sidecar_records_the_source_digest_and_transform(self):
        sidecar = json.loads(
            (ROOT / "presets" / "head_2.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sidecar["mesh"], "head_2.stl")
        self.assertEqual(len(sidecar["source"]["sha256"]), 64)
        transform = sidecar["transform"]
        self.assertEqual(transform["rotation"], ["Z", "X", "Y"])
        self.assertAlmostEqual(transform["z_plinth_mm"], 10.0, places=9)
        self.assertAlmostEqual(transform["max_radius_mm"], 32.0, places=9)
        self.assertEqual(transform["neck_loop_edges"], 14)
        self.assertEqual(sorted(transform["ear_loop_edges"]), [6, 6])
        self.assertGreater(float(transform["scale"]), 0.0)
        self.assertEqual(len(transform["center_xy_mm"]), 2)
        self.assertTrue(sidecar["geometry"]["watertight"])
        credit = (ROOT / "presets" / "head_2_license.txt").read_text(encoding="utf-8")
        self.assertIn("CC-BY-4.0", credit)

    # -- mesh-keyed landmarks ---------------------------------------------

    def test_landmarks_are_keyed_to_the_active_mesh(self):
        self.assertIsNone(self.landmarks)
        self.assertFalse(face_sculpt.sliders_enabled(self.config))
        sidecar = face_sculpt.landmarks_path(self.config)
        self.assertEqual(sidecar.name, "head_2_landmarks.json")
        self.assertFalse(sidecar.exists())
        ellipsoid = load_config(target_mesh=None)
        self.assertTrue(face_sculpt.sliders_enabled(ellipsoid))
        self.assertEqual(
            face_sculpt.landmarks_path(ellipsoid).name, "base_head_landmarks.json"
        )
        for name in ("nose", "brow", "cheeks", "jaw", "chin"):
            self.assertIn(name, face_sculpt.load_landmarks(ellipsoid))

    def test_non_zero_sliders_emit_sculpt_sliders_ignored(self):
        result = face_sculpt.apply_facial_modifications(
            self.mesh, {"nose": 0.8}, self.config
        )
        self.assertEqual(result.max_displacement_mm, 0.0)
        self.assertTrue(result.ok, [d.as_dict() for d in result.diagnostics])
        np.testing.assert_array_equal(result.mesh.vertices, self.mesh.vertices)
        diag = next(
            d for d in result.diagnostics if d.code == "SCULPT_SLIDERS_IGNORED"
        )
        self.assertEqual(diag.severity, "info")
        self.assertIn("head_2", diag.message)
        # Zero sliders do not even warn.
        quiet = face_sculpt.apply_facial_modifications(self.mesh, {}, self.config)
        self.assertEqual(quiet.diagnostics, [])

    # -- demo toolpath -----------------------------------------------------

    def test_demo_baseline_keeps_its_expected_warnings(self):
        # Intended baseline of the committed mesh: zero errors, ~20.6% of surface
        # points require an unreachable pitch, and the blade buries ~12.7 mm in
        # the target.  This asserts the character of the baseline (it must not be
        # "fixed" to zero) rather than pinning float-exact values.
        result = self.result
        self.assertEqual(
            [d.as_dict() for d in result.diagnostics if d.severity == "error"], []
        )
        self.assertGreater(len(result.frames), 50_000)
        codes = {d.code: d for d in result.diagnostics}
        self.assertIn("UNREACHABLE_UNDERCUT_AREA", codes)
        unreachable = codes["UNREACHABLE_UNDERCUT_AREA"].value
        self.assertEqual(codes["UNREACHABLE_UNDERCUT_AREA"].severity, "warning")
        self.assertGreater(unreachable, 5.0)
        self.assertLess(unreachable, 50.0)
        allowance = float(self.config["stock"]["finish_allowance_mm"])
        self.assertIn("GOUGE", codes)
        self.assertEqual(codes["GOUGE"].severity, "warning")
        self.assertGreater(codes["GOUGE"].value, allowance)
        self.assertLess(codes["GOUGE"].value, 25.0)

    def test_early_return_paths_report_no_collision_events(self):
        config = copy.deepcopy(self.config)
        config["stock"]["H_stock_mm"] = 300.0
        block = trimesh.creation.box(extents=(30.0, 30.0, 40.0))
        block.apply_translation([0.0, 0.0, 30.0])
        result = toolpath_sim.generate_synthetic_carve_path(
            block, config, preset="demo"
        )
        self.assertEqual(result.frames, [])
        self.assertEqual(result.collision_events, [])
        self.assertTrue(any(d.severity == "error" for d in result.diagnostics))

    # -- collision event log ----------------------------------------------

    def test_collision_events_carry_frame_ranges_and_contact_geometry(self):
        events = self.result.collision_events
        self.assertTrue(events, "the demo baseline must log its warnings")
        self.assertEqual(self.result.collision_log["events"], events)
        self.assertEqual(
            set(self.result.collision_log["codes"]),
            {event["code"] for event in events},
        )
        for code, summary in self.result.collision_log["codes"].items():
            self.assertEqual(summary["runs"], sum(1 for e in events if e["code"] == code))
            self.assertIn("truncated", summary)
            self.assertIn("dropped", summary)

        gouges = [event for event in events if event["code"] == "GOUGE"]
        self.assertTrue(gouges)
        for event in gouges:
            self.assertEqual(
                set(event["joints"]), {"r_mm", "theta_deg", "h_mm", "phi_deg"}
            )
            self.assertEqual(
                set(event["pose"]), {"tip_xyz_wax", "tool_axis_wax"}
            )
            self.assertEqual(len(event["pose"]["tip_xyz_wax"]), 3)
            self.assertEqual(len(event["pose"]["tool_axis_wax"]), 3)
            self.assertEqual(len(event["frame_range"]), 2)
            self.assertGreaterEqual(event["frame_range"][1], event["frame_range"][0])
            self.assertEqual(len(event["deepest_sample_xyz_wax"]), 3)
            self.assertEqual(len(event["surface_point_xyz_wax"]), 3)
            self.assertGreater(event["excess_mm"], 0.0)
            self.assertGreater(event["depth_mm"], event["excess_mm"])
            self.assertIn(
                event["stage"], ("finishing", "finishing_link", "roughing_link")
            )
            # The reported surface point really is on the target surface and the
            # deepest sample really is buried below it.
            surface = float(
                self.mesh.nearest.signed_distance([event["surface_point_xyz_wax"]])[0]
            )
            self.assertAlmostEqual(surface, 0.0, delta=1e-3)
            buried = float(
                self.mesh.nearest.signed_distance([event["deepest_sample_xyz_wax"]])[0]
            )
            self.assertAlmostEqual(buried, event["depth_mm"], delta=1e-2)

        summary = next(
            event for event in events if event["code"] == "UNREACHABLE_UNDERCUT_AREA"
        )
        self.assertGreater(summary["count"], 0)
        self.assertLess(
            summary["z_range_mm"][0], summary["z_range_mm"][1] + 1e-9
        )
        self.assertLess(
            summary["theta_deg_range"][0], summary["theta_deg_range"][1] + 1e-9
        )
        self.assertEqual(len(summary["required_phi_deg_range"]), 2)
        self.assertEqual(
            summary["phi_limits_deg"],
            [float(v) for v in self.config["limits"]["phi_limits_deg"]],
        )


class TestCollisionEventLog(unittest.TestCase):
    """Unit tests for the run-capped collision log and its post-pass helpers."""

    def _run(self, frame: int, depth: float) -> dict:
        return {"code": "GOUGE", "frame_range": [frame, frame], "depth_mm": depth}

    def test_deepest_runs_are_kept_and_overflow_is_recorded(self):
        log = toolpath_sim.CollisionEventLog(max_events_per_code=2)
        for depth, frame in ((5.0, 1), (9.0, 2), (7.0, 3), (11.0, 4), (3.0, 5)):
            log.add_run("GOUGE", self._run(frame, depth), weight=depth)
        payload = log.as_dict()
        self.assertEqual(payload["max_events_per_code"], 2)
        self.assertEqual(
            payload["codes"]["GOUGE"], {"runs": 2, "truncated": True, "dropped": 3}
        )
        self.assertEqual(
            sorted(event["depth_mm"] for event in payload["events"]), [9.0, 11.0]
        )
        # Kept runs stay chronological, not ranked.
        self.assertEqual(
            [event["frame_range"][0] for event in payload["events"]], [2, 4]
        )

    def test_no_overflow_means_no_truncation(self):
        log = toolpath_sim.CollisionEventLog(max_events_per_code=3)
        log.add_run("GOUGE", self._run(1, 4.0), weight=4.0)
        payload = log.as_dict()
        self.assertEqual(
            payload["codes"]["GOUGE"], {"runs": 1, "truncated": False, "dropped": 0}
        )

    def test_mixed_codes_are_capped_independently(self):
        log = toolpath_sim.CollisionEventLog(max_events_per_code=1)
        log.add_run("GOUGE", self._run(1, 4.0), weight=4.0)
        log.add_run(
            "BLADE_BROADSIDE_FEED",
            {"code": "BLADE_BROADSIDE_FEED", "frame_range": [9, 20], "length_mm": 12.0},
            weight=12.0,
        )
        payload = log.as_dict()
        self.assertEqual(payload["codes"]["GOUGE"]["dropped"], 0)
        self.assertEqual(payload["codes"]["BLADE_BROADSIDE_FEED"]["runs"], 1)
        self.assertEqual(
            [event["frame_range"][0] for event in payload["events"]], [1, 9]
        )


class TestSampledGougeRuns(unittest.TestCase):
    """`detect_gouges_detailed` groups consecutive *sampled* frames into runs."""

    @classmethod
    def setUpClass(cls):
        cls.config = load_config(target_mesh=None)
        block = trimesh.creation.box(extents=(30.0, 30.0, 40.0))
        block.apply_translation([0.0, 0.0, 30.0])
        cls.mesh = block
        cls.buried = ([0.0, 0.0, 30.0], (0.0, 0.0, -1.0))
        cls.clear = ([0.0, 0.0, 200.0], (0.0, 0.0, -1.0))

    def _frames(self, buried: set[int], count: int = 260) -> tuple[list, list]:
        frames = []
        stages = []
        for index in range(count):
            tip, axis = self.buried if index in buried else self.clear
            frames.append(
                {
                    "r": 60.0,
                    "theta": 0.0,
                    "h": 90.0,
                    "phi": 0.0,
                    "r_s": 60.0,
                    "theta_s": 0.0,
                    "z_s": float(tip[2]),
                    "v_tip": 1.0,
                    "is_rapid": False,
                    "tip_xyz_wax": tip,
                    "tool_axis_wax": axis,
                }
            )
            stages.append("finishing" if index < 40 else "finishing_link")
        return frames, stages

    def test_finishing_stride_4_and_link_stride_50_group_separately(self):
        frames, stages = self._frames({0, 4, 8, 12, 100, 150})
        report = toolpath_sim.detect_gouges_detailed(self.mesh, frames, stages, self.config)
        ranges = [event["frame_range"] for event in report.events]
        self.assertEqual(ranges, [[0, 12], [100, 150]])
        self.assertEqual([event["stage"] for event in report.events],
                         ["finishing", "finishing_link"])
        self.assertEqual([event["samples"] for event in report.events], [4, 2])
        self.assertTrue(all(event["code"] == "GOUGE" for event in report.events))
        # The single worst-depth diagnostic is still produced for the log.
        self.assertEqual(len(report.diagnostics), 1)
        worst = max(event["depth_mm"] for event in report.events)
        self.assertAlmostEqual(float(report.diagnostics[0].value), worst, places=6)

    def test_unsampled_frames_break_a_run(self):
        frames, stages = self._frames({0, 4, 12})  # frame 8 is clean
        report = toolpath_sim.detect_gouges_detailed(self.mesh, frames, stages, self.config)
        self.assertEqual(
            [event["frame_range"] for event in report.events], [[0, 4], [12, 12]]
        )

    def test_detect_gouges_keeps_its_public_contract(self):
        frames, stages = self._frames({0})
        poses = toolpath_sim.gouge_sample_poses(frames, stages)
        self.assertEqual(poses[0]["frame"], 0)
        self.assertEqual(poses[0]["stage"], "finishing")
        self.assertEqual(
            set(poses[0]["joints"]), {"r_mm", "theta_deg", "h_mm", "phi_deg"}
        )
        diagnostics = toolpath_sim.detect_gouges(self.mesh, poses, self.config)
        self.assertIsInstance(diagnostics, list)
        self.assertTrue(all(d.code == "GOUGE" for d in diagnostics))


class TestSoftLimitPostPass(unittest.TestCase):
    """The vectorized SOFT_LIMIT_EXCEEDED post-pass over built frames."""

    @classmethod
    def setUpClass(cls):
        cls.config = load_config(target_mesh=None)

    def _frame(self, r=60.0, degrees=0.0, h=100.0, phi_deg=0.0) -> dict:
        return {
            "r": r,
            "theta": math.radians(degrees),
            "h": h,
            "phi": math.radians(phi_deg),
        }

    def test_runs_are_grouped_per_axis_with_joint_context(self):
        frames = [self._frame() for _ in range(10)]
        frames[3]["h"] = 400.0
        frames[4]["h"] = 450.0
        frames[5]["h"] = 500.0
        frames[7]["phi"] = math.radians(80.0)
        events = toolpath_sim.soft_limit_runs(frames, self.config)
        by_axis = {event["axis"]: event for event in events}
        self.assertEqual(set(by_axis), {"h", "phi"})
        vertical = by_axis["h"]
        self.assertEqual(vertical["frame_range"], [3, 5])
        self.assertEqual(vertical["code"], "SOFT_LIMIT_EXCEEDED")
        h_lo, h_hi = (float(v) for v in self.config["limits"]["h_limits_mm"])
        self.assertAlmostEqual(vertical["value"], 500.0 - h_hi, places=6)
        self.assertEqual(vertical["limit"], [h_lo, h_hi])
        self.assertAlmostEqual(vertical["joints"]["h_mm"], 500.0, places=6)
        self.assertEqual(by_axis["phi"]["frame_range"], [7, 7])

    def test_theta_is_compared_wrapped_to_pm_180(self):
        # theta_limits_deg is [-170, 170]; 185 deg wraps to -175 deg and is
        # therefore out of range, exactly like kinematics.validate_joints.
        frames = [self._frame(degrees=185.0), self._frame(degrees=10.0)]
        events = toolpath_sim.soft_limit_runs(frames, self.config)
        self.assertEqual([event["frame_range"] for event in events], [[0, 0]])
        self.assertEqual(events[0]["axis"], "theta")

    def test_clean_frames_produce_no_events(self):
        frames = [self._frame() for _ in range(50)]
        self.assertEqual(toolpath_sim.soft_limit_runs(frames, self.config), [])


class TestSimulationAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("version", body)

    def test_sculpt_and_sim_columnar_contract(self):
        response = self.client.post(
            "/api/sculpt-and-sim",
            json={
                "sliders": {"nose": 0.8, "brow": 0.4},
                "preset": "demo",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["preset"], "demo")
        self.assertIn("config", body)
        self.assertIn("target_mesh", body)
        self.assertIn("trajectory", body)
        self.assertIn("diagnostics", body)

        mesh_payload = body["target_mesh"]
        vertices = np.frombuffer(
            base64.b64decode(mesh_payload["vertices_b64"]), dtype=np.float32
        )
        faces = np.frombuffer(
            base64.b64decode(mesh_payload["faces_b64"]), dtype=np.uint32
        )
        self.assertEqual(vertices.shape[0], mesh_payload["vertex_count"] * 3)
        self.assertEqual(faces.shape[0], mesh_payload["face_count"] * 3)
        self.assertGreater(mesh_payload["face_count"], 100)

        traj = body["trajectory"]
        self.assertLessEqual(traj["frame_count"], 250_000)
        self.assertGreater(traj["frame_count"], 100)
        columns = traj["columns"]
        for name in (
            "t", "r", "theta", "h", "phi", "r_s", "theta_s", "z_s",
            "v_tip", "tip_xyz_wax", "tool_axis_wax",
        ):
            col = columns[name]
            raw = np.frombuffer(base64.b64decode(col["b64"]), dtype=np.float32)
            expected = traj["frame_count"] * (3 if name in ("tip_xyz_wax", "tool_axis_wax") else 1)
            self.assertEqual(raw.shape[0], expected, name)
            self.assertEqual(col["dtype"], "float32")
        rapid = np.frombuffer(
            base64.b64decode(columns["is_rapid"]["b64"]), dtype=np.uint8
        )
        self.assertEqual(rapid.shape[0], traj["frame_count"])
        self.assertEqual(columns["is_rapid"]["dtype"], "uint8")
        self.assertIn(rapid.max(), (0, 1))

        expanded = body["diagnostics"]
        self.assertIsInstance(expanded, list)


class _FakeNeedle(trimesh.Trimesh):
    """Probe mesh: a vertical spike whose side panels share the section plane.

    Only planar slicing sees the spike; an azimuthal vertex wedge (the old
    implementation) would miss it entirely.
    """

    @classmethod
    def build(cls) -> "_FakeNeedle":
        body = trimesh.creation.box(extents=(30.0, 30.0, 40.0))
        body.apply_translation([0.0, 0.0, 30.0])
        needle = trimesh.creation.box(extents=(1.6, 1.6, 16.0))
        needle.apply_translation([20.0, 0.0, 48.0])
        mesh = trimesh.util.concatenate([body, needle])
        mesh = cls(vertices=mesh.vertices, faces=mesh.faces, process=False)
        return mesh


class TestPatch10ToolpathRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.needle = _FakeNeedle.build()

    # (a) planar r-Z sections ------------------------------------------------

    def test_planar_section_keeps_off_centerline_radii(self):
        needle = self.needle
        # A needle at (r=20, theta=0) is invisible to a slice at theta=0.4 rad.
        away = toolpath_sim.section_contour(needle, 0.4, 10.0, 80.0)
        self.assertTrue(all(point["radius"] <= 22.0 for point in away))
        # The slice through theta = 0 sees both needle flanks as distinct radii.
        # The needle is an axis-aligned box centred on y = 0, so the plane cuts
        # through its middle: its outer face at r = 20.8 spans z 40-56.
        through = toolpath_sim.section_contour(needle, 0.0, 10.0, 80.0)
        needle_points = [p for p in through if p["radius"] > 20.5 and p["z"] > 45.0]
        self.assertGreaterEqual(len(needle_points), 4)
        radii = sorted({round(p["radius"], 1) for p in needle_points})
        self.assertTrue(any(r > 20.3 for r in radii), radii)
        # Every contour point lies exactly on the section plane.
        e_theta = np.array([0.0, 1.0, 0.0])
        for point in through:
            self.assertAlmostEqual(float(np.dot(point["point"], e_theta)), 0.0, places=6)

    def test_finishing_follows_planar_contours(self):
        # Machine-cad-integration exit criterion: the PATCH-10f expectedFailure
        # is gone. Every finishing cut must place the *heated blade* on the
        # target surface (support-function CL), not one cone standoff away.
        result = toolpath_sim.generate_synthetic_carve_path(
            self.needle, self.config, preset="demo"
        )
        finishing = [
            f for f in result.frames if f["stage"] == "finishing" and not f["is_rapid"]
        ]
        self.assertGreater(len(finishing), 40)
        allowance = float(self.config["stock"]["finish_allowance_mm"])
        checked = 0
        for frame in finishing[:: max(1, len(finishing) // 40)]:
            pose = tool_model.tool_pose(
                frame["tip_xyz_wax"], frame["theta"], frame["phi"], self.config
            )
            samples = toolpath_sim._heated_gouge_samples(pose, self.config)
            signed = np.asarray(self.needle.nearest.signed_distance(samples))
            # signed_distance is POSITIVE inside. A tangent blade touches the
            # surface: at least one sample sits near the surface. Deeper burial
            # elsewhere is the existing finishing-strategy limitation the spec
            # reports as GOUGE (the strategy redesign is a follow-up change).
            self.assertLessEqual(float(np.min(np.abs(signed))), 0.75)
            checked += 1
        self.assertGreater(checked, 10)

        # The reported depth must cover the same sampled poses the generator
        # checks. Measure a subset of that selection (a subset cannot exceed
        # the reported maximum).
        stages = [frame["stage"] for frame in result.frames]
        sample = toolpath_sim.gouge_sample_poses(result.frames, stages)
        self.assertGreater(len(sample), 0)
        measured = 0.0
        for entry in sample[:: max(1, len(sample) // 40)]:
            pose = toolpath_sim._pose_for_axis(
                entry["tip_xyz_wax"], entry["tool_axis_wax"], entry["theta"], self.config
            )
            signed = np.asarray(
                self.needle.nearest.signed_distance(
                    toolpath_sim._heated_gouge_samples(pose, self.config)
                )
            )
            measured = max(measured, float(np.max(signed)))
        if measured > allowance + 1e-6:
            gouges = [d for d in result.diagnostics if d.code == "GOUGE"]
            self.assertTrue(gouges, "deep burial must be reported as GOUGE")
            self.assertGreaterEqual(
                max(float(d.value) for d in gouges),
                measured - 1e-6,
                "reported GOUGE depth must not understate the measured burial",
            )

    # (b) reachability condition -------------------------------------------

    def test_finishing_phi_policy_projects_into_the_surface_frame(self):
        # beta is the surface-normal angle from +Z. The policy asks for that
        # pitch and clamps only at the configured phi limits; no cone
        # half-angle is subtracted any more.
        beta_ok = math.radians(40.0)
        phi, reachable = toolpath_sim.finishing_phi(
            math.sin(beta_ok), math.cos(beta_ok), self.config
        )
        self.assertTrue(reachable)
        self.assertAlmostEqual(phi, beta_ok, places=9)

        phi_hi = math.radians(float(self.config["limits"]["phi_limits_deg"][1]))
        phi_c, _ = toolpath_sim.finishing_phi(1.0, 0.0, self.config)
        self.assertAlmostEqual(phi_c, phi_hi, places=9)

        # A downward-facing overhang must clamp, never flip across zero.
        beta_bad = math.radians(179.0)
        phi_bad, _ = toolpath_sim.finishing_phi(
            math.sin(beta_bad), math.cos(beta_bad), self.config
        )
        self.assertGreater(phi_bad, 0.0)

    # (c) safe three-step approach/retract ---------------------------------

    def test_approach_and_retract_never_drop_below_cut_height(self):
        result = toolpath_sim.generate_synthetic_carve_path(
            self.needle, self.config, preset="demo"
        )
        frames = result.frames
        stock_top = float(self.config["stock"]["H_stock_mm"])
        clearance = float(self.config["stock"]["retract_clearance_mm"])
        pivot = float(self.config["pivot_to_tip_mm"])
        blade_length = float(self.config["tool"]["blade_length_mm"])
        # Corrected (PATCH-10c): the generator's safe plane is
        # H_stock + retract_clearance, and the apex at phi = 0 sits p below the
        # pivot, so the apex may rise p above that plane.  The old bound
        # (H_stock) contradicted the generator's own safe_zs.
        ceiling = stock_top + clearance + pivot + 1e-6
        transitions = [
            (prev, cur)
            for prev, cur in zip(frames, frames[1:])
            if cur["is_rapid"] or prev["is_rapid"]
        ]
        self.assertGreater(len(transitions), 10)
        for prev, cur in transitions:
            phi_prev = float(prev["phi"])
            phi_cur = float(cur["phi"])
            if abs(phi_prev - phi_cur) > 1e-6:
                # A phi reorientation must be a well-clear move, not a cut.
                self.assertGreaterEqual(abs(float(cur["r_s"])), float(self.config["stock"]["R_stock_mm"]))
                self.assertGreaterEqual(abs(float(prev["r_s"])), float(self.config["stock"]["R_stock_mm"]))
        # Approach into a cut is a multi-step move: descending h with phi change
        # is never a single step from clearance straight to a tilted cut.
        for prev, cur in zip(frames, frames[1:]):
            if bool(prev["is_rapid"]) and not bool(cur["is_rapid"]):
                # arrive vertical first, then reorient in place
                self.assertAlmostEqual(float(cur["phi"]), 0.0, places=6)
        for frame in frames:
            self.assertGreaterEqual(float(frame["z_s"]), -blade_length - 1e-6)
            # Link moves ("finishing_link") use the same safe plane as rapids.
            self.assertLessEqual(float(frame["z_s"]), ceiling, frame["stage"])

    # (d) multiple_hits shadow ----------------------------------------------

    def test_shadow_profile_uses_multiple_hits(self):
        # Corrected (PATCH-10c): "r ~= 21.2 at z = 20" was the box *corner
        # diagonal* (15 sqrt 2); along theta = 0 the wall is at r = 15.  The
        # needle spans z 40-56, so probe z = 45 (both layers present) rather
        # than z = 56, which only grazes the needle's top face.
        profile = toolpath_sim.radial_profiles(
            self.needle, [0.0], np.array([20.0, 45.0])
        )
        # The body wall alone is 15.0; the needle outer face at 20.8 is only
        # reported when every hit along the ray is collected.
        self.assertAlmostEqual(float(profile[0, 0]), 15.0, delta=0.5)
        self.assertGreaterEqual(float(profile[0, 1]), 20.5)

    # (e) joint limits ------------------------------------------------------

    def test_out_of_bounds_stock_emits_soft_limit_exceeded(self):
        config = copy.deepcopy(self.config)
        config["stock"]["H_stock_mm"] = 600.0
        result = toolpath_sim.generate_synthetic_carve_path(
            self.needle, config, preset="demo"
        )
        codes = {diag.code for diag in result.diagnostics}
        self.assertIn("SOFT_LIMIT_EXCEEDED", codes)
        diag = next(d for d in result.diagnostics if d.code == "SOFT_LIMIT_EXCEEDED")
        self.assertEqual(diag.severity, "error")

    # (f) frame cap ---------------------------------------------------------

    def test_frame_cap_exceedance_raises(self):
        config = copy.deepcopy(self.config)
        config["api"]["max_frames"] = 500
        with self.assertRaises(toolpath_sim.FrameCapExceededError):
            toolpath_sim.generate_synthetic_carve_path(self.needle, config, preset="demo")


class TestFinishingHelpers(unittest.TestCase):
    """Unit tests for the PATCH-10c finishing helpers on analytic fixtures.

    Each helper is gated on the helper actually existing so the red/green
    ladder is unambiguous and a missing seam is reported as a helper gap, not
    as an end-to-end count.
    """

    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        stock = cls.config["stock"]
        cls.R = float(stock["R_stock_mm"])
        cls.H = float(stock["H_stock_mm"])
        cls.tool = cls.config["tool"]
        cls.kerf = float(cls.tool["melt_kerf_mm"])
        cls.length = float(cls.tool["heated_length_mm"])

    def helper(self, name):
        fn = getattr(toolpath_sim, name, None)
        if fn is None:
            self.fail(f"toolpath_sim.{name} is missing")
        return fn

    # -- tolerances under `mesh_contains` -------------------------------------
    def _axis_of(self, phi, theta):
        return np.array(
            [-math.sin(phi) * math.cos(theta), -math.sin(phi) * math.sin(theta), -math.cos(phi)]
        )

    def _ring(self, tip, axis, station, radius):
        tmp = np.array([0.0, 0.0, 1.0])
        if abs(float(axis @ tmp)) > 0.9:
            tmp = np.array([1.0, 0.0, 0.0])
        e1 = np.cross(axis, tmp)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        base = tip - axis * station
        angles = np.arange(8) * (math.pi / 4.0)
        return base + radius * (
            np.cos(angles)[:, None] * e1[None, :] + np.sin(angles)[:, None] * e2[None, :]
        )

    def _pose(self, cc, phi, theta, extra=0.0):
        """Tool pose with its reference point at the support-function CL."""

        n = np.array([math.cos(theta), math.sin(theta), 0.0])
        axes = tool_model.tool_pose(cc, theta, phi, self.config)
        tip = tool_model.place_on_contact(cc, n, axes, self.config)
        if extra:
            tip = tip - n * extra
        return tip, self._axis_of(phi, theta)

    def _distances(self, mesh, points):
        return np.abs(mesh.nearest.signed_distance(np.atleast_2d(points)))

    # -- (1) section_polylines ----------------------------------------------
    def test_section_polylines_continuous_clipped_and_ordered(self):
        polylines = self.helper("section_polylines")
        step = 2.0
        box = trimesh.creation.box(extents=(30.0, 30.0, 40.0))
        box.apply_translation([0.0, 0.0, 30.0])
        lines = polylines(box, 0.0, 10.0, self.H, step)
        self.assertGreaterEqual(len(lines), 1)
        for line in lines:
            self.assertGreater(len(line), 1)
            pts = np.asarray([p["point"] for p in line], dtype=float)
            dists = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            self.assertLessEqual(float(np.max(dists)), 1.5 * step + 1e-6)
            self.assertGreaterEqual(min(p["radius"] for p in line), -1e-9)
            self.assertLessEqual(max(p["radius"] for p in line), self.R + 1e-6)
            for p in line:
                self.assertGreaterEqual(p["z"], 10.0 + 1.5 - 1e-6)
                self.assertLessEqual(p["z"], self.H + 1e-6)
            zs = [p["z"] for p in line]
            self.assertLessEqual(abs(zs[0] - min(zs)), 1e-6)
            self.assertLessEqual(abs(zs[-1] - max(zs)), 1e-6)
            # Normals are planar and unit length.
            for p in line:
                self.assertAlmostEqual(
                    math.hypot(p["n_r"], p["n_z"]), 1.0, places=6
                )
        # A 30x30 prism is one contour: bottom clip, wall, top face, far wall.
        self.assertEqual(len(lines), 1)

    def test_section_polylines_split_islands(self):
        polylines = self.helper("section_polylines")
        body = trimesh.creation.box(extents=(30.0, 30.0, 40.0))
        body.apply_translation([0.0, 0.0, 30.0])
        needle = trimesh.creation.box(extents=(1.6, 1.6, 16.0))
        needle.apply_translation([20.0, 0.0, 48.0])
        mesh = trimesh.util.concatenate([body, needle])
        lines = polylines(mesh, 0.0, 10.0, self.H, 2.0)
        # The body crosses the axis, so it is clipped into one open polyline:
        # the wall from z = 11.5, then the top face inward to r = 0.  The needle
        # is an untouched closed island, split into two bottom-to-top halves.
        # Total 3; a loop that touches a boundary is never split.
        self.assertEqual(len(lines), 3, [len(line) for line in lines])
        self.assertTrue(any(p["radius"] > 20.8 - 1e-6 for line in lines for p in line))
        self.assertTrue(any(p["radius"] < 15.01 for line in lines for p in line))
        # The r = 0 end of the body polyline is the top face reaching the axis
        # (the needle's own points are at r >= 19.2, so this is unambiguously
        # the body).
        self.assertTrue(any(p["radius"] < 15.01 and p["z"] > 40.0 for line in lines for p in line))
        self.assertGreater(max(p["z"] for line in lines for p in line), 50.0)
        for line in lines:
            pts = np.asarray([p["point"] for p in line], dtype=float)
            self.assertLessEqual(
                float(np.max(np.linalg.norm(np.diff(pts, axis=0), axis=1))), 3.0 + 1e-6
            )

    def test_section_contour_flattens_polylines(self):
        contour = self.helper("section_contour")
        box = trimesh.creation.box(extents=(30.0, 30.0, 40.0))
        box.apply_translation([0.0, 0.0, 30.0])
        flat = contour(box, 0.0, 10.0, self.H, 2.0)
        self.assertGreater(len(flat), 5)
        self.assertEqual(
            set(flat[0]),
            {"point", "radius", "z", "n_r", "n_z"},
            "section_contour keeps its flat point schema",
        )

    # -- (2) finishing_phi table --------------------------------------------
    def test_finishing_phi_table(self):
        phi_lo, phi_hi = (float(v) for v in self.config["limits"]["phi_limits_deg"])
        table = [0.0, 40.0, 90.0, 120.0, 179.0, -40.0]
        for beta_deg in table:
            beta = math.radians(beta_deg)
            phi, ok = toolpath_sim.finishing_phi(
                math.sin(beta), math.cos(beta), self.config
            )
            expected = min(max(beta_deg, phi_lo), phi_hi)
            self.assertAlmostEqual(math.degrees(phi), expected, delta=1e-6, msg=beta_deg)
            self.assertTrue(ok, beta_deg)

    def test_finishing_phi_never_flips_an_undercut_forward(self):
        # A steep overhang clamps at phi_hi; it is never mirrored across zero.
        beta = math.radians(150.0)
        phi, _ = toolpath_sim.finishing_phi(math.sin(beta), math.cos(beta), self.config)
        self.assertGreater(phi, 0.0)
        self.assertAlmostEqual(
            math.degrees(phi),
            float(self.config["limits"]["phi_limits_deg"][1]),
            places=6,
        )

    # -- (3) cutter_location ------------------------------------------------
    def test_cutter_location_is_the_support_function_placement(self):
        cutter_location = self.helper("cutter_location")
        # A box rotated 45 deg about y gives an *exact* plane with normal
        # (1, 0, 1)/sqrt2 - no tessellation error, so the fixture is analytic.
        normal = np.array([1.0, 0.0, 1.0]) / math.sqrt(2.0)
        box = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
        box.apply_transform(trimesh.transformations.rotation_matrix(math.radians(45.0), [0.0, 1.0, 0.0]))
        box.apply_translation([0.0, 0.0, 30.0])
        face = int(np.argmax(box.face_normals @ normal))
        cc = np.asarray(box.triangles_center[face], dtype=float)
        self.assertAlmostEqual(float(box.nearest.signed_distance([cc])[0]), 0.0, places=6)
        n_r = float(normal[0])
        n_z = float(normal[2])
        cl = cutter_location(cc, n_r, n_z, 0.0, self.config)
        phi, _ = toolpath_sim.finishing_phi(n_r, n_z, self.config)
        expected = tool_model.place_on_contact(
            cc,
            normal,
            tool_model.tool_pose(cc, 0.0, phi, self.config),
            self.config,
        )
        np.testing.assert_allclose(cl, expected, atol=1e-12)
        # The heated region touches the plane at cc (rounded-box distance 0).
        pose = tool_model.tool_pose(cl, 0.0, phi, self.config)
        self.assertAlmostEqual(
            float(tool_model.heated_sdf([cc], pose, self.config)[0]), 0.0, places=9
        )
        # And it is not a scalar standoff along the normal alone.
        naive = cc + (0.5 * float(self.tool["blade_thickness_mm"]) + self.kerf) * normal
        self.assertGreater(float(np.linalg.norm(cl - naive)), 1e-3)


    def test_tool_body_clear_pose_does_not_penetrate(self):
        penetrates = self.helper("tool_body_penetrates")
        box = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
        box.apply_translation([0.0, 0.0, 30.0])
        # Top-face cut at theta = 0: phi = 0, blade tangent, shaft 14+ mm up.
        phi, reachable = toolpath_sim.finishing_phi(0.0, 1.0, self.config)
        self.assertTrue(reachable)
        cc = np.array([5.0, 0.0, 40.0])
        tip, axis = self._pose(cc, phi, 0.0)
        self.assertFalse(bool(penetrates(box, [tip], [axis], self.config, [0.0])[0]))

    def test_tool_body_penetrates_when_pushed_in(self):
        penetrates = self.helper("tool_body_penetrates")
        box = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
        box.apply_translation([0.0, 0.0, 30.0])
        phi, _ = toolpath_sim.finishing_phi(0.0, 1.0, self.config)
        cc = np.array([5.0, 0.0, 40.0])
        tip, axis = self._pose(cc, phi, 0.0)
        self.assertFalse(bool(penetrates(box, [tip], [axis], self.config, [0.0])[0]))
        # The unheated shaft starts at blade_length (14 mm) above the reference
        # point, so a 3 mm push-in only buries the heated blade (a GOUGE, not a
        # body collision). Pushing 20 mm brings the shaft into the top face.
        pushed = tip - np.array([0.0, 0.0, 20.0])
        self.assertTrue(
            bool(penetrates(box, [pushed], [axis], self.config, [0.0])[0]),
            "a 20 mm push-in must bring the shaft into the block",
        )

    def test_tool_body_penetrates_when_the_shaft_reaches_a_wall(self):
        penetrates = self.helper("tool_body_penetrates")
        # A tall wall whose face is at x = 10.
        # A tall block whose face is at x = 10, spanning the shaft height but
        # stopping below the tilt head so this is a shaft-only collision.
        wall = trimesh.creation.box(extents=(10.0, 30.0, 30.0))
        wall.apply_translation([15.0, 0.0, 85.0])
        tip_clear = np.array([7.0, 0.0, 65.0])
        tip_buried = np.array([9.0, 0.0, 65.0])
        axis = np.array([0.0, 0.0, -1.0])
        self.assertFalse(
            bool(penetrates(wall, [tip_clear], [axis], self.config, [0.0])[0])
        )
        self.assertTrue(
            bool(penetrates(wall, [tip_buried], [axis], self.config, [0.0])[0])
        )

    # -- (5) exit_moves -----------------------------------------------------
    def test_exit_moves_are_clear_and_end_outboard(self):
        exit_moves = self.helper("exit_moves")
        # Box overhang: an 80 mm wide slab whose underside is at z = 90, over a
        # column wall at r = 10 (plus the stock body the wall belongs to).
        slab = trimesh.creation.box(extents=(80.0, 80.0, 20.0))
        slab.apply_translation([0.0, 0.0, 150.0])
        column = trimesh.creation.box(extents=(20.0, 20.0, 80.0))
        column.apply_translation([0.0, 0.0, 50.0])
        body = trimesh.creation.box(extents=(19.0, 19.0, 79.0))
        body.apply_translation([-0.5, 0.0, 50.0])
        mesh = trimesh.util.concatenate([slab, column, body])
        clearance_target = self.R + float(self.config["stock"]["retract_clearance_mm"])
        theta = 0.0
        # A pitched 75 deg cut on the column wall at r = 10, placed with the
        # support function so the heated blade touches the wall, tucked at
        # z = 82 under the overhang at z = 90.
        phi = math.radians(75.0)
        cc = np.array([10.0, 0.0, 82.0])
        tip, _axis = self._pose(cc, phi, theta)
        collector = kinematics.DiagnosticCollector()
        moves = exit_moves(tip, phi, theta, mesh, self.config, clearance_target, collector)
        self.assertGreaterEqual(len(moves), 2)
        self.assertAlmostEqual(float(moves[-1]["phi"]), 0.0, places=9)
        self.assertGreaterEqual(float(moves[-1]["r"]) or 0.0, 0.0)
        # Sample each non-rapid pose every 1 mm and require the body to clear.
        # (poses are dicts in joint space; FK them back to wax poses)
        poses = []
        for move in moves:
            fk = kinematics.forward_kinematics(
                float(move["r"]), float(move["theta"]), float(move["h"]), float(move["phi"]), self.config
            )
            poses.append((np.asarray(fk.tip_xyz_wax), np.asarray(fk.tool_axis_wax)))
        self.assertGreaterEqual(float(np.hypot(*poses[-1][0][:2])), self.R + 1e-6)
        for tip_i, axis_i in poses[:-1]:
            self.assertFalse(
                bool(
                    self.helper("tool_body_penetrates")(
                        mesh, [tip_i], [axis_i], self.config, [theta]
                    )[0]
                ),
                "exit pose buried",
            )


def _tool_body_points(mesh, config, tip, axis):
    """Independent reference: heated blade corners in the wax frame."""

    del mesh
    theta = 0.0
    pose = toolpath_sim._pose_for_axis(tip, axis, theta, config)
    return tool_model.heated_corners(pose, config)


class TestPatch10APIRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_negative_stock_returns_422(self):
        response = self.client.post(
            "/api/sculpt-and-sim",
            json={"sliders": {}, "preset": "demo", "stock_cfg": {"R_stock_mm": -5.0}},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_removed_cone_key_returns_422_naming_it(self):
        response = self.client.post(
            "/api/sculpt-and-sim",
            json={"sliders": {}, "preset": "demo", "tool_cfg": {"cone_half_angle_deg": 30.0}},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("cone_half_angle_deg", response.text)

    def test_heated_length_longer_than_the_blade_returns_422(self):
        response = self.client.post(
            "/api/sculpt-and-sim",
            json={"sliders": {}, "preset": "demo", "tool_cfg": {"heated_length_mm": 99.0}},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("heated_length_mm", response.text)

    def test_demo_response_carries_geometry_provenance(self):
        response = self.client.post(
            "/api/sculpt-and-sim",
            json={"sliders": {}, "preset": "demo"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        provenance = response.json()["config"]["geometry_provenance"]
        self.assertEqual(
            provenance["step_sha256"],
            "00882f0ebeaeaae66b7b8eb28e4d2dc9bbf30d65c2d66705f86deec566fd7bd0",
        )
        self.assertIsNone(provenance["home_pose"])

    def test_max_frames_exceedance_maps_to_422(self):
        response = self.client.post(
            "/api/sculpt-and-sim",
            json={
                "sliders": {},
                "preset": "demo",
                "stock_cfg": {"H_stock_mm": 600.0},
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        codes = {d["code"] for d in detail["diagnostics"]}
        self.assertTrue(
            "FRAME_CAP_EXCEEDED" in codes or "SOFT_LIMIT_EXCEEDED" in codes, codes
        )


class TestCollisionLogAPI(unittest.TestCase):
    """`POST /api/sculpt-and-sim` returns and persists the collision log.

    The trajectory generator is patched so these assertions are deterministic
    and fast: what is under test is the HTTP envelope, the atomic file write,
    and the `mesh_path` / `sliders_enabled` plumbing, not the toolpath itself
    (TestHead2Target covers the real `head_2` run).
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.log_path = Path(self.tempdir.name) / "nested" / "last_collision_report.json"
        config = load_config()
        config["logging"]["collision_log_path"] = str(self.log_path)
        patcher = unittest.mock.patch.object(
            kinematics, "load_config", side_effect=lambda *a, **k: copy.deepcopy(config)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stub(self, *, error: bool = False, events: list | None = None):
        diagnostics = []
        if error:
            diagnostics = [
                kinematics.Diagnostic(
                    code="SOFT_LIMIT_EXCEEDED",
                    severity="error",
                    message="radial joint r=200.000 mm outside [-51.0, 135.0] mm",
                    axis="r",
                    value=200.0,
                    frame=3,
                )
            ]
        events = events or []
        log = {
            "max_events_per_code": 200,
            "codes": {
                event["code"]: {"runs": 1, "truncated": False, "dropped": 0}
                for event in events
            },
            "events": events,
        }
        return toolpath_sim.ToolpathResult(
            frames=[],
            diagnostics=diagnostics,
            preset="demo",
            collision_events=events,
            collision_log=log,
        )

    def _post(self, payload: dict, stub):
        with unittest.mock.patch.object(
            toolpath_sim, "generate_synthetic_carve_path", return_value=stub
        ):
            return self.client.post("/api/sculpt-and-sim", json=payload)

    def test_200_returns_and_writes_the_collision_log(self):
        events = [
            {"code": "GOUGE", "frame_range": [10, 22], "depth_mm": 4.5},
            {"code": "UNREACHABLE_UNDERCUT_AREA", "count": 12},
        ]
        response = self._post({"preset": "demo"}, self._stub(events=events))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["sliders_enabled"])
        self.assertEqual(body["collision_log"]["events"], events)
        self.assertEqual(body["collision_log"]["status"], "ok")
        self.assertEqual(body["collision_log"]["preset"], "demo")
        written = json.loads(self.log_path.read_text(encoding="utf-8"))
        self.assertEqual(written, body["collision_log"])
        self.assertEqual(
            sorted(p.name for p in self.log_path.parent.iterdir()),
            ["last_collision_report.json"],
            "the log is written by atomic replace, not a leftover temp file",
        )

    def test_trajectory_422_returns_and_writes_the_collision_log(self):
        events = [{"code": "SOFT_LIMIT_EXCEEDED", "axis": "r", "frame_range": [3, 3]}]
        response = self._post({"preset": "demo"}, self._stub(error=True, events=events))
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["status"], "error")
        self.assertEqual(detail["collision_log"]["events"], events)
        self.assertEqual(detail["collision_log"]["status"], "error")
        self.assertTrue(
            any(d["code"] == "SOFT_LIMIT_EXCEEDED" for d in detail["diagnostics"])
        )
        written = json.loads(self.log_path.read_text(encoding="utf-8"))
        self.assertEqual(written, detail["collision_log"])

    def test_non_trajectory_422_returns_a_null_collision_log(self):
        response = self.client.post(
            "/api/sculpt-and-sim", json={"tool_cfg": {"heated_length_mm": 99.0}}
        )
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIsNone(detail["collision_log"])
        self.assertEqual(detail["diagnostics"][0]["code"], "TOOL_CFG_INVALID")
        self.assertFalse(self.log_path.exists())

    def test_frame_cap_422_returns_a_null_collision_log(self):
        with unittest.mock.patch.object(
            toolpath_sim,
            "generate_synthetic_carve_path",
            side_effect=toolpath_sim.FrameCapExceededError(300_000, 250_000),
        ):
            response = self.client.post("/api/sculpt-and-sim", json={"preset": "demo"})
        self.assertEqual(response.status_code, 422, response.text)
        detail = response.json()["detail"]
        self.assertIsNone(detail["collision_log"])
        self.assertEqual(detail["diagnostics"][0]["code"], "FRAME_CAP_EXCEEDED")

    def test_mesh_path_traversal_is_rejected(self):
        for value in ("../machine_config.json", "/etc/passwd", "sub/../../machine_config.json"):
            response = self.client.post(
                "/api/sculpt-and-sim", json={"preset": "demo", "mesh_path": value}
            )
            self.assertEqual(response.status_code, 422, f"{value}: {response.text}")
            self.assertIsNone(response.json()["detail"]["collision_log"])

    def test_mesh_path_selects_the_mesh_keyed_landmarks(self):
        response = self._post(
            {"preset": "demo", "mesh_path": "base_head.stl"}, self._stub()
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["sliders_enabled"])
        self.assertEqual(
            response.json()["config"]["target_mesh"]["path"], "presets/base_head.stl"
        )


class TestSignedDistanceConvention(unittest.TestCase):
    """Locks trimesh's sign convention: POSITIVE inside, NEGATIVE outside.

    Inverting this was the root cause of the PATCH-10 `phi = 0` workaround, so it
    is asserted explicitly rather than assumed.
    """

    def test_signed_distance_is_positive_inside_watertight_mesh(self):
        sphere = trimesh.creation.icosphere(radius=10.0, subdivisions=3)
        self.assertTrue(sphere.is_watertight)
        inside = sphere.nearest.signed_distance([[0.0, 0.0, 0.0]])[0]
        outside = sphere.nearest.signed_distance([[30.0, 0.0, 0.0]])[0]
        self.assertGreater(inside, 0.0, "signed_distance is positive inside")
        self.assertLess(outside, 0.0, "signed_distance is negative outside")
        self.assertAlmostEqual(float(inside), 10.0, delta=0.2)
        self.assertAlmostEqual(float(outside), -20.0, delta=1e-6)
        # contains() agrees with the sign convention.
        self.assertTrue(bool(sphere.contains([[0.0, 0.0, 0.0]])[0]))
        self.assertFalse(bool(sphere.contains([[30.0, 0.0, 0.0]])[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

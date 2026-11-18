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
import unittest
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kinematics  # noqa: E402
import face_sculpt  # noqa: E402
import toolpath_sim  # noqa: E402
from server import app  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

CONFIG_PATH = ROOT / "machine_config.json"
HW_FIXTURE = ROOT / "tests" / "fixtures" / "hardware_poses.json"


def load_config(**overrides):
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
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
    """Independent dense-sample check of the full engaged cone sweep."""
    apex_a = np.asarray(a["tip_xyz_wax"], dtype=float)
    apex_b = np.asarray(b["tip_xyz_wax"], dtype=float)
    axis_a = np.asarray(a["tool_axis_wax"], dtype=float)
    axis_b = np.asarray(b["tool_axis_wax"], dtype=float)
    worst = 0.0
    for s in np.linspace(0.0, length_mm, samples):
        pa = apex_a - axis_a * s
        pb = apex_b - axis_b * s
        worst = max(worst, float(np.linalg.norm(pb - pa)))
    return worst


class TestConfigAndForwardKinematics(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.x = self.config["arm_radial_offset_mm"]
        self.h2 = self.config["arm_to_pivot_z_mm"]
        self.p = self.config["pivot_to_tip_mm"]

    def test_config_declares_datums_tool_and_limits(self):
        self.assertGreater(self.p, 0.0)
        self.assertGreater(self.x, 0.0)
        self.assertGreater(self.h2, 0.0)
        self.assertEqual(self.config["stock"]["R_stock_mm"], 40.0)
        self.assertEqual(self.config["stock"]["H_stock_mm"], 120.0)
        self.assertEqual(self.config["stock"]["z_plinth_mm"], 10.0)
        self.assertEqual(self.config["stock"]["finish_allowance_mm"], 1.5)
        self.assertEqual(self.config["singularity"]["r_s_min_mm"], 2.0)
        self.assertEqual(self.config["singularity"]["theta_dot_warn_rad_s"], 3.0)
        for key in (
            "tip_radius_mm",
            "cone_half_angle_deg",
            "engaged_length_mm",
            "melt_kerf_mm",
            "shank_radius_mm",
            "shank_length_mm",
        ):
            self.assertIn(key, self.config["tool"])

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
            (20.0, 0.0, 40.0), normal, config
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
            (100.0, 0.0, 40.0), None, self.config
        )
        self.assertFalse(ik.ok)
        err = next(d for d in ik.diagnostics if d.code == "SOFT_LIMIT_EXCEEDED")
        self.assertEqual(err.severity, "error")
        self.assertEqual(err.axis, "r")
        self.assertGreater(err.value, self.config["limits"]["r_limits_mm"][1])

    def test_height_limit_is_enforced(self):
        ik = kinematics.inverse_kinematics_with_policy(
            (10.0, 0.0, 400.0), None, self.config
        )
        self.assertFalse(ik.ok)
        codes = {d.code for d in ik.diagnostics}
        self.assertIn("SOFT_LIMIT_EXCEEDED", codes)


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
        cls.config = load_config()
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
        cls.config = load_config()
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
        # Independent shadow check on a deterministic subset of poses.
        stock = self.config["stock"]
        allowance = stock["finish_allowance_mm"]
        for f in frames[:: max(1, len(frames) // 12)]:
            theta = f["theta_s"]
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
            self.assertGreaterEqual(f["r_s"], required - 1e-3)

    def test_rapids_retract_outside_stock(self):
        clearance = self.config["stock"]["retract_clearance_mm"]
        limit = self.config["stock"]["R_stock_mm"] + clearance
        rapids = [f for f in self.result.frames if f["is_rapid"]]
        self.assertGreater(len(rapids), 0)
        for f in rapids:
            self.assertGreaterEqual(f["r_s"], limit - 1e-6)

    def test_finishing_uses_phi_and_reports_unreachable_undercuts(self):
        finishing = [f for f in self.result.frames if f["stage"] == "finishing" and not f["is_rapid"]]
        self.assertGreater(len(finishing), 20)
        self.assertTrue(any(abs(f["phi"]) > 0.05 for f in finishing))
        codes = {d.code for d in self.result.diagnostics}
        self.assertIn("UNREACHABLE_UNDERCUT_AREA", codes)
        diag = next(d for d in self.result.diagnostics if d.code == "UNREACHABLE_UNDERCUT_AREA")
        self.assertEqual(diag.severity, "warning")
        self.assertGreater(diag.value, 0.0)

    def test_engaged_length_resampling_bound(self):
        tip_width = self.config["tool"]["tip_width_mm"]
        engaged = self.config["tool"]["engaged_length_mm"]
        limit = 0.5 * tip_width
        frames = self.result.frames
        worst = 0.0
        for prev, cur in zip(frames, frames[1:]):
            if cur["is_rapid"]:
                continue
            worst = max(worst, engaged_cone_displacement(prev, cur, engaged))
        self.assertLessEqual(worst, limit + 1e-6)
        self.assertLess(worst, 1.0)

    def test_unwrapped_theta_is_continuous_through_generator(self):
        thetas = [f["theta_s"] for f in self.result.frames]
        deltas = np.diff(thetas)
        self.assertGreaterEqual(float(np.min(deltas)), -0.5)
        self.assertLessEqual(float(np.max(deltas)), 5.0)
        self.assertGreaterEqual(thetas[-1], thetas[0])

    def test_gouge_detection_flags_tool_inside_target(self):
        # Construct a deliberately bad CL pose that buries the tool in the target.
        cc = np.array([20.0, 0.0, 50.0])
        normal = np.array([1.0, 0.0, 0.0])
        bad_tip = cc - normal * 4.0
        pose = {
            "tip_xyz_wax": tuple(float(v) for v in bad_tip),
            "tool_axis_wax": (1.0, 0.0, 0.0),
        }
        diags = toolpath_sim.detect_gouges(self.mesh, [pose], self.config)
        self.assertTrue(any(d.code == "GOUGE" for d in diags))

    def test_standard_preset_produces_denser_path(self):
        standard = toolpath_sim.generate_synthetic_carve_path(
            self.sculpt, self.config, preset="standard"
        )
        self.assertGreater(len(standard.frames), len(self.result.frames))
        self.assertLessEqual(
            len(standard.frames), self.config["api"]["max_frames"]
        )


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
        # Corrected (PATCH-10c): the old bounds (|z - 48| < 24, r < 34) had no
        # basis.  The body spans z 10-50 and the needle to z 56, so |z - 48| < 24
        # is not a surface test at all.  What matters is that every finishing cut
        # puts the tip apex exactly one standoff (rho + kerf) off the target
        # surface.  Link moves are excluded: only stage == "finishing" cuts.
        result = toolpath_sim.generate_synthetic_carve_path(
            self.needle, self.config, preset="demo"
        )
        finishing = [
            f for f in result.frames if f["stage"] == "finishing" and not f["is_rapid"]
        ]
        self.assertGreater(len(finishing), 40)
        standoff = (
            float(self.config["tool"]["tip_radius_mm"])
            + float(self.config["tool"]["melt_kerf_mm"])
        )
        for frame in finishing[:: max(1, len(finishing) // 40)]:
            tip = np.asarray(frame["tip_xyz_wax"], dtype=float)
            distance = float(abs(self.needle.nearest.signed_distance([tip])[0]))
            self.assertAlmostEqual(distance, standoff, delta=0.6, msg=frame["stage"])

    # (b) reachability condition -------------------------------------------

    def test_finishing_phi_reachability_allows_surface_close_to_phi(self):
        alpha = math.radians(float(self.config["tool"]["cone_half_angle_deg"]))
        phi_hi = math.radians(float(self.config["limits"]["phi_limits_deg"][1]))
        # beta 40 deg with 30 deg bevel -> phi = 10 deg, well inside limits.
        beta_ok = math.radians(40.0)
        phi, reachable = toolpath_sim.finishing_phi(
            math.sin(beta_ok), math.cos(beta_ok), self.config
        )
        self.assertTrue(reachable)
        self.assertAlmostEqual(phi, beta_ok - alpha, places=9)

        # beta inside the "within 90 - alpha" band but beyond the clamp: still reachable.
        beta_clamped = phi_hi + alpha + math.radians(5.0)
        beta_clamped = min(beta_clamped, math.radians(89.0))
        phi_c, reachable_c = toolpath_sim.finishing_phi(
            math.sin(beta_clamped), math.cos(beta_clamped), self.config
        )
        self.assertLessEqual(phi_c, phi_hi + 1e-9)
        self.assertLessEqual(abs(beta_clamped - phi_c), math.pi / 2 - alpha + 1e-9)
        self.assertTrue(reachable_c)

        # A face pointing almost straight down cannot be reached by the bevel
        # flank.  Corrected (PATCH-10c): beta = 89.9 deg is a *vertical wall*
        # (horizontal normal, n_z ~= 0), reachable because |89.9 - 59.9| = 30
        # <= 90 - 30.  beta = 179 deg is the downward-facing case the test means.
        beta_bad = math.radians(179.0)
        phi_bad, reachable_bad = toolpath_sim.finishing_phi(
            math.sin(beta_bad), math.cos(beta_bad), self.config
        )
        self.assertFalse(reachable_bad)
        self.assertGreater(abs(beta_bad - phi_bad), math.pi / 2 - alpha + 1e-9)

    # (c) safe three-step approach/retract ---------------------------------

    def test_approach_and_retract_never_drop_below_cut_height(self):
        result = toolpath_sim.generate_synthetic_carve_path(
            self.needle, self.config, preset="demo"
        )
        frames = result.frames
        stock_top = float(self.config["stock"]["H_stock_mm"])
        clearance = float(self.config["stock"]["retract_clearance_mm"])
        pivot = float(self.config["pivot_to_tip_mm"])
        engaged = float(self.config["tool"]["engaged_length_mm"])
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
                self.assertGreaterEqual(float(cur["r_s"]), float(self.config["stock"]["R_stock_mm"]))
                self.assertGreaterEqual(float(prev["r_s"]), float(self.config["stock"]["R_stock_mm"]))
        # Approach into a cut is a multi-step move: descending h with phi change
        # is never a single step from clearance straight to a tilted cut.
        for prev, cur in zip(frames, frames[1:]):
            if bool(prev["is_rapid"]) and not bool(cur["is_rapid"]):
                # arrive vertical first, then reorient in place
                self.assertAlmostEqual(float(cur["phi"]), 0.0, places=6)
        for frame in frames:
            self.assertGreaterEqual(float(frame["z_s"]), -engaged - 1e-6)
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
        cls.kerf_offset = float(cls.config["tool"]["tip_radius_mm"]) + float(
            cls.config["tool"]["melt_kerf_mm"]
        )
        cls.alpha = math.radians(float(cls.config["tool"]["cone_half_angle_deg"]))

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

    def _ring(self, apex, axis, station, radius):
        tmp = np.array([0.0, 0.0, 1.0])
        if abs(float(axis @ tmp)) > 0.9:
            tmp = np.array([1.0, 0.0, 0.0])
        e1 = np.cross(axis, tmp)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(axis, e1)
        base = apex - axis * station
        angles = np.arange(8) * (math.pi / 4.0)
        return base + radius * (
            np.cos(angles)[:, None] * e1[None, :] + np.sin(angles)[:, None] * e2[None, :]
        )

    def _pose(self, cc, phi, theta, extra=0.0):
        """Tool pose with its apex at the CL (or pushed `extra` along -n)."""
        n = np.array([math.cos(theta), math.sin(theta), 0.0])
        apex = np.asarray(cc, dtype=float) + n * (self.kerf_offset - extra)
        return apex, self._axis_of(phi, theta)

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
        table = [
            (0.0, 0.0, True),
            (40.0, 10.0, True),
            (90.0, 60.0, True),
            (120.0, 75.0, True),
            (179.0, 75.0, False),
            (-40.0, -10.0, True),
        ]
        for beta_deg, phi_deg, reachable in table:
            beta = math.radians(beta_deg)
            phi, ok = toolpath_sim.finishing_phi(
                math.sin(beta), math.cos(beta), self.config
            )
            self.assertAlmostEqual(math.degrees(phi), phi_deg, delta=1e-6, msg=beta_deg)
            self.assertEqual(ok, reachable, beta_deg)
            if reachable:
                self.assertLessEqual(
                    abs(beta - phi), math.pi / 2 - self.alpha + 1e-9, beta_deg
                )

    def test_finishing_phi_never_flips_an_undercut_forward(self):
        # A steep overhang must not be clamped to phi_hi and called reachable.
        beta = math.radians(150.0)
        _, ok = toolpath_sim.finishing_phi(math.sin(beta), math.cos(beta), self.config)
        self.assertFalse(ok)

    # -- (3) cutter_location ------------------------------------------------
    def test_cutter_location_offsets_along_true_normal(self):
        cutter_location = self.helper("cutter_location")
        # 45 deg plane in x-z: normal (1, 0, 1)/sqrt2, no snapping allowed.
        normal = np.array([1.0, 0.0, 1.0]) / math.sqrt(2.0)
        sphere = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
        sphere.apply_transform(trimesh.geometry.align_vectors([0.0, 0.0, 1.0], normal))
        face = int(np.argmax(sphere.face_normals @ normal))
        cc = np.asarray(sphere.triangles_center[face], dtype=float)
        # Project onto the exact 45 deg plane so the fixture is analytic.
        cc = cc - normal * (float(cc @ normal) - 10.0 * math.sqrt(2.0))
        n_r = float(normal[0])
        n_z = float(normal[2])
        apex = cutter_location(cc, n_r, n_z, 0.0, self.config)
        signed = float(sphere.nearest.signed_distance([apex])[0])
        self.assertAlmostEqual(-signed, self.kerf_offset, delta=1e-6)
        self.assertAlmostEqual(float(apex[2] - cc[2]), self.kerf_offset * n_z, delta=1e-9)
        self.assertAlmostEqual(float(apex[0] - cc[0]), self.kerf_offset * n_r, delta=1e-9)

    # -- (4) tool_body_penetrates -------------------------------------------
    def test_tool_body_clear_pose_does_not_penetrate(self):
        penetrates = self.helper("tool_body_penetrates")
        box = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
        box.apply_translation([0.0, 0.0, 30.0])
        # Top-face cut at theta = 0, phi from finishing_phi (u_phi = -1).
        phi, reachable = toolpath_sim.finishing_phi(0.0, 1.0, self.config)
        self.assertTrue(reachable)
        cc = np.array([5.0, 0.0, 40.0])
        apex, axis = self._pose(cc, phi, 0.0)
        self.assertFalse(bool(penetrates(box, [apex], [axis], self.config)[0]))

    def test_tool_body_penetrates_when_pushed_in(self):
        penetrates = self.helper("tool_body_penetrates")
        box = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
        box.apply_translation([0.0, 0.0, 30.0])
        phi, _ = toolpath_sim.finishing_phi(0.0, 1.0, self.config)
        cc = np.array([5.0, 0.0, 40.0])
        apex, axis = self._pose(cc, phi, 0.0, extra=1.0)
        self.assertTrue(bool(penetrates(box, [apex], [axis], self.config)[0]))

    def test_tool_body_penetrates_when_tilted_into_wall(self):
        penetrates = self.helper("tool_body_penetrates")
        # A tall wall at r = 15 (theta = 0, y in [-15, 15]).
        wall = trimesh.creation.box(extents=(30.0, 30.0, 60.0))
        wall.apply_translation([0.0, 0.0, 40.0])
        theta = 0.0
        cc = np.array([15.0, 0.0, 65.0])
        # Correct pitch from the wall's radial normal: apex sits outboard.
        phi_ok, reachable = toolpath_sim.finishing_phi(1.0, 0.0, self.config)
        self.assertTrue(reachable)
        apex_ok, axis_ok = self._pose(cc, phi_ok, theta)
        self.assertFalse(bool(penetrates(wall, [apex_ok], [axis_ok], self.config)[0]))
        # Apex still clear of the wall, but the body pitched so the flank
        # leans back into it: the ring at mid-station crosses r = 15.
        for phi_bad in (math.radians(-60.0), math.radians(-30.0), 0.0):
            apex_bad = np.array([15.0 + self.kerf_offset, 0.0, 65.0])
            axis_bad = self._axis_of(phi_bad, theta)
            stations = (0.25, 0.5, 0.75, 1.0)
            engaged = float(self.config["tool"]["engaged_length_mm"])
            radii = [
                float(self.config["tool"]["tip_radius_mm"])
                + t * engaged * math.tan(self.alpha)
                for t in stations
            ]
            reaches_wall = [
                float((apex_bad - axis_bad * (t * engaged))[0]) - r < 0.0
                for t, r in zip(stations, radii)
            ]
            if any(reaches_wall):
                self.assertTrue(
                    bool(penetrates(wall, [apex_bad], [axis_bad], self.config)[0]),
                    f"phi {math.degrees(phi_bad):.1f}",
                )
                return
        self.fail("fixture did not lean the body into the wall")

    # -- (5) exit_moves -----------------------------------------------------
    def test_exit_moves_are_clear_and_end_outboard(self):
        exit_moves = self.helper("exit_moves")
        # Box overhang: an 80 mm wide slab whose underside is at z = 90.
        slab = trimesh.creation.box(extents=(80.0, 80.0, 20.0))
        slab.apply_translation([0.0, 0.0, 100.0])
        column = trimesh.creation.box(extents=(20.0, 20.0, 80.0))
        column.apply_translation([0.0, 0.0, 50.0])
        mesh = trimesh.util.concatenate([slab, column])
        clearance_target = self.R + float(self.config["stock"]["retract_clearance_mm"])
        theta = 0.0
        # Cut the column wall at r = 10 pitched forward, apex tucked at z = 82.
        phi = math.radians(75.0)
        apex = np.array([10.0 + self.kerf_offset, 0.0, 82.0])
        collector = kinematics.DiagnosticCollector()
        moves = exit_moves(apex, phi, theta, mesh, self.config, clearance_target, collector)
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
        for apex_i, axis_i in poses[:-1]:
            self.assertFalse(
                bool(self.helper("tool_body_penetrates")(mesh, [apex_i], [axis_i], self.config)[0]),
                "exit pose buried",
            )


def _tool_body_points(mesh, config, apex, axis, stations=(0.25, 0.5, 0.75, 1.0)):
    """Independent reference: axis + 8 ring points at each station."""
    del mesh
    tool = config["tool"]
    engaged = float(tool["engaged_length_mm"])
    tip_r = float(tool["tip_radius_mm"])
    alpha = math.radians(float(tool["cone_half_angle_deg"]))
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    tmp = np.array([0.0, 0.0, 1.0])
    if abs(float(axis @ tmp)) > 0.9:
        tmp = np.array([1.0, 0.0, 0.0])
    e1 = np.cross(axis, tmp)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    points = [np.asarray(apex, dtype=float)]
    for t in stations:
        base = np.asarray(apex, dtype=float) - axis * (t * engaged)
        radius = tip_r + t * engaged * math.tan(alpha)
        for k in range(8):
            angle = k * math.pi / 4.0
            points.append(base + radius * (math.cos(angle) * e1 + math.sin(angle) * e2))
    return np.asarray(points)


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

    def test_zero_tool_radius_returns_422(self):
        response = self.client.post(
            "/api/sculpt-and-sim",
            json={"sliders": {}, "preset": "demo", "tool_cfg": {"tip_radius_mm": 0.0}},
        )
        self.assertEqual(response.status_code, 422, response.text)

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

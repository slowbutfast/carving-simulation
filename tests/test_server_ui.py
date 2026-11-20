"""End-to-end endpoint tests for the Windows XP studio UI shell.

These exercise the FastAPI app that actually ships: the static root mount, the
stylesheet, and the upload-limit / preset contracts that ``static/upload.js``
and ``static/app.js`` rely on.
"""

import unittest

from fastapi.testclient import TestClient

import server


class ServerUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def test_index_serves_xp_studio(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn("4-DOF Wax Carver Studio 2001", response.text)

    def test_xp_css_served(self):
        response = self.client.get("/xp.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers.get("content-type", ""))
        self.assertIn(".transport-dock", response.text)

    def test_health_advertises_upload_limits(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertIsInstance(body.get("max_upload_bytes"), int)
        self.assertGreater(body["max_upload_bytes"], 0)

        formats = body.get("accepted_formats") or []
        for suffix in (".stl", ".obj", ".3mf"):
            self.assertIn(suffix, formats)

    def test_presets_lists_bundled_base_head(self):
        response = self.client.get("/api/presets")
        self.assertEqual(response.status_code, 200)
        presets = response.json().get("presets") or []
        self.assertTrue(presets, "expected at least one bundled preset")

        entry = next(
            (
                preset
                for preset in presets
                if preset.get("id") == "base_head" or preset.get("slug") == "base_head"
            ),
            None,
        )
        self.assertIsNotNone(entry, presets)
        self.assertTrue(entry.get("label") or entry.get("name"))


if __name__ == "__main__":
    unittest.main()

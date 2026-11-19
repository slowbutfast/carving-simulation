"""OCP-gated tests for the offline CAD extractor.

Skipped when ``cadquery-ocp`` is not importable, so the normal runtime suite
does not require the dev-only CAD stack.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR = ROOT / "scripts" / "extract_machine.py"


def load_extractor():
    spec = importlib.util.spec_from_file_location("extract_machine", EXTRACTOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["extract_machine"] = module
    spec.loader.exec_module(module)
    return module


try:
    import OCP  # noqa: F401

    HAVE_OCP = True
except Exception:  # pragma: no cover - depends on the dev environment
    HAVE_OCP = False


@unittest.skipUnless(HAVE_OCP, "cadquery-ocp is not installed (dev-only)")
class TestExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_extractor()
        cls.committed = json.loads(
            (ROOT / "machine_geometry.json").read_text(encoding="utf-8")
        )

    def test_extraction_is_deterministic(self):
        first = self.module.dumps(self.module.build_geometry(models_dir=None))
        second = self.module.dumps(self.module.build_geometry(models_dir=None))
        self.assertEqual(first, second)

    def test_committed_artifact_is_current(self):
        rebuilt = self.module.build_geometry(models_dir=None)
        committed = copy.deepcopy(self.committed)
        committed.pop("models", None)
        rebuilt.pop("models", None)
        self.assertEqual(json.dumps(rebuilt, sort_keys=True), json.dumps(committed, sort_keys=True))

    def test_glb_export_is_deterministic_within_the_budget(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            a = self.module.build_geometry(models_dir=Path(first_dir))
            b = self.module.build_geometry(models_dir=Path(second_dir))
            self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
            for name in a["models"]:
                left = Path(first_dir) / f"{name}.glb"
                right = Path(second_dir) / f"{name}.glb"
                self.assertEqual(left.exists(), right.exists())
                if left.exists():
                    self.assertEqual(left.read_bytes(), right.read_bytes(), name)

    def test_unmatched_part_surfaces_as_unassigned(self):
        roles = json.loads((ROOT / "cad_part_roles.json").read_text(encoding="utf-8"))
        roles = copy.deepcopy(roles)
        roles["rules"] = [
            rule for rule in roles["rules"] if rule["prefix"] != "Platform_Ring"
        ]
        # The remaining rules must still assign everything else by prefix.
        occurrences = self.module.load_occurrences(ROOT / "assets" / "Wax+Face+Carver+v2.stp")
        by_link = self.module.assign_roles(occurrences, roles)
        unmatched = [name for name in by_link["unassigned"] if name.startswith("Platform_Ring")]
        self.assertTrue(unmatched, "a removed rule must surface its parts as unassigned")
        self.assertEqual(sum(len(names) for names in by_link.values()), 295)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Test tiers and per-class fixture release.

``heavy`` marks tests that perform a full toolpath generation. They are skipped
unless ``RUN_HEAVY_TESTS=1`` and only run during verification, once, through
``scripts/safe-test.sh``.

``ReleasesClassFixtures`` gives a test class a ``tearDownClass`` that drops the
attributes named in ``_class_fixtures`` and runs ``gc.collect()``, so a cached
toolpath result or mesh cannot outlive its class.
"""

from __future__ import annotations

import gc
import os
import unittest

RUN_HEAVY_ENV = "RUN_HEAVY_TESTS"
HEAVY_REASON = "heavy test: set RUN_HEAVY_TESTS=1"

heavy = unittest.skipUnless(os.environ.get(RUN_HEAVY_ENV) == "1", HEAVY_REASON)


class ReleasesClassFixtures:
    """Mixin: free the class fixtures named in ``_class_fixtures``."""

    _class_fixtures: tuple[str, ...] = ()

    @classmethod
    def tearDownClass(cls) -> None:
        for name in cls._class_fixtures:
            try:
                delattr(cls, name)
            except AttributeError:  # pragma: no cover - defensive
                pass
        gc.collect()
        parent = getattr(super(), "tearDownClass", None)
        if parent is not None:
            parent()

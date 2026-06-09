"""Shared access to real DDD sample files.

The files in ``DDD/`` contain personal data (driver names, card numbers, VINs)
and are intentionally excluded from version control (see ``.gitignore``). Tests
that require them should cleanly skip when the folder is not present
(e.g. in CI) instead of failing.
"""
import os
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")


def real_ddd_files():
    """Paths to present .ddd files, empty list if DDD/ is absent."""
    if not os.path.isdir(DDD_DIR):
        return []
    return [os.path.join(DDD_DIR, n) for n in sorted(os.listdir(DDD_DIR))
            if n.lower().endswith(".ddd")]


HAS_REAL_FILES = bool(real_ddd_files())

requires_real_files = unittest.skipUnless(
    HAS_REAL_FILES,
    "real DDD files absent (DDD/ is git-ignored: contains personal data)")

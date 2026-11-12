"""Shared access to real DDD sample files.

The files in ``DDD/`` contain personal data (driver names, card numbers, VINs)
and are intentionally excluded from version control (see ``.gitignore``). Tests
that require them should cleanly skip when the folder is not present
(e.g. in CI) instead of failing.
"""
import glob
import os
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")


def real_ddd_files():
    """Paths to present .ddd files, empty list if DDD/ is absent."""
    if not os.path.isdir(DDD_DIR):
        return []
    return [os.path.join(DDD_DIR, n) for n in sorted(os.listdir(DDD_DIR))
            if n.lower().endswith(".ddd")]


def require_real_file(name):
    """Return a named private fixture or skip only tests that require it.

    ``name`` may use ``*``/``?`` glob characters (e.g. match by the file's
    hash suffix): the private names carry plates, VINs and card numbers and
    must never be embedded in tracked code.
    """
    path = os.path.join(DDD_DIR, name)
    if not os.path.isfile(path):
        matches = sorted(glob.glob(path))
        if not matches:
            raise unittest.SkipTest(f"Private DDD fixture not available: {name}")
        path = matches[0]
    return path


#: Leading TRTP of a VU download (``0x76 TRTP``), per generation (Annex 1B
#: TREP table; Annex 1C TRTP table). ``0x76 0x06`` is a VU-relayed card image.
VU_TRTP = {
    "g1": frozenset(range(0x01, 0x06)),
    "g2": frozenset(range(0x21, 0x26)),
    "g22": frozenset({0x31, 0x32, 0x33, 0x35}),
}


def vu_generation(path):
    """``"g1"``/``"g2"``/``"g22"`` for a VU download, ``None`` for anything else.

    Read from the leading message header only, so tests can state which *kind*
    of file they need without knowing the private file names.
    """
    with open(path, "rb") as handle:
        head = handle.read(2)
    if len(head) != 2 or head[0] != 0x76:
        return None
    for generation, trtps in VU_TRTP.items():
        if head[1] in trtps:
            return generation
    return None


def real_vu_files(*generations):
    """Present VU downloads, optionally restricted to the given generations."""
    wanted = set(generations or VU_TRTP)
    return [path for path in real_ddd_files() if vu_generation(path) in wanted]


#: Hash-suffixed fixtures of the original author's private corpus. Assertions
#: that pin facts of *that* corpus (exact record counts, corpus-wide totals) run
#: only when all of them are present; any other corpus gets the invariants only.
AUTHOR_CORPUS_MARKERS = (
    "*_3B330594AC.ddd", "*_D47C4D98DF.ddd", "*98F20BEDC7.ddd", "*95537A1054.ddd",
)


def is_author_corpus():
    """True when ``DDD/`` holds the original author's private corpus."""
    return all(glob.glob(os.path.join(DDD_DIR, name))
               for name in AUTHOR_CORPUS_MARKERS)


HAS_REAL_FILES = bool(real_ddd_files())

requires_real_files = unittest.skipUnless(
    HAS_REAL_FILES,
    "real DDD files absent (DDD/ is git-ignored: contains personal data)")

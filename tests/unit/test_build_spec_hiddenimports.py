"""BUILD-SPEC-IMPORTS: every ``hiddenimports`` entry must name a real module.

``build.spec`` lists modules PyInstaller cannot see statically so that they are
bundled anyway. Five entries named modules that do not exist
(``core.decoders.primitives``, ``core.decoders.card``, ``core.decoders.g22_card``,
``core.decoders.vu_trep``, ``core.decoders.g2_dispatch``) after the decoders were
split into ``card_ef`` / ``card_g22`` / ``vu_g1`` / ``vu_g2``. PyInstaller treats
an unresolvable hidden import as a warning, so the bundle kept working only
because those decoders happen to be imported statically — the guarantee the list
exists for was gone.

This test imports every entry, so a rename that misses the spec fails here
instead of in a release build.
"""
import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "build.spec"


def _hiddenimports():
    """The ``hiddenimports=[...]`` literal from ``build.spec``."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "hiddenimports":
                return [element.value for element in keyword.value.elts]
    raise AssertionError("build.spec has no hiddenimports= list")


def test_hiddenimports_is_not_empty():
    """Guard the parser above: an empty list would make the test vacuous."""
    assert len(_hiddenimports()) > 10


@pytest.mark.parametrize("module", _hiddenimports())
def test_hidden_import_resolves(module):
    """Each listed module must be importable from this tree."""
    importlib.import_module(module)


def test_decoder_and_parser_modules_are_all_listed():
    """Every real decoder/parser module must be listed, not just importable."""
    listed = set(_hiddenimports())
    for package in ("core.decoders", "core.parser", "core.crypto",
                    "core.registry", "core.utils"):
        for path in (ROOT / package.replace(".", "/")).glob("*.py"):
            if path.stem.startswith("_"):
                continue
            name = f"{package}.{path.stem}"
            assert name in listed, f"{name} is missing from build.spec hiddenimports"

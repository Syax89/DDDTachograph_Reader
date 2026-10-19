"""The bundled PDF fallback font: asset, licence, coverage and resolution.

The PDF report is set in Helvetica, whose encoding has no ``Ė`` (U+0116) — and the
official name of one registry manufacturer is
``UŽDAROJI AKCINĖ BENDROVĖ "LODVILA"``. reportlab boxes what its font cannot
encode, and reportlab's own bundled Vera face has no U+0116 either, so the export
ships a face of its own instead of hoping the reader's machine has one.

What these tests pin is the *behaviour and the packaging*: the markup that comes
out, the glyph coverage of all 65 public labels, the real PDF that is written,
where the asset sits relative to the package and to a frozen bundle's
``_MEIPASS``, and — because the file is a packaging prerequisite, not an optional
runtime fallback — that a missing asset fails the export instead of returning a
report with a boxed identity.
"""
import os
import re
import shutil
import sys

import pytest

reportlab = pytest.importorskip("reportlab")

from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from xml.sax.saxutils import escape  # noqa: E402

import app.export as export  # noqa: E402
from core.utils.manufacturer_codes import MANUFACTURER_CODES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT = os.path.join(ROOT, "assets", "fonts", "DejaVuSans.ttf")
LICENCE = os.path.join(ROOT, "assets", "fonts", "DejaVuSans.LICENSE")
#: The one registry label the standard font cannot set (see the module docstring).
UNICODE_LABEL = MANUFACTURER_CODES[0xB1]
FALLBACK = export._PDF_FALLBACK_FONT


def _export_pdf(path, name=UNICODE_LABEL):
    """Export a one-event report carrying *name* as the manufacturer."""
    export.ExportManager.export_to_pdf(
        {"metadata": {"filename": "manufacturer.ddd", "is_vu": True},
         "events": [{"description": "Over speeding", "manufacturer": name}]},
        str(path))
    with open(path, "rb") as handle:
        return handle.read()


@pytest.fixture
def unregistered_fallback(monkeypatch):
    """A fresh fallback-registration context (reportlab has no unregister API)."""
    monkeypatch.delitem(pdfmetrics._fonts, FALLBACK, raising=False)
    assert FALLBACK not in pdfmetrics.getRegisteredFontNames()
    return FALLBACK


# ── the asset, its licence and the package build ───────────────────────────


def test_the_font_ships_in_the_package_where_the_export_looks_for_it():
    assert os.path.isfile(FONT), f"{FONT} must ship with the application"
    with open(FONT, "rb") as handle:
        assert handle.read(4) in (b"\x00\x01\x00\x00", b"true", b"ttcf")
    assert os.path.getsize(FONT) > 100_000, "a truncated font would box silently"


def test_the_upstream_licence_ships_beside_the_font():
    text = open(LICENCE, encoding="utf-8").read()
    assert "Bitstream Vera" in text                     # the face it derives from
    assert "https://dejavu-fonts.github.io/" in text    # where it came from
    assert "Permission is hereby granted" in text       # the licence itself


def test_the_package_build_carries_the_font_directory():
    spec = open(os.path.join(ROOT, "build.spec"), encoding="utf-8").read()
    assert re.search(r'os\.path\.join\(base_path,\s*"assets",\s*"fonts"\)', spec), (
        "build.spec must collect assets/fonts")
    assert re.search(r'added_files\.append\(\(ui_fonts,\s*os\.path\.join\('
                     r'"assets",\s*"fonts"\)\)\)', spec), (
        "build.spec must place assets/fonts where app/export.py looks for it")


# ── glyph coverage of the public registry ──────────────────────────────────


def test_the_font_covers_every_character_of_every_public_label():
    assert len(MANUFACTURER_CODES) == 65, "the public registry is the 65 assigned codes"
    face = TTFont("CoverageProbe", FONT).face
    missing = {
        char for name in MANUFACTURER_CODES.values() for char in name
        if not char.isspace() and face.charToGlyph.get(ord(char), 0) == 0
    }
    assert not missing, f"the bundled face cannot draw {sorted(missing)}"


def test_exactly_one_registry_label_needs_the_fallback_face():
    """The markup states which names the standard font cannot set — nothing else."""
    needs_fallback = [name for name in MANUFACTURER_CODES.values()
                      if export._pdf_markup(name) != escape(name)]
    assert needs_fallback == [UNICODE_LABEL]


def test_the_letters_of_that_name_are_preserved_not_repaired():
    markup = export._pdf_markup(UNICODE_LABEL)
    # Both "Ė" are still "Ė", set in the fallback face; no ASCII "E", no "?".
    assert markup.count(f'<font name="{FALLBACK}">\u0116</font>') == 2
    assert markup.replace(f'<font name="{FALLBACK}">', "").replace("</font>", "") \
        == UNICODE_LABEL


# ── the real PDF: the face is embedded, and only where it is needed ────────


def test_the_exported_pdf_embeds_the_bundled_face(tmp_path):
    assert b"DejaVuSans" in _export_pdf(tmp_path / "unicode.pdf")


def test_a_report_without_unsupported_text_embeds_no_extra_face(tmp_path):
    payload = _export_pdf(tmp_path / "ascii.pdf", "Actia S.A.")
    assert b"DejaVuSans" not in payload
    assert b"Helvetica" in payload


# ── resolution: source checkout and frozen bundle ──────────────────────────


def test_the_export_resolves_the_font_from_a_frozen_bundle(
        tmp_path, monkeypatch, unregistered_fallback):
    """``sys._MEIPASS`` is where PyInstaller unpacks the bundled datas."""
    bundle = tmp_path / "meipass"
    (bundle / "assets" / "fonts").mkdir(parents=True)
    shutil.copy(FONT, bundle / "assets" / "fonts" / "DejaVuSans.ttf")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    assert FALLBACK not in pdfmetrics.getRegisteredFontNames()
    payload = _export_pdf(tmp_path / "frozen.pdf")
    assert b"DejaVuSans" in payload
    assert FALLBACK in pdfmetrics.getRegisteredFontNames()


def test_a_missing_font_fails_the_export_instead_of_boxing_the_name(
        tmp_path, monkeypatch, unregistered_fallback, caplog):
    """Fail closed: no plausible-looking report with a corrupted identity."""
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "empty-bundle"), raising=False)
    path = tmp_path / "missing.pdf"
    with caplog.at_level("WARNING"):
        with pytest.raises(FileNotFoundError) as failure:
            export.ExportManager.export_to_pdf(
                {"metadata": {"filename": "missing.ddd", "is_vu": True},
                 "events": [{"description": "Over speeding",
                             "manufacturer": UNICODE_LABEL}]},
                str(path))
    message = str(failure.value)
    assert "DejaVuSans.ttf" in message and "missing from this installation" in message
    assert not path.exists(), "a failed export must not leave a half report behind"
    assert FALLBACK not in pdfmetrics.getRegisteredFontNames()


# ── the dependency stays optional ──────────────────────────────────────────


def test_importing_the_exporter_does_not_import_reportlab():
    """PDF stays an optional, lazily imported dependency of the exporter."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c",
         "import sys, app.export; print('reportlab' in sys.modules)"],
        cwd=ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False", result.stdout + result.stderr

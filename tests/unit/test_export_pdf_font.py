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
import base64
import hashlib
import os
import re
import shutil
import sys
import zlib

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
#: The official upstream release files, not a distribution rebuild: a Debian
#: rebuild (759720 bytes) and its packaging copyright once shipped here, and the
#: packaged licence is not the font's own notice. Pinned so a silent swap — an
#: older release, a patched face, a different licence file — fails the suite.
FONT_SHA256 = "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954"
LICENCE_SHA256 = "7a083b136e64d064794c3419751e5c7dd10d2f64c108fe5ba161eae5e5958a93"
#: The one registry label the standard font cannot set (see the module docstring).
UNICODE_LABEL = MANUFACTURER_CODES[0xB1]
FALLBACK = export._PDF_FALLBACK_FONT


def _winansi_can_draw(char, encoding):
    """Can the report's own font encode *char*, so no fallback is needed?"""
    try:
        char.encode(encoding)
    except UnicodeEncodeError:
        return False
    return True


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
        payload = handle.read()
    assert payload[:4] in (b"\x00\x01\x00\x00", b"true", b"ttcf")
    assert len(payload) > 100_000, "a truncated font would box silently"
    assert hashlib.sha256(payload).hexdigest() == FONT_SHA256, (
        "the bundled face is the official DejaVu Sans 2.37 release file")


def test_the_upstream_licence_ships_beside_the_font():
    with open(LICENCE, "rb") as handle:
        raw = handle.read()
    assert hashlib.sha256(raw).hexdigest() == LICENCE_SHA256, (
        "the licence is the DejaVu 2.37 release file, not a packaging copyright")
    text = raw.decode("utf-8")
    assert "Bitstream Vera Fonts Copyright" in text   # the face it derives from
    assert "Arev Fonts Copyright" in text             # the imported glyphs
    assert "Tavmjong Bah" in text                     # ... and their notice
    assert "Permission is hereby granted" in text     # the licence itself


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


# ── the glyphs really in the PDF, read back from its own bytes ─────────────
#
# "DejaVuSans" being somewhere in the file only says a face was written. What
# proves the letters survived is the subset's own ToUnicode map: which code
# points the embedded face declares. Nothing here imports a PDF library — the
# objects are found in the raw bytes and the Flate/ASCII85 stream is decoded —
# so the check holds whatever reportlab's object layout does.


def _stream_bytes(pdf_bytes, number):
    """The decoded payload of object *number* (ASCII85 and/or Flate)."""
    body = re.search(rb"\b%d 0 obj(.*?)endobj" % number, pdf_bytes, re.S).group(1)
    stream = body.partition(b"stream")[2].lstrip(b"\r\n")
    stream = stream[:stream.rfind(b"endstream")]
    try:
        return zlib.decompress(stream)
    except zlib.error:                       # reportlab may ASCII85 it first
        return zlib.decompress(base64.a85decode(
            stream, adobe=stream.lstrip().startswith(b"<~")))


def _fallback_code_points(pdf_bytes):
    """Code points the embedded DejaVu subset declares in its ToUnicode map.

    The subset maps every byte 0x00-0x7F to itself (reportlab's default table),
    so a character the report had to set in this face is exactly a mapping to a
    different, non-zero code point.
    shortcut: only bfchar destinations are read; extend it if reportlab starts
    writing bfrange, the test then sees no entries and fails loudly.
    """
    font = re.search(
        rb"/BaseFont\s*/[A-Z]{6}\+\w*DejaVuSans\b[^>]*?/ToUnicode\s+(\d+)\s+\d+\s+R",
        pdf_bytes, re.S)
    assert font, "the PDF embeds no DejaVu subset with a ToUnicode map"
    cmap = _stream_bytes(pdf_bytes, int(font.group(1))).decode("latin-1")
    assert "begincmap" in cmap
    code_points = set()
    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
        for source, target in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            if int(target, 16) and int(target, 16) != int(source, 16):
                code_points.add(int(target, 16))
    return code_points


def test_the_pdf_bytes_show_which_letters_needed_the_bundled_face(tmp_path):
    """The embedded subset carries exactly the letters WinAnsi cannot draw.

    Of the label's letters only "Ė" (U+0116) is outside the report's own
    WinAnsi encoding — "Ž" (U+017D) is cp1252 0x8E and stays in Helvetica — so
    that one code point is what the bundled face must have and declare. Setting
    the same letter as a plain "E" would leave the subset with nothing to
    declare, which is what this test refuses.
    """
    payload = _export_pdf(tmp_path / "glyphs.pdf")
    encoding = pdfmetrics.getFont("Helvetica").encName
    unsupported = {
        ord(char) for char in UNICODE_LABEL
        if not _winansi_can_draw(char, encoding)
    }
    assert unsupported == {0x0116}, "only Ė is outside the report's encoding"
    assert _fallback_code_points(payload) == unsupported

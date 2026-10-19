"""The PDF must not print a black square where the report row has a real character.

Two different problems, two different answers:

* the shared report's warning sign (``⚠``) is replaced by a plain stand-in the
  standard font has (``_pdf_plain``), because it is a *marker* and the meaning is
  in the word beside it;
* a character the standard font simply does not have — the Lithuanian ``Ė``
  (U+0116) in the official manufacturer name of registry code 0xB1 — is set in
  the bundled fallback face, because it is part of a *fact*: a name is never
  transliterated, ASCII-repaired or replaced.
"""
import pytest

reportlab = pytest.importorskip("reportlab")

from app.export import _PDF_FALLBACK_FONT, _pdf_markup, _pdf_plain  # noqa: E402
from core.utils.manufacturer_codes import MANUFACTURER_CODES  # noqa: E402

#: The official name of manufacturer code 0xB1, the one label Helvetica cannot set.
UNICODE_LABEL = MANUFACTURER_CODES[0xB1]


@pytest.mark.parametrize("cell, expected", [
    ("\u26a0 08:00", "! 08:00"),
    ("08:00", "08:00"),
    (0, "0"),
    ("\u26a0 \u26a0 1:00", "! ! 1:00"),
])
def test_the_warning_sign_becomes_a_character_helvetica_has(cell, expected):
    assert _pdf_plain(cell) == expected


# ── text the standard font can draw is untouched ────────────────────────────


@pytest.mark.parametrize("value, expected", [
    ("Actia S.A.", "Actia S.A."),
    (MANUFACTURER_CODES[0x12], MANUFACTURER_CODES[0x12]),   # accented, drawable
    ("a & b < c > d", "a &amp; b &lt; c &gt; d"),
    ("", ""),
])
def test_drawable_text_is_escaped_and_nothing_else(value, expected):
    """Same markup, same metrics as before: an ordinary report cannot re-paginate."""
    assert _pdf_markup(value) == expected


def test_the_warning_sign_still_reaches_the_markup_as_a_stand_in():
    assert _pdf_markup(_pdf_plain("\u26a0 08:00")) == "! 08:00"


# ── a character outside the standard font: the bundled face, in place ───────


def test_only_the_unsupported_characters_are_switched_to_the_bundled_face():
    assert _pdf_markup(UNICODE_LABEL) == (
        'U\u017dDAROJI AKCIN'
        f'<font name="{_PDF_FALLBACK_FONT}">\u0116</font>'
        ' BENDROV'
        f'<font name="{_PDF_FALLBACK_FONT}">\u0116</font>'
        ' "LODVILA"'
    )


def test_markup_around_unsupported_text_keeps_escaping_too():
    assert _pdf_markup("\u0116 & <co>") == (
        f'<font name="{_PDF_FALLBACK_FONT}">\u0116</font> &amp; &lt;co&gt;')

"""The PDF must not print a black square where the report row has a warning sign."""
import pytest

from app.export import _pdf_plain


@pytest.mark.parametrize("cell, expected", [
    ("\u26a0 08:00", "! 08:00"),
    ("08:00", "08:00"),
    (0, "0"),
    ("\u26a0 \u26a0 1:00", "! ! 1:00"),
])
def test_the_warning_sign_becomes_a_character_helvetica_has(cell, expected):
    assert _pdf_plain(cell) == expected

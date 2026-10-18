"""The palette/font centralisation (``app/theme.py``).

Two things must stay true, because the refactor was supposed to be invisible:

1. ``app/gui.py`` no longer contains a single raw ``#rrggbb`` literal — the goal
   of the change, and the only way to keep the palette from drifting again;
2. the values are *exactly* the ones that shipped before the refactor, so no
   pixel moved. The expected set below is the literal inventory of
   ``app/gui.py`` at the commit before the centralisation; adding a colour
   means adding it here too, deliberately.
"""
import ast
import re
from pathlib import Path

import pytest

import app.theme as theme

REPO_ROOT = Path(__file__).resolve().parents[2]
GUI_PATH = REPO_ROOT / "app" / "gui.py"
THEME_PATH = REPO_ROOT / "app" / "theme.py"

HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
HEX_VALUE_RE = re.compile(r"#[0-9a-f]{6}\Z")

#: Every colour value the UI used before the palette was centralised
#: (``git show 413bfb8:app/gui.py`` and a ``#rrggbb`` grep).
SHIPPED_COLOURS = {
    "#1565c0", "#17212b", "#1c2733", "#263238", "#2e7d32", "#37474f",
    "#536273", "#546e7a", "#5d4037", "#607d8b", "#6a1b9a", "#6b7280",
    "#757575", "#78909c", "#7b1fa2", "#90a4ae", "#9e9e9e", "#b6c3d6",
    "#b71c1c", "#bbdefb", "#bdbdbd", "#c3d1e6", "#c5cfdb", "#c62828",
    "#cdd7e4", "#d0d0d0", "#d2ddec", "#d32f2f", "#d9e1ea", "#dbe4f0",
    "#e3e9f2", "#e3f2fd", "#e65100", "#e8edf2", "#edf1f5", "#ef6c00",
    "#f0f0f0", "#f2f6fb", "#f4f6f9", "#f57c00", "#f8f9fa", "#f9a825",
    "#fafafa", "#ffcdd2", "#fffde7", "#ffffcc", "#ffffff",
}


def _colour_constants():
    """Module-level ``NAME = "#rrggbb"`` constants of ``app.theme``."""
    return {name: value for name, value in vars(theme).items()
            if name.isupper() and isinstance(value, str)}


def _font_constants():
    """Module-level ``FONT_*`` tuples of ``app.theme``."""
    return {name: value for name, value in vars(theme).items()
            if name.startswith("FONT_") and isinstance(value, tuple)}


# ── gui.py holds no colours any more ──────────────────────────────────────

def test_gui_has_no_raw_hex_literal():
    source = GUI_PATH.read_text(encoding="utf-8")
    assert HEX_RE.findall(source) == []


def test_theme_is_the_only_module_declaring_the_palette():
    """Every colour the UI paints comes from ``app.theme``."""
    source = THEME_PATH.read_text(encoding="utf-8")
    assert HEX_RE.findall(source), "theme.py must declare the palette"


def test_colour_values_are_lowercase_rrggbb():
    for name, value in _colour_constants().items():
        assert HEX_VALUE_RE.match(value), f"{name} = {value!r}"


def test_no_colour_was_lost_or_invented():
    """The palette as a *set of values* is the one that shipped."""
    assert {value for value in _colour_constants().values()} == SHIPPED_COLOURS


def test_gen_colors_keeps_its_keys_and_values():
    assert theme.GEN_COLORS == {
        "G1 (Digital)": "#2e7d32",
        "G2 (Smart)": "#1565c0",
        "G2.2 (Smart V2)": "#6a1b9a",
        "Unknown": "#757575",
    }


def test_the_palette_names_the_refactor_promised():
    """The names the rest of the code (and the tests) may rely on."""
    assert theme.SURFACE == "#f4f6f9"
    assert theme.TEXT_PRIMARY == "#1c2733"
    assert theme.FIELD_BG == "#ffffff"
    assert theme.BORDER == "#c5cfdb"
    assert theme.ROW_EVEN == "#ffffff"
    assert theme.ROW_ODD == "#f2f6fb"
    assert theme.HEADER_BG == "#e3e9f2"
    assert theme.APP_BG == theme.SURFACE
    assert theme.APP_FG == theme.TEXT_PRIMARY
    assert theme.HOVER_BG == "#bbdefb"
    assert theme.ACCENT == "#1565c0"


# ── fonts ─────────────────────────────────────────────────────────────────

def test_font_specs_are_the_tuples_that_shipped():
    """Family and size are unchanged: Tk font tuples, never Font objects."""
    assert theme.FONT_TITLE == ("", 13, "bold")
    assert theme.FONT_PAGE_TITLE == ("", 16, "bold")
    assert theme.FONT_SUBTITLE == ("", 11)
    assert theme.FONT_SUBTITLE_BOLD == ("", 11, "bold")
    assert theme.FONT_HEADING == ("", 10, "bold")
    assert theme.FONT_BODY == ("", 10)
    assert theme.FONT_SMALL == ("", 9)
    assert theme.FONT_CAPTION == ("", 8)
    assert theme.FONT_CAPTION_BOLD == ("", 8, "bold")
    assert theme.FONT_BADGE == ("", 12, "bold")
    assert theme.FONT_KPI_VALUE == ("", 14, "bold")
    assert theme.FONT_CANVAS_TITLE == ("TkDefaultFont", 11, "bold")
    # The mono choice is the macOS-only one, deliberately kept as it was.
    assert theme.FONT_MONO == ("Menlo", 11)
    assert theme.FONT_MONO_BOLD == ("Menlo", 11, "bold")
    assert theme.FONT_MONO_NORMAL == ("Menlo", 11, "normal")
    assert theme.FONT_MONO_ITALIC == ("Menlo", 11, "italic")
    assert theme.FONT_MONO_SMALL == ("Menlo", 10)
    assert theme.FONT_MONO_LARGE == ("Menlo", 12, "bold")


def test_font_constants_are_plain_tuples():
    fonts = _font_constants()
    assert len(fonts) >= 15
    for name, value in fonts.items():
        assert 2 <= len(value) <= 3, name
        assert isinstance(value[0], str), name
        assert isinstance(value[1], int) and value[1] > 0, name


def test_gui_uses_the_font_constants():
    """No inline ``font=("", 12, "bold")`` survives in the GUI."""
    source = GUI_PATH.read_text(encoding="utf-8")
    assert 'font=("' not in source
    assert 'font=("", ' not in source


def test_gui_re_exports_the_public_palette_names():
    """``app.gui`` keeps its old public names (re-exported, not redefined)."""
    import app.gui as gui

    for name in ("GEN_COLORS", "ROW_EVEN", "ROW_ODD", "HEADER_BG"):
        assert getattr(gui, name) is getattr(theme, name), name


def test_theme_declares_no_widget_code():
    """``app/theme.py`` stays a data module: no Tk import, no side effects."""
    names = {node.id for node in ast.walk(ast.parse(THEME_PATH.read_text(encoding="utf-8")))
             if isinstance(node, ast.Name)}
    assert "tk" not in names and "ttk" not in names
    source = THEME_PATH.read_text(encoding="utf-8")
    assert "import tkinter" not in source


@pytest.mark.parametrize("name", sorted(_colour_constants()))
def test_every_colour_constant_is_used_by_the_gui(name):
    """A palette entry nothing paints is dead weight: keep the two in sync."""
    value = _colour_constants()[name]
    source = GUI_PATH.read_text(encoding="utf-8")
    alias_users = {alias for alias, alias_value in _colour_constants().items()
                   if alias_value == value}
    assert any(re.search(rf"\b{alias}\b", source) for alias in alias_users), name

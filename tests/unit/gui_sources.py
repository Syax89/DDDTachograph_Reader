"""The GUI's source modules, for tests that inspect the interface's code.

``app/gui.py`` keeps only the main window class and the entry points; the rest
of the interface lives in ``app/gui_*.py`` (foundation, window mixins, charts,
day detail, data preparation, panel text). A check over "every msgid / colour /
icon / emoji the GUI uses" must read all of them, or code moved out of gui.py
would escape it.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

GUI_MODULES = tuple(sorted((REPO_ROOT / "app").glob("gui*.py")))


def gui_source():
    """The concatenated source of every GUI module (valid Python as a whole)."""
    return "\n\n".join(path.read_text(encoding="utf-8") for path in GUI_MODULES)

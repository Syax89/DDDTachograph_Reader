"""The GUI's source modules, for tests that inspect the interface's code.

``app/gui.py`` delegates the detailed-speed chart, the day-detail window, the
data preparation and the panel text to their own modules; a check over "every msgid / colour / icon / emoji the GUI
uses" must read all of them, or code moved out of gui.py would escape it.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

GUI_MODULES = (
    REPO_ROOT / "app" / "gui.py",
    REPO_ROOT / "app" / "gui_day_detail.py",
    REPO_ROOT / "app" / "gui_speed_chart.py",
    REPO_ROOT / "app" / "gui_data.py",
    REPO_ROOT / "app" / "gui_text.py",
)


def gui_source():
    """The concatenated source of every GUI module (valid Python as a whole)."""
    return "\n\n".join(path.read_text(encoding="utf-8") for path in GUI_MODULES)

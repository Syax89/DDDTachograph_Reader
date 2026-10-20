"""D-03: the schema-violation explanation must reach the real banner.

``_integrity_bullets`` carried the text, but only tests called it: the runtime banner
said "The structural walk did not reach the end of file" even when the walk had
consumed every byte and the real finding was about a section's array list.
"""
import os

import pytest

pytest.importorskip("tkinter")

from app import gui  # noqa: E402
from app.engine import TachoParser  # noqa: E402
from core.registry.registry import DecoderRegistry  # noqa: E402
from tests.integration import generate_mock_ddd as mock  # noqa: E402
from tests.unit.test_empty_state import close, new_explorer  # noqa: E402


@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        gui.DayDetailWindow._open_windows.clear()
        close(app)


def test_the_banner_explains_a_schema_violation(explorer, tmp_path):
    path = os.path.join(str(tmp_path), "mock_g2_vu.ddd")
    mock.generate_g2_vu(path)
    DecoderRegistry.reset_instance()
    result = TachoParser(path).parse()
    explorer._parse_done(result, path)
    explorer.update()

    findings = (result.get("metadata") or {}).get("vu_integrity") or []
    assert any(f.get("status") == "schema_violation" for f in findings), findings

    text = str(explorer.integrity_banner.cget("text"))
    details = " ".join(getattr(explorer, "_integrity_warnings", []))
    assert text, "the banner must announce the finding"
    assert "schema violation" in details.lower(), details
    # the single source produced it: the same function the tests call
    bullets, _notices = gui._integrity_bullets(result)
    pretty = [b for b in bullets if "schema violation" in b]
    assert pretty and pretty[0] in details

"""Tests that integrity labels do not overstate VU trust."""
from unittest.mock import Mock

import pytest

pytest.importorskip("tkinter")

from app.gui import TachoExplorer


def _vu_data(**signature_verification):
    return {
        "metadata": {"is_vu": True, "integrity_check": "Verified (VU — TREP ok, chain partial)"},
        "signature_verification": signature_verification,
    }


def test_untrusted_vu_trep_signatures_are_not_labeled_verified():
    data = _vu_data(all_treps_valid=True, msca_to_vu=False, root_anchored=False)

    assert TachoExplorer._integrity_label(None, data) == "VU TREP signatures valid (chain unverified)"


def test_untrusted_vu_trep_signatures_use_warning_badge():
    app = object.__new__(TachoExplorer)
    app.lbl_status = Mock()
    app.current_file = "download.ddd"
    app.title = Mock()

    app._update_status_badge(_vu_data(all_treps_valid=True, msca_to_vu=False, root_anchored=False))

    assert app.lbl_status.config.call_args.kwargs["foreground"] == "#e65100"


def test_gui_rejects_structured_parse_error_before_rendering():
    app = object.__new__(TachoExplorer)
    app._finish_parse = Mock()
    app._parse_error = Mock()
    app._populate_tree = Mock()

    app._parse_done({"metadata": {"parse_error": {"message": "Empty file"}}}, "empty.ddd")

    app._parse_error.assert_called_once_with("Empty file")
    app._populate_tree.assert_not_called()

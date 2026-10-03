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


def test_vu_chain_ok_but_trep_signatures_failed_warns_not_clean():
    """Batch-1 refutation R1: anchored MSCA->VU chain, failed TREP signature.

    integrity_verdict() reports VERDICT_UNVERIFIED (no "Incomplete"/"Error"
    marker in the integrity string), which fell through to the VU branch's
    last ``else`` and rendered an empty/clean badge -- the file read as OK
    while it is explicitly not verified. Must warn like every other
    non-verified VU state.
    """
    app = object.__new__(TachoExplorer)
    app.lbl_status = Mock()
    app.current_file = "download.ddd"
    app.title = Mock()

    app._update_status_badge({
        "metadata": {"is_vu": True, "integrity_check": "Partial (VU — chain ok)"},
        "signature_verification": {
            "all_treps_valid": False, "msca_to_vu": True, "root_anchored": True,
        },
    })

    kwargs = app.lbl_status.config.call_args.kwargs
    assert kwargs["text"] != "", "badge must not be empty for an unverified VU"
    assert kwargs["foreground"] == "#e65100"


def test_gui_rejects_structured_parse_error_before_rendering():
    app = object.__new__(TachoExplorer)
    app._finish_parse = Mock()
    app._parse_error = Mock()
    app._populate_tree = Mock()

    app._parse_done({"metadata": {"parse_error": {"message": "Empty file"}}}, "empty.ddd")

    app._parse_error.assert_called_once_with("Empty file")
    app._populate_tree.assert_not_called()


def _g1_vu_data(all_treps_valid, treps):
    return {
        "metadata": {"is_vu": True, "integrity_check": "Verified (VU Chain)"},
        "coverage": {},
        "signature_verification": {
            "available": True, "msca_to_vu": True, "root_anchored": True,
            "all_treps_valid": all_treps_valid,
            "summary": "G1 VU TREP signatures: 1/1 valid",
            "treps": treps,
        },
    }


def test_g1_sensor_treps_do_not_raise_a_spurious_integrity_warning(monkeypatch):
    """H-F2: TREP 0x11/0x14 carry ``signature_valid=None`` ("not applicable").

    Recounting them over ``len(treps)`` reported "1/3 verified; 2 NOT
    validated" and popped a "File Integrity Warning" on an otherwise fully
    verified G1 VU download. The GUI must reuse the verifier's verdict.
    """
    app = object.__new__(TachoExplorer)
    app.integrity_banner = Mock()
    app._integrity_warnings = []
    app._integrity_file = ""
    monkeypatch.setattr("app.gui.messagebox", Mock())

    data = _g1_vu_data(True, [
        {"trep": "0x01", "signature_valid": True},
        {"trep": "0x11", "signature_valid": None, "reason": "signature not applicable"},
        {"trep": "0x14", "signature_valid": None, "reason": "signature not applicable"},
    ])

    app._check_integrity(data, "g1vu.ddd")

    assert app._integrity_warnings == []
    assert app.integrity_banner.config.call_args.kwargs["text"] == ""


def test_g1_failed_trep_still_raises_an_integrity_warning(monkeypatch):
    """Control for H-F2: a genuine failure must still warn."""
    app = object.__new__(TachoExplorer)
    app.integrity_banner = Mock()
    app._integrity_warnings = []
    app._integrity_file = ""
    monkeypatch.setattr("app.gui.messagebox", Mock())

    data = _g1_vu_data(False, [
        {"trep": "0x01", "signature_valid": True},
        {"trep": "0x02", "signature_valid": False},
    ])

    app._check_integrity(data, "g1vu.ddd")

    assert any("VU sections validated" in w for w in app._integrity_warnings)


def test_integrity_warning_text_is_pinned_to_the_verifier_numbers(monkeypatch):
    """The banner/warning TEXT must carry the verifier's own numbers.

    A fabricated "N/N verified" string, or a recount over ``len(treps)``, must
    not pass: here the verifier reports 1/2 signed sections valid while there
    are 3 TREP rows (one is the not-applicable sensor section), so a recount
    would print "1/3".
    """
    app = object.__new__(TachoExplorer)
    app.integrity_banner = Mock()
    app._integrity_warnings = []
    app._integrity_file = ""
    monkeypatch.setattr("app.gui.messagebox", Mock())

    data = _g1_vu_data(False, [
        {"trep": "0x01", "signature_valid": True},
        {"trep": "0x02", "signature_valid": False},
        {"trep": "0x11", "signature_valid": None,
         "reason": "signature not applicable"},
    ])
    data["signature_verification"]["summary"] = "G1 VU TREP signatures: 1/2 valid"

    app._check_integrity(data, "g1vu.ddd")

    # The VU-sections warning carries the verifier's own "1/2" (signed sections),
    # never a recount over the 3 TREP rows (which would say "1/3").
    assert app._integrity_warnings[0] == (
        "\u2022 VU sections validated: G1 VU TREP signatures: 1/2 valid")
    assert not any("1/3" in w for w in app._integrity_warnings)
    assert app.integrity_banner.config.call_args.kwargs["text"] == (
        "\u26a0\ufe0f  2 integrity warning(s) \u2014 click for details")


def test_fatal_parse_clears_the_previous_file_display(monkeypatch):
    """H-F5: a fatal parse must not leave the previous file's identity,
    integrity banner or collected warnings on screen."""
    app = object.__new__(TachoExplorer)
    app.lbl_file = Mock()
    app.lbl_gen = Mock()
    app.lbl_status = Mock()
    app.integrity_banner = Mock()
    app.status = Mock()
    app.title = Mock()
    app.progress = Mock()
    app.btn_open = Mock()
    app.btn_export = Mock()
    app._parsing = True
    app.current_data = {"metadata": {"generation": "G2 (Smart)"}}
    app.current_file = "first_file.ddd"
    app._integrity_warnings = ["\u2022 5 bytes classified as Unknown (unparseable)"]
    app._integrity_file = "first_file.ddd"
    monkeypatch.setattr("app.gui.messagebox", Mock())

    app._parse_error("no structural data recovered")

    assert app._integrity_warnings == []
    assert app._integrity_file == ""
    assert app.integrity_banner.config.call_args.kwargs["text"] == ""
    assert app.lbl_file.config.call_args.kwargs["text"] == "No file loaded"
    assert app.lbl_gen.config.call_args.kwargs["text"] == ""
    # The previous file stays exportable, but the status says so explicitly.
    assert "previous file" in app.status.config.call_args.kwargs["text"]


def test_fatal_parse_retains_the_exportable_previous_file(monkeypatch):
    """M11: _reset_file_display clears the DISPLAY fields but must retain the
    previous file's identity so export after a fatal parse still works.

    The export path (``_run_export`` / ``_export_json`` in app/gui.py) reads
    ``self.current_data`` (the data to export) and ``self.current_file`` (the
    suggested filename), so both must survive the reset.
    """
    app = object.__new__(TachoExplorer)
    app.lbl_file = Mock()
    app.lbl_gen = Mock()
    app.lbl_status = Mock()
    app.integrity_banner = Mock()
    app.status = Mock()
    app.title = Mock()
    app.progress = Mock()
    app.btn_open = Mock()
    app.btn_export = Mock()
    app._parsing = True
    retained = {"metadata": {"filename": "first_file.ddd"}}
    app.current_data = retained
    app.current_file = "/tmp/first_file.ddd"
    app._integrity_warnings = []
    app._integrity_file = ""
    monkeypatch.setattr("app.gui.messagebox", Mock())

    app._parse_error("no structural data recovered")

    # Display fields are cleared ...
    assert app.lbl_file.config.call_args.kwargs["text"] == "No file loaded"
    assert app._integrity_warnings == []
    # ... but what the export path reads still points at the retained file.
    assert app.current_data is retained
    assert app.current_file == "/tmp/first_file.ddd"
    assert app.btn_export.config.call_args.kwargs["state"] == "normal"

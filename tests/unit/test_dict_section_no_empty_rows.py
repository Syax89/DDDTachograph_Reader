"""A Field/Value row with nothing in it is not a row — in every dict section.

The owner opened a driver card and read three empty rows in the *Security › EF
Signature Verification* panel: ``Key Trust``, ``Untrusted Generations`` and
``Missing Core EFs``. The cause is the shape of the verification report, not a
missing value: ``core.crypto.ef_signature.verify_ef_pairs`` publishes
``key_trust=None`` on a G1 card and ``app.engine`` adds
``untrusted_generations=[]`` / ``missing_core_efs=[]`` when everything verified.
Both dict renderers format them to ``""`` — and the GUI panel
(``app/gui.py::_kv_rows``) emitted the pair anyway, so the tree showed a label
with a blank value.

Two rules, pinned here for the shared renderer so no view can re-introduce them:

* a row whose formatted value has no content is not emitted at all (a fixed
  *table* may say "None"; a key/value panel has no such column);
* a row that *has* content shows it readably: the missing-EF tag list reads
  ``0x0502, 0x0523`` (not ``1298, 1315``) and an untrusted generation keeps its
  name.

The dict-section renderer is shared by the Excel/CSV/PDF sheets
(``report_format.section_tables``) and the GUI key/value panel
(``app/gui.py::_kv_rows``), so the fix lives in
``report_format.dict_section_rows`` and both are checked below.

Synthetic values only; no corpus datum. The last two tests go one level up from
the dict: they parse a synthetic card with **real** RSA/ECDSA material
(``tests.unit.card_crypto``) and read the panel the tree actually builds, so a
non-empty ``missing_core_efs`` / ``untrusted_generations`` is proven to arrive
readable and not merely to survive a hand-written dict.
"""
from __future__ import annotations

from app import gui
from core.utils import report_format
from tests.unit.card_crypto import (
    g1_cert_records,
    g1_core_payloads,
    g1_identity,
    g2_cert_records,
    g2_core_payloads,
    new_cvc_identity,
    parse_bytes,
    signed_pairs,
    trust_store,
    trusted_root_and_msca,
)

#: What a healthy G1 driver card publishes (``app.engine._verify_ef_signatures``).
HEALTHY = {
    "summary": "All 9 EF signature(s) verified",
    "ef_results": [{"tag": "0x0502", "gen": "G1", "algo": "RSA",
                    "status": "verified"}],
    "verified": 9, "failed": 0, "skipped": 0, "total": 9,
    "key_trust": None,
    "untrusted_generations": [],
    "missing_core_efs": [],
}

EMPTY_ONLY = ("Key Trust", "Untrusted Generations", "Missing Core Efs")


def _labels(rows):
    return [row[0] for row in rows]


def _panel(efv):
    _headers, rows = gui._kv_rows(dict(efv))
    return rows


def _export_rows(efv):
    """The dict-section sheets of an export built from one dict."""
    return {label: rows for label, _d, _h, rows, _t
            in report_format.section_tables({"vu_info": dict(efv)})}


# ── the shared renderer ─────────────────────────────────────────────────────

def test_shared_renderer_skips_a_row_whose_formatted_value_is_empty():
    section = {"summary": "ok", "key_trust": None, "untrusted_generations": [],
               "missing_core_efs": []}

    rendered = list(report_format.dict_section_rows(section, report_format.fmt_value))

    assert rendered == [("summary", "ok")]


def test_shared_renderer_keeps_whitespace_only_values_out():
    section = {"manufacturer": "  ", "serial_number": "A1"}

    rendered = list(report_format.dict_section_rows(section, report_format.fmt_value))

    assert rendered == [("serial_number", "A1")]


def test_shared_renderer_formats_the_missing_ef_tag_list_as_hex_tags():
    section = {"missing_core_efs": [0x0502, 0x0523]}

    rendered = list(report_format.dict_section_rows(section, report_format.fmt_value))

    assert rendered == [("missing_core_efs", "0x0502, 0x0523")]


# ── the GUI key/value panel (the surface the owner reported) ───────────────

def test_gui_ef_panel_shows_no_empty_rows_for_a_healthy_card():
    rows = _panel(HEALTHY)

    for label in EMPTY_ONLY:
        assert label not in _labels(rows), label
    assert all(str(value).strip() for _label, value in rows), rows
    # …and the rows that do carry the verdict are untouched.
    assert dict(rows)[gui.ui_text.label("summary")] == HEALTHY["summary"]
    assert dict(rows)[gui.ui_text.label("total")] == "9"


def test_gui_ef_panel_shows_the_missing_efs_when_content_exists():
    efv = dict(HEALTHY, missing_core_efs=[0x0502, 0x0523], verified=7, total=9,
               summary="7/9 EF signature(s) verified, 2 FAILED")

    rows = dict(_panel(efv))

    assert rows[gui.ui_text.label("missing_core_efs")] == "0x0502, 0x0523"
    # The label itself is unchanged (the owner read "Missing Core EFs"; the
    # humaniser keeps "Efs", and renaming a msgid is not part of this fix).
    assert gui.ui_text.label("missing_core_efs") == "Missing Core Efs"


def test_gui_ef_panel_names_the_untrusted_generations():
    efv = dict(HEALTHY, untrusted_generations=["G2"])

    rows = dict(_panel(efv))

    assert rows[gui.ui_text.label("untrusted_generations")] == "G2"
    assert gui.ui_text.label("untrusted_generations") == "Untrusted Generations"


def test_gui_ef_panel_shows_the_key_trust_sentence_of_a_g2_card():
    efv = dict(HEALTHY, key_trust="CVC public key extracted for G2 EF verification")

    rows = dict(_panel(efv))

    assert rows[gui.ui_text.label("key_trust")] == \
        "CVC public key extracted for G2 EF verification"


def test_gui_panel_drops_empty_rows_of_every_dict_section_not_just_the_ef_one():
    chip = {"ic_serial_number": "AB12", "manufacturer": "", "notes": None}

    _headers, rows = gui._kv_rows(chip)

    assert _labels(rows) == [gui.ui_text.label("ic_serial_number")]


def test_gui_panel_drops_empty_nested_rows_too():
    info = {"card_slot_status": {"driver_slot": "occupied", "codriver_slot": ""}}

    _headers, rows = gui._kv_rows(info)

    assert _labels(rows) == ["Card Slot Status \u203a Driver Slot"]


# ── the export sheets (same shared renderer) ───────────────────────────────

def test_export_sheet_has_no_empty_value_row():
    rows = _export_rows(HEALTHY)["VU Information"]

    assert all(str(value).strip() for _field, value in rows), rows
    assert [field for field, _value in rows] == ["Summary", "Ef Results",
                                                 "Verified", "Failed",
                                                 "Skipped", "Total"]


# ── end to end: a real synthetic card, rendered by the real tree builder ────

def _security_panel(result):
    """The rows of *Security › EF Signature Verification* as the tree builds them."""
    security = (result.get("generations") or {}).get("Security") or {}
    _headers, rows = gui._kv_rows(security.get("EF Signature Verification") or {})
    return rows


def test_card_with_a_removed_core_ef_shows_the_missing_tag():
    """A mandatory G1 EF deleted outright must read ``0x0502``, not a blank."""
    identity = g1_identity()
    payloads = g1_core_payloads()
    del payloads[0x0502]  # both the data and the signature copy
    card = (g1_cert_records(identity["card_cert"], identity["msca_cert"])
            + signed_pairs(payloads, identity["card_key"], 1))
    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        result = parse_bytes(card, certs_dir)[1]

    assert result["ef_signature_verification"]["missing_core_efs"] == [0x0502]
    rows = _security_panel(result)

    assert all(str(value).strip() for _label, value in rows), rows
    assert dict(rows)[gui.ui_text.label("missing_core_efs")] == "0x0502"


def test_g2_card_with_an_untrusted_chain_names_the_generation():
    """An attacker-rooted G2 chain: the generation name, never a blank row."""
    trusted_erca, _trusted_identity = trusted_root_and_msca()
    attacker = new_cvc_identity(None)  # self-signed MSCA, not the trusted root
    card = (g2_cert_records(attacker["card_cert"], attacker["msca_cert"])
            + signed_pairs(g2_core_payloads(), attacker["card_key"], 2))
    with trust_store(g2_erca_cert=trusted_erca) as certs_dir:
        result = parse_bytes(card, certs_dir)[1]

    assert result["ef_signature_verification"]["untrusted_generations"] == ["G2"]
    rows = _security_panel(result)

    assert all(str(value).strip() for _label, value in rows), rows
    assert dict(rows)[gui.ui_text.label("untrusted_generations")] == "G2"
    # The G2 key-trust sentence is one of the rows that *does* carry content.
    assert gui.ui_text.label("key_trust") in dict(rows)

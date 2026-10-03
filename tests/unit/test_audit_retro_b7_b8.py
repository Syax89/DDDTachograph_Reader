"""Regressions found by the B7/B8 retroactive process-compliance audit.

These pin the two defects the retrospective audit (branches
``audit/batch7-retrospective`` and ``audit/batch8-retrospective``) found in the
already-merged batches, so neither can silently come back:

* AUDIT-B7-F1 — ``missing_core_efs`` counted an ``unsupported`` EF pair as
  evidence that its *generation* is present. A lone, mis-framed dtype-0x03
  signature record on an otherwise complete G1 card therefore made the whole
  (never captured) G2 application be demanded, so the report claimed eleven
  mandatory EFs were missing on a card that carries them all
  (``Unverified (Missing EF: 0x0501, 0x0502, … 0x0524)``). The card is still
  correctly *not* verified — reporting the unclassifiable signature is the
  deliberate D2-003 behaviour of the same batch — but the diagnosis must be
  ``Unverified (EF Signatures Incomplete)``: the accurate reason.
  The D2-003 behaviour itself is guarded below so the fix cannot be "achieved"
  by re-dropping the unsupported report.

* AUDIT-B8-R1 — the TREP 03 heuristic's de-duplication key omitted the record
  purpose, while ``_parse_trep_03_structured`` deliberately keys on it because
  "the VU stores distinct records sharing the same (type, begin), e.g. one per
  record purpose". Two genuinely distinct records were collapsed into one.
"""
import struct

import pytest

from core.crypto.ef_signature import missing_core_efs, pair_ef_records
from core.decoders.vu_g1 import _parse_trep_03_events_faults_heuristic
from core.utils.report_format import (
    VERDICT_UNVERIFIED,
    VERDICT_VERIFIED,
    integrity_verdict,
)
from tests.unit.card_crypto import (
    g1_cert_records,
    g1_core_payloads,
    g1_identity,
    parse_bytes,
    signed_pairs,
    stap,
    trust_store,
)


# ── AUDIT-B7-F1 ────────────────────────────────────────────────────────────

def _g1_card(g1_ids, payloads):
    return (g1_cert_records(g1_ids["card_cert"], g1_ids["msca_cert"])
            + signed_pairs(payloads, g1_ids["card_key"], 1))


def _parse_g1(g1_ids, data):
    with trust_store(g1_erca_key=g1_ids["erca_key"]) as certs_dir:
        return parse_bytes(data, certs_dir)[1]


@pytest.mark.parametrize("tag", [0x9001, 0x0550, 0x0600])
def test_lone_dtype03_signature_does_not_demand_the_other_generation(tag):
    """A stray dtype-0x03 signature must not invent a missing G2 application."""
    g1_ids = g1_identity()
    data = _g1_card(g1_ids, g1_core_payloads()) + stap(tag, 0x03, b"X" * 64)

    result = _parse_g1(g1_ids, data)
    efv = result["ef_signature_verification"]

    # The lone signature is still reported (D2-003), ...
    assert efv["skipped"] == 1
    # ... but it must not make the G2 mandatory set "missing".
    assert efv["missing_core_efs"] == []
    # The card is legitimately not verified; the reason must be the honest one.
    assert result["metadata"]["integrity_check"] == "Unverified (EF Signatures Incomplete)"
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_complete_g1_card_without_stray_record_is_verified():
    """Control: the same card without the stray record (no behaviour change)."""
    g1_ids = g1_identity()
    result = _parse_g1(g1_ids, _g1_card(g1_ids, g1_core_payloads()))

    assert result["ef_signature_verification"]["missing_core_efs"] == []
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def test_lone_g1_signature_is_still_not_reported_as_verified():
    """The D2-003 fix must survive: an unsupported G1 signature is not 'verified'.

    Without this guard the F1 fix could be "achieved" by dropping the
    ``unsupported`` report altogether, re-opening the original defect.
    """
    g1_ids = g1_identity()
    data = _g1_card(g1_ids, g1_core_payloads()) + stap(0x9001, 0x01, b"X" * 64)

    result = _parse_g1(g1_ids, data)
    assert result["ef_signature_verification"]["skipped"] == 1
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_unsupported_pair_does_not_supply_a_generation():
    """Unit-level statement of the same rule, independent of the parser."""
    observed_g1 = [{"tag": 0x0501, "gen": "G1", "status": "paired"}]
    with_stray = [{"tag": 0x9001, "gen": "G2", "status": "unsupported"}] + observed_g1

    # The unsupported pair must not change the demanded tag set at all, and in
    # particular must not pull in the G2-only EFs (0x0523 / 0x0524).
    assert missing_core_efs(with_stray) == missing_core_efs(observed_g1)
    assert 0x0523 not in missing_core_efs(with_stray)
    assert 0x0524 not in missing_core_efs(with_stray)
    # A certificate/metadata signature stays excluded either way.
    assert pair_ef_records([], [(0xC100, 0x03, b"c" * 200)]) == []


# ── AUDIT-B8-R1 ────────────────────────────────────────────────────────────

def _vu_fault(fault_type, purpose, begin, end):
    rec = bytearray(82)
    rec[0] = fault_type
    rec[1] = purpose
    struct.pack_into(">I", rec, 2, begin)
    struct.pack_into(">I", rec, 6, end)
    return bytes(rec)


def _trep03_body(faults):
    """Count-prefixed TREP 03 body: noOfVuFaults(1) + VuFaultRecord(82)×N."""
    return bytes([len(faults)]) + b"".join(faults) + b"\x00" * 16


def test_records_differing_only_by_purpose_are_both_kept():
    """Two faults sharing (type, begin, end) but not purpose are distinct."""
    body = _trep03_body([
        _vu_fault(0x05, 0x01, 1600000000, 1600000100),
        _vu_fault(0x05, 0x02, 1600000000, 1600000100),
    ])
    results = {}
    _parse_trep_03_events_faults_heuristic(body, results)

    faults = results.get("faults", [])
    assert [f["fault_purpose"] for f in faults] == [0x01, 0x02]


def test_rerun_of_purpose_distinct_records_still_does_not_duplicate():
    """The purpose-aware key must keep the re-run idempotency it was added for."""
    body = _trep03_body([
        _vu_fault(0x05, 0x01, 1600000000, 1600000100),
        _vu_fault(0x05, 0x02, 1600000000, 1600000100),
    ])
    results = {}
    _parse_trep_03_events_faults_heuristic(body, results)
    first = len(results.get("faults", []))
    _parse_trep_03_events_faults_heuristic(body, results)

    assert first == 2
    assert len(results.get("faults", [])) == 2


def test_identical_fault_records_are_still_deduplicated_within_one_run():
    """Genuine repeats (same type, times AND purpose) collapse to one."""
    fault = _vu_fault(0x05, 0x01, 1600000000, 1600000100)
    results = {}
    _parse_trep_03_events_faults_heuristic(_trep03_body([fault, fault]), results)

    assert len(results.get("faults", [])) == 1

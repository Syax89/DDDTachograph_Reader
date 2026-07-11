import typing
from dataclasses import dataclass, field
from typing import List, Dict, Any

from core.decoders.vu_g1 import (
    _merge_card_download,
    _CARD_MERGE_LIST_KEYS,
    _CARD_MERGE_DICT_KEYS,
    _derive_card_merge_keys,
)

# ── Structural assertions on the derived allowlist ────────────────────────

def test_missing_card_list_keys_now_included():
    """Keys that card EF decoders produce but the old hand-maintained tuple
    omitted must now appear in the derived list."""
    for expected in ("vehicle_sessions", "calibrations", "control_activities"):
        assert expected in _CARD_MERGE_LIST_KEYS, \
            f"'{expected}' should be in _CARD_MERGE_LIST_KEYS"


def test_wrong_and_dead_keys_are_absent():
    """'controls' (wrong name) and 'card_download_records' (dead) must not be
    carried forward from the old hand-maintained tuple."""
    for bogus in ("controls", "card_download_records"):
        assert bogus not in _CARD_MERGE_LIST_KEYS, \
            f"'{bogus}' should NOT be in _CARD_MERGE_LIST_KEYS"


def test_infrastructure_keys_are_excluded():
    for infra in ("metadata", "raw_tags", "coverage", "sections", "generations"):
        assert infra not in _CARD_MERGE_LIST_KEYS
        assert infra not in _CARD_MERGE_DICT_KEYS


def test_vu_only_keys_are_excluded():
    vu_only = (
        "card_numbers", "vu_certificates", "vu_identifications", "vu_controller",
        "vu_record_arrays", "vu_overview", "company_locks", "inserted_drivers",
        "speed_blocks", "signed_daily_records", "company_info", "vu_info",
        "sensor_info", "previous_vehicle", "signature_verification",
        "certificate_temporal_validity",
    )
    for key in vu_only:
        assert key not in _CARD_MERGE_LIST_KEYS
        assert key not in _CARD_MERGE_DICT_KEYS


def test_g22_only_keys_are_excluded():
    g22 = (
        "gnss_ad_records", "load_unload_records", "trailer_registrations",
        "gnss_places", "load_sensor_data", "border_crossings",
        "gnss_auth", "load_unload_auth",
    )
    for key in g22:
        assert key not in _CARD_MERGE_LIST_KEYS
        assert key not in _CARD_MERGE_DICT_KEYS


def test_card_dict_keys_include_beyond_driver_vehicle():
    """card_application, card_chip, card_icc, and card_issuer are Dict fields
    produced by card EF decoders; they should now be part of the derived dict
    merge set."""
    for expected in ("card_application", "card_chip", "card_icc", "card_issuer",
                     "driver", "vehicle"):
        assert expected in _CARD_MERGE_DICT_KEYS, \
            f"'{expected}' should be in _CARD_MERGE_DICT_KEYS"


# ── Behavioural assertions — prove that the merge actually works ────────

def test_list_extension_dedup():
    """A list key present in the sub-parse is extended into the live result
    with deduplication."""
    results = {}
    sub = {"activities": [
        {"type": "drive", "from": "09:00"},
        {"type": "rest", "from": "12:00"},
    ]}
    _merge_card_download(results, sub)
    assert "activities" in results
    assert len(results["activities"]) == 2

    # Second merge with a duplicate and a new entry
    sub2 = {"activities": [
        {"type": "drive", "from": "09:00"},  # duplicate
        {"type": "work", "from": "13:00"},   # new
    ]}
    _merge_card_download(results, sub2)
    assert len(results["activities"]) == 3


def test_dict_fill_when_target_is_empty():
    """A dict key fills only when the live result is still empty/N-A."""
    results = {}
    sub = {"driver": {"surname": "ROSSI", "firstname": "MARIO"}}
    _merge_card_download(results, sub)
    assert results["driver"]["surname"] == "ROSSI"
    assert results["driver"]["firstname"] == "MARIO"


def test_dict_does_not_overwrite_existing_value():
    """Existing non-N/A values in the live result are preserved."""
    results = {"driver": {"surname": "BIANCHI", "firstname": "N/A"}}
    sub = {"driver": {"surname": "ROSSI", "firstname": "MARIO"}}
    _merge_card_download(results, sub)
    assert results["driver"]["surname"] == "BIANCHI"   # kept
    assert results["driver"]["firstname"] == "MARIO"    # filled (was N/A)


# ── Proof that new decoders are auto-covered ─────────────────────────────

def test_new_card_list_key_merged_without_allowlist_change():
    """When a card EF decoder produces a *new* list key that corresponds to a
    TachoResult List[...] field (and is not excluded), the merge happens
    automatically — no allowlist edit is needed."""
    results = {}
    # "vehicle_units" was never in the old hand-maintained tuple; it appears
    # now because the derivation picks it up from the TachoResult dataclass.
    sub = {"vehicle_units": [
        {"plate": "AB123CD", "vin": "VIN1"},
        {"plate": "XY987ZZ", "vin": "VIN2"},
    ]}
    _merge_card_download(results, sub)
    assert "vehicle_units" in results
    assert len(results["vehicle_units"]) == 2
    assert results["vehicle_units"][0]["plate"] == "AB123CD"


def test_new_card_dict_key_merged_without_allowlist_change():
    """Same guarantee for Dict fields — the derivation automatically covers
    new card-side dict keys added to TachoResult."""
    results = {}
    # "card_issuer" was never in the old hand-maintained dict tuple.
    sub = {"card_issuer": {"issuing_nation": "ITA", "issuing_authority": "MIT"}}
    _merge_card_download(results, sub)
    assert "card_issuer" in results
    assert results["card_issuer"]["issuing_nation"] == "ITA"


# ── Derivation hygiene ───────────────────────────────────────────────────

def test_derived_keys_are_all_tacho_result_fields():
    """Every key in the derived sets must be a real TachoResult dataclass
    field of the expected generic type."""
    from core.registry.models import TachoResult
    fields = TachoResult.__dataclass_fields__

    for key in _CARD_MERGE_LIST_KEYS:
        fdef = fields[key]
        assert typing.get_origin(fdef.type) is list, \
            f"'{key}' is in _CARD_MERGE_LIST_KEYS but TachoResult type is {fdef.type}"

    for key in _CARD_MERGE_DICT_KEYS:
        fdef = fields[key]
        assert typing.get_origin(fdef.type) is dict, \
            f"'{key}' is in _CARD_MERGE_DICT_KEYS but TachoResult type is {fdef.type}"


def test_derive_function_consistent_with_module_level():
    """The module-level constants must be exactly what _derive_card_merge_keys
    returns (no intermediate mutation of TachoResult)."""
    list_keys, dict_keys = _derive_card_merge_keys()
    assert list_keys == _CARD_MERGE_LIST_KEYS
    assert dict_keys == _CARD_MERGE_DICT_KEYS

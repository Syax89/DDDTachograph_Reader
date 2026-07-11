import struct

import pytest

from core.decoders import vu_g2
from core.registry.models import TachoResult, _split_raw_tags


EXPECTED_RESULT_KEYS = {
    "metadata", "driver", "vehicle", "activities", "vehicle_sessions",
    "events", "faults", "locations", "places", "calibrations", "raw_tags",
    "gnss_ad_records", "load_unload_records", "trailer_registrations",
    "gnss_places", "load_sensor_data", "border_crossings", "signed_daily_records",
    "card_application", "control_activities", "card_downloads", "card_chip",
    "company_info", "vu_overview", "vu_info", "card_numbers", "card_iw_records",
    "company_locks", "overspeeding_events", "overspeeding_control",
    "specific_conditions", "time_adjustments", "sensor_daily_records", "sensor_info",
    "previous_vehicle", "inserted_drivers", "workshops", "calibration_vins",
    "speed_blocks", "certificates", "card_issuer", "card_icc", "company_holders",
    "vehicle_units", "vu_certificates", "vu_identifications", "card_records",
    "download_activities", "downloadable_periods", "its_consents",
    "power_interruptions", "signature_verification", "sensor_pairings",
    "sensor_gnss_couplings", "vu_record_arrays", "gnss_auth", "load_unload_auth",
    "sensor_faults", "vu_controller", "time_adj_gnss",
    "certificate_temporal_validity", "ef_signature_verification", "coverage",
    "sections", "generations",
}


def test_tacho_result_to_dict_exposes_every_declared_public_section():
    result = TachoResult().to_dict()

    assert set(result) == EXPECTED_RESULT_KEYS
    assert set(TachoResult.__dataclass_fields__) == EXPECTED_RESULT_KEYS


@pytest.mark.parametrize(("tag", "record_type", "canonical", "aliases", "record"), [
    (0x0510, 0x20, "sensor_pairings", ("sensor_paired", "sensor_paired_g22"),
     b"\x01" * 8 + b"APPROVAL        " + struct.pack(">I", 1700000000)),
    (0x0511, 0x21, "sensor_gnss_couplings", ("sensor_gnss_coupled", "sensor_gnss_coupled_g22"),
     b"\x01" * 8 + b"APPROVAL        " + struct.pack(">I", 1700000000)),
    (0x052C, 0x12, "speed_blocks", ("detailed_speed",),
     struct.pack(">I", 1700000000) + bytes(range(60))),
    (0x0532, 0x21, "sensor_gnss_couplings", ("sensor_gnss_coupled", "sensor_gnss_coupled_g22"),
     b"\x01" * 8 + b"APPROVAL        " + struct.pack(">I", 1700000000)),
    (0x0533, 0x20, "sensor_pairings", ("sensor_paired", "sensor_paired_g22"),
     b"\x01" * 8 + b"APPROVAL        " + struct.pack(">I", 1700000000)),
])
def test_g2_vu_aliases_are_normalized_at_the_producer_boundary(
        tag, record_type, canonical, aliases, record):
    results = TachoResult().to_dict()
    record_array = struct.pack(">BHH", record_type, len(record), 1) + record

    vu_g2.parse_g2_vu_record(record_array, results, tag)

    assert len(results[canonical]) == 1
    for alias in aliases:
        assert alias not in results


def test_raw_tags_use_explicit_generation_over_misleading_key_prefix():
    occurrence = {"generation": "G2.2 (Smart V2)", "offset": "0x00000000"}

    buckets = _split_raw_tags({"G1_Misleading": [occurrence]}, {})

    assert buckets == {"Generation 2.2": {"Misleading": [occurrence]}}


def test_raw_tags_split_mixed_generation_occurrences_under_one_key():
    gen1 = {"generation": "G1 (Digital)", "offset": "0x00000000"}
    gen2 = {"generation": "Generation 2", "offset": "0x00000001"}
    gen22 = {"generation": "G2.2", "offset": "0x00000002"}

    buckets = _split_raw_tags({"SharedTag": [gen1, gen2, gen22]}, {})

    assert buckets == {
        "Generation 1": {"SharedTag": [gen1]},
        "Generation 2": {"SharedTag": [gen2]},
        "Generation 2.2": {"SharedTag": [gen22]},
    }


@pytest.mark.parametrize("occurrence", [
    {"offset": "0x00000000"},
    {"generation": "Unknown", "offset": "0x00000000"},
])
def test_raw_tags_without_recognized_generation_fall_back_to_key_prefix(occurrence):

    buckets = _split_raw_tags({"G22_LegacyTag": [occurrence]}, {})

    assert buckets == {"Generation 2.2": {"LegacyTag": [occurrence]}}

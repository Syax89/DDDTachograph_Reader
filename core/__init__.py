"""DDD Tachograph Reader — core parsing, decoding and crypto library."""

# ruff: noqa: F401

from core.decoders import (
    _CODEPAGE_ENCODINGS,
    get_nation,
    decode_string,
    decode_date,
    decode_datef,
    decode_activity_val,
    get_cyclic_data,
    parse_cyclic_buffer_activities,
    _decode_gnss_coord,
    _decode_vehicle_record,
    _vehicle_record_valid,
    parse_card_download,
    parse_control_activity_data,
    parse_g1_vu_overview,
    parse_g2_vu_record,
    parse_certificate,
    parse_certificate_signature,
    parse_public_key_info,
    parse_g22_certificate_profile,
    parse_g22_certificate_subtag,
    parse_g22_auth_subtag,
    parse_g22_gnss_accumulated_driving,
    parse_g22_load_unload_operations,
    parse_g22_trailer_registrations,
    parse_g22_gnss_enhanced_places,
    parse_g22_load_sensor_data,
    parse_g22_border_crossings,
    parse_g1_app_identification,
    parse_g1_events_data,
    parse_g1_faults_data,
    parse_g1_vehicles_used,
    parse_g1_current_usage,
    parse_calibration_data,
    parse_g1_identification,
    parse_g1_driving_licence,
    parse_specific_conditions,
    parse_card_vehicle_units,
    parse_card_gnss_places,
    parse_g2_card_icc_identification,
    parse_card_identification,
    parse_driver_card_holder_identification,
    parse_ef_icc,
    parse_ef_ic,
    parse_card_issuer_identification,
    parse_company_holder_data,
)

from core.parser import DeterministicParser, RecordArrayParser, parse_g2_trep02_activities
from core.registry import DecoderRegistry, TagDecoder, TachoResult, build_generations_tree
from core.crypto import SignatureValidator, pair_ef_records, verify_ef_pairs
from core.utils import get_logger, BytesEncoder, __version__, APP_NAME

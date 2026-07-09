"""Field-level decoders for DDD tachograph card and vehicle unit data.

Facade module: the implementations live in the type-split modules below,
grouped by domain and generation:

* ``common``    — shared primitives (strings, dates, GNSS, cyclic buffers)
* ``card_ef``   — card EF decoders (multi-generation, G1/G2/G2.2 dedup)
* ``card_g22``  — G2.2-specific card EF decoders
* ``cert``      — certificate / CVC decoders
* ``vu_g1``     — G1 vehicle-unit stream walkers (TREP 01-06)
* ``vu_g2``     — G2/G2.2 vehicle-unit RecordArray dispatch

Only the public decoder API is re-exported here. Internal helpers (names
prefixed with ``_``) must be imported from their own module directly.
"""
# ruff: noqa: F401

from core.decoders.common import (
    get_nation,
    decode_string,
    decode_date,
    decode_datef,
    decode_activity_val,
    get_cyclic_data,
    parse_cyclic_buffer_activities,
)
from core.decoders.card_ef import (
    parse_g1_identification,
    parse_g1_driving_licence,
    parse_g1_vehicles_used,
    parse_g1_current_usage,
    parse_card_identification,
    parse_driver_card_holder_identification,
    parse_calibration_data,
    parse_g1_app_identification,
    parse_g1_events_data,
    parse_g1_faults_data,
    parse_g1_places,
    parse_card_vehicle_units,
    parse_card_gnss_places,
    parse_g2_card_icc_identification,
    parse_ef_icc,
    parse_ef_ic,
    parse_control_activity_data,
    parse_card_download,
    parse_specific_conditions,
    parse_card_issuer_identification,
    parse_company_holder_data,
)
from core.decoders.card_g22 import (
    parse_g22_gnss_accumulated_driving,
    parse_g22_load_unload_operations,
    parse_g22_trailer_registrations,
    parse_g22_gnss_enhanced_places,
    parse_g22_load_sensor_data,
    parse_g22_border_crossings,
)
from core.decoders.cert import (
    parse_g22_auth_subtag,
    parse_g22_certificate_subtag,
    parse_g1_certificate,
    parse_certificate,
    parse_certificate_signature,
    EC_CURVE_OIDS,
    parse_public_key_info,
    parse_g22_certificate_profile,
)
from core.decoders.vu_g2 import (
    parse_g2_vu_record,
)
from core.decoders.vu_g1 import (
    parse_vu_vehicle_identification,
    parse_g1_vu_overview,
    parse_vu_download_messages,
)

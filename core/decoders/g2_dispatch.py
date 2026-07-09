"""G2/G2.2 Vehicle Unit record dispatch table (tag-keyed, 0x05xx).

Real G2/G2.2 VU downloads are recordType-keyed RecordArray streams handled by
:mod:`core.parser.vu_dispatcher`. This table maps TLV tags (0x0509-0x0533) to
their canonical decoders — each entry references the dispatcher directly, with
no intermediate wrappers (the caller slices the record before invoking).
"""
from core.parser.vu_dispatcher import (
    decode_vu_card_record,
    decode_card_iw,
    decode_downloadable_period,
    decode_time_adjustment,
    decode_company_lock,
    decode_sensor_paired,
    decode_sensor_gnss_coupled,
    decode_its_consent,
    decode_overspeeding_event,
    decode_overspeeding_control,
    decode_time_adj_gnss,
    decode_power_interruption,
    decode_sensor_fault,
    decode_detailed_speed,
    decode_controller_identification,
)

G2_VU_RECORD_DECODERS = {
    0x0509: ("CardRecord",        decode_vu_card_record,           45),
    0x050A: ("CardIWRecord",      decode_card_iw,                  131),
    0x050B: ("DownloadablePeriod", decode_downloadable_period,     8),
    0x050D: ("TimeAdjustment",    decode_time_adjustment,          99),
    0x050F: ("CompanyLocks",      decode_company_lock,             99),
    0x0510: ("SensorPaired",      decode_sensor_paired,            28),
    0x0511: ("SensorGNSS",        decode_sensor_gnss_coupled,      28),
    0x0512: ("ITSConsent",        decode_its_consent,              20),
    0x052B: ("ControllerIdentification", decode_controller_identification, 0),
    0x052C: ("DetailedSpeed",     decode_detailed_speed,           64),
    0x052D: ("OverSpeedingEvent", decode_overspeeding_event,       32),
    0x052E: ("OverSpeedingControl", decode_overspeeding_control,   9),
    0x052F: ("TimeAdjGNSS",       decode_time_adj_gnss,            8),
    0x0530: ("PowerInterruption", decode_power_interruption,       87),
    0x0531: ("SensorFault",       decode_sensor_fault,             90),
    0x0532: ("SensorGNSS",        decode_sensor_gnss_coupled,      28),
    0x0533: ("SensorPaired",      decode_sensor_paired,            28),
}

# Backward-compatible aliases for direct decoder imports (e.g. test_gen22.py).
parse_g2_card_record           = decode_vu_card_record
parse_g2_card_iw_record        = decode_card_iw
parse_g2_downloadable_period   = decode_downloadable_period
parse_g2_time_adjustment        = decode_time_adjustment
parse_g2_company_locks         = decode_company_lock
parse_g2_sensor_paired         = decode_sensor_paired
parse_g2_sensor_gnss_coupled   = decode_sensor_gnss_coupled
parse_g2_its_consent           = decode_its_consent
parse_g22_overspeeding_event   = decode_overspeeding_event
parse_g22_overspeeding_control = decode_overspeeding_control
parse_g22_time_adj_gnss        = decode_time_adj_gnss
parse_g22_power_interruption   = decode_power_interruption
parse_g22_sensor_fault         = decode_sensor_fault
parse_g22_detailed_speed       = decode_detailed_speed
parse_g22_controller_identification = decode_controller_identification

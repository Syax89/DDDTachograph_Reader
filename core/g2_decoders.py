"""G2/G2.2 Vehicle Unit record dispatch table (tag-keyed, 0x05xx).

Real G2/G2.2 VU downloads are recordType-keyed RecordArray streams handled by
:mod:`core.vu_record_dispatcher`. This module maps TLV tags (0x0509-0x0533)
to their canonical decoders — every wrapper below delegates to the dispatcher,
so there is a single byte-level definition per record type.
"""
import struct

from . import vu_record_dispatcher as _vrd


# Thin wrappers — the canonical implementation is in vu_record_dispatcher.

def parse_g2_card_record(data, offset=0):
    return _vrd.decode_vu_card_record(data[offset:])

def parse_g2_card_iw_record(data, offset=0):
    return _vrd.decode_card_iw(data[offset:])

def parse_g2_downloadable_period(data, offset=0):
    return _vrd.decode_downloadable_period(data[offset:])

def parse_g2_time_adjustment(data, offset=0):
    return _vrd.decode_time_adjustment(data[offset:])

def parse_g2_company_locks(data, offset=0):
    return _vrd.decode_company_lock(data[offset:])

def parse_g2_sensor_paired(data, offset=0):
    return _vrd.decode_sensor_paired(data[offset:])

def parse_g2_sensor_gnss_coupled(data, offset=0):
    return _vrd.decode_sensor_gnss_coupled(data[offset:])

def parse_g2_its_consent(data, offset=0):
    return _vrd.decode_its_consent(data[offset:])

def parse_g22_overspeeding_event(data, offset=0):
    return _vrd.decode_overspeeding_event(data[offset:])

def parse_g22_overspeeding_control(data, offset=0):
    return _vrd.decode_overspeeding_control(data[offset:])

def parse_g22_time_adj_gnss(data, offset=0):
    return _vrd.decode_time_adj_gnss(data[offset:])

def parse_g22_power_interruption(data, offset=0):
    return _vrd.decode_power_interruption(data[offset:])

def parse_g22_sensor_fault(data, offset=0):
    return _vrd.decode_sensor_fault(data[offset:])

def parse_g22_detailed_speed(data, offset=0):
    return _vrd.decode_detailed_speed(data[offset:])

def parse_g22_controller_identification(data, offset=0):
    return _vrd.decode_controller_identification(data[offset:])


G2_VU_RECORD_DECODERS = {
    0x0509: ("CardRecord", parse_g2_card_record, 45),
    0x050A: ("CardIWRecord", parse_g2_card_iw_record, 131),
    0x050B: ("DownloadablePeriod", parse_g2_downloadable_period, 8),
    0x050D: ("TimeAdjustment", parse_g2_time_adjustment, 99),
    0x050F: ("CompanyLocks", parse_g2_company_locks, 99),
    0x0510: ("SensorPaired", parse_g2_sensor_paired, 28),
    0x0511: ("SensorGNSS", parse_g2_sensor_gnss_coupled, 28),
    0x0512: ("ITSConsent", parse_g2_its_consent, 20),
    0x052B: ("ControllerIdentification", parse_g22_controller_identification, 0),
    0x052C: ("DetailedSpeed", parse_g22_detailed_speed, 64),
    0x052D: ("OverSpeedingEvent", parse_g22_overspeeding_event, 32),
    0x052E: ("OverSpeedingControl", parse_g22_overspeeding_control, 9),
    0x052F: ("TimeAdjGNSS", parse_g22_time_adj_gnss, 8),
    0x0530: ("PowerInterruption", parse_g22_power_interruption, 87),
    0x0531: ("SensorFault", parse_g22_sensor_fault, 90),
    0x0532: ("SensorGNSS", parse_g2_sensor_gnss_coupled, 28),
    0x0533: ("SensorPaired", parse_g2_sensor_paired, 28),
}

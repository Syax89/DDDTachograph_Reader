"""Vehicle-unit G2/G2.2 record decoder.

Dispatches G2/G2.2 VU RecordArray streams (tags 0x0509-0x0533) to the
record-type decoders in :mod:`core.parser.vu_dispatcher`. The tag → decoder
table is built lazily (``_record_decoders``) to break the import cycle
``core.decoders -> core.parser -> core.decoders``.
"""

import struct

from core.utils.logger import get_logger

_log = get_logger(__name__)

# tag -> (record name, default record size). The decoder callable is resolved
# lazily in :func:`_record_decoders` from ``core.parser.vu_dispatcher``.
_RECORD_TABLE = {
    0x0509: ("CardRecord",                  "decode_vu_card_record",          45),
    0x050A: ("CardIWRecord",                "decode_card_iw",                 131),
    0x050B: ("DownloadablePeriod",          "decode_downloadable_period",     8),
    0x050D: ("TimeAdjustment",              "decode_time_adjustment",         99),
    0x050F: ("CompanyLocks",                "decode_company_lock",            99),
    0x0510: ("SensorPaired",                "decode_sensor_paired",           28),
    0x0511: ("SensorGNSS",                  "decode_sensor_gnss_coupled",     28),
    0x0512: ("ITSConsent",                  "decode_its_consent",             20),
    0x052B: ("ControllerIdentification",    "decode_controller_identification", 0),
    0x052C: ("DetailedSpeed",               "decode_detailed_speed",          64),
    0x052D: ("OverSpeedingEvent",           "decode_overspeeding_event",      32),
    0x052E: ("OverSpeedingControl",         "decode_overspeeding_control",    9),
    0x052F: ("TimeAdjGNSS",                 "decode_time_adj_gnss",           8),
    0x0530: ("PowerInterruption",           "decode_power_interruption",      87),
    0x0531: ("SensorFault",                 "decode_sensor_fault",            90),
    0x0532: ("SensorGNSS",                  "decode_sensor_gnss_coupled",     28),
    0x0533: ("SensorPaired",                "decode_sensor_paired",           28),
}

# Destination key in the result dict per tag (keeps GUI/export consumers stable).
_RESULT_KEYS = {
    0x0509: "card_records",
    0x050A: "card_iw_records",
    0x050B: "downloadable_periods",
    0x050D: "time_adjustments",
    0x050F: "company_locks",
    0x0510: "sensor_paired",
    0x0511: "sensor_gnss_coupled",
    0x0512: "its_consents",
    0x052B: "vu_controller",
    0x052C: "detailed_speed",
    0x052D: "overspeeding_events",
    0x052E: "overspeeding_control",
    0x052F: "time_adj_gnss",
    0x0530: "power_interruptions",
    0x0531: "sensor_faults",
    0x0532: "sensor_gnss_coupled_g22",
    0x0533: "sensor_paired_g22",
}

_DECODERS_CACHE = None


def _record_decoders():
    """Resolve and cache the tag -> (name, decode_fn, size) dispatch table.

    Imported lazily from :mod:`core.parser.vu_dispatcher` to avoid a circular
    import at module load time (the parser package imports ``core.decoders``).
    """
    global _DECODERS_CACHE
    if _DECODERS_CACHE is None:
        from core.parser import vu_dispatcher as _vd
        _DECODERS_CACHE = {
            tag: (name, getattr(_vd, fn_name), size)
            for tag, (name, fn_name, size) in _RECORD_TABLE.items()
        }
    return _DECODERS_CACHE


def parse_g2_vu_record(val, results, tag):
    """Dispatch G2/G2.2 VU records to appropriate decoders.

    Handles tags 0x0509-0x0512 (G2 VU records) and 0x052B-0x0533 (G2.2 VU records).
    The raw value may be a RecordArray or a single record.
    """
    from core.parser.record_array import RecordArrayParser as _RAP

    try:
        decoders_map = _record_decoders()
        if tag not in decoders_map:
            return

        _name, decode_fn, _default_size = decoders_map[tag]
        result_key = _RESULT_KEYS.get(tag, f"g2_{tag:04X}")

        hdr = _RAP.parse_header(val, 0)
        if hdr and hdr["record_size"] > 0 and hdr["no_of_records"] > 0:
            records = []
            for _idx, rec, _ in _RAP.iter_records(val, 0):
                decoded = decode_fn(rec)
                if decoded:
                    records.append(decoded)
            if records:
                results.setdefault(result_key, []).extend(records)
        else:
            # Bare record without a RecordArray header: same destination key,
            # so consumers (GUI/export) see the data regardless of wrapping.
            decoded = decode_fn(val)
            if decoded:
                results.setdefault(result_key, []).append(decoded)
    except (struct.error, IndexError, ValueError, KeyError, AttributeError) as exc:
        _log.debug("G2 VU record parse failed for tag 0x%04X: %s", tag, exc)

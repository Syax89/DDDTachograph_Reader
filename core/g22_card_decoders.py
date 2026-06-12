"""Gen 2.2 (Smart Tachograph V2, Reg. EU 2023/980) card decoders: GNSS accumulated driving, load/unload, trailers, enhanced places, load sensor, border crossings."""

import struct
from datetime import datetime, timezone

from core.logger import get_logger
from core.decode_primitives import _decode_gnss_coord, decode_string, get_nation

_log = get_logger(__name__)

def parse_g22_gnss_accumulated_driving(val, results):
    """Parse GNSSAccumulatedDrivingRecord — Annex 1C §2.79 (11 bytes per record).

    Structure (Annex 1C §2.79, amended Reg. 2021/1228):
      timeStamp        4  TimeReal
      gnssAccuracy     1  UInt8 (metres)
      geoCoordinates   6  latitude(3, signed int24) + longitude(3, signed int24) — §2.76
    Total: 11 bytes
    """
    if len(val) < 11:
        return
    try:
        rec_size = 11
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            gnss_accuracy = chunk[4]
            lat = _decode_gnss_coord(chunk, 5)
            lon = _decode_gnss_coord(chunk, 8)
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                results.setdefault("gnss_ad_records", []).append({
                    "timestamp": dt,
                    "gnss_accuracy": gnss_accuracy,
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("GNSS accumulated driving parse failed: %s", exc)

def parse_g22_load_unload_operations(val, results):
    """Parse VuLoadUnloadRecord — ASN.1 (tachograph.asn:379-384), 11 bytes per record.

    Structure (all fields required):
      timestamp       4  TimeReal
      operationType   1  UInt8 (0x01=LOAD, 0x02=UNLOAD, 0x03=SIMULTANEOUS)
      latitude        3  Int24 (signed, ±DDMM.M ×10)
      longitude       3  Int24 (signed, ±DDDMM.M ×10)
    Total: 11 bytes
    """
    if len(val) < 11:
        return
    try:
        rec_size = 11
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            op_type = chunk[4]
            lat = _decode_gnss_coord(chunk, 5)
            lon = _decode_gnss_coord(chunk, 8)
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                op_map = {0x01: "LOAD", 0x02: "UNLOAD", 0x03: "SIMULTANEOUS"}
                results.setdefault("load_unload_records", []).append({
                    "timestamp": dt,
                    "operation": op_map.get(op_type, f"0x{op_type:02X}"),
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Load/unload operations parse failed: %s", exc)

def parse_g22_trailer_registrations(val, results):
    """Parse VehicleRegistrationIdentificationRecord — ASN.1 (tachograph.asn:386-391), 20 bytes.

    Structure (ASN.1):
      timestamp              4  TimeReal
      trailerNation          1  NationNumeric
      trailerPlate          14  InternationalString{13} (codePage 1 + chars 13)
      couplingStatus         1  UInt8 (0=COUPLED, 1=UNCOUPLED)
    Total: 20 bytes
    """
    if len(val) < 20:
        return
    try:
        rec_size = 20
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            nation = get_nation(chunk[4])
            plate = decode_string(chunk[5:19], is_id=True)
            coupling = chunk[19]
            coupling_map = {0: "COUPLED", 1: "UNCOUPLED"}
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            results.setdefault("trailer_registrations", []).append({
                "timestamp": dt,
                "nation": nation,
                "trailer_plate": plate,
                "coupling_code": coupling,
                "event": coupling_map.get(coupling, f"UNKNOWN_{coupling:02X}")
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Trailer registrations parse failed: %s", exc)

def parse_g22_gnss_enhanced_places(val, results):
    """Parse GNSSPlaceAuthRecord — Annex 1C §2.79c (12 bytes per record).

    Structure (Annex 1C §2.79c + §2.76):
      timeStamp             4  TimeReal
      gnssAccuracy          1  UInt8 (metres)
      geoCoordinates        6  latitude(3, int24) + longitude(3, int24)
      authenticationStatus  1  UInt8 (0=not authenticated, 1=authenticated)
    Total: 12 bytes
    """
    if len(val) < 12:
        return
    try:
        rec_size = 12
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            gnss_accuracy = chunk[4]
            lat = _decode_gnss_coord(chunk, 5)
            lon = _decode_gnss_coord(chunk, 8)
            auth_status = chunk[11]
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                results.setdefault("gnss_places", []).append({
                    "timestamp": dt,
                    "gnss_accuracy": gnss_accuracy,
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                    "authentication_status": auth_status,
                    "authenticated": auth_status == 1,
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("GNSS enhanced places parse failed: %s", exc)

def parse_g22_load_sensor_data(val, results):
    """Parse load sensor (weight) data (Gen 2.2)."""
    if len(val) < 8:
        return
    try:
        # timestamp(4) + axle_weight(2) per axle + total(2)
        ts = struct.unpack(">I", val[0:4])[0]
        if ts == 0 or ts == 0xFFFFFFFF:
            return
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        weights = []
        for j in range(4, len(val) - 1, 2):
            w = struct.unpack(">H", val[j:j+2])[0]
            if w != 0xFFFF:
                weights.append(w)
        results.setdefault("load_sensor_data", []).append({
            "timestamp": dt,
            "weights_kg": weights
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Load sensor data parse failed: %s", exc)

def parse_g22_border_crossings(val, results):
    """Parse VuBorderCrossingRecord — ASN.1 (tachograph.asn:393-399), 12 bytes.

    Structure (all fields required, Annex 1C §2.76 for geo):
      timestamp      4  TimeReal
      nationFrom     1  NationNumeric
      nationTo       1  NationNumeric
      latitude       3  Int24 (signed, ±DDMM.M ×10)
      longitude      3  Int24 (signed, ±DDDMM.M ×10)
    Total: 12 bytes
    """
    if len(val) < 12:
        return
    try:
        rec_size = 12
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            lat = _decode_gnss_coord(chunk, 6)
            lon = _decode_gnss_coord(chunk, 9)
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                results.setdefault("border_crossings", []).append({
                    "timestamp": dt,
                    "nation_from": get_nation(chunk[4]),
                    "nation_to": get_nation(chunk[5]),
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Border crossings parse failed: %s", exc)

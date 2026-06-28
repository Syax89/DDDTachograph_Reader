"""Gen 2.2 (Smart Tachograph V2, Reg. EU 2023/980) card decoders: GNSS accumulated driving, load/unload, trailers, enhanced places, load sensor, border crossings."""

import struct
from datetime import datetime, timezone

from core.logger import get_logger
from core.decode_primitives import decode_string, get_nation

_log = get_logger(__name__)


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _valid_ts(ts):
    return ts not in (0, 0xFFFFFFFF)


def _u24(data, offset):
    return int.from_bytes(data[offset:offset + 3], "big")


def _coord32(data, offset):
    """Decode G2.2 card-side coordinates: signed 32-bit, 1/10 micro-degree."""
    if len(data) < offset + 4:
        return None
    raw = int.from_bytes(data[offset:offset + 4], "big", signed=True)
    if raw in (0x7FFFFFFF, -0x80000000):
        return None
    return round(raw / 10_000_000.0, 7)


def _iter_records(val, record_sizes):
    """Yield records from either a bare EF payload or a RecordArray wrapper."""
    if len(val) >= 5:
        record_size = struct.unpack(">H", val[1:3])[0]
        count = struct.unpack(">H", val[3:5])[0]
        total = 5 + record_size * count
        if record_size in record_sizes and total == len(val):
            for i in range(count):
                start = 5 + i * record_size
                yield val[start:start + record_size]
            return

    for size in record_sizes:
        if len(val) >= size and len(val) % size == 0:
            for i in range(0, len(val), size):
                yield val[i:i + size]
            return


def _decode_gnss_place_auth(chunk, offset=0):
    """GNSSPlaceAuthRecord: timestamp(4), accuracy(1), lat(4), lon(4), auth(1)."""
    if len(chunk) < offset + 14:
        return None
    ts = struct.unpack(">I", chunk[offset:offset + 4])[0]
    lat = _coord32(chunk, offset + 5)
    lon = _coord32(chunk, offset + 9)
    if lat is None or lon is None:
        return None
    return {
        "timestamp": _iso(ts) if _valid_ts(ts) else None,
        "gnss_accuracy": chunk[offset + 4],
        "latitude": lat,
        "longitude": lon,
        "authentication_status": chunk[offset + 13],
        "authenticated": chunk[offset + 13] == 1,
    }

def parse_g22_gnss_accumulated_driving(val, results):
    """Parse GNSSAccumulatedDrivingRecord — Annex 1C §2.79 (13 bytes).

    Structure (Reg. 2021/1228 / local ASN.1):
      timeStamp        4  TimeReal
      gnssAccuracy     1  UInt8 (metres)
      latitude         4  signed int32, 1/10 micro-degree
      longitude        4  signed int32, 1/10 micro-degree
    """
    if len(val) < 13:
        return
    try:
        for chunk in _iter_records(val, (13,)):
            ts = struct.unpack(">I", chunk[0:4])[0]
            if not _valid_ts(ts):
                continue
            gnss_accuracy = chunk[4]
            lat = _coord32(chunk, 5)
            lon = _coord32(chunk, 9)
            if lat is not None and lon is not None:
                results.setdefault("gnss_ad_records", []).append({
                    "timestamp": _iso(ts),
                    "gnss_accuracy": gnss_accuracy,
                    "latitude": lat,
                    "longitude": lon,
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("GNSS accumulated driving parse failed: %s", exc)

def parse_g22_load_unload_operations(val, results):
    """Parse LoadUnloadRecord/CardLoadUnloadRecord (13 or 22 bytes).

    CardLoadUnloadRecord adds a nested GNSSPlaceAuthRecord and odometer.
    """
    if len(val) < 13:
        return
    try:
        op_map = {0x01: "LOAD", 0x02: "UNLOAD", 0x03: "SIMULTANEOUS"}
        for chunk in _iter_records(val, (22, 13)):
            ts = struct.unpack(">I", chunk[0:4])[0]
            if not _valid_ts(ts):
                continue
            op_type = chunk[4]
            record = {"timestamp": _iso(ts), "operation": op_map.get(op_type, f"0x{op_type:02X}")}
            if len(chunk) == 22:
                place = _decode_gnss_place_auth(chunk, 5)
                if not place:
                    continue
                record.update({f"gnss_{k}": v for k, v in place.items() if k != "timestamp"})
                record["gnss_timestamp"] = place["timestamp"]
                record["vehicle_odometer_value"] = _u24(chunk, 19)
            else:
                lat = _coord32(chunk, 5)
                lon = _coord32(chunk, 9)
                if lat is None or lon is None:
                    continue
                record.update({"latitude": lat, "longitude": lon})
            results.setdefault("load_unload_records", []).append(record)
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
    """Parse GNSSPlaceAuthRecord — Annex 1C §2.79c (14 bytes per record).

    Structure (Annex 1C §2.79c + §2.76):
      timeStamp             4  TimeReal
      gnssAccuracy          1  UInt8 (metres)
      latitude              4  signed int32, 1/10 micro-degree
      longitude             4  signed int32, 1/10 micro-degree
      authenticationStatus  1  UInt8 (0=not authenticated, 1=authenticated)
    """
    if len(val) < 14:
        return
    try:
        for chunk in _iter_records(val, (14,)):
            place = _decode_gnss_place_auth(chunk)
            if not place or place["timestamp"] is None:
                continue
            results.setdefault("gnss_places", []).append(place)
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
    """Parse BorderCrossingRecord/CardBorderCrossingRecord (14 or 19 bytes).

    Structure (all fields required, Annex 1C §2.76 for geo):
      timestamp      4  TimeReal
      nationFrom     1  NationNumeric
      nationTo       1  NationNumeric
      latitude       4  signed int32, 1/10 micro-degree
      longitude      4  signed int32, 1/10 micro-degree
    """
    if len(val) < 14:
        return
    try:
        for chunk in _iter_records(val, (19, 14)):
            if len(chunk) == 19:
                place = _decode_gnss_place_auth(chunk, 2)
                if not place:
                    continue
                record = {
                    "timestamp": place["timestamp"],
                    "nation_from": get_nation(chunk[0]),
                    "nation_to": get_nation(chunk[1]),
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "gnss_accuracy": place["gnss_accuracy"],
                    "authentication_status": place["authentication_status"],
                    "authenticated": place["authenticated"],
                    "vehicle_odometer_value": _u24(chunk, 16),
                }
            else:
                ts = struct.unpack(">I", chunk[0:4])[0]
                if not _valid_ts(ts):
                    continue
                lat = _coord32(chunk, 6)
                lon = _coord32(chunk, 10)
                if lat is None or lon is None:
                    continue
                record = {
                    "timestamp": _iso(ts),
                    "nation_from": get_nation(chunk[4]),
                    "nation_to": get_nation(chunk[5]),
                    "latitude": lat,
                    "longitude": lon,
                }
            results.setdefault("border_crossings", []).append(record)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Border crossings parse failed: %s", exc)

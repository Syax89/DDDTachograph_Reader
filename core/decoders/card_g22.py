"""Gen 2.2 (Smart Tachograph V2, Reg. EU 2023/980) card decoders: GNSS accumulated driving, load/unload, trailers, enhanced places, load sensor, border crossings."""

import struct
from datetime import datetime, timezone

from core.utils.logger import get_logger
from core.utils.constants import UNIX_EPOCH_2000, UNIX_EPOCH_2100
from core.decoders.common import decode_string, get_nation

_log = get_logger(__name__)


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _valid_ts(ts):
    return ts not in (0, 0xFFFFFFFF) and UNIX_EPOCH_2000 <= ts <= UNIX_EPOCH_2100


def _u24(data, offset):
    return int.from_bytes(data[offset:offset + 3], "big")


def _coord(data, offset, maximum_degrees):
    """Decode Annex 1C GeoCoordinates: signed int24, +/-DD(D)MM.M x10."""
    if len(data) < offset + 3:
        return None
    raw = int.from_bytes(data[offset:offset + 3], "big", signed=True)
    if raw == 0x7FFFFF:
        return None
    encoded = abs(raw)
    degrees, tenths_of_minute = divmod(encoded, 1000)
    if degrees > maximum_degrees or tenths_of_minute > 599:
        return None
    if degrees == maximum_degrees and tenths_of_minute:
        return None
    decimal = degrees + tenths_of_minute / 600.0
    return round(-decimal if raw < 0 else decimal, 7)


def _flat_records(val, record_size, pointer=False):
    """Yield the fixed-width records from one card EF payload format."""
    data = val[2:] if pointer else val
    if (pointer and len(val) < 2) or not data or len(data) % record_size:
        return
    for offset in range(0, len(data), record_size):
        yield data[offset:offset + record_size]


def _decode_gnss_place_auth(chunk, offset=0):
    """GNSSPlaceAuthRecord: timestamp(4), accuracy(1), coordinates(6), auth(1)."""
    if len(chunk) < offset + 12:
        return None
    ts = struct.unpack(">I", chunk[offset:offset + 4])[0]
    lat = _coord(chunk, offset + 5, 90)
    lon = _coord(chunk, offset + 8, 180)
    if not _valid_ts(ts) or lat is None or lon is None:
        return None
    return {
        "timestamp": _iso(ts),
        "gnss_accuracy": chunk[offset + 4],
        "latitude": lat,
        "longitude": lon,
        "authentication_status": chunk[offset + 11],
        "authenticated": chunk[offset + 11] == 1,
    }

def parse_g22_gnss_accumulated_driving(val, results):
    """Parse GNSSAccumulatedDriving: pointer(2) + 19-byte card records."""
    if len(val) < 21:
        return
    try:
        for chunk in _flat_records(val, 19, pointer=True):
            ts = struct.unpack(">I", chunk[0:4])[0]
            if not _valid_ts(ts):
                continue
            place = _decode_gnss_place_auth(chunk, 4)
            if not place:
                continue
            record = {
                "timestamp": _iso(ts),
                "gnss_accuracy": place["gnss_accuracy"],
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "gnss_timestamp": place["timestamp"],
                "authentication_status": place["authentication_status"],
                "authenticated": place["authenticated"],
            }
            odometer = _u24(chunk, 16)
            if odometer != 0xFFFFFF:
                record["vehicle_odometer_value"] = odometer
            results.setdefault("gnss_ad_records", []).append(record)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("GNSS accumulated driving parse failed: %s", exc)

def parse_g22_load_unload_operations(val, results):
    """Parse pointer-prefixed 20-byte CardLoadUnloadRecord values."""
    if len(val) < 22:
        return
    try:
        op_map = {0x01: "LOAD", 0x02: "UNLOAD", 0x03: "SIMULTANEOUS"}
        for chunk in _flat_records(val, 20, pointer=True):
            ts = struct.unpack(">I", chunk[0:4])[0]
            if not _valid_ts(ts):
                continue
            op_type = chunk[4]
            place = _decode_gnss_place_auth(chunk, 5)
            if not place:
                continue
            record = {"timestamp": _iso(ts), "operation": op_map.get(op_type, f"0x{op_type:02X}")}
            record.update({f"gnss_{k}": v for k, v in place.items() if k != "timestamp"})
            record["gnss_timestamp"] = place["timestamp"]
            record["vehicle_odometer_value"] = _u24(chunk, 17)
            results.setdefault("load_unload_records", []).append(record)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Load/unload operations parse failed: %s", exc)

def parse_g22_trailer_registrations(val, results):
    """Parse the 0x24 VehicleRegistrationIdentification RecordArray wrapper."""
    if len(val) < 5:
        return
    try:
        record_type = val[0]
        record_size, count = struct.unpack(">HH", val[1:5])
        if record_type != 0x24 or record_size != 15 or len(val) != 5 + record_size * count:
            return
        for i in range(count):
            chunk = val[5 + i * record_size:5 + (i + 1) * record_size]
            results.setdefault("trailer_registrations", []).append({
                "nation": get_nation(chunk[0]),
                "trailer_plate": decode_string(chunk[1:15], is_id=True),
            })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Trailer registrations parse failed: %s", exc)

def parse_g22_gnss_enhanced_places(val, results):
    """Parse 12-byte GNSSPlaceAuthRecord values (Annex 1C §§2.76, 2.79c)."""
    if len(val) < 12:
        return
    try:
        for chunk in _flat_records(val, 12):
            place = _decode_gnss_place_auth(chunk)
            if not place:
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
        if not _valid_ts(ts):
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
    """Parse pointer-prefixed 17-byte CardBorderCrossingRecord values."""
    if len(val) < 19:
        return
    try:
        for chunk in _flat_records(val, 17, pointer=True):
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
                "vehicle_odometer_value": _u24(chunk, 14),
            }
            results.setdefault("border_crossings", []).append(record)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Border crossings parse failed: %s", exc)

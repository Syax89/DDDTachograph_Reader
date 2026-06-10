#!/usr/bin/env python3
"""Generate mock DDD files for all tachograph generations (G1, G2, G2.2)."""

import struct
import os
from datetime import datetime, timezone


def get_nation_byte(code="I"):
    mapping = {"I": 0x1A, "D": 0x0D, "F": 0x11, "E": 0x0F, "UK": 0x15,
               "NL": 0x26, "B": 0x06, "A": 0x01, "CH": 0x0A, "PL": 0x28,
               "RO": 0x29, "CZ": 0x0C, "SK": 0x2D, "H": 0x18, "P": 0x27,
               "FIN": 0x12, "DK": 0x0E, "BG": 0x07}
    return mapping.get(code, 0x1A)


def s(s, n):
    """Encode string padded with spaces to n bytes."""
    return s.encode("latin-1")[:n].ljust(n, b'\x20')


def ts(y, m, d, h=0, mi=0):
    """Unix timestamp."""
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp())


def datef(y, m, d):
    """4-byte BCD date."""
    return bytes([((y//100)//10<<4)|((y//100)%10),
                  ((y%100)//10<<4)|((y%100)%10),
                  (m//10<<4)|(m%10),
                  (d//10<<4)|(d%10)])


def stap(tag, dtype, data):
    """Encode STAP: 2B tag(BE) + 1B dtype + 2B len(BE) + data."""
    return struct.pack(">HBH", tag, dtype, len(data)) + data


def act_val(activity, minute):
    """2-byte activityChangeInfo: activity(0=rest,1=avail,2=work,3=drive), minute(0-1439)."""
    return struct.pack(">H", (activity & 3) << 11 | (minute & 0x7FF))


def make_cyclic(records):
    """Build G1 cyclic buffer for tag 0x0504. records: list of (ts, odo, [(act,min),...])."""
    body = bytearray()
    for ts_val, odo_val, changes in records:
        act_bytes = b"".join(act_val(a, m) for a, m in changes)
        counters = struct.pack(">HH", 0, odo_val)
        hdr = struct.pack(">HHI", 0, 12 + len(act_bytes), ts_val)
        body.extend(hdr + counters + act_bytes)
    buf = struct.pack(">HH", 0, 0) + bytes(body)
    return buf.ljust(2048, b'\x00')[:2048]


# ─── Building blocks ───

def build_ef_icc():
    return b'\x00' + b'\x12\x34\x56\x78\x9A\xBC\xDE\xF0' + b'EF_ICC_HISTORY'


def build_ef_ic():
    return b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09'


def build_g1_id():
    return (bytes([get_nation_byte("I")])
            + s("I100000168598002", 16)
            + s("MINISTERO INFRASTRUTTURE", 36)
            + datef(2020, 6, 15) + datef(2020, 6, 15) + datef(2025, 6, 15)
            + s("ROSSI", 36) + s("MARIO", 36)
            + datef(1985, 3, 22) + b"IT")


def build_g1_licence():
    return b'\x00' * 36 + bytes([get_nation_byte("I")]) + s("U1M9999999A", 16)


def build_g1_app_id():
    return struct.pack(">BHHBBHB", 0x01, 0x0100, 6, 2, 20, 10, 10)


def build_g1_vehicles():
    def rec(odo_b, odo_e, ts1, ts2, nation, plate):
        return (struct.pack(">I", odo_b)[1:] + struct.pack(">I", odo_e)[1:]
                + struct.pack(">I", ts1) + struct.pack(">I", ts2)
                + bytes([nation]) + s(plate, 14) + b'\x00\x00')
    r = [rec(50000, 50350, ts(2025,5,1,8), ts(2025,5,1,17), get_nation_byte(), "AB123CD"),
         rec(50500, 50800, ts(2025,5,2,8), ts(2025,5,2,17), get_nation_byte(), "DE456FG"),
         rec(50900, 51050, ts(2025,5,3,8), 0xFFFFFFFF, get_nation_byte(), "HI789LM")]
    return struct.pack(">H", 0) + b"".join(r)


def build_g1_places():
    """EF Places (G1, Annex 1B §2.27): placePointerNewestRecord(1) + N x PlaceRecord(10).

    PlaceRecord: entryTime(4) + entryType(1, 0=begin/1=end) + country(1) +
    region(1) + odometer(3).
    """
    body = bytearray()
    for d in range(3):
        body.extend(struct.pack(">IBBB", ts(2025,5,1+d,8), 0x00, get_nation_byte(), 0x12))
        body.extend((50000 + d * 300).to_bytes(3, 'big'))
        body.extend(struct.pack(">IBBB", ts(2025,5,1+d,17), 0x01, get_nation_byte(), 0x12))
        body.extend((50150 + d * 300).to_bytes(3, 'big'))
    return bytes([len(body) // 10 - 1]) + bytes(body)


def build_g1_current_usage():
    return struct.pack(">IB", ts(2025,5,3,8), get_nation_byte()) + s("HI789LM", 14)


def build_g1_events():
    return struct.pack(">BIIB", 0x01, ts(2025,4,10,10), ts(2025,4,10,12), get_nation_byte()) + s("AB123CD", 14) + b'\x00'


def build_g1_faults():
    return struct.pack(">BIIB", 0x01, ts(2025,4,11,8), ts(2025,4,11,9), get_nation_byte()) + s("DE456FG", 14) + b'\x00'


def build_g1_controls():
    ptr = struct.pack(">H", 0)
    rec = struct.pack(">IB", ts(2025,4,15,10), 0x01).ljust(24, b'\x00')
    return ptr + rec


def build_g1_calibrations():
    ptr = struct.pack(">H", 0)
    rec = struct.pack(">B", 0x04) + s("WVWZZZ3CZ9E123456", 17)
    rec += bytes([get_nation_byte()]) + s("AB123CD", 14)
    rec += struct.pack(">HHH", 6200, 8000, 2200)
    rec += s("295/80R22.5", 15)
    rec += struct.pack(">B", 90)
    rec += struct.pack(">I", 50000)[1:]
    rec = rec.ljust(105, b'\x00')
    return ptr + rec


def build_g1_card_download():
    """EF Card_Download (Annex 1B §2.18): a single 4-byte TimeReal, no header."""
    return struct.pack(">I", ts(2025,5,3,18))


def build_g1_specific_conditions():
    """EF Specific_Conditions (G1, Annex 1B §2.27): 5-byte records, no header."""
    return struct.pack(">IB", ts(2025,4,12,14), 0x00) + struct.pack(">IB", ts(2025,4,12,18), 0x02)


def build_g2_icc():
    return (b'\x00' + b'\x12\x34\x56\x78\x9A\xBC\xDE\xF0'
            + s("e1-000000", 16) + s("TACHOCOMPANY SPA", 36))


def build_g2_card_id():
    return bytes([get_nation_byte()]) + s("I100000168598002", 16) + datef(2022,3,1) + datef(2027,3,1)


def build_g2_driver():
    return s("BIANCHI", 36) + s("LUCA", 36) + datef(1990,7,15) + b"EN"


def activities_week(base_date=(2025,5,1)):
    """Generate a week of daily activities."""
    records = []
    for d in range(7):
        changes = [(0,0), (3,480), (0,750), (3,795), (2,960), (0,1020)]
        records.append((ts(base_date[0], base_date[1], base_date[2]+d), 450+d*200, changes))
    return records


# ─── G1 Card ───

def generate_g1_card(out):
    acts = activities_week()
    recs = [
        (0x0002, 0x00, build_ef_icc()),
        (0x0005, 0x00, build_ef_ic()),
        (0x0520, 0x02, build_g1_id()),
        (0x0521, 0x02, build_g1_licence()),
        (0x0501, 0x02, build_g1_app_id()),
        (0x0504, 0x02, make_cyclic(acts)),
        (0x0505, 0x02, build_g1_vehicles()),
        (0x0506, 0x02, build_g1_places()),
        (0x0507, 0x02, build_g1_current_usage()),
        (0x0508, 0x02, build_g1_controls()),
        (0x050C, 0x01, build_g1_calibrations()),
        (0x050E, 0x02, build_g1_card_download()),
        (0x0522, 0x02, build_g1_specific_conditions()),
        (0x0502, 0x02, build_g1_events()),
        (0x0503, 0x02, build_g1_faults()),
        (0xC100, 0x01, b'\x00' * 194),
        (0xC108, 0x01, b'\x00' * 194),
    ]
    data = b"".join(stap(t, dt, p) for t, dt, p in recs)
    with open(out, "wb") as f:
        f.write(data)
    print(f"  G1 Card: {os.path.basename(out)} ({len(data):,} bytes)")


# ─── G1 VU ───

def generate_g1_vu(out):
    ov_data = (
        s("TACHOCOMPANY SPA", 36)
        + s("VIA ROMA 123, MILANO", 36)
        + s("e1", 8)
        + s("WVWZZZ3CZ9E123456", 17)
        + bytes([get_nation_byte("I")])
        + s("AB123CD", 14)
        + b'\x00' * 200
    )
    data = stap(0x7601, 0x00, ov_data)
    with open(out, "wb") as f:
        f.write(data)
    print(f"  G1 VU:  {os.path.basename(out)} ({len(data):,} bytes)")


# ─── G2 Card ───

def generate_g2_card(out):
    acts = activities_week()
    inner = b"".join([
        b'\x00\x02',
        stap(0x0101, 0x00, build_g2_icc()),
        stap(0x0102, 0x00, build_g2_card_id()),
        stap(0x0201, 0x00, build_g2_driver()),
        stap(0x0524, 0x02, make_cyclic(acts)),
        stap(0x0523, 0x02, build_g1_vehicles()),
        stap(0x0506, 0x02, build_g1_places()),
        stap(0x050C, 0x01, build_g1_calibrations()),
        stap(0x0522, 0x02, build_g1_specific_conditions()),
        stap(0x0502, 0x02, build_g1_events()),
        stap(0x0503, 0x02, build_g1_faults()),
        stap(0x0103, 0x01, b'\x00' * 200),
        stap(0x0104, 0x01, b'\x00' * 200),
        stap(0x2020, 0x02, s("TRASPORTI SRL", 64)),
        stap(0x0100, 0x02, s("I000000000001  TRASPORTI SRL", 64)),
        stap(0x0508, 0x02, build_g1_controls()),
        stap(0x050E, 0x02, build_g1_card_download()),
        stap(0x0505, 0x02, build_g1_vehicles()),
    ])
    data = stap(0x7621, 0x00, inner)
    with open(out, "wb") as f:
        f.write(data)
    print(f"  G2 Card: {os.path.basename(out)} ({len(data):,} bytes)")


# ─── G2 VU ───

def generate_g2_vu(out):
    acts = activities_week()
    inner = bytearray(b'\x00\x02')
    for tag in [0x0509, 0x050A, 0x050B, 0x050D, 0x050F, 0x0510, 0x0511, 0x0512]:
        sizes = {0x0509: 29, 0x050A: 28, 0x050B: 8, 0x050D: 30, 0x050F: 25, 0x0510: 24, 0x0511: 20, 0x0512: 23}
        inner.extend(stap(tag, 0x02, b'\x00' * sizes[tag]))
    inner.extend(stap(0x0524, 0x02, make_cyclic(acts)))
    inner.extend(stap(0x0523, 0x02, build_g1_vehicles()))
    inner.extend(stap(0x0502, 0x02, build_g1_events()))
    inner.extend(stap(0x0503, 0x02, build_g1_faults()))
    inner.extend(stap(0x050C, 0x01, build_g1_calibrations()))
    inner.extend(stap(0x0103, 0x01, b'\x00' * 200))
    inner.extend(stap(0x0104, 0x01, b'\x00' * 200))
    data = stap(0x7621, 0x00, bytes(inner))
    with open(out, "wb") as f:
        f.write(data)
    print(f"  G2 VU:  {os.path.basename(out)} ({len(data):,} bytes)")


# ─── G2.2 Card ───

def generate_g22_card(out):
    acts = activities_week()
    gnss = b""
    for d in range(7):
        gnss += struct.pack(">IiiHH", ts(2025,5,1+d,12), int(45.4642*1e7), int(9.19*1e7), 85, 180)
    inner = b"".join([
        b'\x00\x02',
        stap(0x0101, 0x00, build_g2_icc()),
        stap(0x0102, 0x00, build_g2_card_id()),
        stap(0x0201, 0x00, build_g2_driver()),
        stap(0x0524, 0x02, make_cyclic(acts)),
        stap(0x0525, 0x02, gnss),
        stap(0x0526, 0x02, struct.pack(">IBii", ts(2025,5,2,10), 0, int(45.4642*1e7), int(9.19*1e7))),
        stap(0x0527, 0x02, struct.pack(">IB", ts(2025,5,1,8), get_nation_byte()) + s("AB12345CD", 14) + b'\x00' * 7),
        stap(0x0528, 0x02, struct.pack(">IiiBB", ts(2025,5,1,8), int(45.4642*1e7), int(9.19*1e7), 0x01, get_nation_byte())),
        stap(0x0529, 0x02, struct.pack(">IHHH", ts(2025,5,2,14), 5000, 7000, 12000)),
        stap(0x052A, 0x02, struct.pack(">IBBii", ts(2025,5,3,18), get_nation_byte(), get_nation_byte("F"), int(44.5*1e7), int(7.0*1e7))),
        stap(0x0523, 0x02, build_g1_vehicles()),
        stap(0x0506, 0x02, build_g1_places()),
        stap(0x050C, 0x01, build_g1_calibrations()),
        stap(0x0502, 0x02, build_g1_events()),
        stap(0x0503, 0x02, build_g1_faults()),
        stap(0x0103, 0x01, b'\x00' * 200),
        stap(0x0104, 0x01, b'\x00' * 200),
        stap(0x2020, 0x02, s("TRASPORTI SRL", 64)),
        stap(0x0100, 0x02, s("I000000000001  TRASPORTI SRL", 64)),
    ])
    data = stap(0x7631, 0x00, inner)
    with open(out, "wb") as f:
        f.write(data)
    print(f"  G2.2 Card: {os.path.basename(out)} ({len(data):,} bytes)")


# ─── G2.2 VU ───

def generate_g22_vu(out):
    acts = activities_week()
    gnss = b""
    for d in range(7):
        gnss += struct.pack(">IiiHH", ts(2025,5,1+d,12), int(45.4642*1e7), int(9.19*1e7), 85, 180)
    inner = bytearray(b'\x00\x02')
    inner.extend(stap(0x0525, 0x02, gnss))
    inner.extend(stap(0x0526, 0x02, struct.pack(">IBii", ts(2025,5,2,10), 0, int(45.4642*1e7), int(9.19*1e7))))
    inner.extend(stap(0x0527, 0x02, struct.pack(">IB", ts(2025,5,1,8), get_nation_byte()) + s("AB12345CD", 14) + b'\x00' * 7))
    inner.extend(stap(0x0528, 0x02, struct.pack(">IiiBB", ts(2025,5,1,8), int(45.4642*1e7), int(9.19*1e7), 0x01, get_nation_byte())))
    inner.extend(stap(0x0529, 0x02, struct.pack(">IHHH", ts(2025,5,2,14), 5000, 7000, 12000)))
    inner.extend(stap(0x052A, 0x02, struct.pack(">IBBii", ts(2025,5,3,18), get_nation_byte(), get_nation_byte("F"), int(44.5*1e7), int(7.0*1e7))))
    for tag in [0x052B, 0x052C, 0x052D, 0x052E, 0x052F, 0x0530, 0x0531, 0x0532, 0x0533]:
        inner.extend(stap(tag, 0x02, b'\x00' * 50))
    inner.extend(stap(0x0524, 0x02, make_cyclic(acts)))
    inner.extend(stap(0x0523, 0x02, build_g1_vehicles()))
    data = stap(0x7631, 0x00, bytes(inner))
    with open(out, "wb") as f:
        f.write(data)
    print(f"  G2.2 VU: {os.path.basename(out)} ({len(data):,} bytes)")


# ─── Main ───

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "mock_data")
    os.makedirs(out_dir, exist_ok=True)
    generate_g1_card(os.path.join(out_dir, "mock_g1_card.ddd"))
    generate_g1_vu(os.path.join(out_dir, "mock_g1_vu.ddd"))
    generate_g2_card(os.path.join(out_dir, "mock_g2_card.ddd"))
    generate_g2_vu(os.path.join(out_dir, "mock_g2_vu.ddd"))
    generate_g22_card(os.path.join(out_dir, "mock_g22_card.ddd"))
    generate_g22_vu(os.path.join(out_dir, "mock_g22_vu.ddd"))
    print(f"\nGenerated 6 mock DDD files in {out_dir}")

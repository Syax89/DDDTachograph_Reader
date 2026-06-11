import struct

from .decoders import get_nation


class RecordArrayParser:
    """Parse G2/G2.2 RecordArray structures per Annex 1C Appendix 7.

    RecordArray header:
      recordType   (1 byte)   - defines the type of record contained
      recordSize   (2 bytes)  - size of each record in bytes (big-endian)
      noOfRecords  (2 bytes)  - number of records in the array

    Total header: 5 bytes.
    """

    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.offset = offset

    @staticmethod
    def parse_header(data: bytes, offset: int = 0):
        if offset + 5 > len(data):
            return None
        record_type = data[offset]
        record_size = struct.unpack(">H", data[offset + 1:offset + 3])[0]
        no_of_records = struct.unpack(">H", data[offset + 3:offset + 5])[0]
        return {
            "record_type": record_type,
            "record_size": record_size,
            "no_of_records": no_of_records,
            "header_size": 5,
        }

    @staticmethod
    def iter_records(data: bytes, offset: int = 0, max_records: int = None):
        """Iterate over records in a RecordArray. Yields (index, record_bytes, next_offset)."""
        hdr = RecordArrayParser.parse_header(data, offset)
        if hdr is None:
            return
        record_size = hdr["record_size"]
        no_of_records = hdr["no_of_records"]
        if max_records is not None:
            no_of_records = min(no_of_records, max_records)

        pos = offset + hdr["header_size"]
        for i in range(no_of_records):
            if pos + record_size > len(data):
                break
            yield i, data[pos:pos + record_size], pos + record_size
            pos += record_size


def decode_card_number(data: bytes, offset: int = 0) -> str:
    """Decode a G2 card number: 1 byte nation + 16 chars + optional 0x02 terminator."""
    result = []
    if offset >= len(data):
        return ""
    nation = data[offset]
    if 0x01 <= nation <= 0xFD:
        result.append(get_nation(nation))
    offset += 1
    for i in range(16):
        if offset + i >= len(data):
            break
        b = data[offset + i]
        if b in (0x00, 0x02, 0x03, 0xFF):
            break
        if 0x20 <= b < 0x7F:
            result.append(chr(b))
        else:
            result.append(f"\\x{b:02X}")
    return "".join(result)


def decode_g2_driver_record(data: bytes, offset: int = 0):
    """Decode a G2 driver card record from TREP 02 Activities section 1.

    Structure per Annex 1C:
      [marker 0x76?] [prefix 0x6864] [meta 2] [cardExpiry 4?] [cardHolderName 72] [fullCardNumber 18]

    cardHolderName = codePage(1) + surname(35) + codePage(1) + firstname(35) = 72 bytes
    fullCardNumber = cardType(1) + nation(1) + cardNumber(16) + terminator(0x02) = 19 bytes
    """
    if offset >= len(data):
        return None

    pos = offset
    if data[pos] == 0x76:
        pos += 1

    if pos + 4 > len(data):
        return None

    prefix = struct.unpack(">H", data[pos:pos + 2])[0]
    if prefix != 0x6864:
        return None

    meta = struct.unpack(">H", data[pos + 2:pos + 4])[0]
    pos += 4

    card_expiry = None
    if pos + 4 <= len(data):
        expiry_val = struct.unpack(">I", data[pos:pos + 4])[0]
        if expiry_val == 0xFFFFFFFF or expiry_val == 0:
            pos += 4
        elif 946684800 <= expiry_val <= 4102444800:
            card_expiry = expiry_val
            pos += 4
        else:
            pos += 4

    if pos >= len(data):
        return None
    pos += 1  # skip code_page
    if pos + 35 > len(data):
        return None
    surname = data[pos:pos + 35].decode("latin-1", errors="replace").strip()
    pos += 35

    if pos >= len(data):
        return None
    pos += 1  # skip code_page
    if pos + 35 > len(data):
        return None
    firstname = data[pos:pos + 35].decode("latin-1", errors="replace").strip()
    pos += 35

    if pos + 18 > len(data):
        return None
    pos += 1  # skip code_page
    nation = data[pos]
    pos += 1
    card_number = ""
    for i in range(16):
        b = data[pos + i]
        if b in (0x00, 0x02, 0xFF):
            break
        card_number += chr(b) if 0x20 <= b < 0x7F else f"\\x{b:02X}"
    pos += 16
    if pos < len(data) and data[pos] == 0x02:
        pos += 1

    nation_char = get_nation(nation) if 0x01 <= nation <= 0xFD else f"0x{nation:02X}"

    return {
        "surname": surname,
        "firstname": firstname,
        "card_number": card_number,
        "nation": nation_char,
        "meta": meta,
        "expiry": card_expiry,
        "end_offset": pos,
    }


def decode_g2_daily_record(data: bytes, offset: int = 0):
    """Decode a G2/G2.2 daily activity record from TREP 02 Activities.

    Structure (112 bytes for G2 with a 64-byte signature):
      [0-1]   uint16 pseudo-tag (0x7622 G2, 0x7632 G2.2)
      [2]     uint8 dtype
      [3-4]   uint16 length
      [5-8]   uint32 daily_counter
      [9-13]  pseudo-STAP header (tag, dtype=0x05, len=3)
      [14-16] uint24 field
      [17-18] uint16 day_field  (days since 1998-01-01)
      [19]    uint8 marker
      [20-21] uint16 changes_count
      [22-43] 11 x uint16 counters (first 3 are metadata: 0x0000, 0x0100, 0x0200)
      [44]    0x00
      [45]    uint8 sig_len (0x40 = 64)
      [46-47] 0x00 0x01
      [48-111] 64-byte ECDSA signature (r[32] || s[32])
    """
    if offset + 22 > len(data):
        return None

    rec_data = data[offset:]

    tag = struct.unpack(">H", rec_data[0:2])[0]
    daily_counter = struct.unpack(">I", rec_data[5:9])[0]
    day_field = struct.unpack(">H", rec_data[17:19])[0]
    changes_count = struct.unpack(">H", rec_data[20:22])[0]

    if changes_count == 0 or changes_count > 300:
        return None

    generation = "G2.2" if tag == 0x7632 else "G2"

    counters_data = rec_data[22:44]
    counters = []
    for i in range(11):
        if i * 2 + 1 < len(counters_data):
            c = struct.unpack(">H", counters_data[i * 2:i * 2 + 2])[0]
            counters.append(c)

    activity_map = {0: "REST", 1: "AVAILABLE", 2: "WORK", 3: "DRIVE"}

    changes = []
    for i in range(3, len(counters)):
        c = counters[i]
        if c == 0:
            continue
        slot = (c >> 15) & 1
        crew = (c >> 14) & 1
        activity = (c >> 11) & 3
        minute = c & 0x7FF
        if minute > 1439:
            continue
        changes.append({
            "time": f"{minute // 60:02d}:{minute % 60:02d}",
            "activity": activity_map.get(activity, f"type_{activity}"),
            "slot": "Second" if slot else "First",
            "crew": bool(crew),
        })

    sig_len = rec_data[45] if len(rec_data) > 45 else None

    return {
        "generation": generation,
        "tag": f"0x{tag:04X}",
        "daily_counter": daily_counter,
        "day_field": day_field,
        "changes_count": changes_count,
        "changes": changes,
        "counters_raw": counters,
        "sig_len": sig_len,
        # signature starts at offset 48; default to a 64-byte signature when
        # sig_len is absent (48 + 64 = 112)
        "record_size": 48 + (sig_len if sig_len is not None else 64),
    }


def parse_g2_trep02_activities(data: bytes, results: dict):
    """Parse G2/G2.2 TREP 02 Activities message (full G2 RecordArray format).

    Sections:
      1. Driver card holder records (0x6864 prefix)
      2. Signed daily activity records (0x7622/0x7632 prefix)
    """
    if len(data) < 50:
        return

    pos = 0
    if data[pos] == 0x76:
        pos += 1

    drivers = results.setdefault("inserted_drivers", [])

    while pos + 8 <= len(data):
        if data[pos:pos + 2] == b'\x68\x64':
            drv = decode_g2_driver_record(data, pos)
            if drv and drv.get("surname"):
                if not all(c in (' ', '\xff', '\x00') for c in drv["surname"]):
                    driver_key = f"{drv['surname']}|{drv['firstname']}|{drv['card_number']}"
                    if not any(d.get("_key") == driver_key for d in drivers):
                        drivers.append({
                            "surname": drv["surname"],
                            "firstname": drv["firstname"],
                            "card_number": drv["card_number"],
                            "nation": drv["nation"],
                            "_key": driver_key,
                        })
                pos = drv["end_offset"]
                continue
            pos += 1
        else:
            break

    separator = b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'
    sep_idx = data.find(separator, pos)
    if sep_idx >= 0:
        pos = sep_idx + len(separator)

    activity_list = results.setdefault("activities", [])
    signed_records = results.setdefault("signed_daily_records", [])

    first_daily_pos = None
    for scan in range(pos, min(pos + 300, len(data) - 22)):
        tag = struct.unpack(">H", data[scan:scan + 2])[0]
        if tag in (0x7622, 0x7632):
            daily = decode_g2_daily_record(data, scan)
            if daily and daily["changes_count"] > 0:
                counter = daily["daily_counter"]
                if counter > 0 and counter < 10000000:
                    first_daily_pos = scan
                    break

    if first_daily_pos is not None:
        pos = first_daily_pos
        last_counter = None
        while pos + 22 <= len(data):
            tag_check = struct.unpack(">H", data[pos:pos + 2])[0]
            if tag_check not in (0x7622, 0x7632):
                break

            daily = decode_g2_daily_record(data, pos)
            if daily is None:
                break

            counter = daily["daily_counter"]
            if last_counter is not None:
                if counter <= last_counter or counter > last_counter + 100:
                    break
            last_counter = counter

            signed_records.append({
                "daily_counter": counter,
                "generation": daily["generation"],
                "sig_len": daily.get("sig_len", 64),
            })

            rec_size = daily.get("record_size", 112)
            pos += rec_size

    def _date_key(entry):
        try:
            day, month, year = entry.get("date", "").split("/")
            return (int(year), int(month), int(day))
        except (ValueError, AttributeError):
            return (0, 0, 0)

    activity_list.sort(key=_date_key, reverse=True)

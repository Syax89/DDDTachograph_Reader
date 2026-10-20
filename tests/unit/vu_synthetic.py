"""Builders for synthetic (never real) VU download streams.

Every constant here is obviously synthetic: card numbers are ``T`` + zeros, names
are ASCII placeholders, and the timestamps are arbitrary non-round values. The
builders exist so the TREP/RecordArray tests can exercise exact normative
layouts without a private download.
"""
import struct

#: Arbitrary, clearly synthetic TimeReal values (never a corpus timestamp).
BASE_TIME = 1712345678
DAY_TIME = BASE_TIME + 86_400

#: Marker byte that opens every VU TREP section.
SID = 0x76

#: Obviously synthetic registration plate (13 characters, Annex 1B §2.114).
PLATE = "TZ000SYNTH001"
VIN = "TZSYNTHVIN0000001"


def record_array(record_type, record_size, records):
    """One RecordArray: recordType(1) + recordSize(2 BE) + noOfRecords(2 BE)."""
    for rec in records:
        assert len(rec) == record_size, (record_type, len(rec), record_size)
    body = b"".join(records)
    return (bytes([record_type]) + struct.pack(">HH", record_size, len(records))
            + body)


def section(trep, *arrays):
    """A TREP section: ``0x76 TREP`` followed by its RecordArrays in order."""
    return bytes([SID, trep]) + b"".join(arrays)


def signature_record(size=64):
    """SignatureRecord — structurally opaque ECC bytes (all-zero, synthetic)."""
    return record_array(0x08, size, [b"\x00" * size])


def interface_version(first=0x01, second=0x01):
    """TREP 00 DownloadInterfaceVersion: SID + TREP + the two transfer bytes."""
    return bytes([SID, 0x00, first, second])


def card_number(card_type=0x01, nation=0x1A, number=b"T" + b"0" * 15,
                generation=0x02):
    """FullCardNumberAndGeneration (19 bytes, Annex 1C §2.74)."""
    assert len(number) == 16
    return bytes([card_type, nation]) + number + bytes([generation])


def full_card_number(card_type=0x02, nation=0x1A, number=b"T" + b"0" * 15):
    """FullCardNumber (18 bytes, Annex 1B §2.57) — no generation byte."""
    assert len(number) == 16
    return bytes([card_type, nation]) + number


EMPTY_CARD = b"\xff" * 19

#: CardSlotsStatus byte 'ccccdddd'B (Annex 1B §2.28 / Annex 1C §2.152):
#: driver card (1) in the driver slot, company card (4) in the co-driver slot.
SLOTS_DRIVER_AND_COMPANY = 0x41


def coded_string(text, code_page=5, length=0):
    """``codePage`` + text, padded with ``00`` to *length* (0 = pad to text)."""
    raw = bytes([code_page]) + text.encode("latin-1")
    if length:
        raw = raw + b"\x00" * (length - len(raw))
    return raw


def bcd_month_year(year_suffix, month):
    """BCDString(SIZE(2)) monthYear of one ExtendedSerialNumber (§2.56)."""
    return bytes([((month // 10) << 4) | (month % 10),
                  ((year_suffix // 10) << 4) | (year_suffix % 10)])


def extended_serial(serial, year_suffix=0x23, month=0x07, equipment_type=0x81,
                    manufacturer=0x0C):
    """ExtendedSerialNumber (8 bytes): serialNumber(4) + monthYear(2) + type(1)
    + manufacturerCode(1). Every value below is synthetic."""
    return (struct.pack(">I", serial) + bcd_month_year(year_suffix, month)
            + bytes([equipment_type, manufacturer]))

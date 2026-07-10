"""Centralised event & fault type descriptions per EU tachograph legislation.

References:
  - Regulation (EEC) 3821/85 Annex 1B §2.70 (G1 EventFaultType)
  - Regulation (EU) 2016/799 Annex 1C §2.86 (G2 EventFaultType)
  - Regulation (EU) 2021/1228 / 2023/980 (G2.2 amendments)

``EventFaultType`` is a single byte shared by events and faults:
  '00'H..'0F'H  general events
  '10'H..'1F'H  VU related security breach attempt events
  '20'H..'2F'H  sensor related security breach attempt events
  '30'H..'3F'H  recording equipment faults
  '40'H..'4F'H  card faults
  '50'H..'7F'H  reserved for future use
  '80'H..'FF'H  manufacturer specific

Every decoder that produces an event / fault entry should call
:func:`describe_event` / :func:`describe_fault` to attach a human-readable
description alongside the numeric code.
"""

# ── Event types ('00'H..'2F'H) ───────────────────────────────────────────────

EVENT_TYPES: dict[int, str] = {
    # General events ('00'H..'0F'H)
    0x00: "No further details",
    0x01: "Insertion of a non-valid card",
    0x02: "Card conflict",
    0x03: "Time overlap",
    0x04: "Driving without an appropriate card",
    0x05: "Card insertion while driving",
    0x06: "Last card session not correctly closed",
    0x07: "Over speeding",
    0x08: "Power supply interruption",
    0x09: "Motion data error",
    # G2 (Annex 1C)
    0x0A: "Vehicle motion conflict",
    0x0B: "Time conflict (GNSS vs VU internal clock)",
    0x0C: "Communication error with the remote communication facility",
    0x0D: "Absence of position information from GNSS receiver",
    0x0E: "Communication error with the external GNSS facility",
    0x0F: "GNSS anomaly",
    # VU related security breach attempt events ('10'H..'1F'H)
    0x10: "Security breach attempt, no further details",
    0x11: "Motion sensor authentication failure",
    0x12: "Tachograph card authentication failure",
    0x13: "Unauthorised change of motion sensor",
    0x14: "Card data input integrity error",
    0x15: "Stored user data integrity error",
    0x16: "Internal data transfer error",
    0x17: "Unauthorised case opening",
    0x18: "Hardware sabotage",
    # G2 (Annex 1C)
    0x19: "Tamper detection of GNSS",
    0x1A: "External GNSS facility authentication failure",
    0x1B: "External GNSS facility certificate expired",
    0x1C: "Inconsistency between motion data and stored driver activity data",
    # Sensor related security breach attempt events ('20'H..'2F'H)
    0x20: "Sensor security breach attempt, no further details",
    0x21: "Sensor authentication failure",
    0x22: "Sensor stored data integrity error",
    0x23: "Sensor internal data transfer error",
    0x24: "Sensor unauthorised case opening",
    0x25: "Sensor hardware sabotage",
}

# ── Fault types ('30'H..'4F'H) ───────────────────────────────────────────────

FAULT_TYPES: dict[int, str] = {
    # Recording equipment faults ('30'H..'3F'H)
    0x30: "Recording equipment fault, no further details",
    0x31: "VU internal fault",
    0x32: "Printer fault",
    0x33: "Display fault",
    0x34: "Downloading fault",
    0x35: "Sensor fault",
    # G2 (Annex 1C)
    0x36: "Internal GNSS receiver fault",
    0x37: "External GNSS facility fault",
    0x38: "Remote communication facility fault",
    0x39: "ITS interface fault",
    0x3A: "Internal sensor fault",
    # Card faults ('40'H..'4F'H)
    0x40: "Card fault, no further details",
}

# ── Specific condition types (Annex 1B / Annex 1C §2.154) ──────────────────
#
# Value assignment (Reg. 2016/799 §2.154):
#   '00'H RFU
#   '01'H Out of scope — Begin
#   '02'H Out of scope — End
#   '03'H Ferry / Train crossing (G2: — Begin)
#   '04'H Ferry / Train crossing — End (G2 only)
#   '05'H..'FF'H RFU

SPECIFIC_CONDITION_TYPES: dict[int, str] = {
    0x00: "RFU",
    0x01: "Out of scope — Begin",
    0x02: "Out of scope — End",
    0x03: "Ferry / Train crossing — Begin",
    0x04: "Ferry / Train crossing — End",
}

# Compact labels used as the machine-friendly ``condition`` field in results.
SPECIFIC_CONDITION_LABELS: dict[int, str] = {
    0x00: "RFU",
    0x01: "OutOfScope Begin",
    0x02: "OutOfScope End",
    0x03: "Ferry/Train Begin",
    0x04: "Ferry/Train End",
}


def specific_condition_label(code) -> str:
    """Compact label for a SpecificConditionType code (Annex 1C §2.154)."""
    if code is None:
        return "Unknown"
    return SPECIFIC_CONDITION_LABELS.get(code, f"0x{code:02X}")

# ── Calibration purpose (Annex 1B §2.8 / Annex 1C req. 120) ────────────────
#
# CalibrationPurpose: why a set of calibration parameters was recorded.
#   0x00 reserved value
#   0x01 activation — calibration parameters known at VU activation
#   0x02 first installation — first calibration after activation
#   0x03 installation — first calibration in the current vehicle
#   0x04 periodic inspection

CALIBRATION_PURPOSE: dict[int, str] = {
    0x00: "Reserved",
    0x01: "Activation",
    0x02: "First installation",
    0x03: "Installation (current vehicle)",
    0x04: "Periodic inspection",
}

# ── Control type (Annex 1B §2.53 / Annex 1C req. 126) ──────────────────────
#
# ControlType is a BIT MASK ('cvds'B), not an enumeration: each bit flags an
# activity carried out during the control. Real records carry values such as
# 0x40 (VU downloaded) or 0xE0 (card + VU downloaded + printing).

CONTROL_TYPE_BITS: tuple[tuple[int, str], ...] = (
    (0x80, "Card downloaded"),
    (0x40, "VU downloaded"),
    (0x20, "Printing"),
    (0x10, "Display"),
    # Annex 1C (smart tachograph) only — roadside calibration checking.
    (0x08, "Roadside calibration check"),
)

# ── Helpers ─────────────────────────────────────────────────────────────────

def describe_event(code) -> str:
    """Return a human-readable description for an EventFaultType *code*
    recorded as an event. Falls back to the normative range groups."""
    if code is None:
        return "Unknown event"
    if code in EVENT_TYPES:
        return EVENT_TYPES[code]
    if 0x10 <= code <= 0x1F:
        return f"VU security breach attempt (0x{code:02X})"
    if 0x20 <= code <= 0x2F:
        return f"Sensor security breach attempt (0x{code:02X})"
    if 0x30 <= code <= 0x4F:
        return describe_fault(code)
    if 0x50 <= code <= 0x7F:
        return f"Reserved event (0x{code:02X})"
    if code >= 0x80:
        return f"Manufacturer specific event (0x{code:02X})"
    return f"Unknown event (0x{code:02X})"


def describe_fault(code) -> str:
    """Return a human-readable description for an EventFaultType *code*
    recorded as a fault. Falls back to the normative range groups."""
    if code is None:
        return "Unknown fault"
    if code in FAULT_TYPES:
        return FAULT_TYPES[code]
    if 0x30 <= code <= 0x3F:
        return f"Recording equipment fault (0x{code:02X})"
    if 0x40 <= code <= 0x4F:
        return f"Card fault (0x{code:02X})"
    if 0x50 <= code <= 0x7F:
        return f"Reserved fault (0x{code:02X})"
    if isinstance(code, int) and code >= 0x80:
        return f"Manufacturer specific fault (0x{code:02X})"
    if 0x00 <= code <= 0x2F:
        # An event code recorded in a fault slot — describe it as the event.
        return describe_event(code)
    return f"Unknown fault (0x{code:02X})"


def describe_specific_condition(code: int) -> str:
    """Return description for a specific condition type code."""
    return SPECIFIC_CONDITION_TYPES.get(code, f"Condition 0x{code:02X}")


# ── Event/Fault record purpose (Annex 1B §2.72 / Annex 1C §2.75) ───────────
#
# EventFaultRecordPurpose explains WHY a given event or fault was stored:
#   '00'H one of the 10 most recent (or last) events or faults
#   '01'H the longest event for one of the last 10 days of occurrence
#   '02'H one of the 5 longest events over the last 365 days
#   '03'H the last event for one of the last 10 days of occurrence
#   '04'H the most serious event for one of the last 10 days of occurrence
#   '05'H one of the 5 most serious events over the last 365 days
#   '06'H the first event or fault having occurred after the last calibration
#   '07'H an active / on-going event or fault
#   '08'H..'7F'H reserved for future use
#   '80'H..'FF'H manufacturer specific

EVENT_FAULT_RECORD_PURPOSE: dict[int, str] = {
    0x00: "One of the 10 most recent (or last) events/faults",
    0x01: "Longest event for one of the last 10 days of occurrence",
    0x02: "One of the 5 longest events over the last 365 days",
    0x03: "Last event for one of the last 10 days of occurrence",
    0x04: "Most serious event for one of the last 10 days of occurrence",
    0x05: "One of the 5 most serious events over the last 365 days",
    0x06: "First event/fault after the last calibration",
    0x07: "Active / on-going event or fault",
}


def describe_record_purpose(code) -> str:
    """Human-readable EventFaultRecordPurpose (Annex 1B §2.72)."""
    if code is None:
        return "Unknown"
    if code in EVENT_FAULT_RECORD_PURPOSE:
        return EVENT_FAULT_RECORD_PURPOSE[code]
    if 0x08 <= code <= 0x7F:
        return f"Reserved (0x{code:02X})"
    if code >= 0x80:
        return f"Manufacturer specific (0x{code:02X})"
    return f"Unknown (0x{code:02X})"


def describe_calibration_purpose(code) -> str:
    """Return a human-readable label for a CalibrationPurpose byte."""
    if code is None:
        return "Unknown"
    return CALIBRATION_PURPOSE.get(code, f"0x{code:02X}")


def describe_control_type(code) -> str:
    """Decode a ControlType bit mask ('cvds'B, Annex 1B §2.53) into a
    comma-separated list of the activities carried out during the control."""
    if code is None:
        return "Unknown"
    parts = [label for bit, label in CONTROL_TYPE_BITS if code & bit]
    leftover = code & ~sum(bit for bit, _ in CONTROL_TYPE_BITS)
    if leftover:
        parts.append(f"0x{leftover:02X}")
    return ", ".join(parts) if parts else "None recorded"

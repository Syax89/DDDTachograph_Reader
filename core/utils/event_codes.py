"""Centralised event & fault type descriptions per EU tachograph legislation.

References:
  - Regulation (EEC) 3821/85 Annex 1B §2.70 (generation 1 EventFaultType)
  - Regulation (EU) 2016/799 Annex 1C, Appendix 1, point 2.70 (EventFaultType),
    as amended by Reg. (EU) 2018/502 Annex (29)(h) ("Generation 2, version 1")
    and Reg. (EU) 2021/1228 Annex (30)(n)(i)/(ii) ("Generation 2, version 2")
  - Regulation (EU) 2023/980 (generation 2 version 2 amendments)

The two dicts below carry the generation-2 *version 2* assignment of point 2.70,
read from the amending acts; :data:`EVENT_TYPES_V1` / :data:`FAULT_TYPES_V1` are
the *version 1* tables (the same minus the three codes 2021/1228 introduced), and
:func:`describe_event_fault_type` picks the right one for a resolved section
version. :func:`describe_event` / :func:`describe_fault` keep their historical
default (the version-2 wording) for callers that have no section context, such
as the generation-1 and card decoders.

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

# ── EventFaultType assignment per schema version (point 2.70) ──────────────
#
# Point 2.70 comes in two generation-2 variants and they are *not*
# interchangeable: Reg. 2018/502 Annex (29)(h) replaced the text under the
# "Generation 2" heading ("Generation 2, version 1"), and Reg. 2021/1228 Annex
# (30)(n)(i) renamed that header "Generation 2, version 1" while (30)(n)(ii)
# added the "Generation 2, version 2" table. Which one a record is read against
# is a property of the section that carries it — Appendix 7: the request table
# DDP_011 gives the transfer types, and DDP_031 defines the per-TREP data
# structures "under the SID 76 Hex, the TREP 03, 23 or 33 Hex":
#
#   generation 1                                    TREP '03'H
#   generation 2, version 1                         TREP '23'H
#   generation 2, version 2                         TREP '33'H
#
# The version-2 table is the one in EVENT_TYPES/FAULT_TYPES above. The version-1
# table is that table minus the three codes the 2021/1228 amendment introduced,
# because the 2018/502 text still calls them RFU: after '0E'H the v1 list
# continues with "RFU", likewise after '1B'H and after '39'H.
EVENT_FAULT_VERSION_G1 = "generation1"
EVENT_FAULT_VERSION_1 = "generation2version1"
EVENT_FAULT_VERSION_2 = "generation2version2"
EVENT_FAULT_VERSION_UNKNOWN = "unknown"
EVENT_FAULT_VERSIONS = (EVENT_FAULT_VERSION_G1, EVENT_FAULT_VERSION_1,
                        EVENT_FAULT_VERSION_2, EVENT_FAULT_VERSION_UNKNOWN)

#: Codes the version-2 amendment defines and version 1 still calls RFU:
#: '0F'H GNSS anomaly, '1C'H motion/activity inconsistency, '3A'H internal
#: sensor fault. Reading any of them as its version-2 meaning in a version-1
#: (or unknown-version) section would fabricate an event.
GEN2_V2_ONLY_TYPES: frozenset[int] = frozenset({0x0F, 0x1C, 0x3A})

#: "Generation 1" assignment of the same point 2.70, read from the consolidated
#: Annex 1C text (Reg. (EU) 2016/799, Appendix 1, point 2.70, the "Generation 1"
#: list — the 2002 Annex 1B page is the same list *before* the amending act that
#: added '0A'H):
#:
#:   '00'H..'0A'H general events, '0B'H RFU
#:   '10'H..'18'H VU related security breach attempt events, '19'H RFU
#:   '20'H..'25'H sensor related security breach attempt events, '26'H RFU
#:   '30'H..'35'H recording equipment faults, '36'H RFU
#:   '40'H card fault with no further details, '41'H/'42'H RFU
#:
#: Two differences from generation 2 matter: '0A'H is *Vehicle Motion Conflict*
#: in the amended generation-1 list (not RFU as the 2002 text still printed), and
#: everything generation 2 added after the shared codes ('0B'H time conflict,
#: GNSS/RCM/ITS groups, '36'H..'3A'H) is RFU here.
EVENT_TYPES_G1: dict[int, str] = {
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
    0x0A: "Vehicle motion conflict",
    0x10: "Security breach attempt, no further details",
    0x11: "Motion sensor authentication failure",
    0x12: "Tachograph card authentication failure",
    0x13: "Unauthorised change of motion sensor",
    0x14: "Card data input integrity error",
    0x15: "Stored user data integrity error",
    0x16: "Internal data transfer error",
    0x17: "Unauthorised case opening",
    0x18: "Hardware sabotage",
    0x20: "Sensor security breach attempt, no further details",
    0x21: "Sensor authentication failure",
    0x22: "Sensor stored data integrity error",
    0x23: "Sensor internal data transfer error",
    0x24: "Sensor unauthorised case opening",
    0x25: "Sensor hardware sabotage",
}
FAULT_TYPES_G1: dict[int, str] = {
    0x30: "Recording equipment fault, no further details",
    0x31: "VU internal fault",
    0x32: "Printer fault",
    0x33: "Display fault",
    0x34: "Downloading fault",
    0x35: "Sensor fault",
    0x40: "Card fault, no further details",
}

#: "Generation 2, version 1" tables (Reg. 2018/502): identical to version 2 for
#: every shared code, with '0F'H/'1C'H/'3A'H left RFU.
EVENT_TYPES_V1: dict[int, str] = {
    code: name for code, name in EVENT_TYPES.items()
    if code not in GEN2_V2_ONLY_TYPES}
FAULT_TYPES_V1: dict[int, str] = {
    code: name for code, name in FAULT_TYPES.items()
    if code not in GEN2_V2_ONLY_TYPES}

# How a single EventFaultType byte relates to one version's value assignment.
TYPE_ASSIGNED = "assigned"                  # the version names this code
TYPE_RESERVED = "reserved"                  # the version says RFU
TYPE_MANUFACTURER_SPECIFIC = "manufacturer_specific"   # '80'H..'FF'H, all versions
TYPE_UNKNOWN_VERSION = "unknown_version"     # defined only by v2; section version unknown


def _version_tables(version):
    """The (event, fault) tables of *version*; unknown resolves to the v1 subset.

    The subset is the only set of codes *every* candidate version agrees on, so
    an unresolved section can still describe a shared code and never gains a
    version-2-only meaning.
    """
    if version == EVENT_FAULT_VERSION_2:
        return EVENT_TYPES, FAULT_TYPES
    if version == EVENT_FAULT_VERSION_G1:
        return EVENT_TYPES_G1, FAULT_TYPES_G1
    return EVENT_TYPES_V1, FAULT_TYPES_V1


def assigned_types(version=EVENT_FAULT_VERSION_UNKNOWN) -> frozenset[int]:
    """Every EventFaultType code *version* gives a meaning to.

    ``EventFaultType`` is one byte shared by events and faults, so the answer is
    the union of both tables (a fault record carrying '0B'H still names the
    time-conflict event).
    """
    event_table, fault_table = _version_tables(version)
    return frozenset(event_table) | frozenset(fault_table)


def event_fault_type_status(code, version=EVENT_FAULT_VERSION_UNKNOWN) -> str:
    """One of the ``TYPE_*`` constants: how *version* assigns the byte *code*."""
    if not isinstance(code, int) or not 0x00 <= code <= 0xFF:
        return TYPE_UNKNOWN_VERSION
    if code >= 0x80:
        # '80'H..'FF'H is manufacturer specific in every version.
        return TYPE_MANUFACTURER_SPECIFIC
    if code in assigned_types(version):
        return TYPE_ASSIGNED
    if version == EVENT_FAULT_VERSION_G1:
        # Generation 1 assigns nothing above its own table below '80'H.
        return TYPE_RESERVED
    if (version not in (EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2)
            and code in GEN2_V2_ONLY_TYPES):
        # A version-2-only code in a section whose version we could not resolve:
        # calling it RFU would state more than we know.
        return TYPE_UNKNOWN_VERSION
    return TYPE_RESERVED


def describe_event_fault_type(code, is_event, version=EVENT_FAULT_VERSION_UNKNOWN) -> str:
    """Describe an EventFaultType byte against *version*'s value assignment.

    The shared codes keep the exact wording :func:`describe_event` /
    :func:`describe_fault` give them. Only the three version-2-only codes differ
    by version: version 1 calls them "Reserved for future use" (what its table
    says), an unresolved version says "Unknown", and neither claims the
    "GNSS anomaly" / "inconsistency" / "internal sensor fault" meaning.
    """
    if version == EVENT_FAULT_VERSION_G1:
        table = EVENT_TYPES_G1 if is_event else FAULT_TYPES_G1
        if code in table:
            return table[code]
        if code >= 0x80:
            return (f"Manufacturer specific event (0x{code:02X})" if is_event
                    else f"Manufacturer specific fault (0x{code:02X})")
        return (f"Reserved for future use (0x{code:02X})" if is_event
                else f"Reserved for future use (0x{code:02X})")
    if code not in GEN2_V2_ONLY_TYPES or version == EVENT_FAULT_VERSION_2:
        return describe_event(code) if is_event else describe_fault(code)
    if version == EVENT_FAULT_VERSION_1:
        return f"Reserved for future use (0x{code:02X})"
    return (f"Unknown event (0x{code:02X})" if is_event
            else f"Unknown fault (0x{code:02X})")


# ── Specific condition types (Annex 1B / Annex 1C §2.154) ──────────────────
#
# Value assignment (Reg. 2016/799 §2.154):
#   '00'H RFU
#   '01'H Out of scope — Begin
#   '02'H Out of scope — End
#   '03'H Ferry / Train crossing (G2: — Begin)
#   '04'H Ferry / Train crossing — End (G2 only)
#   '05'H..'FF'H RFU

# Compact labels used as the machine-friendly ``condition`` field in results.
# Generation 2 (and 2.2) distinguishes the Begin/End pair; generation 1 has a
# single ``Ferry / Train crossing`` code and treats 0x04 as RFU.
SPECIFIC_CONDITION_LABELS: dict[int, str] = {
    0x00: "RFU",
    0x01: "OutOfScope Begin",
    0x02: "OutOfScope End",
    0x03: "Ferry/Train Begin",
    0x04: "Ferry/Train End",
}

SPECIFIC_CONDITION_LABELS_G1: dict[int, str] = {
    0x00: "RFU",
    0x01: "OutOfScope Begin",
    0x02: "OutOfScope End",
    0x03: "Ferry/Train crossing",
}


def specific_condition_label(code, generation: str = "G2") -> str:
    """Compact label for a SpecificConditionType code (Annex 1C §2.154).

    Generation 1 assigns a single meaning to 0x03 (``Ferry / Train crossing``)
    and leaves 0x04 RFU; generation 2/2.2 splits it into Begin/End.
    """
    if code is None:
        return "Unknown"
    table = SPECIFIC_CONDITION_LABELS_G1 if generation == "G1" else SPECIFIC_CONDITION_LABELS
    return table.get(code, f"0x{code:02X}")


# ── Calibration purpose (Annex 1B §2.8 / Annex 1C req. 120) ────────────────
#
# CalibrationPurpose: why a set of calibration parameters was recorded.
#   0x00 reserved value
#   0x01 activation — calibration parameters known at VU activation
#   0x02 first installation — first calibration after activation
#   0x03 installation — first calibration in the current vehicle
#   0x04 periodic inspection
#   0x05 entry of VRN by company          (generation 2 only)
#   0x06 time adjustment without calibration (generation 2 only)
#   0x07-0x7F RFU, 0x80-0xFF manufacturer specific
# Source: Reg. (EU) 2016/799, Annex 1C Appendix 1, CalibrationPurpose.

CALIBRATION_PURPOSE: dict[int, str] = {
    0x00: "Reserved",
    0x01: "Activation",
    0x02: "First installation",
    0x03: "Installation (current vehicle)",
    0x04: "Periodic inspection",
    0x05: "Entry of VRN by company",
    0x06: "Time adjustment without calibration",
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


#: CalibrationPurpose values generation 1 assigns: 00..04. Generation 2 adds
#: '05'H (entry of the VRN by the company) and '06'H (time adjustment without
#: calibration) — Reg. (EU) 2016/799 Appendix 1 point 2.71 lists them under
#: "In addition to generation 1 ... Generation 2".
CALIBRATION_PURPOSE_G1_MAX = 0x04


def describe_calibration_purpose(code, generation="G2") -> str:
    """Human-readable CalibrationPurpose label, generation-aware.

    A generation-1 record cannot mean "entry of VRN by company" or "time
    adjustment without calibration": those two values exist only from generation 2
    on, so they are reported as reserved for a generation-1 record instead of
    borrowing the later meaning.
    """
    if code is None:
        return "Unknown"
    if generation == "G1" and isinstance(code, int) and 0x05 <= code <= 0x7F:
        return f"Reserved for future use (0x{code:02X})"
    if code in CALIBRATION_PURPOSE:
        return CALIBRATION_PURPOSE[code]
    if code >= 0x80:
        return f"Manufacturer specific (0x{code:02X})"
    return f"Reserved for future use (0x{code:02X})"


#: Generation-1 ControlType (Annex 1B §2.44 / Annex 1C §2.53 "Generation 1"):
#: 'cvpdxxxx'B — the low nibble is *not used*, so bit 0x08 is not the
#: generation-2 roadside-calibration check.
CONTROL_TYPE_BITS_G1: tuple[tuple[int, str], ...] = (
    (0x80, "Card downloaded"),
    (0x40, "VU downloaded"),
    (0x20, "Printing"),
    (0x10, "Display"),
)


def control_type_bits(code, generation="G2"):
    """The flagged activities of a ControlType byte, per *generation*."""
    if not isinstance(code, int):
        return []
    table = CONTROL_TYPE_BITS_G1 if generation == "G1" else CONTROL_TYPE_BITS
    return [label for bit, label in table if code & bit]


def describe_control_type(code, generation="G2") -> str:
    """Decode a ControlType bit mask into a comma-separated activity list.

    Generation 1: 'cvpdxxxx'B (Annex 1B §2.44) — 0x08 is part of the unused
    nibble. Generation 2: 'cvpdexxx'B (Annex 1C §2.53) — 0x08 is the roadside
    calibration check. Reading a generation-1 byte with the generation-2 table
    would claim a calibration check that the record cannot express.
    """
    if code is None:
        return "Unknown"
    table = CONTROL_TYPE_BITS_G1 if generation == "G1" else CONTROL_TYPE_BITS
    parts = [label for bit, label in table if code & bit]
    leftover = code & ~sum(bit for bit, _ in table)
    if leftover:
        parts.append(f"0x{leftover:02X}")
    return ", ".join(parts) if parts else "None recorded"

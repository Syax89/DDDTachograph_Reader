"""Centralised event & fault type descriptions per EU tachograph legislation.

References:
  - Regulation (EU) 2016/799 Annex 1C, Appendix 1 (G2)
  - Regulation (EU) 2023/980 (G2.2 amendments)
  - ASN.1 schema from specs/tachograph.asn

All event / fault type codes in one place. Every decoder that produces an event
or fault entry should call :func:`describe_event` / :func:`describe_fault` to
attach a human-readable ``description`` field alongside the numeric codes.
"""

# ── Event types (Annex 1C Appendix 1, §2.162 / §2.162a) ─────────────────────

EVENT_TYPES: dict[int, str] = {
    # Core (G2)
    0x01: "Insertion of a non-valid card",
    0x02: "Card conflict",
    0x03: "Time overlap",
    0x04: "Driving without a valid card",
    0x05: "Card insertion while driving",
    0x06: "Last card session not correctly closed",
    0x07: "Over speeding",
    0x08: "Power supply interruption",
    0x09: "Motion data error",
    0x0A: "Security breach attempt",
    0x0B: "Sensor fault",
    0x0C: "VU internal fault",
    0x0D: "Download conflict",
    0x0E: "Sensor communication interruption",
    0x0F: "Data memory error",
    0x10: "Internal clock adjustment (GNSS)",
    0x11: "Recording equipment security breach",
    # G2.2 additions (Reg. EU 2023/980)
    0x12: "Operation without a valid motion sensor",
    0x13: "Illegitimate use of security mechanism",
    0x14: "Unauthorised change of sensor paired",
    0x15: "Unauthorised change of authorised workshop",
    # GNSS / remote events (G2.2)
    0x16: "GNSS communication error",
    0x17: "Motion sensor power interruption",
    0x18: "Data synchronisation error",
    0x19: "Seal tampering attempt",
    0x1A: "DSRC-V2X communication error",
    0x1B: "Load sensor error",
    0x1C: "Remote communication module fault",
}

# ── Fault types (Annex 1C Appendix 1, §2.163 / §2.163a) ─────────────────────

FAULT_TYPES: dict[int, str] = {
    # Core (G2)
    0x01: "Card data download fault",
    0x02: "Recording equipment internal fault",
    0x03: "Display fault",
    0x04: "Downloading fault",
    0x05: "Sensor fault",
    0x06: "Printer fault",
    0x07: "Internal GNSS receiver fault",
    0x08: "Motion sensor fault",
    0x09: "Motion data entry fault",
    0x0A: "Cable fault",
    0x0B: "No further details",
    # G2.2 additions (Reg. EU 2023/980)
    0x0C: "External GNSS facility fault",
    0x0D: "DSRC-V2X module fault",
    0x0E: "Remote early detection communication module fault",
    0x0F: "Load sensor fault",
    0x10: "Auto-calibration error",
    0x11: "Prolonged GNSS signal loss",
}

# ── Card event groups (Annex 1B, G1) ──────────────────────────────────────

CARD_EVENT_GROUPS: dict[int, str] = {
    0: "Time overlap",
    1: "Last card session (card not inserted)",
    2: "Power supply interruption",
    3: "Card conflict",
    4: "Time difference",
    5: "Driving without card",
}

# ── Card fault groups (Annex 1B, G1) ─────────────────────────────────────

CARD_FAULT_GROUPS: dict[int, str] = {
    0: "Recording equipment",
    1: "Card",
}

# ── Specific condition types (Annex 1B §2.27 / Annex 1C §2.152) ────────────

SPECIFIC_CONDITION_TYPES: dict[int, str] = {
    0x00: "Ferry / Train crossing",
    0x01: "Ferry / Train crossing",
    0x02: "Out of scope",
    0x03: "Begin of GNSS blackout area",
    0x04: "End of GNSS blackout area",
}

# ── Helpers ─────────────────────────────────────────────────────────────────

def describe_event(code: int) -> str:
    """Return a human-readable event description for *code*."""
    return EVENT_TYPES.get(code, f"Unknown event (0x{code:02X})")


def describe_fault(code: int) -> str:
    """Return a human-readable fault description for *code*."""
    return FAULT_TYPES.get(code, f"Unknown fault (0x{code:02X})")


def describe_card_event_group(idx: int) -> str:
    """Return description for a card event group index (0-5)."""
    return CARD_EVENT_GROUPS.get(idx, f"Event group {idx}")


def describe_card_fault_group(idx: int) -> str:
    """Return description for a card fault group index (0-1)."""
    return CARD_FAULT_GROUPS.get(idx, f"Fault group {idx}")


def describe_specific_condition(code: int) -> str:
    """Return description for a specific condition type code."""
    return SPECIFIC_CONDITION_TYPES.get(code, f"Condition 0x{code:02X}")

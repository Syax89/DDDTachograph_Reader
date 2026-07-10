"""TREP completeness inventory for VU downloads.

A VU download is a sequence of ``SID 0x76 + TREP`` messages (Annex 1B App.7 for
Gen1, Annex 1C App.7 for Gen2/2.2). Some TREPs are mandatory in a well-formed
download; a file missing them (or whose TREP decodes to implausible data) is
partial/corrupt. This module turns the observed TREPs plus their decode status
into a simple completeness report surfaced in metadata, the CLI and the GUI.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

# TREP marker (byte after 0x76) → human name, per generation family.
TREP_NAMES = {
    "G1": {
        0x01: "Overview", 0x02: "Activities", 0x03: "EventsFaults",
        0x04: "DetailedSpeed", 0x05: "TechnicalData", 0x06: "CardDownload",
        0x11: "SensorSpecialData", 0x14: "SensorTrailer",
    },
    "G2": {
        0x21: "Overview", 0x22: "Activities", 0x23: "EventsFaults",
        0x24: "DetailedSpeed", 0x25: "TechnicalData",
    },
    "G2.2": {
        0x31: "Overview", 0x32: "Activities", 0x33: "EventsFaults",
        0x34: "DetailedSpeed", 0x35: "TechnicalData",
    },
}

# Mandatory TREPs in a well-formed download (Overview + Activities +
# EventsFaults + TechnicalData). DetailedSpeed/CardDownload are optional.
MANDATORY_TREPS = {
    "G1": {0x01, 0x02, 0x03, 0x05},
    "G2": {0x21, 0x22, 0x23, 0x25},
    "G2.2": {0x31, 0x32, 0x33, 0x35},
}


def _family(generation: str) -> str:
    """Map a metadata generation label to a TREP family key."""
    g = (generation or "").upper()
    if "2.2" in g:
        return "G2.2"
    if "G2" in g:
        return "G2"
    return "G1"


def trep_name(generation: str, trep: int) -> str:
    fam = _family(generation)
    return TREP_NAMES.get(fam, {}).get(trep, f"TREP_0x{trep:02X}")


def build_trep_report(
    generation: str,
    present_treps: Iterable[int],
    suspect_treps: Iterable[int] = (),
    complete_walk: bool = True,
) -> Dict:
    """Build a completeness report for the observed TREPs.

    ``present_treps``  — every TREP marker the walk yielded.
    ``suspect_treps``  — TREPs whose decoded payload failed plausibility gating.
    ``complete_walk``  — whether the structural walk reached EOF cleanly.
    """
    fam = _family(generation)
    mandatory = MANDATORY_TREPS.get(fam, set())
    present = sorted(set(present_treps))
    suspect = set(suspect_treps)

    present_set = set(present)
    mandatory_present = sorted(mandatory & present_set)
    mandatory_missing = sorted(mandatory - present_set)
    decoded_ok = sorted(t for t in present if t not in suspect)
    decoded_suspect = sorted(t for t in present if t in suspect)

    mandatory_ok = sorted(t for t in mandatory_present if t not in suspect)
    completeness = (
        round(100.0 * len(mandatory_ok) / len(mandatory), 1) if mandatory else 100.0
    )

    def _named(treps: List[int]) -> List[Dict]:
        return [{"trep": f"0x{t:02X}", "name": trep_name(generation, t)} for t in treps]

    return {
        "generation": fam,
        "complete_walk": bool(complete_walk),
        "mandatory_total": len(mandatory),
        "mandatory_present": len(mandatory_present),
        "mandatory_ok": len(mandatory_ok),
        "completeness_pct": completeness,
        "present": _named(present),
        "mandatory_missing": _named(mandatory_missing),
        "decoded_ok": _named(decoded_ok),
        "decoded_suspect": _named(decoded_suspect),
        "is_partial": bool(mandatory_missing) or bool(decoded_suspect) or not complete_walk,
    }


def format_trep_summary(report: Dict) -> str:
    """One-line human summary for CLI/log output."""
    if not report:
        return ""
    parts = [
        f"TREP: {report['mandatory_ok']}/{report['mandatory_total']} mandatory OK "
        f"({report['completeness_pct']}%)"
    ]
    if report.get("mandatory_missing"):
        parts.append("missing " + ", ".join(t["name"] for t in report["mandatory_missing"]))
    if report.get("decoded_suspect"):
        parts.append("suspect " + ", ".join(t["name"] for t in report["decoded_suspect"]))
    return "; ".join(parts)

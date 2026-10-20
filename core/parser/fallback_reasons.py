"""Closed vocabulary that explains WHY a fallback route ran.

The owner's rule: decoding is normative; the heuristic fallback runs only when
there is a real problem, and whenever it runs we must be able to say why. If the
cause is not an error on our side, the file is damaged. A fallback on an intact
file means a defect of ours.

One place for the codes, so the parsers, the engine and the tests cannot invent
different vocabularies.
"""

#: EOF inside a declared structure (a body/record the bytes do not contain).
CAUSE_FILE_TRUNCATED = "file_truncated"
#: A declared count/size points past the end of the data.
CAUSE_COUNT_EXCEEDS_EOF = "count_exceeds_eof"
#: A record size contradicts the size the regulation fixes.
CAUSE_SIZE_MISMATCH = "size_mismatch"
#: A section marker is unknown or in a place its transfer does not define.
CAUSE_UNKNOWN_OR_MISPLACED_SECTION = "unknown_or_misplaced_section"
#: The section does not match the prescribed array order/placement.
CAUSE_SCHEMA_VIOLATION = "schema_violation"
#: A normative decoder raised on bytes it was expected to handle.
CAUSE_NORMATIVE_DECODER_EXCEPTION = "normative_decoder_exception"
#: The bytes do not match the normative layout although the structure is intact.
CAUSE_NORMATIVE_LAYOUT_NOT_MATCHED = "normative_layout_not_matched"

#: The bytes contradict the regulation: the file is damaged.
CLASSIFICATION_FILE_DAMAGED = "file_damaged"
#: A structurally complete section that our normative decoder could not read:
#: our defect until proven otherwise.
CLASSIFICATION_DECODER_DEFECT = "decoder_defect_suspected"

CAUSE_CLASSIFICATION = {
    CAUSE_FILE_TRUNCATED: CLASSIFICATION_FILE_DAMAGED,
    CAUSE_COUNT_EXCEEDS_EOF: CLASSIFICATION_FILE_DAMAGED,
    CAUSE_SIZE_MISMATCH: CLASSIFICATION_FILE_DAMAGED,
    CAUSE_UNKNOWN_OR_MISPLACED_SECTION: CLASSIFICATION_FILE_DAMAGED,
    CAUSE_SCHEMA_VIOLATION: CLASSIFICATION_FILE_DAMAGED,
    CAUSE_NORMATIVE_DECODER_EXCEPTION: CLASSIFICATION_DECODER_DEFECT,
    CAUSE_NORMATIVE_LAYOUT_NOT_MATCHED: CLASSIFICATION_DECODER_DEFECT,
}

CAUSES = frozenset(CAUSE_CLASSIFICATION)
CLASSIFICATIONS = frozenset((CLASSIFICATION_FILE_DAMAGED,
                             CLASSIFICATION_DECODER_DEFECT))


def classification_for(cause):
    """The classification of a cause code (``None`` for an unknown code)."""
    return CAUSE_CLASSIFICATION.get(cause)


def fallback_reason(route, cause, *, trep=None, offset=None, detail=None):
    """One structured reason for taking a backup route.

    ``route`` names the backup route (``vu_fallback_scan``,
    ``vu_events_faults_TREP03``, ...), ``trep`` and ``offset`` locate the bytes,
    ``cause`` is one of :data:`CAUSES` and the classification is derived from it
    so a caller cannot label an exception "file damaged".
    """
    if cause not in CAUSE_CLASSIFICATION:
        raise ValueError(f"unknown fallback cause: {cause!r}")
    return {
        "route": route,
        "trep": trep,
        "offset": offset,
        "cause": cause,
        "detail": detail,
        "classification": CAUSE_CLASSIFICATION[cause],
    }


def record_fallback_reason(results, route, cause=None, **kwargs):
    """Append one reason to ``metadata.decode_paths.fallback_reasons``.

    A section-level route (a heuristic sub-parser, a scan) usually runs *because*
    of a cause the caller already established: with ``cause=None`` the most
    recent recorded cause is inherited, so a truncated file is not relabelled as
    a decoder defect by the section that had to be scanned.
    """
    paths = results.setdefault("metadata", {}).setdefault("decode_paths", {})
    reasons = paths.setdefault("fallback_reasons", [])
    if cause is None:
        cause = (reasons[-1]["cause"] if reasons
                 else CAUSE_NORMATIVE_LAYOUT_NOT_MATCHED)
    reason = fallback_reason(route, cause, **kwargs)
    if reason not in reasons:
        reasons.append(reason)
    return reason


def primary_reason(results):
    """The first (most specific) recorded reason, or ``None``."""
    reasons = ((results.get("metadata") or {}).get("decode_paths") or {}).get(
        "fallback_reasons") or []
    return reasons[0] if reasons else None

"""Text built for the GUI's summary and integrity panels, the table columns
(hidden/leading/trailing keys) and the About box.

Pure functions and constants (no Tk), moved out of ``app/gui.py`` unchanged;
``app.gui`` re-exports every name, so callers and tests that use
``app.gui.<name>`` are unaffected.
"""

from app import ui_text
from app.i18n import _
from core.utils import report_format
from core.utils.report_format import visible_columns
from core.utils.version import APP_NAME, __version__


# Internal keys to hide from columns (service noise). Keys starting with "_"
# (e.g. "_key" dedup markers) are always hidden — see _columns_for.
# ``record_type`` is the file's internal record code: of no use on screen, it is
# kept for the exports, where it sits next to the section title.
HIDDEN_KEYS = {"source", "raw_tail_hex", "name", "size", "confidence", "record_type",
               # Same conformance bookkeeping report_format.HIDDEN_KEYS hides:
               # the verdict lives in the JSON, the table keeps its columns.
               "normative", "spec_reference", "conformance_reason",
               "low_confidence_fields", "end_semantics",
               "manufacturer_error_code",
               "event_fault_version", "type_status", "manufacturer_status",
               # VuCardIWRecord tail: previous vehicle, numeric manual-input
               # flag and completeness bookkeeping stay in the JSON; the table
               # layout is the owner's and did not change (a visible column
               # would also need a translated label in all 33 catalogs).
               "previous_vehicle", "manual_input_flag",
               "manual_input_flag_meaning", "record_bytes", "record_complete",
               "missing_bytes", "raw_tail_bytes",
               # CardSlotsStatus complete typing (numeric nibble + assignment
               # status): JSON only, the table keeps its existing columns.
               "driver_slot_code", "codriver_slot_code",
               "driver_slot_type", "codriver_slot_type",
               "driver_slot_status", "codriver_slot_status",
               # EntryTypeDailyWorkPeriod assignment status (assigned / not
               # assigned for generation 1 / unknown above the shared six).
               "entry_type_status", "calibration_variant_source",
               "digital_map_version_raw",
               # Technical-data detail: ExtendedSerialNumber / seal subfields,
               # the CardStructureVersion halves, the calibration variant and
               # the unresolved-encoding statuses stay in the JSON export only.
               "card_serial", "card_structure_version_parts",
               "equipment_type_status",
               "month_year_status", "seal_identifier", "calibration_variant",
               "digital_map_version_status", "consent_status", "consent_raw"}


# Descriptive columns pushed to table start.
# Bookkeeping of the all-TREP decoding pass (status/provenance/diagnostics):
# the shared set, so the window hides exactly what the exports hide.
HIDDEN_KEYS |= set(report_format.BOOKKEEPING_KEYS)


LEADING_KEYS = ["description", "purpose", "control_type_label", "calibration_purpose_label"]


# Technical columns pushed to table end.
TRAILING_KEYS: list[str] = []


def _bool_text(value):
    """A boolean as the word the UI shows: a cell, so the tick decides."""
    if ui_text.translate_data_enabled():
        return _("Yes") if value else _("No")
    return "Yes" if value else "No"


def technical_columns(keys):
    """The columns of a record that repeat, in machine form, what another one says.

    They stay in the record (the JSON and the exports keep everything) and in
    the table behind its *Technical columns* switch, but a reader does not need
    them to read the row:

    * ``*_raw`` / ``*_hex`` — the undecoded value next to its decoded form
      (``odometer_raw`` next to ``odometer_km``, ``timestamp_raw`` next to
      ``timestamp``, ``sensor_serial_hex`` next to ``sensor_serial``);
    * ``X`` when ``X_label`` or ``X_description`` is there (the numeric
      ``calibration_purpose`` next to ``calibration_purpose_label``);
    * ``*_code`` when the record already says it in words: its stem
      (``manufacturer_code`` → ``manufacturer``), a label, or a description
      (``event_type_code`` → ``description``, ``type_code`` →
      ``entry_type_description``).

    A code with no words beside it is the only form of that fact, so it stays.
    """
    keys = [str(k) for k in keys]
    present = set(keys)
    worded = ("description" in present
              or any(k.endswith(("_description", "_label")) for k in present))
    technical = []
    for key in keys:
        if key.endswith(("_raw", "_hex")):
            technical.append(key)
        elif f"{key}_label" in present or f"{key}_description" in present:
            technical.append(key)
        elif key in ("fault_type", "event_type") and worded:
            # The numeric type of a record whose description spells it out.
            technical.append(key)
        elif key.endswith("_code"):
            stem = key[:-len("_code")]
            if stem in present or worded:
                technical.append(key)
    return technical


def _columns_for(records, transformer):
    """Derive column order from the union of record keys.

    Technical columns (:func:`technical_columns`) come last, so a table that
    hides them keeps every other column where it was.
    """
    if transformer:
        sample = transformer(records[0])
        if isinstance(sample, list):
            sample = sample[0]
        return list(sample.keys())
    # Reversed leading keys preserve this view's historical front-insertion
    # order while the shared helper performs visibility filtering.
    cols = visible_columns(
        records,
        hidden_keys=HIDDEN_KEYS,
        leading_keys=tuple(reversed(LEADING_KEYS)),
        trailing_keys=TRAILING_KEYS,
        value_column_for_non_dict=True,
    )
    technical = set(technical_columns(cols))
    return [c for c in cols if c not in technical] + [c for c in cols if c in technical]


class Columns(list):
    """Table headers that also name which of them are technical.

    A plain list everywhere a list is expected (payloads, tests, the CSV-like
    copy); :class:`app.gui_base.DataTable` reads ``technical`` to decide what
    its *Technical columns* switch shows and hides.
    """

    def __init__(self, headers, technical=()):
        super().__init__(headers)
        self.technical = frozenset(technical)


def _summary_block(rows):
    """Return the first block of a ``(label, value, is_header)`` summary page.

    ``_build_driver_summary`` and ``_build_vehicle_summary`` each build a whole
    panel of stacked blocks separated by blank ``("", "", True)`` rows. The
    file overview reuses one block of each (the identity, the vehicle) by
    calling the builder and taking its leading block, so the two pages can
    never disagree about the same facts.
    """
    block = []
    for index, row in enumerate(rows):
        if index and row[2]:
            break  # a separator row or the next block header ends the block
        block.append(row)
    return block


def _drop_empty_values(rows):
    """Drop the ``N/A`` rows of a borrowed block, keeping headers.

    The section builders emit a handful of rows unconditionally, with the
    model's ``"N/A"`` sentinel (``core/registry/models.py``) as the value. On a
    section page that reads as "we looked and found nothing"; in a one-page
    overview it is noise, so an unknown fact is simply not listed.
    """
    return [row for row in rows
            if row[2] or str(row[1]).strip() not in ("", "N/A")]


#: Informational bullet for a card image relayed through the vehicle unit. It is a
#: NOTE, never a damage claim: the file is the standard card plus the transfer header
#: the saving tool kept (SID 0x76 + TREP 06), which DDP_050 strips for the storage
#: form. Other programs reject that form, so the customer is told what it is.
CARD_ENVELOPE_NOTICE = _(
    "Card image downloaded through the vehicle unit: the two leading bytes "
    "are the transfer header (SID + TREP 06) kept by the tool that saved it, not the "
    "standard storage form of a card file (DDP_050). Some other programs report such "
    "a file as corrupt; this reader reports the card's own signature verdict "
    "separately.")


def _envelope_notice(data):
    """The informational bullet for a stand-alone TREP 06 envelope, or None."""
    meta = (data or {}).get("metadata") or {}
    envelope = meta.get("envelope")
    if not isinstance(envelope, dict):
        return None
    if meta.get("is_vu") is not False:
        return None
    return "\u2022 " + CARD_ENVELOPE_NOTICE


#: Informational bullet for a card file whose opening record is not the record a
#: standard download starts with (``metadata["header_form"]``). Like the envelope
#: note it describes the file's FORM and hands the trust question to the count in
#: the note itself: a file altered at its header may still carry every signed EF
#: untouched, so the note must never read as a clean bill of health.
CARD_HEADER_NOTICE = _(
    "File header differs from a standard download: the first record is {tag}, "
    "where a card download starts with the card's identification record "
    "(0x0002 or 0x0005 for a G1 card, 0x0101 for a G2 card).")


def _signature_verdict_clause(data):
    """How many card-data signatures could not be verified, as one sentence.

    Counts come from the verification report itself (``failed`` + ``skipped`` of
    ``total``), so a file whose signatures all verified says "0 of N" instead of
    borrowing a reassuring word, and one with no report at all says exactly that.
    """
    efv = (data or {}).get("ef_signature_verification") or {}
    total = int(efv.get("total") or 0)
    if not total:
        return _("No EF signatures verified")
    unverified = int(efv.get("failed") or 0) + int(efv.get("skipped") or 0)
    return _("{unverified} of {total} signature(s) could not be verified").format(
        unverified=unverified, total=total)


def _header_notice(data):
    """The informational bullet for a non-standard card header, or None."""
    meta = (data or {}).get("metadata") or {}
    header = meta.get("header_form")
    if not isinstance(header, dict) or not header.get("first_record"):
        return None
    if meta.get("is_vu") is not False:
        return None
    return "\u2022 {} {}.".format(
        CARD_HEADER_NOTICE.format(tag=header["first_record"]),
        _signature_verdict_clause(data))


def _integrity_bullets(data):
    """``(bullets, notices)`` for *data* without a GUI instance.

    *bullets* is what ``_check_integrity`` shows (real warnings plus the
    informational envelope notice); *notices* is the subset that is a fact about
    the file's form rather than a problem, so a caller can keep the banner honest.
    """
    meta = (data or {}).get("metadata") or {}
    efv = (data or {}).get("ef_signature_verification") or {}
    integrity = str(meta.get("integrity_check") or "")
    warnings = []
    failed = int(efv.get("failed") or 0)
    skipped = int(efv.get("skipped") or 0)
    if failed:
        warnings.append(f"\u2022 EF data signatures: {failed} failed verification")
    if skipped:
        warnings.append(
            f"\u2022 Card data signatures: {skipped} EF signature(s) not checked")
    if (meta.get("is_vu") is not True and not failed and not skipped
            and "Verified" not in integrity and integrity):
        warnings.append(f"\u2022 Card integrity: {integrity}")
    # Structure findings: the walk may have consumed every byte, so the reason is
    # the section's array list — name it instead of blaming the walk.
    findings = meta.get("vu_integrity") or []
    schema_findings = [f for f in findings if f.get("status") == "schema_violation"]
    if schema_findings:
        details = "; ".join(
            f"{f.get('trep', '?')}: {f.get('detail', '')}".strip()
            for f in schema_findings)
        warnings.append("\u2022 Section structure (schema violation): " + details)
    truncated = [f for f in findings
                 if f.get("status") in ("trailing_bytes", "array_truncated",
                                        "card_download_incomplete")]
    trep = meta.get("trep_report") or {}
    if truncated or (not trep.get("complete_walk", True) and not schema_findings):
        warnings.append("\u2022 The structural walk did not reach the end of file")
    # Form notes, never problems: a card image relayed through the vehicle unit,
    # and a card whose header is not the record a standard download opens with.
    notices = [note for note in (_envelope_notice(data), _header_notice(data)) if note]
    return warnings + notices, notices


#: The project's public address.
PROJECT_URL = "https://github.com/Syax89/DDDTachograph_Reader"


#: The donation link the project already publishes (README.md).
DONATION_URL = "https://buymeacoffee.com/syax89"


def help_links():
    """``(label, url)`` for every address the Help entries open.

    The one source of both entry points: the macOS Help menu and the
    Windows/Linux Help dialog render this list. The labels are msgids and are
    translated at call time, so a language switch reaches them too.
    """
    return (
        (_("DDD Reader on GitHub"), PROJECT_URL),
        (_("Report an issue"), f"{PROJECT_URL}/issues"),
        (_("Releases"), f"{PROJECT_URL}/releases"),
        (_("Buy me a coffee"), DONATION_URL),
    )


def about_text():
    """The About body: name, version, licence and credits.

    Shown by the Help dialog and by the macOS About panel, which is the same
    text: the application menu's "About" item calls the Tcl command published in
    :meth:`TachoExplorer._install_macos_help_menu`.
    """
    return "\n".join((
        _("{app} version {version}").format(app=APP_NAME, version=__version__),
        _("An open-source reader for digital tachograph (.ddd) files: card and "
          "vehicle-unit downloads, parsed, signature-checked and exportable."),
        _("License: MIT"),
        _("Credits: the field layouts and the cryptographic checks follow "
          "Commission Regulation (EU) 2016/799 (Annex 1C), Regulation (EEC) "
          "3821/85 (Annex 1B) and Regulations (EU) 2021/1228 and 2023/980."),
    ))

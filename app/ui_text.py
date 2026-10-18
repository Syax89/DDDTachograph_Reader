"""The one display-text layer: every readable label is mapped here.

The GUI builds its tree and tables from three different kinds of text, and only
the first of them used to be translatable:

1. literals written in ``app/gui.py`` (wrapped in ``_()`` — translated);
2. raw ``CamelCase`` section names straight out of the registry
   (`core/registry/models.py`: ``CalibrationData``, ``EventsData``,
   ``VU_TechnicalInfo``, ``CalibrationVINs`` …);
3. ``snake_case`` record keys run through
   :func:`core.utils.report_format.humanize_key`, which produces English
   headers (``Card Number``, ``Begin Time``, ``Manufacturer`` …) that never
   passed through ``_()``.

Layers 2 and 3 leaked English identifiers into every translated UI: an Italian
user read ``CalibrationData`` in the tree and ``Card Driver Begin`` above the
events table. :func:`humanize` turns any of those keys into a space separated
English label and :func:`label` translates it, so there is exactly one place
that decides what a label reads like — and one place to teach a new key.

English is the msgid, so a label with no catalog entry falls back to English
and the UI is never half-empty (see :mod:`app.i18n`).

A second, orthogonal decision is *what kind* of text is being shown. The
application's chrome (menus, column headers it owns, messages) is always
translated, but a value decoded from the tachograph file — the activity of a
record (``Drive``), a nation (``Italy``), a record-type name — is evidence
from the file, and some users need to see it exactly as the file names it.
:func:`configure_translate_data` holds that preference (off by default) and
:func:`data_text` is the only place it is applied, so the choice is one cached
flag read per rendered cell instead of a settings-file read per cell.
"""
import re

from app.i18n import _
from core.utils.report_format import humanize_key

__all__ = ["humanize", "label", "data_text", "configure_translate_data",
           "translate_data_enabled"]

#: Whether labels decoded from the file are translated. Cached on purpose: the
#: GUI renders one cell at a time and must never touch the settings file there.
_translate_data = False

#: One CamelCase token: a plural acronym (``VINs``, ``IDs``), an uppercase run
#: (``VU``, ``GNSS``), a Capitalised word (``Calibration``) or a digits run
#: (``22``, ``0``).  The plural acronym has to come first, or ``CalibrationVINs``
#: splits as ``Calibration VI Ns``.
_TOKEN_RE = re.compile(r"[A-Z]+s(?![a-z])|[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

#: A raw identifier: what a registry section name or a record key looks like.
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_]+")

#: A lowercase→uppercase pair — the only trace a CamelCase name leaves inside
#: text that is otherwise already display text (``VU RecordArray Summary``).
_CAMEL_BOUNDARY_RE = re.compile(r"[a-z0-9][A-Z]")

#: One whitespace-delimited word of an already-display-text label.
_WORD_RE = re.compile(r"\S+")


def _word(token: str) -> str:
    """Humanise one CamelCase token, keeping acronyms intact.

    ``humanize_key`` handles the snake_case word and the acronyms it knows
    (``vin`` → ``VIN``); the two cases it cannot see are a *plural* acronym
    (its ``capitalize()`` would give ``Vins``) and an acronym missing from its
    table (``DAC`` → ``Dac``), so both are preserved here.
    """
    if len(token) > 1 and token.endswith("s") and _is_acronym(token[:-1]):
        return _word(token[:-1]) + "s"
    if len(token) > 1 and token.isupper():
        return token
    return humanize_key(token)


def _is_acronym(token: str) -> bool:
    """True when *token* is an acronym — as written, or as ``humanize_key`` knows it.

    Mirrors ``core.utils.report_format._ACRONYMS`` through the public helper:
    ``humanize_key`` upper-cases exactly the words in that table, so a word it
    returns in capitals is an acronym (``id`` → ``ID``).
    """
    return token.isupper() or (len(token) > 1 and humanize_key(token) == token.upper())


def _identifier_label(key: str) -> str:
    """``card_driver_begin``/``CalibrationData`` → ``Card Driver Begin``/…"""
    words = [_word(token)
             for segment in key.split("_")
             for token in _TOKEN_RE.findall(segment)]
    return " ".join(words) if words else str(key)


def _camel_word(match: "re.Match[str]") -> str:
    """Split the CamelCase words of a label that is already display text."""
    word = match.group(0)
    if _IDENTIFIER_RE.fullmatch(word) and _CAMEL_BOUNDARY_RE.search(word):
        return _identifier_label(word)
    return word


def humanize(key) -> str:
    """Map a raw key to a space separated English label; never raise.

    CamelCase and snake_case keys are split into words and capitalised
    (``CalibrationVINs`` → ``Calibration VINs``, ``card_number`` → ``Card
    Number``).  A key that is already display text — ``Daily Activities``, or a
    label a catalog already translated — is returned as it is, so this layer is
    idempotent and can be put in front of an already-translated string.
    Non-string and empty keys fall back to ``str(key)``.
    """
    if not isinstance(key, str) or not key:
        return str(key)
    if _IDENTIFIER_RE.fullmatch(key):
        return _identifier_label(key)
    return _WORD_RE.sub(_camel_word, key)


def label(key) -> str:
    """The translated label for *key*: the only entry point the GUI needs."""
    return _(humanize(key))


def configure_translate_data(flag) -> None:
    """Set whether labels decoded from the file are translated.

    Called once when the window starts and again from the Language menu; the
    value is cached in this module so the render path never reads the settings
    file. Only the JSON boolean ``True`` means on (see
    :func:`app.i18n.saved_translate_data`).
    """
    global _translate_data
    _translate_data = flag is True


def translate_data_enabled() -> bool:
    """The cached preference (``True`` when file-decoded labels are translated)."""
    return _translate_data


def data_text(text):
    """Translate a label that was decoded *from the file*, when the user asked.

    With the preference off — the default — the text is returned unchanged, so
    a record reads exactly as the file/decoder names it (``Drive``, ``Rest``,
    ``Italy``). With it on, the text goes through the same catalog as the rest
    of the UI (``Guida``, ``Riposo``, ``Italia``). Non-string values pass
    through untouched in both cases, so a caller may wrap any cell value.
    """
    if not _translate_data or not isinstance(text, str):
        return text
    return _(text)

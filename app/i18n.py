"""UI localization (gettext).

Every user-visible string is wrapped in ``_()``; the English text is the msgid,
so any string missing from a catalog falls back to English and the app is never
half-empty. A language is added by dropping ``locale/<code>/LC_MESSAGES/
tacho.po`` in the source tree and compiling it with
``python3 scripts/compile_translations.py`` (see CONTRIBUTING.md).

The chosen language is stored in the per-user settings file (same file future
preferences should share) and applied at startup by :func:`install`. English is
the default and is never inferred from the OS locale: a fresh install starts in
English, and only an explicit choice in the Language menu changes it.
"""
import gettext
import json
import os
import struct
import sys
import tempfile

DOMAIN = "tacho"
DEFAULT_LANGUAGE = "en"
_ENGLISH = "English"

#: Settings key of the "translate file contents" preference. It decides whether
#: text *decoded from the tachograph file* (activity names, nations, record
#: labels) is translated. The application's own chrome is translated either
#: way, so this is a separate, deliberately opt-in choice: the default keeps
#: every file-derived label exactly as the file/decoder names it.
TRANSLATE_DATA_KEY = "translate_file_content"

#: Language code -> name shown in the Language menu, in menu order.
#:
#: Every name is written in its own language ("native name"), so a user who
#: cannot read the current UI language can still find their own. English comes
#: first because it is the default and the msgid language of every catalog.
#: Only codes listed here are ever loaded; anything else falls back to English.
LANGUAGES = {
    "en": _ENGLISH,
    "it": "Italiano",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "pt": "Português",
    "nl": "Nederlands",
    "pl": "Polski",
    "ro": "Română",
    "bg": "Български",
    "cs": "Čeština",
    "sk": "Slovenčina",
    "hu": "Magyar",
    "hr": "Hrvatski",
    "sl": "Slovenščina",
    "el": "Ελληνικά",
    "da": "Dansk",
    "sv": "Svenska",
    "fi": "Suomi",
    "et": "Eesti",
    "lv": "Latviešu",
    "lt": "Lietuvių",
    "ga": "Gaeilge",
    "mt": "Malti",
    "nb": "Norsk bokmål",
    "is": "Íslenska",
    "ru": "Русский",
    "uk": "Українська",
    "be": "Беларуская",
    "tr": "Türkçe",
    "sr": "Српски",
    "bs": "Bosanski",
    "sq": "Shqip",
    "mk": "Македонски",
}

#: Settings key of the recently opened files, most recent first.
RECENT_FILES_KEY = "recent_files"

#: How many recently opened files the settings file remembers.
RECENT_FILES_LIMIT = 8

#: A catalog that cannot be read must degrade to English, never to a crash, so
#: every parse/decoding failure of ``gettext`` is treated the same way. The
#: concrete types are what ``GNUTranslations._parse`` raises on a truncated or
#: garbled ``.mo`` (bad magic -> OSError, short header -> struct.error, mangled
#: strings -> UnicodeDecodeError/ValueError).
_CATALOG_ERRORS = (OSError, EOFError, ValueError, IndexError, struct.error)

_translation: gettext.NullTranslations = gettext.NullTranslations()


def locale_dir():
    """Directory holding ``<lang>/LC_MESSAGES/tacho.mo`` (bundle root when frozen)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "locale")


def settings_path():
    """Per-user settings file, in the platform's conventional location."""
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        root = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "TachoReader", "settings.json")


def _read_settings():
    """Return the settings mapping; a missing/corrupt/non-object file is empty."""
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_settings(settings):
    """Atomically replace the settings file; ``False`` when that is impossible.

    The new content is written to a temporary file in the same directory and
    handed to ``os.replace`` only once it is complete: an interrupted or failing
    write leaves the previous settings file exactly as it was (never truncated,
    never half-written).
    """
    path = settings_path()
    tmp_path = None
    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return True


def saved_language():
    """The language picked in the menu, or English when unset/unknown.

    The stored value comes from a user-editable file, so it can be anything at
    all (``null``, a number, a list). Only a known language *code* is honoured;
    everything else — including unhashable values that would raise on a plain
    ``in LANGUAGES`` lookup — falls back to English.
    """
    lang = _read_settings().get("language")
    if isinstance(lang, str) and lang in LANGUAGES:
        return lang
    return DEFAULT_LANGUAGE


def save_language(lang):
    """Persist ``lang``; returns False when it is unknown or cannot be written.

    Keys other than ``language`` are preserved, so this can share the settings
    file with other preferences.
    """
    if not isinstance(lang, str) or lang not in LANGUAGES:
        return False
    settings = _read_settings()
    settings["language"] = lang
    return _write_settings(settings)


def saved_translate_data():
    """Whether file-decoded labels should be translated (default ``False``).

    The settings file is user-editable, so the stored value can be anything.
    Only the JSON boolean ``true`` turns the preference on; a missing key, a
    string (``"yes"``), a number (``1``) or ``null`` all mean off. ``is True``
    is what enforces that: ``1 == True`` in Python, but ``1 is True`` is False.
    """
    return _read_settings().get(TRANSLATE_DATA_KEY) is True


def save_translate_data(flag):
    """Persist the "translate file contents" preference; ``False`` on failure.

    Only a real ``bool`` is accepted — storing ``"yes"`` or ``1`` would be a
    value :func:`saved_translate_data` then has to guess about. Keys other than
    the preference are preserved, so this shares the settings file with the
    language choice.
    """
    if not isinstance(flag, bool):
        return False
    settings = _read_settings()
    settings[TRANSLATE_DATA_KEY] = flag
    return _write_settings(settings)


def saved_recent_files():
    """The recently opened files, most recent first (``[]`` when unknown).

    A pure read: it never touches the file system beyond the settings file, so
    a path that has since been deleted or unmounted is still returned — hiding
    those is the GUI's decision, and forgetting them here would erase a history
    that a temporarily unavailable drive should get back.

    The settings file is user-editable, so the stored value can be anything: a
    non-list (``null``, a number, a string) means "no history", and inside a
    list every entry that is not a non-empty string is dropped individually
    instead of discarding the whole history. Duplicates are collapsed and the
    list is capped at :data:`RECENT_FILES_LIMIT`.
    """
    stored = _read_settings().get(RECENT_FILES_KEY)
    if not isinstance(stored, list):
        return []
    files = []
    for entry in stored:
        if not isinstance(entry, str) or not entry.strip():
            continue
        if entry not in files:
            files.append(entry)
        if len(files) >= RECENT_FILES_LIMIT:
            break
    return files


def add_recent_file(path):
    """Record ``path`` as the most recently opened file; ``False`` if not stored.

    The list is kept as absolute paths, newest first, without duplicates: a file
    opened twice moves to the top instead of appearing twice, and only the
    :data:`RECENT_FILES_LIMIT` most recent are kept. Everything else in the
    settings file is preserved, and a failed write returns ``False`` (the
    previous history is untouched) exactly like the sibling setters.
    """
    if not isinstance(path, str) or not path.strip():
        return False
    try:
        entry = os.path.abspath(path)
    except (OSError, TypeError, ValueError):
        return False
    kept = [other for other in saved_recent_files() if not _same_path(other, entry)]
    settings = _read_settings()
    settings[RECENT_FILES_KEY] = [entry] + kept[:RECENT_FILES_LIMIT - 1]
    return _write_settings(settings)


def _same_path(first, second):
    """Whether two stored paths point at the same file (best effort)."""
    try:
        return os.path.abspath(first) == os.path.abspath(second)
    except (OSError, TypeError, ValueError):
        return first == second


def install(lang):
    """Load the catalog for ``lang`` and return the selected language code.

    An unsupported code, a missing ``.mo`` or a corrupt one all resolve to
    English (``NullTranslations``) instead of raising: a bad catalog must never
    stop the application from starting.

    The return value is the *selected* language code, not a probe of whether the
    catalog loaded: a supported code whose catalog is unreadable still returns
    that code while the strings come out as English msgids (the existing
    behaviour ``test_i18n.py`` pins). A build ships every catalog compiled, so
    the two only differ for a damaged bundle.
    """
    global _translation
    if not isinstance(lang, str) or lang not in LANGUAGES:
        lang = DEFAULT_LANGUAGE
    translation: gettext.NullTranslations = gettext.NullTranslations()
    if lang != DEFAULT_LANGUAGE:
        try:
            translation = gettext.translation(
                DOMAIN, locale_dir(), languages=[lang], fallback=True)
        except _CATALOG_ERRORS:
            translation = gettext.NullTranslations()
    _translation = translation
    return lang


def _(message):
    """Translate ``message`` (the English source text)."""
    return _translation.gettext(message)

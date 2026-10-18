"""The recent-files history kept in the per-user settings file.

``saved_recent_files``/``add_recent_file`` share ``settings.json`` with the
language preference, so they inherit the same contract as their siblings: a
user-editable file may hold *anything* (``null``, numbers, nested lists), a
failed write must report itself instead of raising, and unrelated keys must
survive. Nothing here touches the real user's settings file: ``conftest.py``
already redirects ``app.i18n.settings_path`` to a per-test temporary path, and
every test below asserts that redirection really is in place.
"""
import json
import os
from pathlib import Path

import pytest

import app.i18n as i18n


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Point ``app.i18n`` at a temporary settings file and return its path."""
    path = tmp_path / "TachoReader" / "settings.json"
    monkeypatch.setattr(i18n, "settings_path", lambda: str(path))
    return path


def _write_raw(path, payload):
    """Put ``payload`` in the settings file exactly as a user could."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                    encoding="utf-8")


def _read_raw(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── reading ────────────────────────────────────────────────────────────────

def test_empty_history_by_default(settings):
    assert i18n.saved_recent_files() == []
    assert not settings.exists(), "reading must not create the settings file"


def test_missing_or_corrupt_settings_means_no_history(settings):
    _write_raw(settings, "{not json")
    assert i18n.saved_recent_files() == []


@pytest.mark.parametrize("payload", [None, 42, "a string", True, {}, [], [[]]])
def test_hostile_stored_values_yield_no_history(settings, payload):
    _write_raw(settings, {"recent_files": payload})
    assert i18n.saved_recent_files() == []


def test_non_string_entries_are_dropped_one_by_one(settings):
    """One bad entry must not throw the whole history away."""
    _write_raw(settings, {"recent_files": [
        "/data/a.ddd", None, 7, ["/data/b.ddd"], {"path": "/data/c.ddd"},
        "", "   ", "/data/d.ddd",
    ]})
    assert i18n.saved_recent_files() == ["/data/a.ddd", "/data/d.ddd"]


def test_duplicates_collapse_keeping_the_newest_position(settings):
    _write_raw(settings, {"recent_files": ["/a.ddd", "/b.ddd", "/a.ddd"]})
    assert i18n.saved_recent_files() == ["/a.ddd", "/b.ddd"]


def test_order_and_cap(settings):
    entries = [f"/data/file{index}.ddd" for index in range(12)]
    _write_raw(settings, {"recent_files": entries})
    assert i18n.saved_recent_files() == entries[:i18n.RECENT_FILES_LIMIT]
    assert i18n.RECENT_FILES_LIMIT == 8


def test_reading_does_not_check_existence(settings):
    """Pure read: a vanished file stays in the history."""
    _write_raw(settings, {"recent_files": ["/nowhere/missing.ddd"]})
    assert i18n.saved_recent_files() == ["/nowhere/missing.ddd"]


# ── writing ────────────────────────────────────────────────────────────────

def test_newest_file_comes_first(settings):
    assert i18n.add_recent_file("/data/first.ddd")
    assert i18n.add_recent_file("/data/second.ddd")
    assert i18n.saved_recent_files() == ["/data/second.ddd", "/data/first.ddd"]
    assert _read_raw(settings)[i18n.RECENT_FILES_KEY] == [
        "/data/second.ddd", "/data/first.ddd"]


def test_reopening_moves_a_file_to_the_top_without_duplicating_it(settings):
    for name in ("a", "b", "c"):
        assert i18n.add_recent_file(f"/data/{name}.ddd")
    assert i18n.add_recent_file("/data/a.ddd")
    assert i18n.saved_recent_files() == [
        "/data/a.ddd", "/data/c.ddd", "/data/b.ddd"]


def test_history_is_capped_and_drops_the_oldest(settings):
    for index in range(12):
        assert i18n.add_recent_file(f"/data/file{index}.ddd")
    stored = i18n.saved_recent_files()
    assert len(stored) == i18n.RECENT_FILES_LIMIT
    assert stored[0] == "/data/file11.ddd"
    assert stored[-1] == "/data/file4.ddd"


def test_paths_are_stored_absolute(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "download.ddd").write_bytes(b"\x00")
    assert i18n.add_recent_file("download.ddd")
    assert i18n.saved_recent_files() == [str(tmp_path / "download.ddd")]


def test_relative_and_absolute_spellings_are_the_same_entry(settings, tmp_path,
                                                           monkeypatch):
    target = tmp_path / "same.ddd"
    target.write_bytes(b"\x00")
    assert i18n.add_recent_file(str(target))
    monkeypatch.chdir(tmp_path)
    assert i18n.add_recent_file("same.ddd")
    assert i18n.saved_recent_files() == [str(target)]


def test_other_settings_keys_are_preserved(settings):
    _write_raw(settings, {"language": "it", "translate_file_content": True,
                          i18n.RECENT_FILES_KEY: ["/data/old.ddd"],
                          "future_key": {"nested": 1}})
    assert i18n.add_recent_file("/data/new.ddd")
    assert _read_raw(settings) == {
        "language": "it",
        "translate_file_content": True,
        i18n.RECENT_FILES_KEY: ["/data/new.ddd", "/data/old.ddd"],
        "future_key": {"nested": 1},
    }


@pytest.mark.parametrize("bad", [None, 5, [], {}, True, "", "   "])
def test_rejects_anything_but_a_path(settings, bad):
    assert i18n.add_recent_file(bad) is False
    assert not settings.exists(), "a rejected path must not create the file"


def test_added_file_does_not_disturb_the_language_choice(settings):
    assert i18n.save_language("de")
    assert i18n.add_recent_file("/data/a.ddd")
    assert i18n.saved_language() == "de"
    assert i18n.saved_recent_files() == ["/data/a.ddd"]


# ── failure handling ───────────────────────────────────────────────────────

def test_unwritable_settings_location_is_reported_not_raised(tmp_path, monkeypatch):
    """A settings file that cannot be written must return False, not raise."""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    path = blocker / "TachoReader" / "settings.json"
    monkeypatch.setattr(i18n, "settings_path", lambda: str(path))

    assert i18n.add_recent_file("/data/a.ddd") is False
    assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_failed_write_keeps_the_previous_history(settings, monkeypatch):
    assert i18n.add_recent_file("/data/kept.ddd")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    assert i18n.add_recent_file("/data/lost.ddd") is False
    assert i18n.saved_recent_files() == [str(Path("/data/kept.ddd"))]

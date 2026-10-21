import logging

import pytest

import app.i18n as i18n_module
import core.utils.logger as logger_module
from core.registry.registry import DecoderRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    DecoderRegistry.reset_instance()
    yield
    DecoderRegistry.reset_instance()


@pytest.fixture(autouse=True)
def pump_mode(monkeypatch):
    """Pin the render pump to the events mode.

    ``app.gui._PUMP_USES_EVENTS`` follows the platform (macOS renders with
    ``update_idletasks`` only, see docs/developer/testing.md), so without this a macOS
    developer would run a different suite from CI. The tests that check the idle mode set
    the constant themselves, after this fixture.
    """
    try:
        import app.gui as gui
    except ImportError:                  # no tkinter at all: nothing to pin
        return
    monkeypatch.setattr(gui, "_PUMP_USES_EVENTS", True)


@pytest.fixture(autouse=True)
def isolate_translate_data():
    """Reset the "translate file contents" flag: it is process-global state."""
    import app.ui_text as ui_text
    ui_text.configure_translate_data(False)
    try:
        yield
    finally:
        ui_text.configure_translate_data(False)


@pytest.fixture
def translated_file_content():
    """Turn on translation of file-decoded labels (activity names, nations).

    Off is the product default: a test that asserts a *translated* activity
    label must ask for it explicitly, and this fixture proves the toggle works.
    """
    import app.ui_text as ui_text
    ui_text.configure_translate_data(True)
    try:
        yield
    finally:
        ui_text.configure_translate_data(False)


@pytest.fixture(autouse=True)
def isolate_i18n(tmp_path, monkeypatch):
    """Keep the process-global UI translator and the settings file per-test.

    Both are process-wide state: the translator is a module global in
    ``app.i18n`` and the settings file is the *user's* real preferences file.
    A test that installs a catalog (or that constructs the GUI, which calls
    ``install(saved_language())``) would otherwise leak a language into every
    later test, and would read — or overwrite — the real ``settings.json``.
    """
    monkeypatch.setattr(i18n_module, "settings_path",
                        lambda: str(tmp_path / "TachoReader" / "settings.json"))
    i18n_module.install(i18n_module.DEFAULT_LANGUAGE)
    try:
        yield
    finally:
        i18n_module.install(i18n_module.DEFAULT_LANGUAGE)


@pytest.fixture(autouse=True)
def isolate_logging():
    """Fully isolate process-global logging state around every test.

    Python's ``logging`` package keeps state that is shared by every module in
    the interpreter: the manager's global disable level (``logging.disable``)
    and the handlers/level/``propagate`` of the singleton returned by
    ``logging.getLogger("ddd_tacho")``. Left unchecked, a module that disables
    logging at import time or configures the shared logger silently starves
    *every other* test module of the records it asserts on — the classic
    "logger singleton leak" that made counter/``assertLogs``/``captured_logs``
    tests fail non-deterministically depending on collection order.

    This fixture restores both to a clean slate before and after each test, so
    ordering and multi-module runs (incl. CI's parallel Python matrix) can no
    longer leak logging state.
    """
    manager = logging.Logger.manager
    saved_disable = manager.disable
    logger_module.reset_logger()
    logging.disable(logging.NOTSET)
    try:
        yield
    finally:
        logger_module.reset_logger()
        logging.disable(saved_disable)

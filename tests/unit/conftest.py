import logging

import pytest

import core.utils.logger as logger_module
from core.registry.registry import DecoderRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    DecoderRegistry.reset_instance()
    yield
    DecoderRegistry.reset_instance()


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

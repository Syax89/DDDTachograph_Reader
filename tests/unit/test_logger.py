import logging

import pytest

import core.utils.logger as logger_module


def _remove_all_counting_handlers():
    ddd_logger = logging.getLogger("ddd_tacho")
    for h in list(ddd_logger.handlers):
        if isinstance(h, logger_module._CountingHandler):
            ddd_logger.removeHandler(h)


@pytest.fixture(autouse=True)
def reset_logger_singleton():
    _remove_all_counting_handlers()
    logger_module._logger = None
    logger_module._console_handler = None
    logger_module._counter = None
    yield
    _remove_all_counting_handlers()
    logger_module._logger = None
    logger_module._console_handler = None
    logger_module._counter = None


class TestCountingHandler:
    def test_counts_failure_messages(self):
        logger_module.get_logger()
        log = logging.getLogger("ddd_tacho")

        log.debug("decode F123 failed")
        log.debug("something failed")
        log.debug("not a match")
        log.debug("operation fail")

        assert logger_module.decoder_failure_count() == 3
        assert len(logger_module.decoder_failures()) == 3

    def test_reset_clears_counts(self):
        logger_module.get_logger()
        log = logging.getLogger("ddd_tacho")

        log.debug("decode failed")
        assert logger_module.decoder_failure_count() == 1

        logger_module.reset_decoder_failures()
        assert logger_module.decoder_failure_count() == 0
        assert logger_module.decoder_failures() == []


class TestCountingHandlerWithExternalHandler:
    def test_counter_works_when_external_handler_exists(self):
        ddd_logger = logging.getLogger("ddd_tacho")
        external_handler = logging.StreamHandler()
        external_handler.setLevel(logging.DEBUG)
        ddd_logger.addHandler(external_handler)

        try:
            logger_module.get_logger()
            log = logging.getLogger("ddd_tacho")

            log.debug("decode F999 failed")
            log.debug("external handler present failure")

            assert logger_module.decoder_failure_count() == 2
            assert len(logger_module.decoder_failures()) == 2
        finally:
            ddd_logger.removeHandler(external_handler)

    def test_counter_attached_only_once_with_external_handler(self):
        ddd_logger = logging.getLogger("ddd_tacho")
        external_handler = logging.StreamHandler()
        ddd_logger.addHandler(external_handler)

        try:
            logger_module.get_logger()
            counting_handlers = [
                h for h in ddd_logger.handlers
                if isinstance(h, logger_module._CountingHandler)
            ]
            assert len(counting_handlers) == 1
        finally:
            ddd_logger.removeHandler(external_handler)

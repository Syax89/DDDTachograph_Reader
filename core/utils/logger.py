"""Centralized logging configuration for DDD Tachograph Reader."""
import logging
import threading

_logger = None
_console_handler = None
_counter = None
_lock = threading.Lock()


class _CountingHandler(logging.Handler):
    """Counts decoder failure events without emitting them to the console.

    Decoder leaf functions report problems via ``logger.debug("... failed ...")``.
    Those events are otherwise invisible when the console level is WARNING. This
    handler always receives them (the logger is kept at DEBUG) and tallies the
    ones whose message signals a failure, so the parser can expose a
    ``decoder_failure_count`` metric regardless of console verbosity.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.failure_count = 0
        self.failures: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return
        if " fail" in message.lower() or message.lower().endswith("failed"):
            self.failure_count += 1
            if len(self.failures) < 500:
                self.failures.append(message)

    def reset(self) -> None:
        self.failure_count = 0
        self.failures.clear()


def get_logger(name: str = "ddd_tacho") -> logging.Logger:
    """Get or create the project logger.

    A single shared logger is returned regardless of *name*: callers pass
    ``__name__`` only by convention, but using it would label every record
    with whichever module happened to call first.
    """
    global _logger, _console_handler, _counter
    with _lock:
        if _logger is None:
            _logger = logging.getLogger("ddd_tacho")
            _counter = _CountingHandler()
            _has_external = bool(_logger.handlers)
            _logger.addHandler(_counter)
            _logger.setLevel(logging.DEBUG)
            _logger.propagate = False
            if not _has_external:
                _console_handler = logging.StreamHandler()
                _console_handler.setFormatter(logging.Formatter(
                    '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%H:%M:%S'
                ))
                _console_handler.setLevel(logging.WARNING)
                _logger.addHandler(_console_handler)
    return _logger


def set_level(level: int) -> None:
    """Set console verbosity. The logger stays at DEBUG so failures are counted."""
    get_logger()
    if _console_handler is not None:
        _console_handler.setLevel(level)


def enable_debug() -> None:
    """Enable debug output on the console."""
    set_level(logging.DEBUG)


def decoder_failure_count() -> int:
    """Number of decoder failure events recorded since the last reset."""
    get_logger()
    with _lock:
        return _counter.failure_count if _counter else 0


def decoder_failures() -> list:
    """Captured decoder failure messages (capped) since the last reset."""
    get_logger()
    with _lock:
        return list(_counter.failures) if _counter else []


def reset_decoder_failures() -> None:
    """Reset the decoder failure tally; call at the start of each parse."""
    get_logger()
    with _lock:
        if _counter is not None:
            _counter.reset()

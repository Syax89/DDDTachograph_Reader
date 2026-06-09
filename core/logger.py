"""Centralized logging configuration for DDD Tachograph Reader."""
import logging

_logger = None
_console_handler = None
_counter = None


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
    """Get or create the project logger."""
    global _logger, _console_handler, _counter
    if _logger is None:
        _logger = logging.getLogger(name)
        _counter = _CountingHandler()
        if not _logger.handlers:
            _console_handler = logging.StreamHandler()
            _console_handler.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%H:%M:%S'
            ))
            # Console stays quiet (WARNING+); the logger itself runs at DEBUG so
            # the counting handler always sees decoder failure events.
            _console_handler.setLevel(logging.WARNING)
            _logger.addHandler(_console_handler)
            _logger.addHandler(_counter)
            _logger.setLevel(logging.DEBUG)
            # The logger runs at DEBUG so the counter sees every failure event;
            # don't bubble those debug records up to the root handler (which would
            # flood the console), the project's own console handler gates output.
            _logger.propagate = False
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
    return _counter.failure_count if _counter else 0


def decoder_failures() -> list:
    """Captured decoder failure messages (capped) since the last reset."""
    get_logger()
    return list(_counter.failures) if _counter else []


def reset_decoder_failures() -> None:
    """Reset the decoder failure tally; call at the start of each parse."""
    get_logger()
    if _counter is not None:
        _counter.reset()

import signal
import sys
import threading
from types import FrameType

import structlog

from intakefold.logging import configure_logging
from intakefold.settings import ConfigurationError, load_settings

POLL_SECONDS = 1.0


def run() -> None:
    try:
        settings = load_settings()
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None

    configure_logging(settings.log_level)
    log = structlog.get_logger()
    stop = threading.Event()

    def request_stop(signum: int, _: FrameType | None) -> None:
        log.info("worker_stop_requested", signal=signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    if sys.platform == "win32":  # Windows has no real SIGTERM for other processes.
        signal.signal(signal.SIGBREAK, request_stop)

    log.info("worker_started")
    while not stop.wait(POLL_SECONDS):
        pass  # Jobs arrive in M2.
    log.info("worker_stopped")


if __name__ == "__main__":
    run()

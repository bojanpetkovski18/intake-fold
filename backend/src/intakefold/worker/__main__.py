import signal
import sys
import threading
from functools import partial
from types import FrameType

import structlog

from intakefold.clock import SystemClock
from intakefold.db.engine import build_engine
from intakefold.documents.storage import Storage
from intakefold.logging import configure_logging
from intakefold.settings import ConfigurationError, load_settings
from intakefold.worker.handlers import build_handlers, fail_documents_of_dead_jobs
from intakefold.worker.loop import Worker


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

    engine = build_engine(settings)
    clock = SystemClock()
    handlers = build_handlers(engine, Storage(settings.storage_dir), clock)
    log.info("worker_started")
    Worker(
        engine,
        handlers,
        clock=clock,
        on_job_dead=partial(fail_documents_of_dead_jobs, engine, clock),
    ).run(stop)
    engine.dispose()
    log.info("worker_stopped")


if __name__ == "__main__":
    run()

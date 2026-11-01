import os
import random
import socket
import threading
import uuid
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from datetime import timedelta

import structlog
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from intakefold.clock import Clock
from intakefold.db.models import JobStatus
from intakefold.jobs import queue
from intakefold.jobs.queue import ClaimedJob

log = structlog.get_logger()

Handler = Callable[[ClaimedJob], None]

DEFAULT_LEASE = timedelta(minutes=5)
DEFAULT_POLL_SECONDS = 1.0
RECLAIM_INTERVAL = timedelta(seconds=30)


class PermanentJobError(Exception):
    """Retrying cannot help. `code` is stored and displayed, so it holds no document content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Worker:
    def __init__(
        self,
        engine: Engine,
        handlers: Mapping[str, Handler],
        *,
        clock: Clock,
        rng: random.Random | None = None,
        lease: timedelta = DEFAULT_LEASE,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        on_job_dead: Callable[[], None] = lambda: None,
    ) -> None:
        self.engine = engine
        self.handlers = handlers
        self.clock = clock
        # Timing jitter, not security, so a seedable generator is the right kind.
        self.rng = rng or random.Random()  # noqa: S311
        self.lease = lease
        self.poll_seconds = poll_seconds
        self.on_job_dead = on_job_dead
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._next_reclaim = clock.now()

    def run(self, stop: threading.Event) -> None:
        """Runs until `stop` is set. A job in progress is finished, not abandoned."""
        while not stop.is_set():
            try:
                worked = self.run_once()
            except SQLAlchemyError as error:
                # The type only: the message of a connection error can contain the URL.
                log.warning("worker_database_error", error_type=type(error).__name__)
                worked = False
            if not worked:
                stop.wait(self.poll_seconds)

    def run_once(self) -> bool:
        self._reclaim_if_due()
        job = queue.claim(self.engine, self.worker_id, self.lease, self.clock)
        if job is None:
            return False
        structlog.contextvars.bind_contextvars(job_id=str(job.id), job_kind=job.kind)
        try:
            self._execute(job)
        finally:
            structlog.contextvars.unbind_contextvars("job_id", "job_kind")
        return True

    def _reclaim_if_due(self) -> None:
        now = self.clock.now()
        if now < self._next_reclaim:
            return
        self._next_reclaim = now + RECLAIM_INTERVAL
        reclaimed = queue.reclaim_expired(self.engine, self.clock)
        if reclaimed:
            log.warning("jobs_reclaimed", count=reclaimed)
            self.on_job_dead()

    def _execute(self, job: ClaimedJob) -> None:
        handler = self.handlers.get(job.kind)
        if handler is None:
            self._record_failure(job, "unknown_job_kind", retryable=False)
            return
        try:
            with self._heartbeat(job):
                handler(job)
        except PermanentJobError as error:
            self._record_failure(job, error.code, retryable=False)
        except Exception as error:
            log.exception("job_attempt_failed", attempt=job.attempts)
            # The type only: an exception's message may quote document content.
            self._record_failure(job, type(error).__name__, retryable=True)
        else:
            if queue.succeed(self.engine, job, self.clock):
                log.info("job_succeeded", attempt=job.attempts)
            else:
                log.warning("job_result_discarded", attempt=job.attempts)

    def _record_failure(self, job: ClaimedJob, error: str, *, retryable: bool) -> None:
        status = queue.fail(self.engine, job, error, self.clock, self.rng, retryable=retryable)
        log.warning("job_failed", attempt=job.attempts, error=error, status=status)
        if status == JobStatus.DEAD:
            self.on_job_dead()

    @contextmanager
    def _heartbeat(self, job: ClaimedJob) -> Generator[None]:
        finished = threading.Event()

        def beat() -> None:
            while not finished.wait(self.lease.total_seconds() / 3):
                try:
                    if not queue.heartbeat(self.engine, job, self.lease, self.clock):
                        log.warning("job_lease_lost", attempt=job.attempts)
                        return
                except SQLAlchemyError as error:
                    log.warning("worker_database_error", error_type=type(error).__name__)

        thread = threading.Thread(target=beat, name="job-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            finished.set()
            thread.join()

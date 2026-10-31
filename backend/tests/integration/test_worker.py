import random
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.clock import Clock, SystemClock
from intakefold.db.models import Job, JobStatus
from intakefold.jobs import queue
from intakefold.jobs.queue import ClaimedJob
from intakefold.worker.loop import DEFAULT_LEASE, Handler, PermanentJobError, Worker

pytestmark = pytest.mark.integration


def add_job(engine: Engine, clock: Clock, kind: str = "work", key: str = "key") -> uuid.UUID:
    with Session(engine) as session, session.begin():
        return queue.enqueue(
            session, kind=kind, idempotency_key=key, payload={}, clock=clock, max_attempts=3
        ).job_id


def load(engine: Engine, job_id: uuid.UUID) -> Job:
    with Session(engine) as session:
        return session.get_one(Job, job_id)


def worker(
    engine: Engine, handlers: dict[str, Handler], clock: Clock, lease: timedelta = DEFAULT_LEASE
) -> Worker:
    return Worker(engine, handlers, clock=clock, rng=random.Random(3), lease=lease)  # noqa: S311


def test_idle_worker_reports_no_work(engine: Engine) -> None:
    assert not worker(engine, {}, FakeClock()).run_once()


def test_handler_runs_and_the_job_succeeds(engine: Engine) -> None:
    clock = FakeClock()
    job_id = add_job(engine, clock)
    seen: list[ClaimedJob] = []

    assert worker(engine, {"work": seen.append}, clock).run_once()

    assert [job.id for job in seen] == [job_id]
    assert load(engine, job_id).status is JobStatus.SUCCEEDED


def test_exception_retries_and_stores_only_its_type(engine: Engine) -> None:
    clock = FakeClock()
    job_id = add_job(engine, clock)

    def fail(_: ClaimedJob) -> None:
        raise ValueError("total on page 1 was 1,234.56")

    worker(engine, {"work": fail}, clock).run_once()

    row = load(engine, job_id)
    assert row.status is JobStatus.QUEUED
    assert row.last_error == "ValueError"


def test_permanent_error_goes_straight_to_dead(engine: Engine) -> None:
    clock = FakeClock()
    job_id = add_job(engine, clock)

    def fail(_: ClaimedJob) -> None:
        raise PermanentJobError("anthropic_authentication")

    worker(engine, {"work": fail}, clock).run_once()

    row = load(engine, job_id)
    assert row.status is JobStatus.DEAD
    assert row.last_error == "anthropic_authentication"


def test_unknown_kind_is_dead_not_retried(engine: Engine) -> None:
    clock = FakeClock()
    job_id = add_job(engine, clock, kind="mystery")

    worker(engine, {}, clock).run_once()

    row = load(engine, job_id)
    assert row.status is JobStatus.DEAD
    assert row.last_error == "unknown_job_kind"


def test_failing_job_ends_up_dead_through_real_retries(engine: Engine) -> None:
    clock = FakeClock()
    job_id = add_job(engine, clock)
    calls: list[int] = []

    def fail(job: ClaimedJob) -> None:
        calls.append(job.attempts)
        raise RuntimeError

    subject = worker(engine, {"work": fail}, clock)
    for _ in range(3):
        subject.run_once()
        clock.advance(timedelta(minutes=10))

    assert calls == [1, 2, 3]
    assert load(engine, job_id).status is JobStatus.DEAD
    assert not subject.run_once()


def test_heartbeat_keeps_a_long_job_leased(engine: Engine) -> None:
    clock = SystemClock()
    job_id = add_job(engine, clock)
    lease = timedelta(seconds=0.3)
    renewed = threading.Event()
    first_lease: list[object] = []

    def long_job(_: ClaimedJob) -> None:
        first_lease.append(load(engine, job_id).locked_until)
        deadline = time.monotonic() + 5
        while not renewed.wait(0.02) and time.monotonic() < deadline:
            if load(engine, job_id).locked_until != first_lease[0]:
                renewed.set()

    worker(engine, {"work": long_job}, clock, lease=lease).run_once()

    assert renewed.is_set()
    assert load(engine, job_id).status is JobStatus.SUCCEEDED


def test_finished_job_stops_its_heartbeat_thread(engine: Engine) -> None:
    clock = FakeClock()
    add_job(engine, clock)

    worker(engine, {"work": lambda _: None}, clock).run_once()

    assert not any(thread.name == "job-heartbeat" for thread in threading.enumerate())


def test_stop_finishes_the_current_job_then_exits(engine: Engine) -> None:
    clock = FakeClock()
    first = add_job(engine, clock, key="first")
    clock.advance(timedelta(seconds=1))
    second = add_job(engine, clock, key="second")
    stop = threading.Event()

    def stop_during_job(_: ClaimedJob) -> None:
        stop.set()

    worker(engine, {"work": stop_during_job}, clock).run(stop)

    assert load(engine, first).status is JobStatus.SUCCEEDED
    assert load(engine, second).status is JobStatus.QUEUED


def test_killed_worker_leaves_a_job_that_runs_again(database_url: str, engine: Engine) -> None:
    system_clock = SystemClock()
    job_id = add_job(engine, system_clock, kind="crash")
    crashing_worker = """
import os, sys
from sqlalchemy import create_engine
from intakefold.clock import SystemClock
from intakefold.worker.loop import Worker

def die(job):
    os._exit(9)

Worker(create_engine(sys.argv[1]), {"crash": die}, clock=SystemClock()).run_once()
"""

    result = subprocess.run(
        [sys.executable, "-c", crashing_worker, database_url],
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 9
    row = load(engine, job_id)
    assert row.status is JobStatus.RUNNING
    assert row.attempts == 1

    after_lease = FakeClock(system_clock.now() + DEFAULT_LEASE + timedelta(seconds=1))
    done: list[int] = []
    worker(engine, {"crash": lambda job: done.append(job.attempts)}, after_lease).run_once()

    assert done == [2]
    assert load(engine, job_id).status is JobStatus.SUCCEEDED


def test_worker_only_claims_due_jobs_in_order(engine: Engine) -> None:
    clock = FakeClock()
    first = add_job(engine, clock, key="first")
    clock.advance(timedelta(seconds=1))
    second = add_job(engine, clock, key="second")
    seen: list[uuid.UUID] = []

    subject = worker(engine, {"work": lambda job: seen.append(job.id)}, clock)
    subject.run_once()
    subject.run_once()

    assert seen == [first, second]
    with Session(engine) as session:
        assert session.scalars(select(Job.status).distinct()).all() == [JobStatus.SUCCEEDED]

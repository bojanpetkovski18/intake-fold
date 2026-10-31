import random
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from support import FakeClock

from intakefold.clock import SystemClock
from intakefold.db.models import Job, JobStatus
from intakefold.jobs import queue
from intakefold.jobs.queue import ClaimedJob

pytestmark = pytest.mark.integration

LEASE = timedelta(minutes=5)
WORKER = "worker-a"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def rng() -> random.Random:
    return random.Random(7)  # noqa: S311


def add_job(engine: Engine, clock: FakeClock, key: str = "key", max_attempts: int = 3) -> uuid.UUID:
    with Session(engine) as session, session.begin():
        return queue.enqueue(
            session,
            kind="test",
            idempotency_key=key,
            payload={"key": key},
            clock=clock,
            max_attempts=max_attempts,
        ).job_id


def load(engine: Engine, job_id: uuid.UUID) -> Job:
    with Session(engine) as session:
        return session.get_one(Job, job_id)


def claimed(engine: Engine, clock: FakeClock, worker: str = WORKER) -> ClaimedJob:
    job = queue.claim(engine, worker, LEASE, clock)
    assert job is not None
    return job


class TestEnqueue:
    def test_repeat_key_returns_the_same_job(self, engine: Engine, clock: FakeClock) -> None:
        with Session(engine) as session, session.begin():
            first = queue.enqueue(
                session, kind="test", idempotency_key="k", payload={"n": 1}, clock=clock
            )
            second = queue.enqueue(
                session, kind="test", idempotency_key="k", payload={"n": 2}, clock=clock
            )

        assert first.created
        assert not second.created
        assert first.job_id == second.job_id
        assert load(engine, first.job_id).payload == {"n": 1}

    def test_rolled_back_enqueue_leaves_no_job(self, engine: Engine, clock: FakeClock) -> None:
        with Session(engine) as session:
            queue.enqueue(session, kind="test", idempotency_key="k", payload={}, clock=clock)
            session.rollback()

        assert queue.claim(engine, WORKER, LEASE, clock) is None

    def test_concurrent_enqueue_creates_one_job(self, engine: Engine, clock: FakeClock) -> None:
        barrier = threading.Barrier(12)

        def enqueue_once(_: int) -> queue.Enqueued:
            barrier.wait()
            with Session(engine) as session, session.begin():
                return queue.enqueue(
                    session, kind="test", idempotency_key="k", payload={}, clock=clock
                )

        with ThreadPoolExecutor(12) as pool:
            results = list(pool.map(enqueue_once, range(12)))

        assert sum(result.created for result in results) == 1
        assert len({result.job_id for result in results}) == 1


class TestClaim:
    def test_claim_marks_the_job_running(self, engine: Engine, clock: FakeClock) -> None:
        job_id = add_job(engine, clock)

        job = claimed(engine, clock)

        row = load(engine, job_id)
        assert job.id == job_id
        assert job.attempts == 1
        assert row.status is JobStatus.RUNNING
        assert row.locked_by == WORKER
        assert row.locked_until == clock.now() + LEASE

    def test_empty_queue_returns_nothing(self, engine: Engine, clock: FakeClock) -> None:
        assert queue.claim(engine, WORKER, LEASE, clock) is None

    def test_oldest_due_job_goes_first(self, engine: Engine, clock: FakeClock) -> None:
        first = add_job(engine, clock, "first")
        clock.advance(timedelta(seconds=1))
        second = add_job(engine, clock, "second")

        assert claimed(engine, clock).id == first
        assert claimed(engine, clock).id == second

    def test_job_is_not_claimed_before_run_after(self, engine: Engine, clock: FakeClock) -> None:
        job_id = add_job(engine, clock)
        with engine.begin() as connection:
            connection.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(run_after=clock.now() + timedelta(minutes=1))
            )

        assert queue.claim(engine, WORKER, LEASE, clock) is None

    def test_many_workers_never_claim_the_same_job(self, engine: Engine, clock: FakeClock) -> None:
        job_count = 300
        worker_count = 16
        with Session(engine) as session, session.begin():
            for index in range(job_count):
                queue.enqueue(
                    session, kind="test", idempotency_key=str(index), payload={}, clock=clock
                )
        barrier = threading.Barrier(worker_count)

        def drain(worker: int) -> list[uuid.UUID]:
            barrier.wait()
            taken: list[uuid.UUID] = []
            while (job := queue.claim(engine, f"worker-{worker}", LEASE, clock)) is not None:
                taken.append(job.id)
            return taken

        with ThreadPoolExecutor(worker_count) as pool:
            results = list(pool.map(drain, range(worker_count)))

        taken = [job_id for result in results for job_id in result]
        assert len(taken) == job_count
        assert len(set(taken)) == job_count
        assert sum(bool(result) for result in results) > 1, "the workers did not actually race"

    def test_locked_row_is_skipped_not_waited_on(
        self, database_url: str, engine: Engine, clock: FakeClock
    ) -> None:
        first = add_job(engine, clock, "first")
        clock.advance(timedelta(seconds=1))
        second = add_job(engine, clock, "second")
        impatient = create_engine(
            make_url(database_url), connect_args={"options": "-c lock_timeout=2000"}
        )

        try:
            with engine.begin() as holder:
                holder.execute(select(Job.id).where(Job.id == first).with_for_update())
                job = queue.claim(impatient, WORKER, LEASE, clock)
        finally:
            impatient.dispose()

        assert job is not None
        assert job.id == second


class TestFinishing:
    def test_success_clears_the_lease(self, engine: Engine, clock: FakeClock) -> None:
        job_id = add_job(engine, clock)

        assert queue.succeed(engine, claimed(engine, clock), clock)

        row = load(engine, job_id)
        assert row.status is JobStatus.SUCCEEDED
        assert row.locked_by is None
        assert row.locked_until is None

    def test_failure_retries_after_backoff(
        self, engine: Engine, clock: FakeClock, rng: random.Random
    ) -> None:
        job_id = add_job(engine, clock)

        status = queue.fail(engine, claimed(engine, clock), "Boom", clock, rng)

        row = load(engine, job_id)
        assert status is JobStatus.QUEUED
        assert row.last_error == "Boom"
        assert row.locked_by is None
        assert clock.now() + timedelta(seconds=2.5) <= row.run_after
        assert row.run_after <= clock.now() + timedelta(seconds=5)
        assert queue.claim(engine, WORKER, LEASE, clock) is None

        clock.advance(timedelta(seconds=5))
        assert claimed(engine, clock).attempts == 2

    def test_job_is_dead_after_max_attempts(
        self, engine: Engine, clock: FakeClock, rng: random.Random
    ) -> None:
        job_id = add_job(engine, clock, max_attempts=3)
        statuses: list[JobStatus | None] = []

        for _ in range(3):
            statuses.append(queue.fail(engine, claimed(engine, clock), "Boom", clock, rng))
            clock.advance(timedelta(minutes=10))

        assert statuses == [JobStatus.QUEUED, JobStatus.QUEUED, JobStatus.DEAD]
        assert load(engine, job_id).status is JobStatus.DEAD
        assert queue.claim(engine, WORKER, LEASE, clock) is None

    def test_permanent_failure_is_dead_at_once(
        self, engine: Engine, clock: FakeClock, rng: random.Random
    ) -> None:
        job_id = add_job(engine, clock)

        queue.fail(engine, claimed(engine, clock), "bad", clock, rng, retryable=False)

        assert load(engine, job_id).status is JobStatus.DEAD

    def test_long_errors_are_cut_to_fit(
        self, engine: Engine, clock: FakeClock, rng: random.Random
    ) -> None:
        job_id = add_job(engine, clock)

        queue.fail(engine, claimed(engine, clock), "x" * 2000, clock, rng)

        assert len(load(engine, job_id).last_error or "") == queue.LAST_ERROR_LENGTH

    def test_dead_job_can_be_requeued_with_fresh_attempts(
        self, engine: Engine, clock: FakeClock, rng: random.Random
    ) -> None:
        job_id = add_job(engine, clock, max_attempts=1)
        queue.fail(engine, claimed(engine, clock), "Boom", clock, rng)

        assert queue.requeue(engine, job_id, clock)

        row = load(engine, job_id)
        assert row.status is JobStatus.QUEUED
        assert row.attempts == 0
        assert row.last_error is None
        assert claimed(engine, clock).id == job_id

    def test_only_dead_jobs_can_be_requeued(self, engine: Engine, clock: FakeClock) -> None:
        job_id = add_job(engine, clock)

        assert not queue.requeue(engine, job_id, clock)


class TestLeases:
    def test_heartbeat_extends_the_lease(self, engine: Engine, clock: FakeClock) -> None:
        job_id = add_job(engine, clock)
        job = claimed(engine, clock)
        clock.advance(timedelta(minutes=4))

        assert queue.heartbeat(engine, job, LEASE, clock)

        assert load(engine, job_id).locked_until == clock.now() + LEASE

    def test_live_lease_is_left_alone(self, engine: Engine, clock: FakeClock) -> None:
        add_job(engine, clock)
        claimed(engine, clock)
        clock.advance(LEASE - timedelta(seconds=1))

        assert queue.reclaim_expired(engine, clock) == 0

    def test_expired_lease_returns_the_job_to_the_queue(
        self, engine: Engine, clock: FakeClock
    ) -> None:
        job_id = add_job(engine, clock)
        claimed(engine, clock)
        clock.advance(LEASE + timedelta(seconds=1))

        assert queue.reclaim_expired(engine, clock) == 1

        row = load(engine, job_id)
        assert row.status is JobStatus.QUEUED
        assert row.last_error == "lease_expired"
        assert claimed(engine, clock, "worker-b").attempts == 2

    def test_expired_lease_on_the_last_attempt_is_dead(
        self, engine: Engine, clock: FakeClock
    ) -> None:
        job_id = add_job(engine, clock, max_attempts=1)
        claimed(engine, clock)
        clock.advance(LEASE + timedelta(seconds=1))

        queue.reclaim_expired(engine, clock)

        assert load(engine, job_id).status is JobStatus.DEAD

    def test_stale_worker_cannot_touch_a_reclaimed_job(
        self, engine: Engine, clock: FakeClock, rng: random.Random
    ) -> None:
        job_id = add_job(engine, clock)
        stale = claimed(engine, clock, "worker-a")
        clock.advance(LEASE + timedelta(seconds=1))
        queue.reclaim_expired(engine, clock)
        current = claimed(engine, clock, "worker-b")

        assert not queue.succeed(engine, stale, clock)
        assert queue.fail(engine, stale, "late", clock, rng) is None
        assert not queue.heartbeat(engine, stale, LEASE, clock)

        row = load(engine, job_id)
        assert row.status is JobStatus.RUNNING
        assert row.locked_by == current.worker_id

    def test_same_worker_reclaiming_is_fenced_by_attempt(
        self, engine: Engine, clock: FakeClock
    ) -> None:
        add_job(engine, clock)
        old = claimed(engine, clock, "worker-a")
        clock.advance(LEASE + timedelta(seconds=1))
        queue.reclaim_expired(engine, clock)
        claimed(engine, clock, "worker-a")

        assert not queue.succeed(engine, old, clock)

    def test_requeue_cannot_revive_a_stale_workers_attempt_number(
        self, engine: Engine, clock: FakeClock
    ) -> None:
        job_id = add_job(engine, clock, max_attempts=1)
        stale = claimed(engine, clock, "worker-a")
        clock.advance(LEASE + timedelta(seconds=1))
        queue.reclaim_expired(engine, clock)
        queue.requeue(engine, job_id, clock)
        current = claimed(engine, clock, "worker-b")
        assert current.attempts == stale.attempts

        assert not queue.succeed(engine, stale, clock)

        assert load(engine, job_id).status is JobStatus.RUNNING

    def test_two_reclaimers_count_each_job_once(self, engine: Engine) -> None:
        clock = SystemClock()
        fake = FakeClock(clock.now())
        for index in range(50):
            add_job(engine, fake, str(index))
        while queue.claim(engine, WORKER, LEASE, fake) is not None:
            pass
        fake.advance(LEASE + timedelta(seconds=1))
        barrier = threading.Barrier(6)

        def reclaim(_: int) -> int:
            barrier.wait()
            return queue.reclaim_expired(engine, fake)

        with ThreadPoolExecutor(6) as pool:
            counts = list(pool.map(reclaim, range(6)))

        assert sum(counts) == 50

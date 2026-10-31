import random
from datetime import timedelta

import pytest

from intakefold.jobs.queue import BACKOFF_MAX_SECONDS, backoff_delay


@pytest.mark.parametrize(
    ("attempt", "ceiling"),
    [(1, 5), (2, 10), (3, 20), (4, 40), (7, 300), (30, 300)],
)
def test_delay_stays_between_half_the_ceiling_and_the_ceiling(attempt: int, ceiling: int) -> None:
    rng = random.Random(1)  # noqa: S311

    delays = [backoff_delay(attempt, rng) for _ in range(200)]

    assert min(delays) >= timedelta(seconds=ceiling / 2)
    assert max(delays) <= timedelta(seconds=ceiling)


def test_delay_has_jitter() -> None:
    rng = random.Random(1)  # noqa: S311

    assert len({backoff_delay(3, rng) for _ in range(20)}) > 1


def test_large_attempt_numbers_do_not_overflow() -> None:
    delay = backoff_delay(1000, random.Random(1))  # noqa: S311

    assert delay <= timedelta(seconds=BACKOFF_MAX_SECONDS)

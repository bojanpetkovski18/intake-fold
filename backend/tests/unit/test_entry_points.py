import os
import signal
import subprocess
import sys
import time
from typing import IO

import pytest

CHILD_ENV_WITHOUT_SETTINGS = {
    name: value
    for name, value in os.environ.items()
    if name.upper() not in {"DATABASE_URL", "ENVIRONMENT", "LOG_LEVEL"}
}
VALID_ENV = CHILD_ENV_WITHOUT_SETTINGS | {
    "DATABASE_URL": "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"
}


def stop_signal() -> int:
    return signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM


def creation_flags() -> int:
    # CTRL_BREAK_EVENT reaches a process group, so the child needs its own.
    return subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0


def read_until(stream: IO[str], marker: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = stream.readline()
        if marker in line:
            return
        if not line:
            break
    pytest.fail(f"did not see {marker!r}")


@pytest.mark.parametrize(
    "arguments",
    [
        ["-m", "intakefold.worker"],
        ["-c", "from intakefold.api.app import create_app; create_app()"],
    ],
    ids=["worker", "api"],
)
def test_missing_setting_stops_start_up_with_a_clear_message(arguments: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, *arguments],
        env=CHILD_ENV_WITHOUT_SETTINGS,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr
    assert "Traceback" not in result.stderr


def test_worker_starts_logs_and_stops_cleanly() -> None:
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "intakefold.worker"],
        env=VALID_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creation_flags(),
    )
    try:
        assert process.stdout is not None
        read_until(process.stdout, "worker_started")
        process.send_signal(stop_signal())
        output, _ = process.communicate(timeout=10)
    finally:
        process.kill()

    assert process.returncode == 0
    assert "worker_stopped" in output

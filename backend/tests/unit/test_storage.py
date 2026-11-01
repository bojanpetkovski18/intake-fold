import uuid
from pathlib import Path

import pytest

from intakefold.documents.storage import Storage


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    key = storage.new_original_key()

    storage.write(key, b"content")

    assert storage.read(key) == b"content"
    assert storage.exists(key)


def test_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    key = storage.new_original_key()

    storage.write(key, b"first")
    storage.write(key, b"second")

    assert storage.read(key) == b"second"
    assert [path.name for path in (tmp_path / "originals").iterdir()] == [key.split("/")[1]]


def test_delete_is_safe_to_repeat(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    key = storage.new_original_key()
    storage.write(key, b"content")

    storage.delete(key)
    storage.delete(key)

    assert not storage.exists(key)


def test_page_keys_are_valid(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    key = storage.page_key(uuid.uuid4(), 3)

    storage.write(key, b"png")

    assert storage.read(key) == b"png"


@pytest.mark.parametrize(
    "key",
    [
        "../secret",
        "originals/../../secret",
        "/etc/passwd",
        "..\\secret",
        "originals/not-a-uuid",
        "originals/00000000-0000-0000-0000-000000000000/../../x",
        "",
    ],
)
def test_anything_but_a_generated_key_is_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="storage key"):
        Storage(tmp_path).read(key)

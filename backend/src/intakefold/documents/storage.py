import os
import re
import uuid
from pathlib import Path

# Keys are generated here and only here, so no part of a file name can reach the disk.
KEY_PATTERN = re.compile(r"(originals/[0-9a-f-]{36}|pages/[0-9a-f-]{36}/[0-9]+\.png)")


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def new_original_key() -> str:
        return f"originals/{uuid.uuid4()}"

    @staticmethod
    def page_key(document_id: uuid.UUID, page: int) -> str:
        return f"pages/{document_id}/{page}.png"

    def write(self, key: str, content: bytes) -> None:
        """Atomic: a reader or a crash never sees half a file."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("Not a storage key.")
        return self.root / key

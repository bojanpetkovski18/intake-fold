import base64
import binascii
import enum
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Engine, select, tuple_
from sqlalchemy.orm import InstrumentedAttribute, Session

from intakefold.db.models import Document, DocumentStatus


class DocumentSort(enum.StrEnum):
    RECEIVED_NEWEST = "-received_at"
    RECEIVED_OLDEST = "received_at"
    FILENAME_ASCENDING = "filename"
    FILENAME_DESCENDING = "-filename"


# The fixed allow-list: a request names a key here and never a column.
SORT_COLUMNS: dict[DocumentSort, InstrumentedAttribute[datetime] | InstrumentedAttribute[str]] = {
    DocumentSort.RECEIVED_NEWEST: Document.received_at,
    DocumentSort.RECEIVED_OLDEST: Document.received_at,
    DocumentSort.FILENAME_ASCENDING: Document.original_filename,
    DocumentSort.FILENAME_DESCENDING: Document.original_filename,
}


SORT_IS_TIME = {sort: column is Document.received_at for sort, column in SORT_COLUMNS.items()}


class InvalidCursor(Exception):
    pass


@dataclass(frozen=True)
class DocumentPage:
    items: list[Document]
    next_cursor: str | None


def encode_cursor(sort: DocumentSort, document: Document) -> str:
    value = document.received_at if SORT_IS_TIME[sort] else document.original_filename
    text = value.isoformat() if isinstance(value, datetime) else value
    raw = json.dumps([sort.value, text, str(document.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str, sort: DocumentSort) -> tuple[datetime | str, uuid.UUID]:
    try:
        raw = base64.b64decode(cursor.encode(), altchars=b"-_", validate=True)
        cursor_sort, text, document_id = json.loads(raw)
        if cursor_sort != sort.value or not isinstance(text, str):
            raise InvalidCursor
        value = datetime.fromisoformat(text) if SORT_IS_TIME[sort] else text
        return value, uuid.UUID(document_id)
    except (binascii.Error, ValueError, TypeError) as error:
        raise InvalidCursor from error


def list_documents(
    engine: Engine,
    *,
    status: DocumentStatus | None,
    sort: DocumentSort,
    limit: int,
    cursor: str | None,
) -> DocumentPage:
    column = SORT_COLUMNS[sort]
    descending = sort.value.startswith("-")
    statement = select(Document).limit(limit + 1)
    if status is not None:
        statement = statement.where(Document.status == status)
    if cursor is not None:
        value, document_id = decode_cursor(cursor, sort)
        statement = statement.where(after_cursor(column, value, document_id, descending))
    if descending:
        statement = statement.order_by(column.desc(), Document.id.desc())
    else:
        statement = statement.order_by(column.asc(), Document.id.asc())

    with Session(engine) as session:
        rows = list(session.scalars(statement))
    items = rows[:limit]
    next_cursor = encode_cursor(sort, items[-1]) if len(rows) > limit else None
    return DocumentPage(items, next_cursor)


def after_cursor(
    column: InstrumentedAttribute[datetime] | InstrumentedAttribute[str],
    value: datetime | str,
    document_id: uuid.UUID,
    descending: bool,
) -> ColumnElement[bool]:
    # Keyset paging: stable while rows are added, and it does not slow down on later pages.
    position = tuple_(column, Document.id)
    bound = (value, document_id)
    return position < bound if descending else position > bound

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import Engine
from starlette.datastructures import UploadFile

from intakefold.api.access import Principal, require_role
from intakefold.api.problems import problem_response
from intakefold.api.rate_limit import limit_upload
from intakefold.clock import Clock
from intakefold.db.models import Document, DocumentStatus, Role
from intakefold.documents.checks import too_large
from intakefold.documents.intake import (
    Accepted,
    FileResult,
    Prepared,
    Refused,
    display_filename,
    prepare_file,
    record_batch,
)
from intakefold.documents.queries import (
    DocumentPage,
    DocumentSort,
    InvalidCursor,
    list_documents,
)
from intakefold.documents.storage import Storage
from intakefold.settings import MIB, Settings

router = APIRouter(prefix="/documents")

Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]
MULTIPART_OVERHEAD_BYTES = MIB


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class DocumentSummary(ApiModel):
    id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    received_at: datetime
    finished_at: datetime | None


class DocumentList(ApiModel):
    items: list[DocumentSummary]
    next_cursor: str | None


class UploadedFile(ApiModel):
    filename: str
    document_id: uuid.UUID | None = None
    deduplicated: bool = False
    code: str | None = None
    detail: str | None = None


class UploadResult(ApiModel):
    batch_id: uuid.UUID | None
    files: list[UploadedFile]


def summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        filename=document.original_filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        page_count=document.page_count,
        status=document.status,
        received_at=document.received_at,
        finished_at=document.finished_at,
    )


def uploaded_file(result: FileResult) -> UploadedFile:
    if isinstance(result, Refused):
        return UploadedFile(filename=result.filename, code=result.code, detail=result.detail)
    return UploadedFile(
        filename=result.filename,
        document_id=result.document_id,
        deduplicated=result.deduplicated,
    )


def refuse_oversized_request(request: Request, settings: Settings) -> None:
    # The server holds a body to its declared length, so this bounds what reaches the disk.
    declared = request.headers.get("content-length")
    if declared is None or not declared.isdecimal():
        raise HTTPException(status_code=411, detail="A Content-Length header is required.")
    largest_file = max(settings.max_pdf_bytes, settings.max_image_bytes)
    allowed = settings.max_batch_files * largest_file + MULTIPART_OVERHEAD_BYTES
    if int(declared) > allowed:
        raise HTTPException(status_code=413, detail="The upload is too large.")


async def prepare_upload(request: Request, upload: UploadFile) -> Prepared:
    settings: Settings = request.app.state.settings
    largest_file = max(settings.max_pdf_bytes, settings.max_image_bytes)
    if upload.size is not None and upload.size > largest_file:
        refused = too_large(largest_file)
        return Refused(display_filename(upload.filename), refused.code, refused.detail)
    data = await upload.read()
    return await run_in_threadpool(
        prepare_file,
        request.app.state.engine,
        request.app.state.storage,
        settings,
        raw_filename=upload.filename,
        data=data,
    )


@router.post("", dependencies=[Depends(limit_upload)], response_model=UploadResult)
async def upload_documents(
    request: Request, response: Response, principal: Reviewer
) -> UploadResult | Response:
    # Reads the body here, not through a File parameter: FastAPI parses declared form fields
    # before it runs dependencies, and an anonymous caller must not reach the disk.
    settings: Settings = request.app.state.settings
    refuse_oversized_request(request, settings)
    prepared: list[Prepared] = []
    async with request.form(max_files=settings.max_batch_files) as form:
        for upload in form.getlist("files"):
            if not isinstance(upload, UploadFile):
                continue
            # One at a time, so memory holds one file and not the whole batch.
            prepared.append(await prepare_upload(request, upload))
    if not prepared:
        raise HTTPException(status_code=422, detail="Send at least one file in `files`.")

    clock: Clock = request.app.state.clock
    engine: Engine = request.app.state.engine
    storage: Storage = request.app.state.storage
    batch_id, results = await run_in_threadpool(
        record_batch, engine, storage, clock, settings, user_id=principal.user_id, prepared=prepared
    )
    files = [uploaded_file(result) for result in results]
    if not any(isinstance(result, Accepted) for result in results):
        errors = [file.model_dump(by_alias=True, exclude_none=True) for file in files]
        return problem_response(422, "No file was accepted.", errors=errors)
    if batch_id is None:
        response.status_code = 200
    else:
        response.status_code = 201
    return UploadResult(batch_id=batch_id, files=files)


@router.get("")
def list_all(
    request: Request,
    _: Reviewer,
    status: DocumentStatus | None = None,
    sort: DocumentSort = DocumentSort.RECEIVED_NEWEST,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
) -> DocumentList:
    try:
        page: DocumentPage = list_documents(
            request.app.state.engine, status=status, sort=sort, limit=limit, cursor=cursor
        )
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="The cursor is not valid.") from None
    return DocumentList(
        items=[summary(document) for document in page.items], next_cursor=page.next_cursor
    )


@router.get("/{document_id}/pages/{page}")
def page_image(
    request: Request,
    _: Reviewer,
    document_id: uuid.UUID,
    page: Annotated[int, Path(ge=1)],
) -> Response:
    storage: Storage = request.app.state.storage
    key = storage.page_key(document_id, page)
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="This page is not available.")
    return Response(storage.read(key), media_type="image/png")

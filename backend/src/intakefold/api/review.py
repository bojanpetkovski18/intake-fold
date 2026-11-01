import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from pydantic.alias_generators import to_camel

from intakefold.api.access import Principal, require_role
from intakefold.api.documents import ApiModel, DocumentSummary, summary
from intakefold.db.models import DocumentType, Invoice, LineItem, Role, RuleOutcome
from intakefold.documents.review import (
    CorrectedLine,
    Correction,
    DocumentNotFound,
    NothingToApprove,
    NotReviewable,
    OverrideRequired,
    ReviewRecord,
    VersionConflict,
    approve_document,
    correct_document,
    fields_of_rule,
    load_review,
    reject_document,
)
from intakefold.extraction.schema import CURRENCY_PATTERN, DECIMAL_PATTERN, to_decimal
from intakefold.validation.rules import amount_text

router = APIRouter(prefix="/documents")

Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]
MoneyText = Annotated[str, Field(pattern=DECIMAL_PATTERN, max_length=24)]
NAME_LENGTH = 200
REASON_LENGTH = 2000


class LineItemBody(ApiModel):
    description: str = Field(max_length=2000)
    quantity: MoneyText | None
    unit_price: MoneyText | None
    amount: MoneyText | None


class FieldsBody(ApiModel):
    document_type: DocumentType
    vendor_name: str | None = Field(max_length=NAME_LENGTH)
    invoice_number: str | None = Field(max_length=100)
    issue_date: date | None
    due_date: date | None
    currency: Annotated[str, Field(pattern=CURRENCY_PATTERN)] | None
    subtotal: MoneyText | None
    tax_total: MoneyText | None
    adjustments_total: MoneyText | None
    total: MoneyText | None
    line_items: list[LineItemBody] = Field(max_length=200)


class RuleView(ApiModel):
    rule: str
    outcome: RuleOutcome
    reason_code: str | None
    detail: str | None
    fields: list[str]


class ReviewDetail(DocumentSummary):
    version: int
    status_reasons: list[str]
    fields: FieldsBody | None
    overall_confidence: str | None
    uncertain_fields: list[str]
    contains_embedded_instructions: bool
    rule_results: list[RuleView]


class CorrectionBody(ApiModel):
    version: int
    fields: FieldsBody


class ApproveBody(ApiModel):
    version: int
    override_reason: str | None = Field(default=None, max_length=REASON_LENGTH)


class RejectBody(ApiModel):
    version: int
    reason: str = Field(min_length=1, max_length=REASON_LENGTH)


def money_text(value: Decimal | None) -> str | None:
    return None if value is None else amount_text(value)


def line_body(line: LineItem) -> LineItemBody:
    return LineItemBody(
        description=line.description,
        quantity=money_text(line.quantity),
        unit_price=money_text(line.unit_price),
        amount=money_text(line.amount),
    )


def fields_body(invoice: Invoice, lines: list[LineItem]) -> FieldsBody:
    return FieldsBody(
        document_type=invoice.document_type,
        vendor_name=invoice.vendor_name,
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        currency=invoice.currency,
        subtotal=money_text(invoice.subtotal),
        tax_total=money_text(invoice.tax_total),
        adjustments_total=money_text(invoice.adjustments_total),
        total=money_text(invoice.total),
        line_items=[line_body(line) for line in lines],
    )


def detail_of(record: ReviewRecord) -> ReviewDetail:
    invoice = record.invoice
    rules = [
        RuleView(
            rule=row.rule,
            outcome=row.outcome,
            reason_code=row.reason_code,
            detail=row.detail,
            fields=(
                [to_camel(name) for name in fields_of_rule(row.rule, invoice)]
                if invoice is not None and row.outcome is RuleOutcome.FAIL
                else []
            ),
        )
        for row in record.rules
    ]
    return ReviewDetail(
        **summary(record.document).model_dump(),
        version=record.document.version,
        status_reasons=record.document.status_reasons,
        fields=fields_body(invoice, record.lines) if invoice is not None else None,
        overall_confidence=invoice.overall_confidence.value if invoice is not None else None,
        uncertain_fields=(
            [to_camel(name) for name in invoice.uncertain_fields] if invoice is not None else []
        ),
        contains_embedded_instructions=(
            invoice.contains_embedded_instructions if invoice is not None else False
        ),
        rule_results=rules,
    )


def to_correction(body: FieldsBody) -> Correction:
    return Correction(
        document_type=body.document_type,
        vendor_name=body.vendor_name or None,
        invoice_number=body.invoice_number or None,
        issue_date=body.issue_date,
        due_date=body.due_date,
        currency=body.currency,
        subtotal=to_decimal(body.subtotal),
        tax_total=to_decimal(body.tax_total),
        adjustments_total=to_decimal(body.adjustments_total),
        total=to_decimal(body.total),
        line_items=tuple(
            CorrectedLine(
                line.description,
                to_decimal(line.quantity),
                to_decimal(line.unit_price),
                to_decimal(line.amount),
            )
            for line in body.line_items
        ),
    )


def problem_for(error: Exception) -> HTTPException:
    match error:
        case DocumentNotFound():
            return HTTPException(status_code=404, detail="There is no such document.")
        case VersionConflict():
            return HTTPException(
                status_code=409, detail="Someone else changed this document. Reload to continue."
            )
        case NotReviewable():
            return HTTPException(status_code=409, detail="This document is no longer in review.")
        case OverrideRequired():
            return HTTPException(
                status_code=422, detail="A rule failed, so approving needs an override reason."
            )
        case NothingToApprove():
            return HTTPException(status_code=422, detail="Enter the fields before approving.")
        case _:
            raise error


REVIEW_ERRORS = (
    DocumentNotFound,
    VersionConflict,
    NotReviewable,
    OverrideRequired,
    NothingToApprove,
)


@router.get("/{document_id}")
def detail(request: Request, _: Reviewer, document_id: uuid.UUID) -> ReviewDetail:
    try:
        return detail_of(load_review(request.app.state.engine, document_id))
    except DocumentNotFound as error:
        raise problem_for(error) from None


@router.patch("/{document_id}/fields")
def correct(
    request: Request, principal: Reviewer, document_id: uuid.UUID, body: CorrectionBody
) -> ReviewDetail:
    engine = request.app.state.engine
    try:
        correct_document(
            engine,
            request.app.state.clock,
            request.app.state.settings,
            document_id=document_id,
            version=body.version,
            correction=to_correction(body.fields),
            actor=principal.user_id,
        )
    except REVIEW_ERRORS as error:
        raise problem_for(error) from None
    return detail_of(load_review(engine, document_id))


@router.post("/{document_id}/approve")
def approve(
    request: Request, principal: Reviewer, document_id: uuid.UUID, body: ApproveBody
) -> ReviewDetail:
    engine = request.app.state.engine
    try:
        approve_document(
            engine,
            request.app.state.clock,
            document_id=document_id,
            version=body.version,
            override_reason=(body.override_reason or "").strip() or None,
            actor=principal.user_id,
        )
    except REVIEW_ERRORS as error:
        raise problem_for(error) from None
    return detail_of(load_review(engine, document_id))


@router.post("/{document_id}/reject")
def reject(
    request: Request, principal: Reviewer, document_id: uuid.UUID, body: RejectBody
) -> ReviewDetail:
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Give a reason for rejecting.")
    engine = request.app.state.engine
    try:
        reject_document(
            engine,
            request.app.state.clock,
            document_id=document_id,
            version=body.version,
            reason=reason,
            actor=principal.user_id,
        )
    except REVIEW_ERRORS as error:
        raise problem_for(error) from None
    return detail_of(load_review(engine, document_id))

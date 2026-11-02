from collections.abc import Sequence
from dataclasses import dataclass

from intakefold.db.models import DocumentStatus, RuleOutcome
from intakefold.validation.rules import RuleResult

EMBEDDED_INSTRUCTIONS = "embedded_instructions"
NOT_HIGH_CONFIDENCE = "confidence_not_high"
UNCERTAIN_FIELDS = "uncertain_fields"
NOT_A_DOCUMENT_TYPE = "unsupported_document_type"
APPROVABLE_TYPES = ("invoice", "receipt")


@dataclass(frozen=True)
class Signals:
    """What the model reported about itself. Each can only send a document to review."""

    document_type: str
    overall_confidence: str
    uncertain_fields: tuple[str, ...]
    contains_embedded_instructions: bool


@dataclass(frozen=True)
class Decision:
    status: DocumentStatus
    reasons: list[str]


def route(results: Sequence[RuleResult], signals: Signals) -> Decision:
    """Auto-approves only if nothing at all gives a reason not to, and lists every reason."""
    reasons = [result.rule for result in results if result.outcome is RuleOutcome.FAIL]
    if signals.contains_embedded_instructions:
        reasons.append(EMBEDDED_INSTRUCTIONS)
    if signals.overall_confidence != "high":
        reasons.append(NOT_HIGH_CONFIDENCE)
    if signals.uncertain_fields:
        reasons.append(UNCERTAIN_FIELDS)
    if signals.document_type not in APPROVABLE_TYPES:
        reasons.append(NOT_A_DOCUMENT_TYPE)
    status = DocumentStatus.NEEDS_REVIEW if reasons else DocumentStatus.AUTO_APPROVED
    return Decision(status, reasons)

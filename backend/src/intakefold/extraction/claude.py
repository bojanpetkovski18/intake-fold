import base64
import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import anthropic
import structlog
from anthropic import Anthropic, transform_schema
from anthropic.types.beta import BetaMessage
from pydantic import ValidationError

from intakefold.db.models import ExtractionOutcome
from intakefold.documents.checks import PDF
from intakefold.extraction.budget import TokenBudget
from intakefold.extraction.prices import estimate_cost
from intakefold.extraction.prompt import SYSTEM_PROMPT, USER_INSTRUCTION, repair_note
from intakefold.extraction.schema import ExtractedDocument
from intakefold.extraction.types import (
    DocumentInput,
    ExtractionRejected,
    ExtractionResult,
    Usage,
)
from intakefold.settings import Settings

log = structlog.get_logger()

CLAUDE = "claude"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
SPEND_CAP_CODE = "enforced_spend_limit_reached"
# The SDK types these request bodies as deep unions of TypedDicts. They are built in one place
# and every test inspects the bytes actually sent, so Any costs less here than casts would.
RequestBody = dict[str, Any]


@dataclass(frozen=True)
class Attempt:
    outcome: ExtractionOutcome
    data: ExtractedDocument | None
    raw_output: dict[str, object] | None
    problems: list[str]


def document_block(document: DocumentInput) -> dict[str, object]:
    # The document only ever travels in this block, never inside a prompt string.
    data = base64.standard_b64encode(document.content).decode()
    kind = "document" if document.media_type == PDF else "image"
    return {
        "type": kind,
        "source": {"type": "base64", "media_type": document.media_type, "data": data},
    }


def describe(error: ValidationError) -> list[str]:
    # Location and type only: the message could quote the document.
    return [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
        for item in error.errors(include_input=False, include_url=False, include_context=False)
    ]


def read_output(response: BetaMessage) -> Attempt:
    if response.stop_reason == "refusal":
        return Attempt(ExtractionOutcome.REFUSED, None, None, [])
    if response.stop_reason == "max_tokens":
        return Attempt(
            ExtractionOutcome.INVALID, None, None, ["the output was cut off, so keep it shorter"]
        )
    texts = [block.text for block in response.content if block.type == "text"]
    if not texts:
        return Attempt(ExtractionOutcome.INVALID, None, None, ["there was no output"])
    try:
        raw = json.loads(texts[-1])
    except json.JSONDecodeError:
        return Attempt(ExtractionOutcome.INVALID, None, None, ["the output was not valid JSON"])
    try:
        data = ExtractedDocument.model_validate(raw)
    except ValidationError as error:
        return Attempt(ExtractionOutcome.INVALID, None, None, describe(error))
    return Attempt(ExtractionOutcome.SUCCEEDED, data, raw, [])


def usage_of(response: BetaMessage) -> Usage:
    usage = response.usage
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
    )


def rejection_code(error: anthropic.APIStatusError) -> str | None:
    """The code to stop on, or None if the job queue should retry."""
    if error.status_code == 429:
        return "api_spend_limit" if SPEND_CAP_CODE in str(error.body) else None
    if error.status_code in (408, 409) or error.status_code >= 500:
        return None
    return f"api_{error.status_code}"


class ClaudeExtractor:
    name = CLAUDE

    def __init__(self, client: Anthropic, settings: Settings, budget: TokenBudget) -> None:
        self.client = client
        self.settings = settings
        self.budget = budget
        self.output_format = {
            "type": "json_schema",
            "schema": transform_schema(ExtractedDocument),
        }

    def extract(self, document: DocumentInput) -> ExtractionResult:
        try:
            return self._extract(document)
        except anthropic.APIStatusError as error:
            code = rejection_code(error)
            if code is None:
                raise
            raise ExtractionRejected(code) from None

    def _extract(self, document: DocumentInput) -> ExtractionResult:
        model = self.settings.claude_model
        input_tokens = self._count_tokens(document)
        if input_tokens > self.settings.max_input_tokens_per_doc:
            log.warning("extraction_input_too_large", input_tokens=input_tokens)
            return ExtractionResult(ExtractionOutcome.INPUT_TOO_LARGE, self.name, model=model)

        usage = Usage()
        cost = Decimal(0)
        serving_model = model
        problems: list[str] = []
        attempts = self.settings.extraction_max_repairs + 1
        attempt = Attempt(ExtractionOutcome.INVALID, None, None, [])
        repairs = 0
        for number in range(attempts):
            reserved = input_tokens + self.settings.extraction_max_tokens
            if not self.budget.reserve(document.batch_id, reserved):
                attempt = Attempt(ExtractionOutcome.BUDGET_EXCEEDED, None, None, [])
                break
            try:
                response = self._send(document, problems)
            except Exception:
                self.budget.settle(document.batch_id, reserved, 0, Decimal(0))
                raise
            response_usage = usage_of(response)
            serving_model = response.model
            response_cost = estimate_cost(serving_model, response_usage)
            self.budget.settle(
                document.batch_id,
                reserved,
                response_usage.input_tokens + response_usage.output_tokens,
                response_cost,
            )
            usage += response_usage
            cost += response_cost
            repairs = number
            attempt = read_output(response)
            if attempt.outcome is not ExtractionOutcome.INVALID:
                break
            problems = attempt.problems

        return ExtractionResult(
            outcome=attempt.outcome,
            extractor=self.name,
            data=attempt.data,
            model=serving_model,
            usage=usage,
            estimated_cost_usd=cost,
            repairs=repairs,
            raw_output=attempt.raw_output,
        )

    def _content(self, document: DocumentInput, problems: Iterable[str]) -> list[dict[str, object]]:
        listed = list(problems)
        instruction = repair_note(listed) if listed else USER_INSTRUCTION
        return [document_block(document), {"type": "text", "text": instruction}]

    def _count_tokens(self, document: DocumentInput) -> int:
        request: RequestBody = {
            "model": self.settings.claude_model,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": self._content(document, [])}],
            "output_config": {"format": self.output_format},
        }
        return self.client.messages.count_tokens(**request).input_tokens

    def _send(self, document: DocumentInput, problems: list[str]) -> BetaMessage:
        request: RequestBody = {
            "model": self.settings.claude_model,
            "max_tokens": self.settings.extraction_max_tokens,
            "system": SYSTEM_PROMPT,
            # A repair resends the whole request with a note, never a partial assistant turn.
            "messages": [{"role": "user", "content": self._content(document, problems)}],
            "output_config": {
                "effort": self.settings.claude_effort,
                "format": self.output_format,
            },
        }
        if self.settings.claude_refusal_fallback:
            request |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        return cast(BetaMessage, self.client.beta.messages.create(**request))

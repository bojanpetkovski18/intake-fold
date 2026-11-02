from anthropic import Anthropic
from sqlalchemy import Engine

from intakefold.extraction.budget import TokenBudget
from intakefold.extraction.claude import ClaudeExtractor
from intakefold.extraction.mock import MockExtractor
from intakefold.extraction.types import Extractor
from intakefold.settings import Settings

REQUEST_TIMEOUT_SECONDS = 300.0


def build_extractor(settings: Settings, engine: Engine) -> Extractor:
    if settings.extractor == "mock":
        return MockExtractor(settings.labels_dir)
    key = settings.anthropic_api_key
    assert key is not None  # noqa: S101 - Settings refuses EXTRACTOR=claude without a key
    # No SDK retries: the job queue owns retrying, and two layers would multiply the attempts.
    client = Anthropic(
        api_key=key.get_secret_value(), max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS
    )
    return ClaudeExtractor(client, settings, TokenBudget(engine))

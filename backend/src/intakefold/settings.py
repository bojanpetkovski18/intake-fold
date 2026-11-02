from decimal import Decimal
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import Annotated, Literal, Self

from limits import parse
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIB = 1024 * 1024
TARGET_NAME = r"^[a-z0-9][a-z0-9-]{0,63}$"


class WebhookTarget(BaseModel):
    """From configuration only. No API can set or change a target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=TARGET_NAME)
    url: AnyHttpUrl
    secret: SecretStr = Field(min_length=32)


def split_commas(value: object) -> object:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


CommaSeparated = BeforeValidator(split_commas)
DemoPassword = Annotated[SecretStr, Field(min_length=12)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", frozen=True)

    database_url: SecretStr = Field(min_length=1)
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    # For plain http on a local machine only. Without it the session cookie is Secure.
    allow_insecure_cookies: bool = False
    allowed_origins: Annotated[tuple[str, ...], NoDecode, CommaSeparated] = (
        "http://127.0.0.1:8180",
    )
    # Only these peers may state a client IP through X-Forwarded-For.
    trusted_proxies: Annotated[tuple[IPv4Network | IPv6Network, ...], NoDecode, CommaSeparated] = ()
    sign_in_rate_limit: str = "10/minute"
    upload_rate_limit: str = "30/minute"

    storage_dir: Path = Path("storage")
    max_pdf_bytes: int = Field(default=10 * MIB, gt=0)
    max_image_bytes: int = Field(default=7 * MIB, gt=0)
    max_pdf_pages: int = Field(default=10, gt=0)
    max_image_side: int = Field(default=8000, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    max_batch_files: int = Field(default=25, gt=0)
    batch_token_cap: int = Field(default=2_000_000, gt=0)

    extractor: Literal["mock", "claude"] = "mock"
    labels_dir: Path = Path("../data/labeled")
    anthropic_api_key: SecretStr | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    claude_refusal_fallback: bool = True
    extraction_max_repairs: int = Field(default=2, ge=0, le=5)
    extraction_max_tokens: int = Field(default=16_000, gt=0)
    max_input_tokens_per_doc: int = Field(default=60_000, gt=0)

    rule_line_tolerance: Decimal = Field(default=Decimal("0.01"), ge=0)
    rule_total_tolerance: Decimal = Field(default=Decimal("0.02"), ge=0)
    rule_future_days: int = Field(default=1, ge=0)
    rule_max_age_days: int = Field(default=5 * 365, gt=0)

    webhook_targets: tuple[WebhookTarget, ...] = ()
    webhook_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # Read by the seed, and in demo mode shown on the sign-in page.
    demo_reviewer_password: DemoPassword | None = None
    demo_admin_password: DemoPassword | None = None
    # Publishes the demo passwords and allows a full reset. Never with real data.
    demo_mode: bool = False

    @field_validator("sign_in_rate_limit", "upload_rate_limit")
    @classmethod
    def rate_limit_parses(cls, value: str) -> str:
        try:
            parse(value)
        except ValueError:
            raise ValueError("expected a rate such as 10/minute") from None
        return value

    @field_validator("webhook_targets")
    @classmethod
    def target_names_are_unique(
        cls, targets: tuple[WebhookTarget, ...]
    ) -> tuple[WebhookTarget, ...]:
        names = [target.name for target in targets]
        if len(names) != len(set(names)):
            raise ValueError("target names must be unique")
        return targets

    @model_validator(mode="after")
    def claude_needs_a_key(self) -> Self:
        if self.extractor == "claude" and self.anthropic_api_key is None:
            raise ValueError("EXTRACTOR=claude needs ANTHROPIC_API_KEY")
        return self

    @model_validator(mode="after")
    def demo_mode_is_mock_with_accounts(self) -> Self:
        # A reset re-runs the seed batch, which must never cost money.
        if self.demo_mode and self.extractor != "mock":
            raise ValueError("DEMO_MODE=true needs EXTRACTOR=mock")
        if self.demo_mode and None in (self.demo_reviewer_password, self.demo_admin_password):
            raise ValueError("DEMO_MODE=true needs DEMO_REVIEWER_PASSWORD and DEMO_ADMIN_PASSWORD")
        return self


class ConfigurationError(Exception):
    """A required setting is missing or invalid. The message never contains a value."""


def load_settings(**overrides: object) -> Settings:
    """From the environment. `overrides` win, for command-line tools that take their own flags."""
    try:
        # pyright cannot see that BaseSettings fills required fields from the environment.
        return Settings(**overrides)  # pyright: ignore[reportCallIssue, reportArgumentType]
    except ValidationError as error:
        # Pydantic's own message echoes the input, and these inputs can be secrets.
        problems = [
            f"{'.'.join(str(part) for part in item['loc']).upper()}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        ]
        raise ConfigurationError(
            "Invalid configuration. Fix these environment variables:\n  " + "\n  ".join(problems)
        ) from None

from ipaddress import IPv4Network, IPv6Network
from typing import Annotated, Literal

from limits import parse
from pydantic import BeforeValidator, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Read by the seed only.
    demo_reviewer_password: DemoPassword | None = None
    demo_admin_password: DemoPassword | None = None

    @field_validator("sign_in_rate_limit")
    @classmethod
    def rate_limit_parses(cls, value: str) -> str:
        try:
            parse(value)
        except ValueError:
            raise ValueError("expected a rate such as 10/minute") from None
        return value


class ConfigurationError(Exception):
    """A required setting is missing or invalid. The message never contains a value."""


def load_settings() -> Settings:
    try:
        # pyright cannot see that BaseSettings fills required fields from the environment.
        return Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        # Pydantic's own message echoes the input, and these inputs can be secrets.
        problems = [
            f"{'.'.join(str(part) for part in item['loc']).upper()}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        ]
        raise ConfigurationError(
            "Invalid configuration. Fix these environment variables:\n  " + "\n  ".join(problems)
        ) from None

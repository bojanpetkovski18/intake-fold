from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", frozen=True)

    database_url: SecretStr = Field(min_length=1)
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


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

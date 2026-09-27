from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MSME_",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/msme"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    bcrypt_rounds: int = 12
    cors_origins: list[str] = ["http://localhost:3000"]

    # Optional LLM for the AI command layer.
    # When unset, a deterministic rule parser is used.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"

    # Email notification settings
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # Resend email settings
    resend_api_key: str = ""
    resend_from: str = "onboarding@resend.dev"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, url: str) -> str:
        # Hosting providers (e.g. Render, Heroku) hand out postgres://
        # or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
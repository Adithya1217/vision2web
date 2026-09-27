from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MSME_", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres@localhost:5432/msme"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    bcrypt_rounds: int = 12
    cors_origins: list[str] = ["http://localhost:3000"]
    # Optional LLM for the AI command layer. When unset, a deterministic rule parser is used.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()

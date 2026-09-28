from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MSME_", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/msme"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    bcrypt_rounds: int = 12
    cors_origins: list[str] = ["http://localhost:3000"]
    # Optional LLM for the AI command layer. When unset, a deterministic rule parser is used.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    # Free alternative: Google Gemini (used when no Anthropic key is set). Check AI Studio for the current
    # free-tier model name if this one is retired.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # Sarvam speech (Indian-language STT/TTS). Unset = the browser's built-in speech is used.
    sarvam_api_key: str | None = None
    sarvam_stt_model: str = "saaras:v3"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_language: str = "en-IN"
    sarvam_tts_speaker: str | None = None  # None = the model's default voice

    # Stock alert emails via Resend. Unset key = alerts are skipped.
    resend_api_key: str = ""
    resend_from: str = "onboarding@resend.dev"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, url: str) -> str:
        # Hosting providers (e.g. Render, Heroku) hand out postgres:// or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()

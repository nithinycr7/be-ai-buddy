from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: str = "dev"
    API_PREFIX: str = "/api"
    PROJECT_NAME: str = "AI Buddy Backend"

    # Mongo
    MONGODB_URI: str = ""
    MONGODB_DB: str = "aibuddy-dev"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000","https://delightful-hill-05c05390f.1.azurestaticapps.net/"]

    # Security
    API_KEY_NAME: str = "x-api-key"
    API_KEY_VALUE: str = "dev-local-key"
    JWT_SECRET: str = "changeme"
    JWT_ALG: str = "HS256"

    # Auth — tokens (SPEC §5). Access is short; refresh is long + rotating.
    ACCESS_TOKEN_TTL_MIN: int = 30
    REFRESH_TOKEN_TTL_DAYS: int = 60          # SPEC §12.6 — "after session end auto refresh"
    JWT_ISSUER: str = "mymedha-lxp"

    # Auth — OTP (parent phone login, SPEC §3.3 / §9).
    OTP_LENGTH: int = 6
    OTP_TTL_MIN: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    # In non-prod we have no SMS provider, so echo the OTP back / log it for testing.
    OTP_DEV_ECHO: bool = True

    # Auth — student/child credentials (SPEC §3.1 / §3.5).
    STUDENT_PIN_LENGTH: int = 4               # school-device path
    CHILD_PIN_LENGTH: int = 4                 # family-mode soft sibling lock
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MIN: int = 15

    # Auth — device pairing (trusted learning device). One-time grant, rendered
    # as QR + numeric code; short-lived + single-use.
    PAIRING_CODE_LENGTH: int = 6
    PAIRING_TTL_MIN: int = 5

    # Auth — step-up (AAL): sensitive parent actions (pair device, settings,
    # recovery) require a *fresh* strong auth within this window; otherwise the
    # parent must re-verify OTP.
    FRESH_AUTH_WINDOW_MIN: int = 10

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o-mini"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-large"

    # Anthropic Claude — used for simulation HTML generation (richer SVG output than gpt-4o-mini)
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_SIMULATION_MODEL: str = "claude-sonnet-4-6"

    # Google Gemini — primary for story (JSON) and simulation (HTML/SVG) generation
    GOOGLE_API_KEY: str = ""
    GEMINI_STORY_MODEL: str = "gemini-2.5-flash"
    GEMINI_SIMULATION_MODEL: str = "gemini-3.0-pro"
    # Model used for summary + assessment (quiz) generation, via Gemini's
    # OpenAI-compatible endpoint so existing chat.completions calls work unchanged.
    GEMINI_CHAT_MODEL: str = "gemini-2.5-flash"

    # Azure AI Speech Service — STT (Speech-to-Text)
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = ""

    # Azure AI Speech Service — TTS (Text-to-Speech, separate resource)
    AZURE_SPEECH_TTS_KEY: str = ""
    AZURE_SPEECH_TTS_REGION: str = "centralindia"

    # Azure Storage (for audio upload)
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AUDIO_CONTAINER_NAME: str = "schools"
    AUDIO_QUEUE_NAME: str = "transcription-queue"
    SUMMARY_QUEUE_NAME: str = "summary-ready"
    SUMMARY_POISON_QUEUE_NAME: str = "summary-poison"
    NCERT_COLLECTION_NAME: str = "ncert_textbooks"

    # NCERT pagedex — figure images live in Blob (not base64 in Mongo).
    NCERT_BLOB_CONTAINER: str = "ncert"
    NCERT_INGEST_QUEUE_NAME: str = "ncert-ingest"
    # Minutes a signed figure URL stays valid.
    NCERT_FIGURE_SAS_TTL_MIN: int = 1440

    def is_production(self) -> bool:
        return self.ENV.lower() in {"prod", "production", "staging"}

    def assert_production_ready(self) -> None:
        """Fail fast at startup in prod when critical secrets/config are missing or
        still set to dev placeholders. No-op in dev so the demo keeps working."""
        if not self.is_production():
            return
        problems: list[str] = []
        for key in ("MONGODB_URI", "GOOGLE_API_KEY", "AZURE_STORAGE_CONNECTION_STRING"):
            if not getattr(self, key):
                problems.append(f"{key} is empty")
        if self.JWT_SECRET == "changeme":
            problems.append("JWT_SECRET is still the dev placeholder")
        if self.API_KEY_VALUE == "dev-local-key":
            problems.append("API_KEY_VALUE is still the dev placeholder")
        if problems:
            raise RuntimeError(
                "Refusing to start in production — fix: " + "; ".join(problems)
            )


settings = Settings()

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

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o-mini"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-large"

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


settings = Settings()

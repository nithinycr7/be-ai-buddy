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

    # Azure Speech
    AZURE_SPEECH_KEY: str =""
    AZURE_SPEECH_REGION: str = "eastus"
    AZURE_BLOB_CONN_STR: str = ""

settings = Settings()

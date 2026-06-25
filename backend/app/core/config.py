from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    # App
    app_name: str = "AIA Backend"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://aia_user:aia_password@localhost:5432/aia_db"

    # Security (JWT)
    secret_key: str = "change-this-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24h

    # Admin credentials (created on first run)
    admin_username: str = "admin"
    admin_password: str = "Admin@AIA2026!"

    # Public domains
    frontend_domain: str = "sefako-ai-studio.it-sefako.com"
    api_domain: str = "api-sefako-ai-studio.it-sefako.com"

    # Encryption key for API keys stored in DB (Fernet key)
    encryption_key: str = ""

    # GitHub OAuth
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""

    # LLM API keys (fallback from env if not set in DB)
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    grok_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    nvidia_api_key: str = ""
    mistral_api_key: str = ""
    qwen_api_key: str = ""
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = ""
    bedrock_region: str = ""

    # CORS
    cors_origins: List[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

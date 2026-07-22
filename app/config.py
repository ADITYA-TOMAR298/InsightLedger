from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Financial Report Analyzer API"
    database_url: str = "sqlite:///./financial_reports.db"
    chroma_directory: Path = Path("data/chroma")
    upload_directory: Path = Path("data/uploads")
    chart_directory: Path = Path("data/charts")
    # Small public model that runs locally on CPU; no embedding API key or GPU is required.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"
    # A hosted chat model keeps deployment small; set MISTRAL_API_KEY in the environment.
    mistral_model: str = "mistral-small-latest"
    mistral_api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        """Accept Vercel's comma-separated environment-variable format."""
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (settings.chroma_directory, settings.upload_directory, settings.chart_directory):
        directory.mkdir(parents=True, exist_ok=True)
    return settings

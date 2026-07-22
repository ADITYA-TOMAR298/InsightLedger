import os
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Financial Report Analyzer API"
    # Vercel Functions can only write to /tmp. These locations are temporary
    # there and are suitable only for demos without external storage services.
    storage_root: Path = Field(default_factory=lambda: Path(tempfile.gettempdir()) if os.getenv("VERCEL") else Path("data"))
    database_url: str = Field(default_factory=lambda: "sqlite:///" + str((Path(tempfile.gettempdir()) / "financial_reports.db") if os.getenv("VERCEL") else Path("financial_reports.db")))
    chroma_directory: Path | None = None
    upload_directory: Path | None = None
    chart_directory: Path | None = None
    # A hosted chat model keeps the Vercel Function small; set MISTRAL_API_KEY.
    mistral_model: str = "mistral-small-latest"
    mistral_api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    def model_post_init(self, __context) -> None:
        self.chroma_directory = self.chroma_directory or self.storage_root / "chroma"
        self.upload_directory = self.upload_directory or self.storage_root / "uploads"
        self.chart_directory = self.chart_directory or self.storage_root / "charts"

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

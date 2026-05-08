from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sqlite_path: Path = Field(default=Path("./data/state/imae.sqlite"))
    duckdb_path: Path = Field(default=Path("./data/state/imae.duckdb"))
    data_dir: Path = Field(default=Path("./data"))

    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    app_timezone: str = Field(default="Asia/Kolkata")

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.sqlite_path}"


def get_settings() -> Settings:
    return Settings()

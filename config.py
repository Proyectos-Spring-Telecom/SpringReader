from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "SpringReader"
    APP_PORT: int = 8001
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    AUTH_ENABLED: bool = False
    SERVICE_API_KEY: str = ""

    CORS_ORIGINS: str = ""

    OCR_LAZY_LOAD: bool = True
    OCR_MAX_UPLOAD_SIZE: int = 10485760
    OCR_UNLOAD_TIMEOUT: int = 600
    OCR_LANG: str = "es"
    OCR_USE_ANGLE_CLS: bool = True

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def strip_cors_origins(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.CORS_ORIGINS.strip():
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def auth_enabled(self) -> bool:
        return self.AUTH_ENABLED

    @property
    def service_api_key(self) -> str:
        return self.SERVICE_API_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()

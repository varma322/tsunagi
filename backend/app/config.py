from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TSUNAGI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./tsunagi.db"
    redis_url: str | None = None

    # Legacy shared enrolment secret. Leave unset so single-use enrolment codes
    # are the only way to register a device.
    setup_key: str | None = None
    enrolment_token_ttl_seconds: int = 900
    # Admin key minted on a fresh install. Leave unset to have one generated
    # and logged once at startup.
    bootstrap_api_key: str | None = None
    auto_create_schema: bool = True

    # Must exceed the phone's check-in interval, or a healthy device reads as
    # offline between beats. WorkManager will not schedule periodic work more
    # often than every 15 minutes, and Doze delays it further, so this allows
    # one missed cycle before calling a device offline.
    device_online_window_seconds: int = 1800
    event_log_max: int = 1000

    # Generous by default: a phone uploading a backlog batches its messages, so
    # normal traffic is nowhere near this. It exists to bound abuse and runaway
    # clients, not to shape legitimate use.
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 240
    rate_limit_window_seconds: int = 60
    max_page_size: int = 200
    default_page_size: int = 50
    max_wait_timeout_seconds: int = 60

    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()

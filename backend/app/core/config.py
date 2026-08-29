from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    app_name: str = "Nexora AI"
    api_v1_prefix: str = "/api/v1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=90)
    refresh_cookie_name: str = "nexora_rt"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: Literal["lax", "strict"] = "lax"
    refresh_cookie_path: str = "/api/v1/auth"
    password_min_length: int = Field(default=12, ge=12, le=128)
    argon2_time_cost: int = Field(default=3, ge=2)
    argon2_memory_cost: int = Field(default=65536, ge=19456)
    argon2_parallelism: int = Field(default=4, ge=1)
    email_verification_expire_hours: int = 24
    password_reset_expire_hours: int = 1
    invitation_expire_days: int = 7

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    database_url: str
    database_url_sync: str
    database_owner_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_echo: bool = False
    redis_url: SecretStr
    rate_limit_enabled: bool = True
    celery_broker_url: SecretStr
    celery_result_backend: SecretStr
    celery_task_always_eager: bool = False
    metrics_enabled: bool = True

    # Email delivery. The outbox worker is the only consumer.
    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_tls: bool = False
    email_from: str = "no-reply@nexora.local"
    email_from_name: str = "Nexora AI"
    outbox_batch_size: int = Field(default=50, ge=1, le=500)
    outbox_max_attempts: int = Field(default=8, ge=1, le=50)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 bytes")
        return value

    @model_validator(mode="after")
    def validate_environment_security(self) -> "Settings":
        if "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are forbidden")
        if self.environment != "development" and (self.debug or not self.refresh_cookie_secure):
            raise ValueError("Non-development environments require DEBUG=false and secure cookies")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

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
    # How often beat fires the drain. A password reset should not sit in the
    # queue for a noticeable time, so this is seconds, not minutes.
    outbox_drain_seconds: float = Field(default=10.0, gt=0, le=3600)

    # AI copilot (AI.md §2.6). The provider is a configuration choice; none of
    # the copilot's security properties depend on which one is selected.
    llm_provider: str = "openai"
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    llm_model_chat: str = "gpt-4o"
    llm_model_analysis: str = "gpt-4o"
    llm_model_embedding: str = "text-embedding-3-small"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    llm_max_tool_iterations: int = Field(default=4, ge=1, le=10)
    ai_enabled: bool = True

    # Phase 9 — RAG. One Qdrant collection partitioned by tenant (ADR-0013).
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "nexora_documents"
    # text-embedding-3-small. A mismatch here against the deployed collection
    # produces a dimension error on upsert, not silent nonsense.
    embedding_dimensions: int = Field(default=1536, ge=1, le=8192)
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "nexora-documents"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    document_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)
    rag_chunk_chars: int = Field(default=1200, ge=200, le=8000)
    rag_chunk_overlap: int = Field(default=200, ge=0, le=2000)
    rag_top_k: int = Field(default=6, ge=1, le=50)
    document_reconciliation_seconds: float = Field(default=900.0, gt=0, le=86400)
    # Once a day by default; a wider ceiling than the 24h default so a
    # deployment can space it out further without a code change.
    anomaly_sweep_seconds: float = Field(default=86400.0, gt=0, le=604800)

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

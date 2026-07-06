"""
Application configuration loaded from environment variables.
Heritage AI Services — powered by Heritage AI Services engine.
"""


from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Infrastructure settings loaded from .env or environment.

    AI provider settings (embedding, LLM, vision) are NOT here --
    they are stored in the database and managed via Admin Portal.
    See: app/services/config_service.py and app/ai/registry.py

    Heritage-specific settings (service token, NestJS URL) are added here.
    """

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://heritage_ai:heritage_ai_secret@localhost:5432/heritage_ai",
        description="PostgreSQL connection string (async). Use pgvector-enabled PostgreSQL.",
    )

    # --- Auth (internal portal auth) ---
    secret_key: str = Field(
        default="change-me-to-a-random-secret-string",
        description="Secret key for signing JWT tokens and encrypting config values",
    )
    default_admin_email: str = Field(
        default="admin@heritage-ai.local",
        description="Email for the initial admin account (created on first startup)",
    )
    default_admin_password: str = Field(
        default="admin123",
        description="Password for the initial admin account",
    )

    # --- Heritage Bridge (service-to-service auth with Heritage-LastDance-BE) ---
    heritage_service_token: str = Field(
        default="",
        description=(
            "Shared secret token used by Heritage-LastDance-BE (NestJS) to authenticate "
            "calls to /api/heritage/* endpoints. Set a long random string. "
            "The NestJS service sends: Authorization: Bearer <token>"
        ),
    )

    # --- Heritage NestJS Backend URL (optional, for callbacks/health checks) ---
    heritage_be_url: str = Field(
        default="http://localhost:3000",
        description="URL of Heritage-LastDance-BE NestJS API (used for optional health checks)",
    )

    # --- MinIO ---
    minio_endpoint: str = Field(default="localhost:9000")
    minio_public_endpoint: str = Field(
        default="",
        description=(
            "Public-facing MinIO address used in presigned URLs (browser-accessible). "
            "Defaults to minio_endpoint if not set. "
            "In Docker: set to 'localhost:9000' so presigned URLs work from the browser."
        ),
    )
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin123")
    minio_bucket: str = Field(default="heritage-ai-files")
    minio_secure: bool = Field(default=False)
    minio_presign_expiry_hours: int = Field(default=24)

    # --- CORS ---
    cors_origins: str = Field(
        default="*",
        description=(
            "Comma-separated list of allowed CORS origins, or '*' for all. "
            "In production, set to your Heritage-LastDance-BE and FE URLs, e.g.: "
            "http://localhost:3000,http://localhost:3001"
        ),
    )

    # --- Redis (arq worker queue) ---
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_password: str = Field(default="")
    redis_db: int = Field(default=0)
    worker_max_jobs: int = Field(default=3, description="Max concurrent ingestion jobs")
    worker_job_timeout: int = Field(default=1800, description="Job timeout in seconds")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS_ORIGINS into a list."""
        value = self.cors_origins.strip()
        if value == "*":
            return ["*"]
        return [o.strip() for o in value.split(",") if o.strip()]


settings = Settings()

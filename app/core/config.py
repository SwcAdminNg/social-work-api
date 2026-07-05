from functools import lru_cache
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Social Workers API"
    app_env: str = "local"
    debug: bool = True

    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str

    # JWT / tokens
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    extended_access_token_expire_minutes: int = 60 * 24 * 30  # 30 days
    refresh_token_expire_days: int = 30
    password_reset_token_expire_minutes: int = 30
    admin_invite_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # SMTP (Gmail)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str
    smtp_password: str
    smtp_from_email: str
    smtp_from_name: str = "Social Workers"
    smtp_use_tls: bool = True

    # Cloudflare R2 (course documents)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_url: str = ""
    presigned_url_expire_seconds: int = 600

    # Bunny.net Stream (course videos)
    bunny_stream_library_id: str = ""
    bunny_stream_api_key: str = ""
    bunny_stream_cdn_hostname: str = ""
    bunny_tus_upload_expire_seconds: int = 3600
    bunny_webhook_secret: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{quote(self.postgres_user, safe='')}:{quote(self.postgres_password, safe='')}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Used by Alembic, which runs migrations synchronously."""
        return (
            f"postgresql+psycopg2://{quote(self.postgres_user, safe='')}:{quote(self.postgres_password, safe='')}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

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

    # Two-factor authentication (email OTP and authenticator app TOTP)
    two_factor_challenge_expire_minutes: int = 10
    totp_issuer_name: str = "Social Workers"
    # Optional dedicated key for encrypting stored TOTP secrets. If unset, a key is
    # derived from jwt_secret_key instead so no new required env var is introduced.
    totp_secret_encryption_key: str = ""

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # Resend (email)
    resend_api_key: str
    resend_from_email: str = "noreply@send.socialworknigeria.org"
    resend_from_name: str = "Social Workers"

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
    bunny_stream_token_auth_key: str = ""
    bunny_tus_upload_expire_seconds: int = 3600
    bunny_webhook_secret: str = ""

    # Paystack
    paystack_secret_key: str = ""
    paystack_public_key: str = ""

    # Upstash QStash
    qstash_url: str = "https://qstash-eu-central-1.upstash.io"
    qstash_token: str = ""
    qstash_current_signing_key: str = ""
    qstash_next_signing_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Help & Support
    # Base URL this API is publicly reachable at, used to build the absolute QStash
    # callback URL for delayed escalation checks (see app/modules/support/service.py).
    api_base_url: str = "http://localhost:8000"
    support_escalation_minutes: int = 5


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

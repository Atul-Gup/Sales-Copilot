from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://showroom:showroom@localhost:5432/showroom_copilot"
    # The Next.js dev server's default origin (T7.1, web/). A deployed
    # frontend origin (T7.4) should be added here, not hardcoded elsewhere.
    cors_allow_origins: list[str] = ["http://localhost:3000"]
    # Shared secret for POST /admin/ingest (T7.4) — a one-off, idempotent
    # schema+corpus provisioning call made once after each deploy, not a
    # general-purpose admin surface. Empty by default so a misconfigured
    # deploy fails closed rather than exposing the endpoint to anyone.
    admin_ingest_token: str = ""

    @field_validator("database_url")
    @classmethod
    def _force_psycopg_driver(cls, value: str) -> str:
        # Managed Postgres providers (Railway, Heroku-style DATABASE_URL) hand
        # out a plain "postgresql://" URL, which SQLAlchemy defaults to the
        # psycopg2 driver. This project only installs psycopg (v3), so a
        # bare scheme must be rewritten to name it explicitly.
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value


settings = Settings()

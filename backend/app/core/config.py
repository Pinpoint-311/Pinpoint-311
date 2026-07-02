from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Known-insecure placeholder values that must never be used outside local/dev.
INSECURE_SECRET_KEYS = {
    "your-secret-key-change-in-production",
    "change-this-in-production",
    "demo-secret-key-pinpoint311-2026",
    "",
}


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://township:township@db/township_db"
    
    # Redis
    redis_url: str = "redis://redis:6379/0"
    
    # JWT
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours
    
    # Initial Admin
    initial_admin_user: str = "admin"
    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "admin123"  # Only used for legacy bootstrap, not a login password
    
    # Google Vertex AI
    google_vertex_project: Optional[str] = None
    google_vertex_location: str = "us-central1"
    
    # Application
    app_name: str = "Township 311"
    debug: bool = False
    
    # Demo mode - single shared demo environment
    demo_mode: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


    def validate_security(self) -> list[str]:
        """Return a list of fatal security misconfigurations.

        Empty list means safe to run in production. Called at startup; when
        debug is False any returned problem aborts boot so a deployment can
        never silently run with forgeable JWTs or a public PII-encryption key
        (both are derived from secret_key).
        """
        problems: list[str] = []
        if self.secret_key in INSECURE_SECRET_KEYS:
            problems.append(
                "SECRET_KEY is unset or a known default. It signs JWTs and derives "
                "the PII encryption key — set a strong unique value (e.g. "
                "`openssl rand -hex 32`)."
            )
        elif len(self.secret_key) < 32:
            problems.append("SECRET_KEY is too short; use at least 32 random characters.")
        return problems


@lru_cache()
def get_settings() -> Settings:
    return Settings()

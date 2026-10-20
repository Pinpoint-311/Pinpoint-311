from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)

# Local/dev database default, assembled from parts so no credential-in-URL
# literal ships in source (real deployments set DATABASE_URL). Override the
# pieces via POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_HOST / POSTGRES_DB.
_DB_USER = os.getenv("POSTGRES_USER", "township")
_DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "township")
_DB_HOST = os.getenv("POSTGRES_HOST", "db")
_DB_NAME = os.getenv("POSTGRES_DB", "township_db")
_DEFAULT_DATABASE_URL = f"postgresql+asyncpg://{_DB_USER}:{_DB_PASSWORD}@{_DB_HOST}/{_DB_NAME}"

# Known-insecure placeholder values that must never be used outside local/dev.
INSECURE_SECRET_KEYS = {
    "your-secret-key-change-in-production",
    "change-this-in-production",
    "demo-secret-key-pinpoint311-2026",
    "",
}


class Settings(BaseSettings):
    # Database
    database_url: str = _DEFAULT_DATABASE_URL
    
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

    # Deployment registration form, if the operator hosts one (e.g. a Microsoft
    # Form). When set, the admin console offers it instead of the built-in
    # contact form. Empty means no form: the in-app fallback is used. The URL
    # may carry {organization}/{deployment_url}/... tokens the console fills in
    # -- see frontend/src/components/contactForm.ts.
    contact_form_url: str = ""
    # Whether that form is shown inside the console in a frame, so somebody can
    # answer it without leaving the page. Off sends them to a new tab instead,
    # which is what a form restricted to the operator's own organisation needs:
    # those render a sign-in page in a frame rather than the questions.
    contact_form_embed: bool = True

    # Overpass endpoints for the weekly critical-facilities refresh, tried in
    # order (comma-separated https URLs). Empty means the main public instance.
    # A town that runs its own Overpass, or has a preferred mirror, sets it
    # here; see app/services/critical_facilities.py.
    overpass_urls: str = ""
    # Geofabrik regions to read critical facilities from (comma-separated index
    # ids such as "us/new-jersey"). Empty picks the region covering the town
    # boundary; "off" skips the extract and goes straight to Overpass. See
    # app/services/osm_extract.py.
    geofabrik_regions: str = ""

    # Managed (state-hosted) mode — orchestrator-driven deployment. Every
    # managed-mode hook is additive and a no-op when this flag is off
    # (docs/ORCHESTRATOR_PLAN.md Part A).
    managed_mode: bool = False
    # Shared secret for the orchestrator's provisioning/telemetry API (A4/A5).
    # The endpoints are inert unless this is set.
    provisioning_token: Optional[str] = None

    # Build/version stamp exposed on /api/health/quick for rollout gating (A3).
    #
    # The image carries it: backend/Dockerfile turns the PINPOINT_VERSION,
    # GIT_SHA, DB_REVISION and MIN_DB_REVISION build args into OCI labels and
    # into these environment variables, so the running code reports exactly
    # what the signed artifact says -- no `git rev-parse` against a mounted
    # checkout (production images have neither git nor a checkout). APP_VERSION
    # is still honoured first because the orchestrator's compose template sets
    # it explicitly. Unset or empty reads as None ("not stamped"), never "dev".
    app_version: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("APP_VERSION", "PINPOINT_VERSION")
    )
    git_sha: Optional[str] = Field(default=None, validation_alias=AliasChoices("GIT_SHA"))
    # The Alembic head this build ships (the schema it migrates the DB to).
    build_db_revision: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("DB_REVISION")
    )
    # Oldest Alembic revision this build can run against (expand/contract rule).
    min_db_revision: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("MIN_DB_REVISION")
    )

    @field_validator("app_version", "git_sha", "build_db_revision", "min_db_revision", mode="before")
    @classmethod
    def _blank_stamp_is_unset(cls, value):
        # A build without the args still has the ENV lines, set to "".
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    class Config:
        env_file = ".env"
        case_sensitive = False
        # Settings(app_version=...) keeps working alongside the env aliases.
        populate_by_name = True


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

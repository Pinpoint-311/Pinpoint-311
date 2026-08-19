import logging
from sqlalchemy import select
from app.models import User, Department, ServiceDefinition, SystemSettings, SystemSecret
from app.core.auth import get_password_hash
from app.core.config import get_settings
from app.db.session import SessionLocal, init_db

logger = logging.getLogger(__name__)
settings = get_settings()


# Default service categories
DEFAULT_SERVICES = [
    {
        "service_code": "POTHOLE",
        "service_name": "Pothole",
        "description": "Report potholes on roads or parking lots",
        "icon": "Circle"
    },
    {
        "service_code": "STREETLIGHT",
        "service_name": "Street Light",
        "description": "Report broken or malfunctioning street lights",
        "icon": "Lightbulb"
    },
    {
        "service_code": "GRAFFITI",
        "service_name": "Graffiti",
        "description": "Report graffiti on public or private property",
        "icon": "Spray"
    },
    {
        "service_code": "TRASH",
        "service_name": "Trash / Litter",
        "description": "Report illegal dumping or litter issues",
        "icon": "Trash2"
    },
    {
        "service_code": "SIDEWALK",
        "service_name": "Sidewalk Issue",
        "description": "Report damaged or hazardous sidewalks",
        "icon": "Footprints"
    },
    {
        "service_code": "SIGN",
        "service_name": "Sign Problem",
        "description": "Report damaged, missing, or obscured signs",
        "icon": "SignpostBig"
    },
    {
        "service_code": "NOISE",
        "service_name": "Noise Complaint",
        "description": "Report excessive noise violations",
        "icon": "Volume2"
    },
    {
        "service_code": "OTHER",
        "service_name": "Other Issue",
        "description": "Report any other municipal concern",
        "icon": "HelpCircle"
    }
]

# Default departments
DEFAULT_DEPARTMENTS = [
    {"name": "Public Works", "description": "Roads, infrastructure, and maintenance", "routing_email": None},
    {"name": "Parks & Recreation", "description": "Parks, trails, and recreation facilities", "routing_email": None},
    {"name": "Code Enforcement", "description": "Property maintenance and code violations", "routing_email": None},
]

# Default secrets (keys only, not values)
DEFAULT_SECRETS = [
    # Auth0 SSO (Required for authentication)
    {"key_name": "AUTH0_DOMAIN", "description": "Auth0 domain (e.g., yourapp.us.auth0.com)"},
    {"key_name": "AUTH0_CLIENT_ID", "description": "Auth0 application client ID"},
    {"key_name": "AUTH0_CLIENT_SECRET", "description": "Auth0 application client secret"},
    
    
    # Google Maps / GIS
    {"key_name": "GOOGLE_MAPS_API_KEY", "description": "Google Maps API key for geocoding and maps (public, browser-facing)"},
    {"key_name": "GOOGLE_MAPS_MAP_ID", "description": "Google Maps Map ID (from Cloud Console, with Feature Layers enabled)"},
    {"key_name": "TOWNSHIP_PLACE_ID", "description": "Google Places ID of the township boundary"},
    
    # AI Analysis
    {"key_name": "VERTEX_AI_PROJECT", "description": "Google Cloud project for Vertex AI"},
    {"key_name": "VERTEX_AI_SERVICE_ACCOUNT_KEY", "description": "Service account JSON key for Vertex AI (optional if using default credentials)"},
    
    # SMS Providers - Twilio
    {"key_name": "SMS_PROVIDER", "description": "SMS provider type: twilio, http, or none"},
    {"key_name": "TWILIO_ACCOUNT_SID", "description": "Twilio account SID"},
    {"key_name": "TWILIO_AUTH_TOKEN", "description": "Twilio auth token"},
    {"key_name": "TWILIO_PHONE_NUMBER", "description": "Twilio phone number (e.g., +1234567890)"},
    
    # SMS Providers - Generic HTTP
    {"key_name": "SMS_HTTP_API_URL", "description": "HTTP SMS API endpoint URL"},
    {"key_name": "SMS_HTTP_API_KEY", "description": "HTTP SMS API key/token"},
    {"key_name": "SMS_FROM_NUMBER", "description": "SMS sender number for HTTP provider"},
    
    # Email SMTP
    {"key_name": "EMAIL_ENABLED", "description": "Enable email notifications: true or false"},
    {"key_name": "SMTP_HOST", "description": "SMTP server hostname (e.g., smtp.gmail.com)"},
    {"key_name": "SMTP_PORT", "description": "SMTP server port (e.g., 587 for TLS, 465 for SSL)"},
    {"key_name": "SMTP_USER", "description": "SMTP username/email"},
    {"key_name": "SMTP_PASSWORD", "description": "SMTP password or app-specific password"},
    {"key_name": "SMTP_FROM_EMAIL", "description": "From email address"},
    {"key_name": "SMTP_FROM_NAME", "description": "From name (e.g., Township 311)"},
    {"key_name": "SMTP_USE_TLS", "description": "Use TLS: true (port 587) or false (SSL on 465)"},
    
    # Database Backups
    {"key_name": "BACKUP_S3_BUCKET", "description": "S3 bucket name for database backups"},
    {"key_name": "BACKUP_S3_ACCESS_KEY", "description": "S3 access key ID"},
    {"key_name": "BACKUP_S3_SECRET_KEY", "description": "S3 secret access key"},
    {"key_name": "BACKUP_ENCRYPTION_KEY", "description": "Passphrase for backup encryption (AES-256)"},
    {"key_name": "BACKUP_S3_ENDPOINT", "description": "S3 endpoint URL (for Oracle/non-AWS, optional)"},
    {"key_name": "BACKUP_S3_REGION", "description": "S3 region (optional)"},
]


# --------------------------------------------------------------------------
# This module does NOT own the schema. app/db/migrate.py does.
# --------------------------------------------------------------------------
#
# It used to own half of it, from two hand-maintained lists that ran on every
# boot after migrate.py had already returned 0, and the two authorities fought
# over the same columns:
#
#   _run_pii_migrations   four unconditional
#                         `ALTER TABLE service_requests ALTER COLUMN ... TYPE
#                         VARCHAR(n)` -- a type rewrite, which migrate.py's own
#                         classifier calls DESTRUCTIVE, executed on every single
#                         boot with no gate, no backup and no revision. The
#                         comment it carried recorded the damage: it had been
#                         saying VARCHAR(200) for phone and Postgres allows a
#                         shrink whenever the stored values happen to fit --
#                         which is exactly the state right after a widen -- so
#                         the first restart after revision e7f8a9b0c1d2 silently
#                         un-widened the column and re-broke KMS phone writes in
#                         production. Raising the literal to 500 stopped that
#                         instance of it and left the mechanism in place.
#
#   _run_schema_migrations
#                         a list of ADD COLUMN IF NOT EXISTS, seven of whose
#                         columns are ALSO added by an Alembic revision. Alembic's
#                         `op.add_column` has no IF NOT EXISTS, so whichever ran
#                         first won -- and when it was this list, the revision
#                         later raised DuplicateColumn and the container refused
#                         to start, permanently, with no printed remedy.
#
# Both are gone. Columns and varchar widths are now derived from the models by
# migrate.py's `reconcile()`, which runs after Alembic under the advisory lock
# and can only add or widen. Deriving beats remembering: there is no second list
# to update, so there is nothing to drift.
#
# What stays below is the DDL the models genuinely cannot express -- a GIST
# index on a cast expression, the PostGIS extension, the location trigger and
# its backfill. None of it is a column, so none of it can contradict a revision:
# an index is derived data and `CREATE INDEX IF NOT EXISTS` twice is a no-op.
# Anything that adds, drops or retypes a COLUMN belongs in a revision. Do not
# put one here.


async def _run_schema_migrations():
    """
    Apply the startup DDL that neither the models nor Alembic express.

    Indexes, extensions and triggers only. Every statement is idempotent and
    none of them is a column -- see the note above this function for why that
    boundary exists and what happened when it did not.
    """
    from app.db.session import sync_engine
    from sqlalchemy import text

    migrations = [
        # One integration per platform. The create endpoint does a
        # SELECT-then-INSERT, so without this two concurrent connects produce two
        # enabled rows for one vendor and every report is pushed there twice.
        # Non-unique index dropped by name first, since this replaces it.
        #
        # Not derivable from the models: the swap from a non-unique index to a
        # unique one of the SAME NAME is two statements in a required order.
        "DROP INDEX IF EXISTS ix_integration_configs_platform",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_integration_configs_platform ON integration_configs (platform)",
        # Road geometry for jurisdiction routing (added 2026-07-29). Road-based
        # blocking used to substring-match configured road names against a
        # reverse-geocoded address string, which attributed corner lots to the
        # cross street and park driveways to the park's mailing address --
        # wrongly turning residents away. These tables hold real centrelines so
        # the decision can be "how far is this pin from that road" instead.
        #
        # The GIST index is on the geography CAST, not the geometry: that is
        # what makes ST_DWithin's threshold true metres everywhere without
        # picking a projected SRID per state. Without it the index is unused and
        # every pin drop sequentially scans the town.
        "CREATE INDEX IF NOT EXISTS ix_road_segments_geog ON road_segments USING GIST ((geom::geography))",
        "CREATE INDEX IF NOT EXISTS ix_road_segments_name_norm ON road_segments (name_norm)",
        "CREATE INDEX IF NOT EXISTS ix_road_segments_ref_norm ON road_segments (ref_norm)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_road_segment_source "
        "ON road_segments (source_id, source_feature_id)",
        # Statistics reads these three together when summarising redirects.
        "CREATE INDEX IF NOT EXISTS ix_blocked_log_created ON blocked_request_log (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_blocked_log_jurisdiction ON blocked_request_log (jurisdiction_name)",
        # PostGIS location geometry + auto-populate trigger (added 2026-07-11).
        # Every geospatial analytic (hotspot clustering, coverage/spread metrics,
        # AI nearby-context) reads service_requests.location. That column is only
        # ever filled by this trigger — previously it lived in an orphaned .sql
        # that nothing ran, so on a fresh deploy location stayed NULL and all of
        # those features silently returned empty. Applying it here (idempotently)
        # guarantees it on every startup. On non-PostGIS/dev DBs these fail
        # harmlessly and are skipped by the per-statement try/except below.
        "CREATE EXTENSION IF NOT EXISTS postgis",
        "UPDATE service_requests SET location = ST_SetSRID(ST_MakePoint(long, lat), 4326) "
        "WHERE lat IS NOT NULL AND long IS NOT NULL AND location IS NULL",
        "CREATE OR REPLACE FUNCTION update_location_geometry() RETURNS TRIGGER AS $$ "
        "BEGIN IF NEW.lat IS NOT NULL AND NEW.long IS NOT NULL THEN "
        "NEW.location := ST_SetSRID(ST_MakePoint(NEW.long, NEW.lat), 4326); "
        "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql",
        "DROP TRIGGER IF EXISTS set_location_geometry ON service_requests",
        "CREATE TRIGGER set_location_geometry BEFORE INSERT OR UPDATE ON service_requests "
        "FOR EACH ROW EXECUTE FUNCTION update_location_geometry()",
    ]
    
    try:
        with sync_engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"Migration OK: {sql[:60]}...")
                except Exception as e:
                    logger.debug(f"Migration note: {e}")
                    conn.rollback()
        logger.info(f"Schema migrations completed ({len(migrations)} checked)")
    except Exception as e:
        logger.warning(f"Could not run schema migrations: {e}")


async def seed_database():
    """Initialize database with default data"""
    
    # Create tables
    await init_db()

    # Indexes, extensions and triggers only. Columns and varchar widths are
    # migrate.py's, and were taken away from here on purpose -- see the note
    # above _run_schema_migrations.
    await _run_schema_migrations()

    async with SessionLocal() as db:
        # Check if already seeded
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none():
            logger.info("Database already seeded, skipping...")
            return
        
        logger.info("Seeding database...")
        
        # Create initial admin user
        admin = User(
            username=settings.initial_admin_user,
            email=settings.initial_admin_email,
            full_name="System Administrator",
            hashed_password=get_password_hash(settings.initial_admin_password),
            role="admin",
            is_active=True
        )
        db.add(admin)
        
        # Create departments
        dept_objects = []
        for dept_data in DEFAULT_DEPARTMENTS:
            dept = Department(**dept_data)
            db.add(dept)
            dept_objects.append(dept)
        
        await db.flush()  # Get IDs for relationships
        
        # Create service definitions
        for service_data in DEFAULT_SERVICES:
            service = ServiceDefinition(**service_data)
            # Assign to first department by default
            if dept_objects:
                service.departments.append(dept_objects[0])
            db.add(service)
        
        # Create system settings (singleton)
        settings_obj = SystemSettings(
            township_name="Your Township",
            hero_text="How can we help?",
            primary_color="#6366f1",
            # Only what has no provider behind it. Anything with credentials and
            # a card is switched in `capability_switches`, which starts empty --
            # a fresh install has answered nothing, and an empty map reads as
            # "not answered" rather than as "off".
            modules={"unlisted_reports": False, "research_portal": False},
            capability_switches={},
        )
        db.add(settings_obj)
        
        # Create secret placeholders
        for secret_data in DEFAULT_SECRETS:
            secret = SystemSecret(**secret_data, is_configured=False)
            db.add(secret)
        
        await db.commit()
        logger.info("Database seeded successfully!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(seed_database())

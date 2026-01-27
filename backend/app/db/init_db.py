import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
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
    {"key_name": "AUTH0_DOMAIN", "description": "Auth0 tenant domain (e.g., yourtown.us.auth0.com)"},
    {"key_name": "AUTH0_CLIENT_ID", "description": "Auth0 application client ID"},
    {"key_name": "AUTH0_CLIENT_SECRET", "description": "Auth0 application client secret"},
    {"key_name": "AUTH0_AUDIENCE", "description": "Auth0 API audience (optional, for API tokens)"},
    
    # Google Maps / GIS
    {"key_name": "GOOGLE_MAPS_API_KEY", "description": "Google Maps API key for geocoding, maps, and translation"},
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


async def seed_database():
    """Initialize database with default data"""
    
    # Create tables
    await init_db()
    
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
            modules={"ai_analysis": False, "sms_alerts": False}
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

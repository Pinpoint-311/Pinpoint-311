from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


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
    initial_admin_password: str = "admin123"
    
    # Emergency Access (secure backdoor)
    emergency_access_token: Optional[str] = None
    
    # Google Vertex AI
    google_vertex_project: Optional[str] = None
    google_vertex_location: str = "us-central1"
    
    # Application
    app_name: str = "Township 311"
    debug: bool = False
    
    # Research Suite (can also be toggled via Admin Console modules)
    enable_research_suite: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

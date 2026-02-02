from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "township_311",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.service_requests"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    worker_prefetch_multiplier=1,
    # Celery Beat Schedule
    beat_schedule={
        # Daily retention enforcement at 1:00 AM UTC (before backup)
        "daily-retention-enforcement": {
            "task": "app.tasks.service_requests.enforce_retention_policy",
            "schedule": 60 * 60 * 24,  # Every 24 hours
            "options": {"queue": "default"}
        },
        # Daily database backup at 2:00 AM UTC
        "daily-database-backup": {
            "task": "app.tasks.service_requests.backup_database",
            "schedule": 60 * 60 * 24,  # Every 24 hours
            "options": {"queue": "default"}
        },
        # Weekly backup cleanup on Sundays at 3:00 AM UTC
        "weekly-backup-cleanup": {
            "task": "app.tasks.service_requests.cleanup_expired_backups",
            "schedule": 60 * 60 * 24 * 7,  # Every 7 days
            "options": {"queue": "default"}
        },
        # Weekly staff digest emails on Mondays at 8:00 AM UTC
        "weekly-staff-digest": {
            "task": "app.tasks.service_requests.send_weekly_digest",
            "schedule": 60 * 60 * 24 * 7,  # Every 7 days
            "options": {"queue": "default"}
        },
    }
)

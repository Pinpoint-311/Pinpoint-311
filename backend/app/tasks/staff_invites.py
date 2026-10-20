"""Celery side of the staff invite email (app/services/staff_invite.py)."""

import logging

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.notifications import notification_service
from app.tasks.service_requests import configure_notifications, run_async

logger = logging.getLogger(__name__)


@celery_app.task
def send_staff_invite(user_id: int, actor_id: int = None):
    """Send one staff invite. Not retried: the outcome is in the audit log
    either way, and the admin console has "Resend invite" for a failure."""
    from app.services.staff_invite import deliver_invite

    async def _run():
        async with SessionLocal() as db:
            await configure_notifications(db)
            return await deliver_invite(db, user_id, actor_id, notification_service.send_email)

    return run_async(_run())

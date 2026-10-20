from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_init, worker_process_init, worker_ready
from app.core.config import get_settings

settings = get_settings()


def _use_null_pool_in_worker(**_kwargs):
    """Worker processes get a connection pool that pools nothing.

    Only in the worker: the API keeps its pool, because it has one event loop
    for the life of the process. A worker gives every task a new loop and
    closes it at the end, so a pooled asyncpg connection is a connection bound
    to a dead loop -- see `app.db.session.use_null_pool` for the traceback this
    removes.

    Both signals, because which one fires depends on the pool implementation:
    forked children get `worker_process_init`, `--pool=solo` only ever sees
    `worker_init`. `use_null_pool` is idempotent, so both firing is fine.
    """
    from app.db.session import use_null_pool
    use_null_pool()


worker_process_init.connect(_use_null_pool_in_worker)
worker_init.connect(_use_null_pool_in_worker)


def _fresh_sync_pool_in_child(**_kwargs):
    """Forked children must not reuse the parent's psycopg2 connections.

    The parent opens some before it forks -- the crash-reporting hook below
    reads the saved Sentry DSN through the secret store, which uses the sync
    engine -- and a fork copies those sockets into every child. Two processes
    then talk over one Postgres connection, which is what Sentry showed as
    "error with status PGRES_TUPLES_OK and no message from the libpq" and
    "server closed the connection unexpectedly" in the notification tasks,
    followed by tasks hanging until the 300 s hard limit killed them.

    `dispose(close=False)` is SQLAlchemy's prescribed fix: the child forgets
    the inherited connections without closing them (closing would cut them
    out from under the parent) and opens its own. Children only; connected
    before the crash-reporting hook so that hook already gets a fresh one.
    """
    from app.db.session import sync_engine
    sync_engine.dispose(close=False)


worker_process_init.connect(_fresh_sync_pool_in_child)


def _crash_reporting_in_worker(**kwargs):
    # The worker never started Sentry at all, so a failing nightly sync or
    # notification task was only ever in the container log.
    from app.core.crash_reporting import init_in_worker
    init_in_worker(**kwargs)


worker_process_init.connect(_crash_reporting_in_worker)
worker_init.connect(_crash_reporting_in_worker)


def _fill_critical_facilities_soon(**_kwargs):
    """A new town (or one upgraded onto the store) fills it within minutes.

    Waiting for the daily beat would leave every report until then with no
    "near a hospital" context at all. The task itself does nothing when the
    store already has rows, so a restart costs one SELECT. Never raises: a
    broker hiccup here must not stop the worker coming up.
    """
    try:
        from app.tasks.critical_facilities import refresh_critical_facilities
        refresh_critical_facilities.apply_async(kwargs={"only_if_empty": True}, countdown=90)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("could not queue the critical-facilities fill", exc_info=True)


worker_ready.connect(_fill_critical_facilities_soon)

celery_app = Celery(
    "township_311",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.service_requests", "app.tasks.integrations", "app.tasks.road_data",
             "app.tasks.storage", "app.tasks.connector_checks", "app.tasks.upgrades",
             "app.tasks.critical_facilities", "app.tasks.staff_invites", "app.tasks.arcgis_sync"]
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
    #
    # No per-entry queue option, deliberately. Every entry used to say
    # queue="default", but the worker consumes Celery's actual default queue
    # (named "celery") -- so every scheduled task ever published went into a
    # queue nobody read. Backups, retention, connector checks: none had ever
    # run except by hand, and 2,695 unconsumed messages were sitting in redis
    # when this was found. Publishing on the default queue is what the manual
    # `celery call` path always did, which is why manual runs worked.
    #
    # Hourly-and-slower entries are crontab (wall-clock), not intervals. An
    # interval counts from worker boot and resets on every restart, so during
    # any stretch of active deployment the daily jobs simply never fired --
    # connector checks, backups, retention, all of them -- and several of the
    # comments below promised wall-clock times ("2:00 AM UTC") the interval
    # never honoured. A crontab fires at the stated time whatever the uptime.
    # The 15-minute pollers stay intervals: they fire within minutes of boot
    # regardless, and a fixed-minute stampede buys nothing.
    beat_schedule={
        # Upgrade requests whose host updater stopped reporting become failed
        # (app/tasks/upgrades.py). Interval, not crontab: it is a sweep.
        "upgrade-request-lease": {
            "task": "app.tasks.upgrades.expire_stale_upgrade_requests",
            "schedule": 60 * 5,
        },
        # Proactive health scan: warn admins by email before something fails
        # (disk/memory/connections/backup staleness), every 15 minutes.
        "proactive-health-scan": {
            "task": "app.tasks.service_requests.proactive_health_scan",
            "schedule": 60 * 15,  # Every 15 minutes
        },
        # Road centreline refresh. Fires daily but acts on one day a month --
        # the day is derived from a hash of the township name so deployments
        # spread across the month instead of all hitting a publisher on the 1st.
        # Publishers republish about monthly (NJ's statewide NG911 layer does),
        # and stale road data fails open, so lag costs a new street going
        # unblocked briefly rather than a resident being turned away.
        "monthly-road-refresh": {
            "task": "app.tasks.road_data.refresh_roads_monthly",
            "schedule": crontab(hour=4, minute=15),  # checked daily, acts monthly
        },
        # Hospitals, schools, fire stations... for the "near critical
        # infrastructure" check. Checked daily, refreshes when a week old (or
        # empty), so a failed refresh is retried the next day. One Overpass
        # query for the whole town; reports never call out.
        # While the store is still empty (a new install, or the public
        # Overpass instance was down on the first try), retry every hour
        # instead of waiting a day. A no-op once anything is loaded.
        "hourly-critical-facilities-fill": {
            "task": "app.tasks.critical_facilities.refresh_critical_facilities",
            "schedule": crontab(minute=20),
            "kwargs": {"only_if_empty": True},
        },
        "daily-critical-facilities-check": {
            "task": "app.tasks.critical_facilities.refresh_critical_facilities",
            "schedule": crontab(hour=4, minute=45),
        },
        # Map layers an admin set to sync from ArcGIS daily or weekly. Hourly
        # sweep; each layer is due on its own interval, and an unchanged
        # source costs a request or two (app/tasks/arcgis_sync.py).
        "hourly-arcgis-layer-sync": {
            "task": "app.tasks.arcgis_sync.sync_arcgis_layers",
            "schedule": crontab(minute=23),
        },
        # Test every configured connector once a day.
        #
        # "The credentials are stored" is a fact about our database and stays
        # true forever; "the credentials work" is a fact about somebody else's
        # service and stops being true without warning. Without this the only
        # way to learn a key was revoked is an admin pressing Test, or a
        # resident who never got their email.
        # Infrastructure, hourly. A disk fills in hours; a connector's
        # credentials do not expire faster than once a day.
        "hourly-system-probe": {
            "task": "app.tasks.connector_checks.probe_system",
            "schedule": crontab(minute=7)
        },
        "daily-connector-check": {
            "task": "app.tasks.connector_checks.verify_connectors",
            "schedule": crontab(hour=9, minute=0)
        },
        # Daily anchor of the audit hash-chain head (tamper-evidence beyond the DB)
        "daily-audit-anchor": {
            "task": "app.tasks.service_requests.anchor_audit_chain",
            "schedule": crontab(hour=0, minute=30)
        },
        # Daily retention enforcement at 1:00 AM UTC (before backup)
        "daily-retention-enforcement": {
            "task": "app.tasks.service_requests.enforce_retention_policy",
            "schedule": crontab(hour=1, minute=0)
        },
        # Photos screened at pick time that no report ever claimed. Hourly,
        # because the handles only live an hour and because every unclaimed row
        # is a full-size image written by an unauthenticated endpoint.
        "hourly-photo-handle-reap": {
            "task": "app.tasks.service_requests.reap_expired_photo_handles",
            "schedule": crontab(minute=40)
        },
        # Daily purge of IP addresses older than 90 days (privacy commitment)
        "daily-ip-purge": {
            "task": "app.tasks.service_requests.purge_old_ip_addresses",
            "schedule": crontab(hour=1, minute=30)
        },
        # Daily database backup at 2:00 AM UTC
        "daily-database-backup": {
            "task": "app.tasks.service_requests.backup_database",
            "schedule": crontab(hour=2, minute=0)
        },
        # Weekly backup cleanup on Sundays at 3:00 AM UTC
        "weekly-backup-cleanup": {
            "task": "app.tasks.service_requests.cleanup_expired_backups",
            "schedule": crontab(hour=3, minute=0, day_of_week="sunday")
        },
        # Poll connected govtech platforms for external status changes
        "pull-integration-updates": {
            "task": "app.tasks.integrations.pull_integration_updates",
            "schedule": 60 * 15,  # Every 15 minutes
        },
        # Import new external comments on linked, active requests
        "pull-integration-comments": {
            "task": "app.tasks.integrations.pull_integration_comments",
            "schedule": 60 * 15,  # Every 15 minutes
        },
        # Push again whatever failed to reach a vendor and is due another try.
        # Ten minutes rather than fifteen: the first backoff step is five, and a
        # slower beat than the schedule it serves would round every early
        # attempt up to the beat interval.
        "retry-integration-dead-letters": {
            "task": "app.tasks.integrations.retry_integration_dead_letters",
            "schedule": 60 * 10,
        },
        # Mirror external asset inventories into Pinpoint map layers
        "sync-integration-assets": {
            "task": "app.tasks.integrations.sync_integration_assets",
            "schedule": crontab(hour=5, minute=0)
        },
        # Weekly staff digest emails on Mondays at 8:00 AM UTC
        "weekly-staff-digest": {
            "task": "app.tasks.service_requests.send_weekly_digest",
            "schedule": crontab(hour=8, minute=0, day_of_week="monday")
        },
        # Storage hygiene that used to be two buttons on the setup page. Both
        # verify before they change anything and are no-ops with nothing to do,
        # so nobody has to work out whether they apply.
        "hourly-secret-vaulting": {
            "task": "app.tasks.storage.vault_secrets",
            "schedule": crontab(minute=37)
        },
        "nightly-pii-rewrap": {
            "task": "app.tasks.storage.rewrap_pii",
            "schedule": crontab(hour=6, minute=0)
        },
        # Refresh the live AI model lists so the picker stays current and can
        # flag a retired/deprecated model without anyone opening the admin UI.
        "daily-ai-model-refresh": {
            "task": "app.tasks.service_requests.refresh_ai_models",
            "schedule": crontab(hour=10, minute=0)
        },
    }
)

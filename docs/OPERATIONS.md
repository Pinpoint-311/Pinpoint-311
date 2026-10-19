# Operations

Running a Pinpoint 311 instance after it is set up: upgrades, migrations,
backups, health, and crash reporting. Related runbooks:
[RELEASES.md](RELEASES.md) (signed images, `release.lock`, the host updater),
[DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) (restore and key loss), and
[SENTRY_SETUP.md](SENTRY_SETUP.md).

- [Upgrades](#upgrades)
- [Database migrations](#database-migrations)
- [Backups and restore](#backups-and-restore)
- [Health and monitoring](#health-and-monitoring)
- [Crash reporting](#crash-reporting)

## Upgrades

Nothing updates itself. Production runs signed images pinned by digest in a
per-instance `release.lock`; containers hold no source checkout and no Docker
socket, so editing files in the checkout changes nothing until a new image is
deployed. The old in-app, git-based version switcher has been removed.

### From the Admin Console (with the host updater)

The host updater (`updater/`) is a small systemd service outside the Docker
stack. It is the only component with Docker access, it exposes no port, and it
talks to the backend over its loopback port with a revocable token.

1. An admin opens **Version Control**, picks a release the updater reported as *Signature verified* and *Schema compatible*, and gives a reason. Every admin is emailed.
2. While **two-person approval** is on (the default), a different admin approves it. Restarts need one admin. An instance can make two-person approval non-negotiable host-side with `require_two_person_approval: true` in `instances.yml`.
3. On its next one-minute poll the updater claims the request and runs: preflight (cosign signature and the schema window) → verified backup → pull by digest → migrate → recreate → health check → commit `release.lock`, or roll back to the previous digests. Each step reports to the console as it finishes, and heartbeats keep the request's lease alive during long steps.
4. A destructive migration stops the run as *On hold* with the old version still serving. After checking the backup, file a new request with *Allow a destructive migration*.
5. If the updater stops reporting for `UPGRADE_LEASE_MINUTES` (default 45), the request is marked failed and every admin is emailed.

Setup: [RELEASES.md, "Connecting the host updater"](RELEASES.md#connecting-the-host-updater)
and [updater/README.md](../updater/README.md). Design and threat model:
[design/secure-upgrades.md](design/secure-upgrades.md).

### From the command line

Take a backup first. Then either let the updater do it from the host:

```bash
sudo -u pinpoint-updater pinpoint-updater plan    <instance> v1.8.0   # dry run
sudo -u pinpoint-updater pinpoint-updater upgrade <instance> v1.8.0
```

or pin the release in `release.lock` yourself (digests are in each release's
notes) and run:

```bash
docker compose --env-file .env --env-file release.lock pull
docker compose --env-file .env --env-file release.lock up -d
```

To track the newest published images instead (`docker compose pull` fetches them):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

[RELEASES.md](RELEASES.md) covers verifying a release's signature with cosign
before you deploy it, and moving a stack that still mounts the source onto images.

## Database migrations

The backend and worker entrypoint (`backend/scripts/entrypoint.sh`) runs
`python -m app.db.migrate` before starting. Under a Postgres advisory lock, it:

1. Takes a `pg_dump` into the `migration_backups` volume and keeps the newest three. These dumps are unencrypted copies of the database and stay on the host.
2. Applies pending Alembic revisions that are additive.
3. Adds missing columns and widens text columns to match the models.

A migration that would drop or rewrite data is never applied automatically. The
container stops and prints what an operator has to run
(`PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION=1`). Through the host updater, the same
gate holds the run for approval.

| Exit code | Meaning |
| --- | --- |
| `1` | Database unreachable |
| `2` | A destructive migration needs a human |
| `3` | The pre-migration dump failed, so nothing was applied |

```bash
docker compose exec backend alembic current
docker compose exec backend alembic heads
```

## Backups and restore

Configure **Automatic backups** on the Setup & Integration page: an
S3-compatible endpoint, bucket, access key, secret key, optional region, and an
encryption passphrase. **Save & Test** writes, reads back, and deletes a test
object, and checks that the passphrase can encrypt and decrypt.

- The worker takes a backup daily at 02:00 UTC: `pg_dump -Fc`, encrypted with GPG AES-256, uploaded as `db_backup_YYYYMMDD_HHMMSS.sql.gpg`.
- Old backups are removed weekly according to the records-retention setting. If retention is not configured, every backup is kept.
- **Compliance > Database Backups** lists backups and can create, delete, or restore one. Restore requires an explicit confirmation and overwrites the current database. It is disabled in managed mode.
- `python -m app.cli.backup --verify` (what the host updater runs before an upgrade) takes a backup, restores it into a scratch database and compares table counts.
- If PII is encrypted with a cloud KMS, a restore also needs that key to still exist.

> [!IMPORTANT]
> Keep the backup encryption passphrase somewhere other than the server. A
> backup cannot be restored without it.

> [!WARNING]
> Backups contain the database only. Files staff upload through the console live
> in the `uploads_data` Docker volume and are not included. Back that volume up
> separately.

Restore and disaster-recovery procedures: [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md).

## Health and monitoring

- `GET /api/health/quick` needs no authentication and returns status, version, git SHA, and database revision. Use it for external uptime monitoring.
- `GET /api/health/` (admin only) checks the database, identity provider, KMS, secret store, AI, translation, and credential expiry.
- The worker runs a proactive health scan every 15 minutes (disk, memory, connections, backup age, a live KMS wrap, the translation budget, redaction model files, and more) and emails administrators about problems. Known outages can be muted for a bounded period under System Health without hiding them from the dashboard.
- Connections to town systems are checked daily; failed syncs are retried every 10 minutes and listed under Failed syncs.
- The audit chains are anchored nightly; **Verify integrity** in the audit log recomputes the chain on demand.
- Compose health checks restart unresponsive `backend`, `worker`, and `frontend` containers, and every service uses `restart: unless-stopped`.

## Crash reporting

Paste a Sentry DSN on the **Crash reporting** card of the Setup & Integration
page. The API reads the saved DSN at startup, and the worker reads it when each
worker process starts, so restart both after saving:

```bash
docker compose restart backend worker
```

A `SENTRY_DSN` environment variable, if set, takes precedence. Events are sent
with `send_default_pii=False`, and switching crash reporting off on the setup
page drops events. See [SENTRY_SETUP.md](SENTRY_SETUP.md).

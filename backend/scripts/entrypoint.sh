#!/usr/bin/env bash
#
# Container entrypoint: reconcile the schema, then serve.
#
# The API must not start against a database it could not bring up to the
# image's schema. Serving traffic on a half-migrated database means writing to
# it, and a partial write is much harder to recover from than a container that
# refused to boot with a clear message in the log.
#
# Exit codes from the migrator, all deliberately distinct so an operator reading
# `docker compose ps` can tell what happened without digging:
#
#   0  schema is at head (or was already)
#   1  could not reach or read the database
#   2  a destructive migration is pending and needs a human
#   3  the pre-migration backup failed, so nothing was applied
#
set -euo pipefail

echo "[entrypoint] checking database schema"
python -m app.db.migrate
status=$?

if [ "$status" -ne 0 ]; then
    echo "[entrypoint] schema check failed (exit ${status}); refusing to start the API" >&2
    exit "$status"
fi

echo "[entrypoint] schema OK; starting API"
exec "$@"

"""Process exit codes. Stable: scripts and the systemd unit depend on them.

====  ==================  ===================================================
code  outcome             meaning
====  ==================  ===================================================
0     succeeded/noop/...  done (or nothing to do; plan/verify passed)
1     error               unexpected error; read the message
2     usage               bad arguments, invalid config, or the instance's
                          release.lock / env file is missing
3     refused             stopped before anything changed: resolve, signature,
                          schema window, disk, backup or pull failed
4     needs_approval      a destructive migration is pending; nothing applied,
                          the current version is still serving
5     rolled_back         the new release was unhealthy; the previous digests
                          are serving again (database not restored)
6     rollback_failed     unhealthy AND the rollback failed: act now
7     locked              another run holds this instance's lock
8     not_confirmed       no --yes and the prompt was declined / not a TTY
9     migration_failed    the migrator failed; containers not recreated, the
                          current version still serving; check the schema
====  ==================  ===================================================
"""

from pinpoint_updater import models

OK = 0
ERROR = 1
USAGE = 2
REFUSED = 3
NEEDS_APPROVAL = 4
ROLLED_BACK = 5
ROLLBACK_FAILED = 6
LOCKED = 7
NOT_CONFIRMED = 8
MIGRATION_FAILED = 9

BY_OUTCOME = {
    models.SUCCEEDED: OK,
    models.NOOP: OK,
    models.PLANNED_OUTCOME: OK,
    models.VERIFIED: OK,
    models.REFUSED: REFUSED,
    models.GATED: NEEDS_APPROVAL,
    models.ROLLED_BACK: ROLLED_BACK,
    models.ROLLBACK_FAILED: ROLLBACK_FAILED,
    models.MIGRATION_FAILED: MIGRATION_FAILED,
    models.ERROR: ERROR,
    "locked": LOCKED,
    "not_confirmed": NOT_CONFIRMED,
}


def for_outcome(outcome: str) -> int:
    return BY_OUTCOME.get(outcome, ERROR)

"""Restoring an uploaded backup.

A restore drill on 2026-10-18 (download from the bucket, decrypt, pg_restore into
a throwaway PostGIS database) restored every table exactly -- and pg_restore
still exited 1 with four "errors", so the app's restore reported failure.
"""

import inspect

import pytest

backup = pytest.importorskip("app.services.backup_service")

DRILL_STDERR = """\
pg_restore: error: could not execute query: ERROR:  unrecognized configuration parameter "transaction_timeout"
Command was: SET transaction_timeout = 0;
pg_restore: error: could not execute query: ERROR:  schema "tiger" already exists
pg_restore: error: could not execute query: ERROR:  schema "tiger_data" already exists
pg_restore: error: could not execute query: ERROR:  schema "topology" already exists
pg_restore: warning: errors ignored on restore: 4
"""


def test_the_drill_output_is_a_success():
    assert backup.restore_errors(DRILL_STDERR) == []


def test_a_real_error_is_still_a_failure():
    stderr = DRILL_STDERR + 'pg_restore: error: could not execute query: ERROR:  relation "service_requests" does not exist\n'
    real = backup.restore_errors(stderr)
    assert len(real) == 1 and "service_requests" in real[0]


def test_restore_snapshots_the_current_database_first():
    src = inspect.getsource(backup.restore_backup)
    assert src.index("create_database_dump(snapshot_path)") < src.index("restore_database_dump(decrypted_path)")
    assert "pre_restore_snapshot" in src


def test_restore_does_not_depend_on_the_original_database_owner():
    src = inspect.getsource(backup.restore_database_dump)
    assert '"--no-owner"' in src and '"--no-privileges"' in src

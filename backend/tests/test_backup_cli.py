"""`python -m app.cli.backup --verify`, the backup step pinpoint-updater runs
before every upgrade. It must print one JSON object, exit 0 only for a backup
that was taken and (with --verify) restored with matching table counts, and
never touch the live database as its scratch target."""

import json

import pytest

backup_service = pytest.importorskip("app.services.backup_service")
cli = pytest.importorskip("app.cli.backup")

LIVE = "postgresql+asyncpg://township:pw@db/township_db"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    state = {"counts": {LIVE: [{"service_requests": 10, "users": 2}, {"service_requests": 11, "users": 2}]},
             "restored": {"service_requests": 11, "users": 2}, "dropped": [], "created": []}
    monkeypatch.setenv("DATABASE_URL", LIVE)

    async def create_backup():
        return {"status": "success", "backup_name": "db_backup_20261018_120000.sql.gpg", "size_bytes": 2048,
                "bucket": "b"}

    async def get_backup_config():
        return {"BACKUP_ENCRYPTION_KEY": "k"}

    async def download_backup(name, path):
        open(path, "wb").write(b"x")
        return True

    def table_counts(url):
        if url == LIVE:
            return state["counts"][LIVE].pop(0)
        return state["restored"]

    def create_scratch(live):
        state["created"].append(live)
        return "postgresql://township:pw@db/scratch", "scratch"

    monkeypatch.setattr(backup_service, "create_backup", create_backup)
    monkeypatch.setattr(backup_service, "get_backup_config", get_backup_config)
    monkeypatch.setattr(backup_service, "download_backup", download_backup)
    monkeypatch.setattr(backup_service, "decrypt_file", lambda i, o, k: open(o, "wb").write(b"d") or True)
    monkeypatch.setattr(cli, "table_counts", table_counts)
    monkeypatch.setattr(cli, "create_scratch", create_scratch)
    monkeypatch.setattr(cli, "drop_scratch", lambda live, name: state["dropped"].append(name))
    monkeypatch.setattr(cli, "restore_into", lambda dump, url: None)
    return state


def _run(capsys, argv):
    code = cli.main(argv)
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


def test_verified_backup_reports_ok_and_drops_its_scratch_database(fake, capsys):
    code, report = _run(capsys, ["--verify"])
    assert code == 0
    assert report["status"] == "ok" and report["verified"] is True
    assert report["backup_name"].startswith("db_backup_")
    assert report["tables"] == 2 and report["mismatches"] == []
    assert fake["dropped"] == ["scratch"]


def test_a_short_table_fails_verification(fake, capsys):
    fake["restored"] = {"service_requests": 3, "users": 2}
    code, report = _run(capsys, ["--verify"])
    assert code == 1 and report["status"] == "error" and report["verified"] is False
    assert report["mismatches"][0]["table"] == "service_requests"
    assert fake["dropped"] == ["scratch"]


def test_a_missing_table_fails_verification(fake, capsys):
    fake["restored"] = {"service_requests": 11}
    code, report = _run(capsys, ["--verify"])
    assert code == 1 and any(m["table"] == "users" and m["restored"] is None for m in report["mismatches"])


def test_refuses_the_live_database_as_scratch(fake, capsys):
    code, report = _run(capsys, ["--verify", "--scratch-url", "postgresql://other:x@db:5432/township_db"])
    assert code == 1 and "live database" in report["message"]
    assert fake["created"] == []


def test_unconfigured_backups_are_an_error(fake, capsys, monkeypatch):
    async def not_configured():
        return {"status": "error", "message": "Backup not configured - add S3 credentials"}

    monkeypatch.setattr(backup_service, "create_backup", not_configured)
    code, report = _run(capsys, ["--verify"])
    assert code == 1 and "not configured" in report["message"]


def test_without_verify_only_creates(fake, capsys):
    code, report = _run(capsys, [])
    assert code == 0 and report["verified"] is False and fake["created"] == []


def test_unexpected_errors_do_not_leak_their_message(fake, capsys, monkeypatch):
    async def boom():
        raise RuntimeError("postgresql://township:hunter2@db/x unreachable")

    monkeypatch.setattr(backup_service, "create_backup", boom)
    code, report = _run(capsys, [])
    assert code == 1 and "hunter2" not in json.dumps(report)


def test_same_database_ignores_driver_and_credentials():
    assert cli.same_database(LIVE, "postgresql://x:y@db:5432/township_db")
    assert not cli.same_database(LIVE, "postgresql://x:y@db/township_db_verify")
    assert cli.same_database(LIVE, "postgresql://x:y@DB.:5432/township_db")


def test_a_provided_scratch_database_must_be_empty(fake, capsys, monkeypatch):
    """An alias the URL check cannot see through (a container IP, a second
    hostname) would make the "scratch" database the live one, and pg_restore
    would append every row to production. A non-empty target is refused."""
    restored = []
    monkeypatch.setattr(cli, "restore_into", lambda dump, url: restored.append(url))
    code, report = _run(capsys, ["--verify", "--scratch-url", "postgresql://township:pw@172.18.0.5/township_db"])
    assert code == 1 and "not empty" in report["message"]
    assert restored == [] and fake["created"] == [] and fake["dropped"] == []


def test_an_empty_provided_scratch_database_is_used(fake, capsys, monkeypatch):
    scratch = "postgresql://township:pw@db/verify_target"
    seen = {"calls": 0}
    real = cli.table_counts

    def counts(url):
        if url == scratch:
            seen["calls"] += 1
            return {} if seen["calls"] == 1 else fake["restored"]
        return real(url)

    monkeypatch.setattr(cli, "table_counts", counts)
    code, report = _run(capsys, ["--verify", "--scratch-url", scratch])
    assert code == 0 and report["verified"] is True and report["scratch"] == "provided"

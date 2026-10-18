"""Backups: endpoint as providers show it, passphrase off the command line,
and a real test that reports what is missing."""
import asyncio
import inspect

import pytest

b = pytest.importorskip("app.services.backup_service")


def test_a_bare_host_endpoint_gets_https():
    """Backblaze shows "s3.us-east-005.backblazeb2.com"; boto3 rejected it."""
    assert b.normalize_endpoint("s3.us-east-005.backblazeb2.com") == "https://s3.us-east-005.backblazeb2.com"
    assert b.normalize_endpoint("https://s3.example.com/") == "https://s3.example.com"
    assert b.normalize_endpoint("http://minio:9000") == "http://minio:9000"
    assert b.normalize_endpoint("") is None and b.normalize_endpoint(None) is None


def test_a_blank_region_no_longer_signs_for_oracle():
    """A blank Region used to become us-ashburn-1, which AWS S3 rejects."""
    assert b.resolve_region(None, "") == "us-east-1"
    assert b.resolve_region(None, None) == "us-east-1"
    assert b.resolve_region("https://s3.us-east-005.backblazeb2.com", "") == "us-east-005"
    assert b.resolve_region("https://minio:9000", "  ") is None
    assert b.resolve_region("https://s3.us-east-005.backblazeb2.com", "eu-central-003") == "eu-central-003"
    client = b.get_s3_client({"BACKUP_S3_ACCESS_KEY": "a", "BACKUP_S3_SECRET_KEY": "s"})
    assert client.meta.region_name == "us-east-1"


def test_the_passphrase_never_appears_on_the_gpg_command_line():
    for fn in (b.encrypt_file, b.decrypt_file):
        src = inspect.getsource(fn)
        assert '"--passphrase", passphrase' not in src
        assert '"--passphrase-fd", "0"' in src and "input=passphrase" in src


def test_the_test_names_what_is_missing(monkeypatch):
    async def get_secret(key):
        return {"BACKUP_S3_BUCKET": "b"}.get(key)
    monkeypatch.setattr("app.services.secret_manager.get_secret", get_secret)
    out = asyncio.run(b.test_backups())
    assert out["ok"] is False
    assert "access key ID" in out["detail"] and "secret access key" in out["detail"]


def test_a_missing_passphrase_fails_after_the_storage_check(monkeypatch):
    async def get_secret(key):
        return {"BACKUP_S3_BUCKET": "b", "BACKUP_S3_ACCESS_KEY": "a", "BACKUP_S3_SECRET_KEY": "s"}.get(key)
    monkeypatch.setattr("app.services.secret_manager.get_secret", get_secret)
    monkeypatch.setattr(b, "_test_storage_round_trip", lambda cfg: {"bucket": "b", "endpoint": "AWS S3"})
    out = asyncio.run(b.test_backups())
    assert out["ok"] is False
    assert "Wrote a test file" in out["detail"] and "No backup passphrase" in out["detail"]


def test_an_oracle_endpoint_names_its_region():
    assert b.resolve_region("https://ns.compat.objectstorage.us-ashburn-1.oraclecloud.com", "") == "us-ashburn-1"

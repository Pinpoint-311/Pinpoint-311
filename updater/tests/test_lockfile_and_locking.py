import os

import pytest

from conftest import OLD, OLDER
from pinpoint_updater import lockfile
from pinpoint_updater.lockfile import ImageSet, LockFileError, LockState, read_lock, write_lock
from pinpoint_updater.locking import LOCK_NAME, InstanceLock, InstanceLocked


def test_round_trip_keeps_previous_and_extra_keys(tmp_path):
    p = tmp_path / "release.lock"
    write_lock(p, LockState(current=OLD, previous=OLDER, extra={"PINPOINT_CHANNEL": "stable"}))
    state = read_lock(p)
    assert state.current == OLD and state.previous == OLDER and state.extra == {"PINPOINT_CHANNEL": "stable"}
    text = p.read_text()
    assert "BACKEND_IMAGE=" + OLD.backend in text and "PREVIOUS_BACKEND_IMAGE=" + OLDER.backend in text


def test_rewrite_is_atomic_when_the_rename_fails(tmp_path, monkeypatch):
    p = tmp_path / "release.lock"
    write_lock(p, LockState(current=OLD))
    before = p.read_bytes()

    def boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(lockfile.os, "replace", boom)
    with pytest.raises(OSError):
        write_lock(p, LockState(current=OLDER, previous=OLD))
    assert p.read_bytes() == before
    assert [f.name for f in tmp_path.iterdir()] == ["release.lock"]  # no temp file left behind


def test_rewrite_is_atomic_when_the_write_fails(tmp_path, monkeypatch):
    p = tmp_path / "release.lock"
    write_lock(p, LockState(current=OLD))
    before = p.read_bytes()
    real_fsync = os.fsync
    calls = {"n": 0}

    def failing_fsync(fd):
        calls["n"] += 1
        raise OSError(5, "I/O error")

    monkeypatch.setattr(lockfile.os, "fsync", failing_fsync)
    with pytest.raises(OSError):
        write_lock(p, LockState(current=OLDER))
    monkeypatch.setattr(lockfile.os, "fsync", real_fsync)
    assert p.read_bytes() == before and calls["n"] == 1
    assert [f.name for f in tmp_path.iterdir()] == ["release.lock"]


def test_rewrite_fsyncs_file_and_directory_and_keeps_mode(tmp_path, monkeypatch):
    p = tmp_path / "release.lock"
    write_lock(p, LockState(current=OLD))
    os.chmod(p, 0o600)
    synced = []
    real = os.fsync
    monkeypatch.setattr(lockfile.os, "fsync", lambda fd: (synced.append(fd), real(fd)))
    write_lock(p, LockState(current=OLDER, previous=OLD))
    assert len(synced) == 2  # the temp file, then the directory
    assert (p.stat().st_mode & 0o777) == 0o600
    assert read_lock(p).current == OLDER


def test_refuses_values_that_could_inject_into_an_env_file(tmp_path):
    with pytest.raises(LockFileError):
        write_lock(tmp_path / "release.lock", LockState(current=ImageSet("v1\nEVIL=1", OLD.backend, OLD.frontend)))


def test_missing_or_incomplete_lock_is_an_error(tmp_path):
    with pytest.raises(LockFileError):
        read_lock(tmp_path / "nope")
    (tmp_path / "l").write_text("PINPOINT_VERSION=v1\nBACKEND_IMAGE=x\n")
    with pytest.raises(LockFileError, match="FRONTEND_IMAGE"):
        read_lock(tmp_path / "l")


def test_reads_quoted_values_and_comments(tmp_path):
    (tmp_path / "l").write_text('# hi\nPINPOINT_VERSION="v1"\nBACKEND_IMAGE=\'b@sha256:x\'\nexport FRONTEND_IMAGE=f\n')
    s = read_lock(tmp_path / "l")
    assert s.current == ImageSet("v1", "b@sha256:x", "f") and s.previous is None


def test_instance_lock_is_exclusive_and_released(tmp_path):
    a = InstanceLock(tmp_path, "town")
    b = InstanceLock(tmp_path, "town")
    with a:
        assert not b.available()
        with pytest.raises(InstanceLocked):
            b.acquire()
    assert b.available()


def test_instance_lock_refuses_a_symlink(tmp_path):
    victim = tmp_path / "other-release.lock"
    victim.write_text("PINPOINT_VERSION=v1\n")
    (tmp_path / LOCK_NAME).symlink_to(victim)
    with pytest.raises(InstanceLocked, match="symlink"):
        InstanceLock(tmp_path, "town").acquire()
    assert victim.read_text() == "PINPOINT_VERSION=v1\n"   # not truncated

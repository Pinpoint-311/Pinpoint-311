"""A disk filling up should reach somebody before the database stops writing."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import system_probes as P

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


class TestDisk:
    def test_plenty_of_room_is_fine(self):
        assert P.classify_disk(41)["ok"] is True

    def test_filling_up_is_raised_before_it_is_urgent(self):
        """The point of a warning is that there is still time to act on it."""
        out = P.classify_disk(85)
        assert out["ok"] is False
        assert out["recorded"] is True

    def test_nearly_full_says_what_actually_breaks(self):
        """"Disk 94%" means nothing to a clerk. "The database stops accepting
        new reports" is the same fact in terms they can escalate."""
        out = P.classify_disk(94)
        assert out["ok"] is False
        assert "stops accepting new reports" in out["detail"]

    def test_the_boundary_counts_as_over_it(self):
        assert P.classify_disk(P.DISK_WARN_PERCENT)["ok"] is False
        assert P.classify_disk(P.DISK_WARN_PERCENT - 0.1)["ok"] is True

    def test_an_unreadable_disk_is_not_reported_as_a_full_one(self):
        """Not every host exposes this. A failure we cannot substantiate must
        not be written to health, or it becomes a badge that never clears."""
        out = P.classify_disk(None)
        assert out["ok"] is False
        assert out["recorded"] is False

    def test_the_thresholds_leave_room_to_act(self):
        assert P.DISK_WARN_PERCENT < P.DISK_CRITICAL_PERCENT < 100


class TestBackups:
    def test_a_recent_backup_is_fine(self):
        assert P.classify_backup(NOW - timedelta(hours=6), NOW)["ok"] is True

    def test_never_backed_up_says_so_plainly(self):
        out = P.classify_backup(None, NOW)
        assert out["ok"] is False
        assert "restored" in out["detail"]

    def test_one_missed_night_is_a_blip(self):
        assert P.classify_backup(NOW - timedelta(hours=30), NOW)["ok"] is True

    def test_two_is_a_pattern(self):
        out = P.classify_backup(NOW - timedelta(days=3), NOW)
        assert out["ok"] is False
        assert "3 days ago" in out["detail"]

    def test_a_naive_timestamp_does_not_explode(self):
        naive = (NOW - timedelta(hours=2)).replace(tzinfo=None)
        assert P.classify_backup(naive, NOW)["ok"] is True


class TestNaming:
    def test_every_probe_has_a_human_name(self):
        for connector in P.LABELS:
            assert P.is_system(connector)
            assert P.label_for(connector) != connector

    def test_an_unknown_probe_still_gets_a_readable_name(self):
        assert P.label_for("system:queue_depth") == "Queue depth"

    def test_a_connector_is_not_mistaken_for_a_probe(self):
        for connector in ("ai", "maps", "email", "sms"):
            assert not P.is_system(connector)

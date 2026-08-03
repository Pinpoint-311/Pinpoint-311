"""Records retention must not guess which state a town is in.

``retention_state_code`` defaulted to ``NJ`` in the model and again in five
separate ``or "NJ"`` fallbacks. That is the duration a resident's report is kept
and the statute cited when it is destroyed -- so a town in Texas anonymised
records on New Jersey's seven-year OPRA clock, four years before the Texas
Public Information Act allows, while the compliance tab headlined "OPRA" at it.

Two things are tested here. That the guess is gone, and that removing it fails
safe: an unconfigured town archives *nothing* rather than falling through to
some other implicit number.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODELS = (ROOT / "app/models.py").read_text()
TASK = (ROOT / "app/tasks/service_requests.py").read_text()
API = (ROOT / "app/api/system.py").read_text()
BACKUPS = (ROOT / "app/services/backup_service.py").read_text()
HEALTH = (ROOT / "app/services/proactive_health.py").read_text()

pytest.importorskip("sqlalchemy")

from app.services.retention_config import (  # noqa: E402
    NO_SETTINGS, NO_STATE, UNCONFIRMED, read_retention_config,
)


class _Settings:
    """A stand-in for the SystemSettings row, with the defaults it now has."""

    def __init__(self, **kw):
        self.retention_state_code = kw.get("retention_state_code")
        self.retention_state_confirmed = kw.get("retention_state_confirmed", False)
        self.retention_days_override = kw.get("retention_days_override")
        self.retention_mode = kw.get("retention_mode")
        self.retention_scrub_fields = kw.get("retention_scrub_fields")
        self.legal_hold = kw.get("legal_hold", False)


# --------------------------------------------------------------------------- #
# The guess is gone
# --------------------------------------------------------------------------- #

class TestNoStateIsAssumed:
    def test_the_column_has_no_default(self):
        line = next(l for l in MODELS.splitlines()
                    if l.strip().startswith("retention_state_code"))
        assert 'default="NJ"' not in line, "the NJ column default is back"
        assert "default=" not in line, (
            "any default here is the same bug wearing a different state: it "
            "makes an unconfigured town look configured"
        )

    @pytest.mark.parametrize("source,name", [
        (TASK, "the retention task"),
        (API, "the system API"),
        (BACKUPS, "the backup pruner"),
    ])
    def test_nothing_falls_back_to_nj(self, source, name):
        """Changing only the column default would have left these restoring it."""
        offenders = re.findall(r'.*(?:or|else)\s+"NJ".*', source)
        assert not offenders, f"{name} still falls back to NJ: {offenders}"

    def test_no_other_state_was_substituted(self):
        """The fix is not "default to somewhere else"."""
        for source in (TASK, BACKUPS):
            fallbacks = re.findall(r'(?:or|else)\s+"[A-Z]{2}"', source)
            assert not fallbacks, f"an implicit state default reappeared: {fallbacks}"


# --------------------------------------------------------------------------- #
# What "unconfigured" means
# --------------------------------------------------------------------------- #

class TestResolvingTheConfiguration:
    def test_no_settings_row_is_not_configured(self):
        assert read_retention_config(None).configured is False
        assert read_retention_config(None).reason == NO_SETTINGS

    def test_no_state_is_not_configured(self):
        config = read_retention_config(_Settings())
        assert config.configured is False
        assert config.reason == NO_STATE
        assert config.state_code is None

    def test_an_inherited_state_is_not_configured(self):
        """The heart of it. A stored NJ that nobody confirmed is the default
        having materialised into a row, and it is indistinguishable from a
        deliberate choice -- so it is treated as the unsafe one."""
        config = read_retention_config(_Settings(retention_state_code="NJ"))
        assert config.configured is False
        assert config.reason == UNCONFIRMED
        # Still reported, because the console has to show it in order to ask.
        assert config.state_code == "NJ"

    def test_a_confirmed_state_is_configured(self):
        config = read_retention_config(
            _Settings(retention_state_code="TX", retention_state_confirmed=True))
        assert config.configured is True
        assert config.state_code == "TX"
        assert config.reason is None

    def test_confirming_nj_works_too(self):
        """A town genuinely in New Jersey is not punished for the old default."""
        config = read_retention_config(
            _Settings(retention_state_code="NJ", retention_state_confirmed=True))
        assert config.configured is True
        assert config.state_code == "NJ"

    def test_the_reason_says_what_to_do(self):
        config = read_retention_config(_Settings(retention_state_code="NJ"))
        assert config.detail
        assert "Document Retention" in config.detail, (
            "an unconfigured warning that does not say where to go is a dead end"
        )

    def test_a_null_mode_resolves_the_way_every_reader_assumed(self):
        """Live rows predate the retention_mode default and hold NULL."""
        config = read_retention_config(
            _Settings(retention_state_code="NJ", retention_state_confirmed=True))
        assert config.mode == "redact"

    def test_the_state_code_is_normalised(self):
        config = read_retention_config(
            _Settings(retention_state_code=" tx ", retention_state_confirmed=True))
        assert config.state_code == "TX"

    def test_a_blank_state_is_not_a_state(self):
        config = read_retention_config(
            _Settings(retention_state_code="  ", retention_state_confirmed=True))
        assert config.configured is False
        assert config.reason == NO_STATE


# --------------------------------------------------------------------------- #
# Failing safe
# --------------------------------------------------------------------------- #

class TestNothingIsDestroyedWhenUnconfigured:
    def test_the_task_stops_before_touching_a_record(self):
        block = TASK[TASK.index("def enforce_retention_policy"):]
        block = block[:block.index("\n@celery_app.task")]
        guard = block.index("if not config.configured:")
        # The call, not the import at the top of the function.
        first_query = block.index("await get_records_for_archival(")
        assert guard < first_query, (
            "the unconfigured check must come before anything is selected for "
            "archival, or the fail-safe is decorative"
        )
        assert "skipped_unconfigured" in block

    def test_the_run_button_refuses_rather_than_reporting_success(self):
        """Queuing a job that declines leaves the admin with a task id and the
        word "started" -- the contradiction only visible in a worker log."""
        block = API[API.index("async def run_retention_now"):]
        block = block[:block.index("\n@router")]
        assert "if not config.configured:" in block
        assert "409" in block
        assert block.index("if not config.configured:") < block.index("enforce_retention_policy.delay")

    def test_the_preview_does_not_offer_a_schedule_nobody_chose(self):
        block = API[API.index("async def preview_retention_run"):]
        block = block[:block.index("\n@router")]
        assert '"blocked": "unconfigured"' in block

    def test_the_policy_endpoint_says_it_is_unconfigured(self):
        block = API[API.index("async def get_current_retention_policy"):]
        block = block[:block.index("\n@router")]
        assert '"configured": False' in block
        assert '"policy": None' in block, (
            "reporting a policy object for a town that has none is how the tab "
            "came to headline OPRA in Texas"
        )

    def test_the_backup_pruner_keeps_everything(self):
        block = BACKUPS[BACKUPS.index("async def cleanup_old_backups"):]
        block = block[:block.index("\nasync def ")]
        assert "retention_unconfigured" in block
        assert "7 * 365" not in block, (
            "the bare seven-year fallback is a second guess on the destructive "
            "side of the decision"
        )

    def test_the_export_does_not_cite_a_law_it_cannot_name(self):
        """The CSV preamble headlines a statute and leaves the building.

        It read "OPRA EXPORT / State: New Jersey (NJ)" on every deployment. On
        a town in Texas that is a false legal citation on a document the
        requester keeps. The export still runs -- withholding public records
        over a missing setting would be the wrong failure -- but it stops
        naming a law nobody chose.
        """
        assert "law=law, state_name=state_name" in API
        assert 'law=policy["public_records_law"]' not in API


# --------------------------------------------------------------------------- #
# Somebody has to be told
# --------------------------------------------------------------------------- #

class TestTheConsoleIsToldAboutIt:
    def test_there_is_a_proactive_check(self):
        assert "_retention_check" in HEALTH
        assert "await _retention_check(db)" in HEALTH, (
            "a check that is defined but not in collect_checks reports nothing"
        )

    def test_it_warns_rather_than_passing_silently(self):
        block = HEALTH[HEALTH.index("async def _retention_check"):]
        block = block[:block.index("\nasync def ")]
        assert '"warning"' in block
        assert "action=" in block, "a warning with no next step is just noise"

    def test_confirming_is_what_the_admin_console_writes(self):
        block = API[API.index("async def update_retention_policy"):]
        block = block[:block.index("\n@router")]
        assert "settings.retention_state_confirmed = True" in block
        # Inside the `if state_code:` branch. Saving a mode or a field list must
        # not confirm a schedule nobody looked at.
        assert block.index("if state_code:") < block.index(
            "settings.retention_state_confirmed = True")
        assert block.index("settings.retention_state_confirmed = True") < block.index(
            "if override_days is not None:")

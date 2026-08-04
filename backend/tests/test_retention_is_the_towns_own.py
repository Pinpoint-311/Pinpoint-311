"""Records retention runs on the town's own schedule, or it does not run.

This started life as `test_retention_state_is_chosen.py`, which pinned a
narrower fix: `retention_state_code` had defaulted to ``NJ``, so a town in Texas
anonymised records on a seven-year clock it never chose, and the fix was to stop
inheriting the state until an administrator confirmed one.

Confirming a state is no longer a thing to do, because the state never told us
anything worth having. Behind the code sat a table of retention periods for all
51 US jurisdictions that nobody had verified -- 41 of the 51 said five years --
and a fallback citing Federal FOIA at municipalities. Confirming "yes, Texas" got
a clerk a number we had made up, presented with the Texas State Library named as
its source. See test_no_invented_retention_policy.py for the table itself.

So both halves are the municipality's to state, with nothing pre-filled: how
long a closed request is kept, and what a run removes when that expires. What
carries over unchanged from the original file is the shape of the guarantee --
the guess is gone, removing it fails safe, and somebody is told.
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
    NO_FIELDS, NO_PERIOD, NO_SETTINGS, read_retention_config,
)


class _Settings:
    """A stand-in for the SystemSettings row, with the defaults it now has."""

    def __init__(self, **kw):
        self.retention_days = kw.get("retention_days")
        self.retention_mode = kw.get("retention_mode")
        self.retention_scrub_fields = kw.get("retention_scrub_fields")
        self.legal_hold = kw.get("legal_hold", False)


def _configured(**kw):
    """A town that has answered both questions."""
    kw.setdefault("retention_days", 1825)
    kw.setdefault("retention_scrub_fields", ["name", "email"])
    return _Settings(**kw)


# --------------------------------------------------------------------------- #
# Nothing is assumed
# --------------------------------------------------------------------------- #

class TestNothingIsAssumed:
    def test_the_period_column_has_no_default(self):
        line = next(l for l in MODELS.splitlines()
                    if l.strip().startswith("retention_days ="))
        assert "default=" not in line, (
            "any default here makes an unconfigured town look configured, and "
            "the thing it looks configured to do is destroy records"
        )

    def test_the_scrub_column_has_no_default(self):
        line = next(l for l in MODELS.splitlines()
                    if l.strip().startswith("retention_scrub_fields"))
        assert "default=" not in line

    def test_the_state_columns_are_gone(self):
        for column in ("retention_state_code", "retention_state_confirmed"):
            assert column not in MODELS, (
                f"{column} is back. Nothing is inherited from a state any more, "
                f"so there is nothing for it to hold."
            )

    @pytest.mark.parametrize("source,name", [
        (TASK, "the retention task"),
        (API, "the system API"),
        (BACKUPS, "the backup pruner"),
    ])
    def test_no_implicit_state_reappeared(self, source, name):
        """The original failure mode, kept pinned. Changing only the column
        default would have left these restoring it."""
        offenders = re.findall(r'(?:or|else)\s+"[A-Z]{2}"', source)
        assert not offenders, f"{name} fell back to a state again: {offenders}"

    @pytest.mark.parametrize("source,name", [
        (TASK, "the retention task"),
        (BACKUPS, "the backup pruner"),
    ])
    def test_no_implicit_period_reappeared(self, source, name):
        """The same bug wearing a number instead of a state code. `or 7 * 365`
        and `or 2555` are the shapes to watch for, on the destructive side of
        the decision."""
        offenders = re.findall(r'(?:or|else)\s+\d+\s*\*\s*365', source)
        offenders += re.findall(r'retention_days\s*(?:or|else)\s+\d{3,}', source)
        assert not offenders, f"{name} fell back to a period again: {offenders}"


# --------------------------------------------------------------------------- #
# What "unconfigured" means, and which half is missing
# --------------------------------------------------------------------------- #

class TestResolvingTheConfiguration:
    def test_no_settings_row_is_not_configured(self):
        config = read_retention_config(None)
        assert config.configured is False
        assert config.reason == NO_SETTINGS

    def test_no_period_is_not_configured(self):
        config = read_retention_config(_Settings(retention_scrub_fields=["name"]))
        assert config.configured is False
        assert config.reason == NO_PERIOD

    def test_no_chosen_fields_is_not_configured(self):
        """A period with nothing selected is not a policy that removes nothing;
        it is a policy nobody has written. A run would still stamp archived_at,
        which takes the record out of every future run's candidate set -- so the
        record passes out of retention's reach with its PII intact."""
        config = read_retention_config(_Settings(retention_days=1825))
        assert config.configured is False
        assert config.reason == NO_FIELDS

    def test_an_explicitly_emptied_selection_is_still_not_a_policy(self):
        config = read_retention_config(
            _Settings(retention_days=1825, retention_scrub_fields=[]))
        assert config.configured is False
        assert config.reason == NO_FIELDS

    def test_both_halves_together_are_configured(self):
        config = read_retention_config(_configured())
        assert config.configured is True
        assert config.retention_days == 1825
        assert config.scrub_fields == ["name", "email"]
        assert config.reason is None

    @pytest.mark.parametrize("settings,expected", [
        (None, NO_SETTINGS),
        (_Settings(), NO_PERIOD),
        (_Settings(retention_days=1825), NO_FIELDS),
    ])
    def test_the_reason_says_which_half_is_missing(self, settings, expected):
        """"Not configured" is not actionable. A clerk needs to know whether
        they are being asked for a number or for a list of fields."""
        config = read_retention_config(settings)
        assert config.reason == expected
        assert config.detail
        assert "Document Retention" in config.detail, (
            "a warning that does not say where to go is a dead end"
        )

    @pytest.mark.parametrize("stored", [0, -1, "", None, "not a number"])
    def test_a_period_that_is_not_a_period_is_read_as_unset(self, stored):
        """Zero arrives from a cleared form field. Reading it as "everything is
        eligible today" is the one interpretation that must never be inferred."""
        config = read_retention_config(
            _Settings(retention_days=stored, retention_scrub_fields=["name"]))
        assert config.configured is False
        assert config.reason == NO_PERIOD

    def test_a_null_mode_resolves_the_way_every_reader_assumed(self):
        """Live rows predate the retention_mode default and hold NULL."""
        assert read_retention_config(_configured()).mode == "redact"

    def test_an_unconfigured_town_still_gets_back_what_it_has_filled_in(self):
        """The screen has to render the half-finished form it is asking somebody
        to finish. Reporting the stored value is not permission to act on it."""
        config = read_retention_config(_Settings(retention_days=1825))
        assert config.configured is False
        assert config.retention_days == 1825


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
        assert block.index("if not config.configured:") < block.index(
            "enforce_retention_policy.delay")

    def test_the_preview_does_not_offer_a_schedule_nobody_chose(self):
        block = API[API.index("async def preview_retention_run"):]
        block = block[:block.index("\n@router")]
        assert '"blocked": "unconfigured"' in block

    def test_the_policy_endpoint_says_it_is_unconfigured_and_why(self):
        block = API[API.index("async def get_current_retention_policy"):]
        block = block[:block.index("\n@router")]
        assert '"configured": False' in block
        assert '"reason": config.reason' in block
        assert '"detail": config.detail' in block

    def test_the_backup_pruner_keeps_everything(self):
        block = BACKUPS[BACKUPS.index("async def cleanup_old_backups"):]
        block = block[:block.index("\nasync def ")]
        assert "retention_unconfigured" in block
        assert "7 * 365" not in block, (
            "the bare seven-year fallback is a second guess on the destructive "
            "side of the decision"
        )


# --------------------------------------------------------------------------- #
# Legal hold outranks everything
# --------------------------------------------------------------------------- #

class TestLegalHoldOverridesThePolicy:
    """The last stop before irreversible deletion, so it is pinned explicitly.

    A hold is placed because a town is in litigation or has been served, and it
    means *nothing* is purged -- not "nothing beyond the policy", not "nothing
    except the records that are very old". A configured policy is exactly the
    situation in which a hold has to win, because that is the only situation in
    which anything would otherwise be destroyed.
    """

    def test_the_task_checks_the_hold_before_it_reads_the_policy(self):
        block = TASK[TASK.index("def enforce_retention_policy"):]
        block = block[:block.index("\n@celery_app.task")]
        hold = block.index('getattr(settings, "legal_hold", False)')
        config = block.index("config = read_retention_config(settings)")
        assert hold < config, (
            "a hold that is only checked after the policy resolves is one "
            "refactor away from being checked after the deletion"
        )
        assert "skipped_legal_hold" in block

    def test_the_task_returns_before_selecting_anything(self):
        block = TASK[TASK.index("def enforce_retention_policy"):]
        block = block[:block.index("\n@celery_app.task")]
        assert block.index("skipped_legal_hold") < block.index(
            "await get_records_for_archival("
        )

    def test_a_fully_configured_policy_does_not_beat_a_hold(self):
        """Written as source inspection deliberately: the guard has no
        dependency on `config`, so no policy value can reach past it."""
        block = TASK[TASK.index("def enforce_retention_policy"):]
        block = block[:block.index("\n@celery_app.task")]
        guard = block[block.index('if settings is not None and getattr(settings, "legal_hold"'):]
        guard = guard[:guard.index("config = read_retention_config")]
        assert "config" not in guard, (
            "the hold must not consult the policy it is overriding"
        )

    def test_the_preview_reports_the_hold_rather_than_listing_records(self):
        """Listing records that "will be archived next run" while a hold means
        nothing can be is the sort of contradiction that gets a screen
        distrusted."""
        block = API[API.index("async def preview_retention_run"):]
        block = block[:block.index("\n@router")]
        assert '"blocked": "legal_hold"' in block
        assert block.index('"blocked": "legal_hold"') < block.index(
            "if not config.configured:"
        ), "the hold is reported first, whatever the policy says"

    def test_an_individually_held_record_is_never_selected(self):
        """The per-record hold, which is the flag a clerk sets on one report.
        Both the eligibility query and the archiver refuse it."""
        service = (ROOT / "app/services/retention_service.py").read_text()
        selection = service[service.index("async def get_records_for_archival"):]
        selection = selection[:selection.index("\nasync def ")]
        assert "ServiceRequest.flagged == False" in selection

        archive = service[service.index("async def archive_record"):]
        archive = archive[:archive.index("\nasync def ")]
        assert "if record.flagged:" in archive
        assert archive.index("if record.flagged:") < archive.index("apply_scrub(")


# --------------------------------------------------------------------------- #
# The migration has to survive databases that are behind
# --------------------------------------------------------------------------- #

class TestTheColumnsAreRetiredSafely:
    """A plain DROP COLUMN would fail outright on two live databases.

    The provisioned tenants (pp311_town1, pp311_town_two) never received
    `retention_state_confirmed` -- they are behind on migrations -- so dropping
    it unconditionally raises, and takes every later statement in the upgrade
    down with it. Alembic then leaves those instances stuck at a revision they
    cannot move off.
    """

    MIGRATION = next(
        (ROOT / "alembic/versions").glob("*town_sets_its_own_retention*")
    ).read_text()

    def test_it_reads_the_columns_that_are_there_before_acting(self):
        assert "sa.inspect(bind)" in self.MIGRATION
        upgrade = self.MIGRATION[self.MIGRATION.index("def upgrade("):
                                 self.MIGRATION.index("def downgrade(")]
        assert upgrade.index("cols = _columns()") < upgrade.index("op.")

    def test_both_state_columns_are_retired(self):
        assert '"retention_state_code"' in self.MIGRATION
        assert '"retention_state_confirmed"' in self.MIGRATION

    def test_no_drop_happens_outside_a_presence_check(self):
        drops = [l for l in self.MIGRATION.splitlines() if "op.drop_column(" in l]
        assert drops, "the migration stopped dropping anything"
        for line in drops:
            # Every drop is inside the `if column in cols:` loop body, which is
            # the only place indentation runs this deep in this file.
            assert line.startswith(" " * 12), f"unguarded drop: {line.strip()}"

    def test_a_missing_table_is_not_an_error(self):
        """Fresh installs build system_settings from the models and never run
        the chain against a table that exists yet."""
        assert "if not cols:" in self.MIGRATION
        assert "return" in self.MIGRATION

    def test_the_rename_is_guarded_in_both_directions(self):
        """Renaming onto a name that already exists fails as hard as dropping
        one that does not."""
        assert 'if OLD_DAYS in cols and NEW_DAYS not in cols:' in self.MIGRATION

    def test_the_downgrade_restores_no_state(self):
        """Coming back down must not restart destruction on a schedule nobody
        chose. The reverted code reads NULL as "not configured" and pauses,
        which is the safe direction."""
        down = self.MIGRATION[self.MIGRATION.index("def downgrade("):]
        assert '"NJ"' not in down and "'NJ'" not in down


# --------------------------------------------------------------------------- #
# Somebody has to be told, and kept told
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

    def test_it_names_the_consequence_rather_than_the_status(self):
        """This is the one real cost of having no default period: a town that
        never configures keeps resident personal data for ever, and data
        minimisation is its own obligation. Off by default is still right --
        under-deletion is recoverable, over-deletion is not -- but a neutral
        "not configured" badge lets it stay quiet, which is how it stays true.
        """
        block = HEALTH[HEALTH.index("async def _retention_check"):]
        block = block[:block.index("\nasync def ")]
        assert "indefinitely" in block, (
            "say what is happening to resident data, not that a field is empty"
        )

    def test_every_reason_carries_that_consequence_into_the_ui(self):
        """The detail string is what the setup page, the health dashboard and
        the console all render. It is the only place the sentence exists."""
        for settings in (None, _Settings(), _Settings(retention_days=1825)):
            detail = read_retention_config(settings).detail
            assert "indefinitely" in detail, detail

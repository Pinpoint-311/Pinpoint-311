"""Running retention is destructive, unbounded, and was one click away.

Two separate problems, reported together.

It stopped after a hundred records with nothing on screen saying so, which for
a town with five thousand expired records meant fifty presses of a button that
looked finished each time -- while the retention policy the town publishes says
those records are gone. The gap between the claim and the database widened
every day nobody noticed.

And in `delete` mode it destroys resident records permanently, with no preview,
no confirmation, and a response that returned before the task had touched
anything.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = (ROOT / "app/tasks/service_requests.py").read_text()
API = (ROOT / "app/api/system.py").read_text()
BLOCK = TASK[TASK.index("def enforce_retention_policy"):]
BLOCK = BLOCK[:BLOCK.index("\n@celery_app.task")]


def _const(name: str) -> int:
    """Read a module constant without importing the module.

    `app.tasks.service_requests` imports Celery, which CI does not install, so
    importing it here would skip these tests in exactly the environment that is
    supposed to enforce them.
    """
    m = re.search(rf"^{name} = (\d+)$", TASK, re.M)
    assert m, f"{name} is gone"
    return int(m.group(1))


class TestItProcessesEverything:
    def test_it_no_longer_stops_at_a_hundred(self):
        assert "limit=100" not in BLOCK, "the hundred-record cap is back"

    def test_it_keeps_going_until_there_is_nothing_left(self):
        assert "while True:" in BLOCK
        assert "limit=BATCH_SIZE" in BLOCK

    def test_it_still_works_in_batches(self):
        """Not one transaction over five thousand rows: that holds locks for
        the duration and fails all-or-nothing."""
        assert 1 <= _const("BATCH_SIZE") <= 1000

    def test_a_batch_of_untouchable_records_does_not_loop_for_ever(self):
        """Records under legal hold stay eligible by design -- they are past
        their date and must not be archived -- so a batch of nothing but held
        records would be re-fetched for ever."""
        assert "archived_this_batch == 0" in BLOCK

    def test_the_runaway_guard_is_far_above_any_real_backlog(self):
        assert _const("BATCH_SIZE") * _const("MAX_BATCHES") >= 100_000

    def test_hitting_the_guard_is_reported_rather_than_called_success(self):
        assert "more_remaining" in BLOCK


class TestItAsksFirst:
    def test_there_is_a_preview(self):
        assert '"/retention/preview"' in API
        assert "async def preview_retention_now" in API or "async def preview_retention_run" in API

    def test_the_preview_separates_what_will_be_skipped(self):
        """"142 eligible" and "142 eligible, 3 of which will be skipped" are
        different sentences to somebody approving a deletion."""
        for field in ('"eligible"', '"on_legal_hold"', '"will_act_on"'):
            assert field in API

    def test_the_preview_says_which_mode_is_in_force(self):
        """Anonymise and delete are not the same act and the button never said
        which one it was about to perform."""
        assert '"mode": mode' in API

    def test_deleting_requires_the_word_back(self):
        """A modal is a client-side courtesy. Anything a stray fetch can do
        should not include destroying resident records."""
        block = API[API.index("async def run_retention_now"):]
        block = block[:block.index("\n@router")]
        assert 'confirm' in block
        assert '"DELETE"' in block
        assert "status_code=400" in block

    def test_anonymising_does_not_demand_the_word(self):
        """Reversible enough not to need ceremony; asking for a password every
        time is how people learn to type it without reading."""
        block = API[API.index("async def run_retention_now"):]
        block = block[:block.index("\n@router")]
        assert 'mode == "delete"' in block

    def test_a_legal_hold_is_reported_before_anything_is_offered(self):
        assert '"blocked": "legal_hold"' in API

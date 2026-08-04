"""The product does not know any town's retention schedule, and must not say it does.

This file used to be the data-contract test for `STATE_RETENTION_POLICIES`: a
table of retention periods and public-records statutes covering all 51 US
jurisdictions, each entry naming that state's records authority as its "source".
The tests checked that every entry carried a law name and that years was the
floor of days over 365 -- internal consistency, which the table had, and which
is the wrong question.

The right question was where the numbers came from, and the answer was nowhere.
Forty-one of the fifty-one periods were five years; the rest were six, seven,
three or ten. One number wearing fifty-one different citations. A clerk reading
"5 years, source: Alabama State Records Commission" had every reason to believe
somebody had looked it up, and if the real schedule is longer the town destroys
records it was legally required to keep, permanently and with no undo.

`test_unknown_state_falls_back_to_default_policy` pinned the worst of it: towns
outside the table were told they were governed by "Federal FOIA", which applies
to federal executive-branch agencies and has nothing to do with a municipal
pothole report.

So the tests are inverted. What is pinned now is the absence -- that no table,
no fallback and no statute name comes back, in any form.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

pytest.importorskip("sqlalchemy")

import app.services.retention_service as rs  # noqa: E402

# Every .py under app/, read once. The guarantee is about the codebase, not
# about one module: moving the table to a new file would satisfy a narrower
# test and reintroduce the whole problem.
SOURCES = {str(p.relative_to(ROOT)): p.read_text() for p in APP.rglob("*.py")}


def _emitted_strings(source: str):
    """Every string literal the module can actually *produce*.

    Docstrings are excluded, and that distinction is the point rather than a
    convenience. Explaining in prose that the export used to head its files
    "OPRA EXPORT / State: New Jersey (NJ)" is how the next reader learns why it
    must not do that again; emitting the same characters is the bug. A bare
    string statement is a docstring or a block comment either way, so the test
    is about what reaches a user, not about which words appear in a file.
    """
    tree = ast.parse(source)
    prose = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in prose
    ]


EMITTED = {path: _emitted_strings(source) for path, source in SOURCES.items()}


class TestTheTableIsGone:
    def test_the_service_no_longer_supplies_a_policy(self):
        for name in ("STATE_RETENTION_POLICIES", "get_all_states",
                     "get_retention_policy", "calculate_retention_date"):
            assert not hasattr(rs, name), (
                f"{name} is back. This module enforces the schedule a town "
                f"states; it does not supply one."
            )

    def test_no_module_holds_a_lookup_of_states_to_periods(self):
        offenders = [p for p, s in SOURCES.items() if "STATE_RETENTION_POLICIES" in s]
        assert not offenders, f"the state table reappeared in {offenders}"

    def test_no_state_code_maps_to_a_number_of_days_anywhere(self):
        """The shape of the old table, rather than its name.

        `{"NJ": {"days": 7 * 365, ...}}` is the thing being forbidden, and
        renaming the constant would not make it any less invented.
        """
        pattern = re.compile(r'"[A-Z]{2}"\s*:\s*\{[^}]*\bdays\b')
        offenders = [p for p, s in SOURCES.items() if pattern.search(s)]
        assert not offenders, f"a state-to-period table reappeared in {offenders}"


class TestNoStatuteIsNamed:
    def test_nothing_claims_to_know_which_law_applies(self):
        """`public_records_law` was a legal citation printed on exports.

        The town knows which law it answers under. We do not, and a wrong
        citation on a document that leaves the building is worse than none.
        """
        offenders = [p for p, s in SOURCES.items() if "public_records_law" in s]
        assert not offenders, f"a statute field reappeared in {offenders}"

    def test_federal_foia_is_not_offered_to_municipalities(self):
        """The old DEFAULT entry. 5 USC 552 binds federal executive-branch
        agencies and has no bearing on a town's own records, so that one was not
        merely unverified but wrong."""
        offenders = sorted(p for p, strings in EMITTED.items()
                           if any("Federal FOIA" in s for s in strings))
        assert not offenders, f"Federal FOIA is being cited again in {offenders}"

    def test_no_statute_abbreviation_is_emitted_as_a_value(self):
        """OPRA, CPRA, FOIL, GRAMA and the rest, as strings the product prints.

        Several of the old names were accurate -- Connecticut, Michigan,
        Delaware, Arkansas, South Carolina and West Virginia really do call
        their laws FOIA. Accuracy was never the whole problem: the product
        asserting which statute a town is complying with is, because that is a
        legal claim made on the town's behalf by software nobody told.
        """
        pattern = re.compile(
            r"\b(OPRA|CPRA|FOIL|GRAMA|TPIA|MGDPA|VFOIA|IPRA|KORA|MPIA)\b"
        )
        offenders = sorted(p for p, strings in EMITTED.items()
                           if any(pattern.search(s) for s in strings))
        assert not offenders, f"a statute name is being emitted from {offenders}"


class TestThePeriodComesFromTheTown:
    def test_the_functions_that_remain_take_a_period_rather_than_a_state(self):
        for fn in (rs.get_records_for_archival, rs.get_retention_stats):
            params = inspect.signature(fn).parameters
            assert "retention_days" in params, f"{fn.__name__} lost the period"
            assert "state_code" not in params, (
                f"{fn.__name__} still asks which state the town is in"
            )

    def test_there_is_no_default_period_to_fall_back_on(self):
        """A signature default here would be the whole bug in one keyword: a
        town that configured nothing would get a schedule anyway."""
        for fn in (rs.get_records_for_archival, rs.get_retention_stats):
            default = inspect.signature(fn).parameters["retention_days"].default
            assert default is inspect.Parameter.empty, (
                f"{fn.__name__} defaults the retention period to {default!r}"
            )

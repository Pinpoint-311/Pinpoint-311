"""The monthly trend groups by the expression it selects.

The statistics page reported "Platform feedback: Request failed" for any town
with the module switched on, and the cause was one clause of one query. The
grouping expression was written out twice as

    func.to_char(PlatformFeedback.submitted_at, "YYYY-MM")

and SQLAlchemy bound that format string as a parameter each time, so Postgres
received `to_char(submitted_at, $1)` in the SELECT and `to_char(submitted_at,
$3)` in the GROUP BY. It cannot know two placeholders hold the same value, so
the grouped expression did not match the selected one:

    column "platform_feedback.submitted_at" must appear in the GROUP BY clause

The unit suite runs on SQLite, which has no to_char at all and would never have
reproduced it. So this compiles the statement for the PostgreSQL dialect and
reads the SQL, which needs no database and catches exactly the shape that broke.
"""

import pytest

pytest.importorskip("sqlalchemy.dialects.postgresql")
pytest.importorskip("fastapi.routing")

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.api.feedback import month_bucket
from app.models import PlatformFeedback


def _sql() -> str:
    month = month_bucket()
    statement = (
        select(month, func.count(PlatformFeedback.id))
        .group_by(month)
    )
    return str(statement.compile(dialect=postgresql.dialect()))


def test_the_format_is_inlined_rather_than_bound():
    """A bound format is the whole bug: two placeholders, one expression."""
    sql = _sql()
    assert "'YYYY-MM'" in sql, sql
    # Exactly the failure signature -- a parameter where the format should be.
    assert "to_char(platform_feedback.submitted_at, %(" not in sql, sql


def test_the_grouped_expression_matches_the_selected_one():
    sql = _sql()
    select_part, _, group_part = sql.partition("GROUP BY")

    assert group_part.strip(), "the query no longer groups at all"
    expression = "to_char(platform_feedback.submitted_at, 'YYYY-MM')"
    assert expression in select_part, select_part
    assert expression in group_part, group_part


def test_the_bucket_is_a_year_and_month():
    """AdvancedStatistics.requests_by_month uses the same shape; a trend keyed
    differently from every other trend on that page cannot be lined up with
    them."""
    assert "'YYYY-MM'" in _sql()

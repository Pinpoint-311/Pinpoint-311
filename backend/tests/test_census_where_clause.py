"""The Census boundary search builds an ArcGIS `where` clause from typed text.

TIGERweb evaluates it as SQL. The town name went in raw, so an apostrophe
("Coeur d'Alene") broke the query and any quote let the input rewrite it.
"""

import pytest

pytest.importorskip("fastapi.routing")

from app.api.gis import census_name_where  # noqa: E402


def test_plain_name():
    assert census_name_where("Princeton", "34") == "UPPER(BASENAME) LIKE '%PRINCETON%' AND STATE = '34'"


def test_apostrophe_is_a_literal_not_the_end_of_the_string():
    assert census_name_where("Coeur d'Alene", "16") == (
        "UPPER(BASENAME) LIKE '%COEUR D''ALENE%' AND STATE = '16'"
    )


def test_quote_cannot_escape_the_literal():
    clause = census_name_where("x' OR STATE <> '", "34")
    # Every quote the user typed is doubled, so the only unpaired quotes are the
    # four the clause itself opens and closes.
    body = clause.replace("''", "")
    assert body.count("'") == 4
    assert clause.endswith("AND STATE = '34'")

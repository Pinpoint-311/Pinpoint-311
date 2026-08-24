"""Translation that bills must also be translation that is counted.

The usage page reported 6,569 characters while the translation cache held
846,782. The whole difference was translate_batch, which calls the provider and
records nothing -- and translate_batch is the path an unauthenticated request
reaches through the public service catalog. A spend nobody can see is a spend
nobody can cap, and it is why a bill could arrive with no local evidence either
way.
"""
import inspect
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("fastapi.routing")

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_the_batch_path_records_what_it_spends():
    """Every path that calls the provider must also record the characters.

    translate_text recorded; translate_batch did not, and translate_batch is the
    one an unauthenticated request reaches. The usage page reported 6,569
    characters while the cache held 846,782 -- the difference is entirely this
    function, and a spend nobody can see is a spend nobody can cap.
    """
    translation = pytest.importorskip("app.services.translation")
    source = inspect.getsource(translation.translate_batch)
    assert "track_api_usage" in source, (
        "translate_batch calls the provider without recording usage, so "
        "resident-facing translation is missing from every cost figure"
    )

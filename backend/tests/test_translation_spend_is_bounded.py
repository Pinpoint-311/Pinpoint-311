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


def test_the_public_translate_endpoint_bounds_what_one_request_may_ask_for():
    """An unauthenticated endpoint that spends money needs a ceiling.

    `POST /system/translate/batch` took an arbitrary list of arbitrary-length
    strings and translated all of them on the town's cloud account. On 17 August
    2026 the demo translated 674,448 characters of text that is not in its own
    database -- 54 reports totalling 2,679 characters -- so somebody was using a
    municipality's billing account as a free translation service.

    Asserted on the constants rather than by driving the route, because what
    matters is that a bound exists and is small enough to matter. The real
    callers send one or two strings; a page of UI labels does not approach these.
    """
    system = pytest.importorskip("app.api.system")

    assert system.MAX_TRANSLATE_TEXTS <= 500, (
        "the per-request text limit is high enough that one call can still run "
        "up a bill"
    )
    assert system.MAX_TRANSLATE_TOTAL_CHARS <= 50_000, (
        "the per-request character limit is high enough that one call can still "
        "run up a bill"
    )
    # And the route must actually consult them.
    import inspect
    source = inspect.getsource(system.batch_translate)
    for name in ("MAX_TRANSLATE_TEXTS", "MAX_TRANSLATE_TOTAL_CHARS", "MAX_TRANSLATE_TEXT_CHARS"):
        assert name in source, f"{name} is defined but the route never checks it"


def test_a_real_page_of_labels_still_fits():
    """The bound must not be tighter than the product's own use.

    AutoTranslate posts a page of UI labels in one call. If the limit sat below
    that, the fix would present as missing translations on a resident's screen --
    which is how a cost control becomes an outage.
    """
    system = pytest.importorskip("app.api.system")
    typical_labels, typical_label_chars = 150, 40
    assert typical_labels <= system.MAX_TRANSLATE_TEXTS
    assert typical_labels * typical_label_chars <= system.MAX_TRANSLATE_TOTAL_CHARS


def test_the_public_geocode_routes_are_rate_limited():
    """Google bills $5 per 1,000 geocodes and these routes are unauthenticated.

    They had no limit of any kind: a single client could spend a town's mapping
    budget as fast as it could open connections, and the only signal would be
    the invoice. Same shape as the translate endpoint, different SKU -- which is
    why this is asserted for the pair rather than for the one that broke.

    Two limits each, the pattern the photo-screening route established: a global
    ceiling so the town's spend is bounded whoever is calling, and a per-caller
    limit so one client cannot exhaust that ceiling and deny geocoding to
    residents.
    """
    source = (ROOT / "app/api/gis.py").read_text()
    for route in ('@router.get("/geocode")', '@router.get("/reverse-geocode")'):
        assert route in source
        before = source[: source.index(route)]
        tail = before[-400:]
        assert "limiter.limit" in tail, f"{route} has no rate limit above it"
        assert "global" in tail, (
            f"{route} has a per-caller limit but no global ceiling, so the town's "
            f"total spend is still unbounded across many callers"
        )


def test_a_limited_route_can_actually_see_the_caller():
    """slowapi reads the caller off a `request` parameter, and raises at call
    time -- not import time -- when there isn't one. A limit on a route without
    it is a 500 on the first request rather than a limit."""
    source = (ROOT / "app/api/gis.py").read_text()
    for fn in ("async def geocode_address(", "async def reverse_geocode("):
        i = source.index(fn)
        signature = source[i : source.index(")", i)]
        assert "request: Request" in signature, f"{fn} is limited but takes no Request"

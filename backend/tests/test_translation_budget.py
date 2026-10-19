"""The translation spend cap, the anonymous per-request cap, and language
validation.

`/system/translate/batch` is unauthenticated and spends the town's money. The
per-request bounds and per-IP limit stop one request; this pins the ceiling on
all of them together -- a budget per UTC day and per month, counted only on
characters actually sent to a provider -- and that a language the selected
provider cannot translate into is refused rather than billed.

No real provider, Redis or database: the provider is a fake that counts what it
was sent, and the counter store is the module's own in-memory store standing in
for Redis (same four operations), shared between "processes" by reference.
"""
import re
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("fastapi")
tb = pytest.importorskip("app.services.translation_budget")
translation = pytest.importorskip("app.services.translation")
providers = pytest.importorskip("app.services.translation_providers")

ROOT = Path(__file__).resolve().parents[2]


class FakeProvider:
    def __init__(self, name="google", fail=False):
        self.provider = name
        self.calls = []
        self.fail = fail

    async def translate(self, texts, source_lang, target_lang):
        self.calls.append((list(texts), source_lang, target_lang))
        if self.fail:
            raise RuntimeError("provider exploded")
        return [f"[{target_lang}]{t}" for t in texts]


@pytest.fixture
def store(monkeypatch):
    """A shared counter store standing in for Redis, and fixed small budgets."""
    tb._reset_for_tests()
    shared = tb._MemoryStore()
    monkeypatch.setattr(tb, "_client", lambda: shared)
    limits = {"daily": 100, "monthly": 1_000}

    async def _limits():
        return limits["daily"], limits["monthly"]

    monkeypatch.setattr(tb, "get_limits", _limits)
    shared.limits = limits
    yield shared
    tb._reset_for_tests()


@pytest.fixture
def wired(monkeypatch, store):
    """translation.py with its I/O replaced: cache, provider, usage tracking."""
    cache = {}
    provider = FakeProvider()

    async def get_cached(text, lang):
        return cache.get((text, lang))

    async def save(text, lang, translated):
        cache[(text, lang)] = translated

    async def get_provider():
        return provider

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(translation, "get_cached_translation", get_cached)
    monkeypatch.setattr(translation, "save_translation_to_cache", save)
    monkeypatch.setattr(providers, "get_translation_provider", get_provider)
    api_usage = pytest.importorskip("app.services.api_usage")
    monkeypatch.setattr(api_usage, "track_api_usage", noop)
    connector_health = pytest.importorskip("app.services.connector_health")
    monkeypatch.setattr(connector_health, "note_quota_failure", noop)
    return types.SimpleNamespace(cache=cache, provider=provider, store=store)


# --------------------------------------------------------------------------- #
# The budget stops provider calls; cache hits are free
# --------------------------------------------------------------------------- #

async def test_the_budget_stops_provider_calls_at_the_limit(wired):
    results, exhausted = await translation.translate_batch_detailed(["a" * 60], "en", "es")
    assert not exhausted and results["a" * 60] == "[es]" + "a" * 60
    assert len(wired.provider.calls) == 1

    # 60 used of 100: 50 more would cross the line, so the provider is not called.
    results, exhausted = await translation.translate_batch_detailed(["b" * 50], "en", "es")
    assert exhausted is True
    assert results == {"b" * 50: "b" * 50}, "past the budget the source text comes back"
    assert len(wired.provider.calls) == 1, "the provider was called past the budget"

    # Something that fits in what is left still goes through.
    _, exhausted = await translation.translate_batch_detailed(["c" * 40], "en", "es")
    assert not exhausted and len(wired.provider.calls) == 2
    assert (await tb.usage())["day"]["used"] == 100


async def test_single_text_path_is_capped_too(wired):
    wired.store.limits["daily"] = 10
    translated, exhausted = await translation.translate_text_detailed("x" * 11, "en", "es")
    assert translated is None and exhausted is True
    assert wired.provider.calls == []
    # The plain wrapper the notification path uses still just answers None.
    assert await translation.translate_text("y" * 11, "en", "es") is None


async def test_cache_hits_do_not_count(wired):
    wired.cache[("Pothole", "es")] = "Bache"
    for _ in range(50):
        results, exhausted = await translation.translate_batch_detailed(["Pothole"], "en", "es")
        assert results["Pothole"] == "Bache" and not exhausted
    assert wired.provider.calls == []
    assert (await tb.usage())["day"]["used"] == 0


async def test_cached_strings_still_translate_when_the_budget_is_gone(wired):
    wired.store.limits["daily"] = 0
    wired.cache[("Submit", "es")] = "Enviar"
    results, exhausted = await translation.translate_batch_detailed(["Submit", "New text"], "en", "es")
    assert exhausted is True
    assert results == {"Submit": "Enviar", "New text": "New text"}
    assert wired.provider.calls == []


async def test_only_uncached_characters_are_counted(wired):
    wired.cache[("Cached label", "es")] = "Etiqueta"
    await translation.translate_batch_detailed(["Cached label", "abcde"], "en", "es")
    assert (await tb.usage())["day"]["used"] == 5


async def test_a_failed_provider_call_is_refunded(wired):
    wired.provider.fail = True
    results, exhausted = await translation.translate_batch_detailed(["z" * 30], "en", "es")
    assert results == {"z" * 30: "z" * 30} and not exhausted
    usage = await tb.usage()
    assert usage["day"]["used"] == 0 and usage["month"]["used"] == 0


async def test_shared_counter_is_seen_by_every_process(store):
    """API and worker draw from the same budget: two callers, one store."""
    assert await tb.reserve(70) is not None          # "api"
    tb.forget_cached_limits()
    assert await tb.reserve(40) is None              # "worker" sees the 70
    assert await tb.reserve(30) is not None


# --------------------------------------------------------------------------- #
# Rollover
# --------------------------------------------------------------------------- #

async def test_the_day_counter_rolls_over_at_midnight_utc(store):
    late = datetime(2026, 10, 18, 23, 59, tzinfo=timezone.utc)
    early = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
    assert await tb.reserve(100, now=late) is not None
    assert await tb.reserve(1, now=late) is None
    assert await tb.reserve(100, now=early) is not None, "a new UTC day starts empty"
    month = (await tb.usage(now=early))["month"]
    assert month["used"] == 200, "the month keeps counting across days"


async def test_the_month_counter_rolls_over_on_the_first(store):
    store.limits.update(daily=1_000, monthly=1_000)
    oct31 = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    nov1 = datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc)
    assert await tb.reserve(1_000, now=oct31) is not None
    assert await tb.reserve(1, now=datetime(2026, 10, 31, 23, tzinfo=timezone.utc)) is None
    assert await tb.reserve(500, now=nov1) is not None
    usage = await tb.usage(now=nov1)
    assert usage["month"]["period"] == "2026-11" and usage["month"]["used"] == 500


async def test_a_month_refusal_does_not_leave_the_day_charged(store):
    store.limits.update(daily=1_000, monthly=50)
    assert await tb.reserve(60) is None
    usage = await tb.usage()
    assert usage["day"]["used"] == 0 and usage["month"]["used"] == 0


def test_periods_and_resets_use_utc():
    from datetime import timedelta
    eastern = timezone(timedelta(hours=-5))
    # 20:00 on the 31st in New York is already the 1st in UTC.
    assert tb.periods(datetime(2026, 12, 31, 20, tzinfo=eastern)) == ("2027-01-01", "2027-01")
    day, month = tb._resets(datetime(2026, 12, 15, 9, tzinfo=timezone.utc))
    assert day.isoformat().startswith("2026-12-16T00:00")
    assert month.isoformat().startswith("2027-01-01T00:00")


# --------------------------------------------------------------------------- #
# Alert thresholds
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("percent,exhausted,expected", [
    (0, False, "ok"),
    (79.9, False, "ok"),
    (80, False, "warning"),
    (99.9, False, "warning"),
    (100, False, "critical"),
    # Refusals never land in `used`, so a period can be spent at 97%.
    (97, True, "critical"),
])
def test_status_thresholds(percent, exhausted, expected):
    assert tb.status_of({"percent": percent, "exhausted": exhausted}) == expected


async def test_health_check_reports_the_worse_period(store):
    ph = pytest.importorskip("app.services.proactive_health")
    store.limits.update(daily=100, monthly=10_000)
    assert (await ph._translation_budget_check())["status"] == "ok"
    await tb.reserve(85)
    check = await ph._translation_budget_check()
    assert check["key"] == "translation_budget"
    assert check["status"] == "warning" and "today's" in check["message"]
    assert check["action"], "a warning needs to say what to do"
    await tb.reserve(16)  # refused: would be 101
    check = await ph._translation_budget_check()
    assert check["status"] == "critical"
    assert "untranslated" in check["message"]


async def test_health_check_is_collected_and_mutable():
    ph = pytest.importorskip("app.services.proactive_health")
    import inspect
    assert "translation_budget" in ph.CHECK_KEYS
    assert "_translation_budget_check()" in inspect.getsource(ph.collect_checks)


async def test_each_threshold_is_logged_once_per_period(store, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger=tb.logger.name)
    for _ in range(5):
        await tb.reserve(17)       # crosses 80 at the 5th: 85
    for _ in range(3):
        await tb.reserve(20)       # refused each time
    msgs = [r.getMessage() for r in caplog.records if r.name == tb.logger.name]
    assert sum("of today's budget" in m for m in msgs) == 1, msgs
    assert sum("exhausted" in m for m in msgs) == 1, msgs


def test_unreadable_budget_falls_back_to_default_not_unlimited():
    assert tb.parse_budget(None, 5) == 5
    assert tb.parse_budget("", 5) == 5
    assert tb.parse_budget("lots", 5) == 5
    assert tb.parse_budget("-1", 5) == 5
    assert tb.parse_budget("250,000", 5) == 250_000
    assert tb.parse_budget("0", 5) == 0
    assert tb.DEFAULT_DAILY_CHARS <= tb.DEFAULT_MONTHLY_CHARS


async def test_redis_failure_falls_back_to_memory(monkeypatch):
    tb._reset_for_tests()

    class Broken:
        async def incrby(self, *a, **k):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(tb, "_client", lambda: Broken())

    async def _limits():
        return 10, 100

    monkeypatch.setattr(tb, "get_limits", _limits)
    assert await tb.reserve(10) is not None
    assert await tb.reserve(1) is None, "the memory fallback still enforces the ceiling"
    tb._reset_for_tests()


# --------------------------------------------------------------------------- #
# The route: anonymous cap, staff cap, budget flag, language validation
# --------------------------------------------------------------------------- #

class FakeRequest:
    def __init__(self, body):
        self._body = body
        self.headers = {}
        self.client = types.SimpleNamespace(host="203.0.113.9")

    async def json(self):
        return self._body


@pytest.fixture
def route(monkeypatch):
    system = pytest.importorskip("app.api.system")
    map_layers = pytest.importorskip("app.api.map_layers")
    caller = {"user": None}
    sent = []

    async def optional_user(request, db):
        return caller["user"]

    async def fake_batch(texts, src, tgt):
        sent.append((texts, tgt))
        return {t: f"[{tgt}]{t}" for t in texts}, False

    async def provider_name():
        return caller.get("provider", "google")

    monkeypatch.setattr(map_layers, "get_current_user_optional", optional_user)
    monkeypatch.setattr(translation, "translate_batch_detailed", fake_batch)
    monkeypatch.setattr(providers, "selected_provider_name", provider_name)

    handler = system.batch_translate.__wrapped__

    async def call(body):
        from fastapi import HTTPException
        try:
            return await handler(FakeRequest(body))
        except HTTPException as exc:
            return exc

    return types.SimpleNamespace(call=call, caller=caller, sent=sent, system=system)


async def test_anonymous_callers_get_the_tighter_per_request_cap(route):
    s = route.system
    assert s.MAX_TRANSLATE_TOTAL_CHARS_ANON < s.MAX_TRANSLATE_TOTAL_CHARS
    texts = ["x" * 1_500] * 6  # 9,000 characters
    result = await route.call({"texts": texts, "target_lang": "es"})
    assert getattr(result, "status_code", None) == 413
    assert route.sent == [], "an over-cap request must not reach the translator"


async def test_staff_keep_the_larger_cap(route):
    route.caller["user"] = types.SimpleNamespace(role="staff", username="clerk")
    texts = ["x" * 1_500] * 6
    result = await route.call({"texts": texts, "target_lang": "es"})
    assert isinstance(result, dict) and len(result["translations"]) == 6
    assert result["budget_exhausted"] is False


async def test_a_resident_or_signed_in_resident_is_still_anonymous_sized(route):
    route.caller["user"] = types.SimpleNamespace(role="resident", username="r")
    result = await route.call({"texts": ["x" * 1_500] * 6, "target_lang": "es"})
    assert getattr(result, "status_code", None) == 413


async def test_a_page_of_labels_fits_the_anonymous_cap(route):
    labels = [f"Label number {i:03d} here" for i in range(100)]
    result = await route.call({"texts": labels, "target_lang": "es"})
    assert isinstance(result, dict) and len(result["translations"]) == 100


async def test_budget_exhaustion_is_flagged_not_an_error(route, monkeypatch):
    async def exhausted_batch(texts, src, tgt):
        return {t: t for t in texts}, True

    monkeypatch.setattr(translation, "translate_batch_detailed", exhausted_batch)
    result = await route.call({"texts": ["Hello"], "target_lang": "es"})
    assert result == {"translations": ["Hello"], "budget_exhausted": True}


async def test_unsupported_language_is_a_400(route):
    for code in ("xx", "klingon", "", None, 5, "es; DROP"):
        result = await route.call({"texts": ["Hello"], "target_lang": code})
        assert getattr(result, "status_code", None) == 400, code
    assert route.sent == []


async def test_language_is_checked_against_the_selected_provider(route):
    # Latin: Google has it, Azure does not.
    assert isinstance(await route.call({"texts": ["Hi"], "target_lang": "la"}), dict)
    route.caller["provider"] = "azure"
    result = await route.call({"texts": ["Hi"], "target_lang": "la"})
    assert getattr(result, "status_code", None) == 400
    assert "azure" in result.detail


async def test_codes_are_canonicalised(route):
    result = await route.call({"texts": ["Hi"], "target_lang": "ZH-tw"})
    assert isinstance(result, dict)
    assert route.sent[-1][1] == "zh-TW"


async def test_languages_endpoint_follows_the_provider(route):
    body = await route.system.get_supported_languages()
    assert body["provider"] == "google" and "la" in body["codes"] and "es" in body["codes"]
    route.caller["provider"] = "aws"
    body = await route.system.get_supported_languages()
    assert body["provider"] == "aws" and "la" not in body["codes"] and "es" in body["codes"]


async def test_azure_gets_its_own_spelling_at_dispatch(wired):
    wired.provider.provider = "azure"
    await translation.translate_batch_detailed(["Hello"], "en", "zh")
    assert wired.provider.calls[-1][2] == "zh-Hans"
    # ...and the cache keeps the platform code.
    assert ("Hello", "zh") in wired.cache


async def test_the_service_layer_refuses_unsupported_codes_too(wired):
    """Accept-Language reaches translate_text without passing the API's check."""
    assert await translation.translate_text("Hello", "en", "xx") is None
    wired.provider.provider = "aws"
    assert await translation.translate_text("Hello", "en", "la") is None
    assert wired.provider.calls == []
    assert (await tb.usage())["day"]["used"] == 0


def test_every_language_the_frontend_names_is_in_the_catalog():
    """The picker's names and the backend's codes must not drift apart: a code
    the frontend can name but no provider lists would never be offered, and a
    listed code with no name would show as a bare code."""
    src = (ROOT / "frontend/src/utils/languages.ts").read_text()
    frontend = set(re.findall(r"code: '([^']+)'", src))
    assert frontend, "could not read the frontend language list"
    assert frontend == set(providers.GOOGLE_LANGUAGES)
    for name, codes in providers.SUPPORTED_LANGUAGES.items():
        assert codes <= frontend, f"{name} lists codes the picker cannot name: {codes - frontend}"


# --------------------------------------------------------------------------- #
# Admin budget endpoint
# --------------------------------------------------------------------------- #

async def test_budget_update_validates_before_writing():
    system = pytest.importorskip("app.api.system")
    from fastapi import HTTPException
    admin = types.SimpleNamespace(role="admin", username="a", id=1)
    for daily, monthly in ((-1, 10), (10, tb.MAX_BUDGET_CHARS + 1), (200, 100)):
        body = system.TranslationBudgetUpdate(daily_chars=daily, monthly_chars=monthly)
        with pytest.raises(HTTPException) as exc:
            # db=None: a validation failure must not touch the database.
            await system.update_translation_budget(body, db=None, admin=admin)
        assert exc.value.status_code == 400


def test_budget_routes_are_admin_only_and_audited():
    import inspect
    system = pytest.importorskip("app.api.system")
    for fn in (system.get_translation_budget, system.update_translation_budget):
        assert "get_current_admin" in str(inspect.signature(fn)), fn.__name__
    assert "record_admin_action" in inspect.getsource(system.update_translation_budget)

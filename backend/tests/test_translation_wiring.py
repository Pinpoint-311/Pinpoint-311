"""Notification translation and /translate/auto go through the real service.

Before: notifications POSTed to a relative URL (always failed, sent untranslated)
and /translate/auto imported a function that does not exist (always 500).
"""

import asyncio
import inspect

import pytest

translate = pytest.importorskip("app.services.translate")
translation = pytest.importorskip("app.services.translation")


def test_notification_translation_uses_the_service(monkeypatch):
    calls = []

    async def fake(text, source, target):
        calls.append((text, source, target))
        return "Hola"

    monkeypatch.setattr(translation, "translate_text", fake)
    assert asyncio.run(translate.translate_text("Hello", "es")) == "Hola"
    assert calls == [("Hello", "en", "es")]
    assert "httpx" not in inspect.getsource(translate.translate_text)


def test_notification_translation_falls_back_to_the_original(monkeypatch):
    async def none(text, source, target):
        return None

    monkeypatch.setattr(translation, "translate_text", none)
    assert asyncio.run(translate.translate_text("Hello", "es")) == "Hello"


def test_batch_keeps_order_and_fills_gaps(monkeypatch):
    async def fake(texts, source, target):
        return {"a": "A!"}

    monkeypatch.setattr(translation, "translate_batch", fake)
    assert asyncio.run(translate.translate_batch(["a", "b"], "es")) == ["A!", "b"]


def test_auto_translate_route_no_longer_imports_a_missing_function():
    system = pytest.importorskip("app.api.system")
    src = inspect.getsource(system.auto_translate_object)
    assert "import auto_translate_object" not in src
    assert "translate_batch" in src

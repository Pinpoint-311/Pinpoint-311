"""One priority everywhere: staff-set, else AI-suggested, else 5."""
import inspect
from types import SimpleNamespace

import pytest

from app.services.priority import effective_priority


def test_staff_priority_wins():
    assert effective_priority(SimpleNamespace(manual_priority_score=8, ai_analysis={"priority_score": 3})) == 8


def test_ai_priority_when_staff_has_not_set_one():
    assert effective_priority(SimpleNamespace(manual_priority_score=None, ai_analysis={"priority_score": 7})) == 7


def test_default_when_neither():
    assert effective_priority(SimpleNamespace(manual_priority_score=None, ai_analysis=None)) == 5


def test_payload_and_export_use_it():
    pytest.importorskip("sqlalchemy")
    from app.tasks import integrations
    assert '"priority": effective_priority(sr)' in inspect.getsource(integrations)
    pytest.importorskip("fastapi.routing")
    from app.api import research
    assert '"priority": effective_priority(req)' in inspect.getsource(research)

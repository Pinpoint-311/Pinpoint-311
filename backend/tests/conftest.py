"""Lightweight test bootstrap.

These tests exercise the security- and integration-critical *logic* (envelope
encryption, secret-manager caching/merge, connector retry/pagination, work-order
mapping) without needing a database or the full app stack. conftest makes `app`
importable and provides a minimal app.core.config stub if pydantic-settings
isn't installed, so the suite runs fast in CI.
"""
import os
import sys
import types

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("PII_DECRYPT_CACHE", "on")

try:
    import app.core.config  # noqa: F401
except Exception:
    cfg = types.ModuleType("app.core.config")

    class _Settings:
        secret_key = "test-secret-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    cfg.get_settings = lambda: _Settings()
    sys.modules["app.core.config"] = cfg

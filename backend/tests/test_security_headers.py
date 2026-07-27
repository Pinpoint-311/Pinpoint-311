"""Tests for the web-hardening applied after the CISA WAS scan:
- the server software/version banner is not advertised (information disclosure),
- API responses get a locked-down CSP so a reflected parameter is inert,
- validation (422) errors do NOT echo the submitted value back (reflected-XSS).

These import the real middleware + handler from app.main into a minimal app, so
they don't need a database. If app.main can't be imported in this environment
(optional cloud deps), the whole module skips rather than failing.
"""

import pytest

pytest.importorskip("fastapi")
main = pytest.importorskip("app.main")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(main.SecurityHeadersMiddleware)
    app.add_exception_handler(RequestValidationError, main.validation_exception_handler)

    class Body(BaseModel):
        n: int

    @app.get("/api/thing")
    def thing():
        return {"ok": True}

    @app.post("/api/thing")
    def create(b: Body):
        return {"n": b.n}

    return TestClient(app)


def test_server_banner_is_obscured():
    r = _client().get("/api/thing")
    assert r.headers.get("server") == "Pinpoint"
    assert "x-powered-by" not in {k.lower() for k in r.headers}


def test_core_security_headers_present():
    r = _client().get("/api/thing")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "max-age=" in r.headers.get("strict-transport-security", "")


def test_api_csp_is_locked_down():
    csp = _client().get("/api/thing").headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_validation_error_does_not_reflect_input():
    payload = "<script>alert(1)</script>"
    r = _client().post("/api/thing", json={"n": payload})
    assert r.status_code == 422
    # The injected payload must not be reflected anywhere in the response body.
    assert payload not in r.text
    assert "alert(1)" not in r.text
    # But a useful, safe error is still returned.
    assert "detail" in r.json()

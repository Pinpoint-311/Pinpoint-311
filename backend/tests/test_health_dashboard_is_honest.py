"""The health page must not claim more than it checked.

Three things it claimed. A field called `uptime` that never held an uptime; a
reverse proxy reported as running with no probe behind it; and a frontend check
hardcoded to a docker-compose hostname, which reports a healthy frontend as
stopped on any other topology.
"""

from pathlib import Path

import pytest

SOURCE = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
DASHBOARD = SOURCE[SOURCE.index('@router.get("/health-dashboard")'):]
DASHBOARD = DASHBOARD[:DASHBOARD.index("\n@router.", 10)]


def test_nothing_is_presented_as_an_uptime_that_is_not_one():
    """Values like "Port 5173 active" and "6.2 GB - 12 conns" are details.
    Nothing in this product measures availability over a period, so a field
    named uptime promised a statistic that was never computed."""
    assert '"detail"' in DASHBOARD, "the honest field is missing"
    # The old key stays for one release so an older frontend does not blank
    # out, but it must never be the only thing carrying the value.
    for line in DASHBOARD.splitlines():
        if '"uptime"' in line and "detail" not in line and "#" not in line:
            assert False, f"uptime carried alone: {line.strip()}"


def test_the_proxy_is_probed_rather_than_assumed():
    """Behaviour, not source. The first version of this test grepped for the
    header name and for the "cannot tell" string, and both survived a mutation
    that put the status back to a hardcoded "running" -- the strings were still
    there, in the detail line, above a status that had stopped depending on
    them."""
    from app.services.system_probes import proxy_status

    assert proxy_status({"x-forwarded-for": "10.0.0.1"})["status"] == "running"
    assert proxy_status({"X-Real-IP": "10.0.0.1"})["status"] == "running"
    assert proxy_status({})["status"] == "unknown"
    assert proxy_status(None)["status"] == "unknown"
    assert proxy_status({"user-agent": "curl"})["status"] == "unknown"


def test_the_proxy_says_when_it_cannot_tell():
    from app.services.system_probes import proxy_status

    assert "Cannot tell from here" in proxy_status({})["detail"]
    assert '"Active (routing requests)"' not in DASHBOARD


def test_the_frontend_hostname_is_not_hardcoded():
    """'frontend' is a docker-compose service name. On a single container, a
    static bundle behind a CDN, or separate hosts, the connect fails and the
    page reports the frontend down while somebody is looking at it."""
    assert "FRONTEND_HOST" in DASHBOARD
    assert "connect_ex(('frontend'" not in DASHBOARD


def test_an_unreachable_frontend_says_where_it_looked():
    """"Checked ports: [5173, 3000, 80]" does not tell an admin that we were
    looking at a hostname that does not exist in their deployment."""
    assert "No answer from" in DASHBOARD


def test_the_dashboard_can_see_the_request_it_is_answering():
    """The proxy probe reads forwarding headers, so the handler needs the
    request. Without this parameter it raises NameError at runtime -- which no
    test that only reads source would otherwise catch."""
    signature = DASHBOARD[:DASHBOARD.index("):")]
    assert "request: Request" in signature

"""HTTP probes against an instance's loopback URL.

``/api/health/quick`` is the public, unauthenticated stamp endpoint
(backend/app/api/health.py): ``version``, ``git_sha``, ``db_revision`` (read
live from ``alembic_version``) and ``min_db_revision``. It is the same A3 stamp
the orchestrator's rollout gates on.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from pinpoint_updater import __version__


class ProbeError(RuntimeError):
    pass


class AppProbe:
    def __init__(self, app_url: str, *, timeout: float = 10.0, transport: Optional[httpx.BaseTransport] = None):
        self.app_url = app_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=False, transport=transport,
            headers={"User-Agent": f"pinpoint-updater/{__version__}"},
        )

    def close(self) -> None:
        self._client.close()

    def quick(self) -> dict[str, Any]:
        try:
            resp = self._client.get(f"{self.app_url}/api/health/quick")
        except httpx.HTTPError as exc:
            raise ProbeError(f"{self.app_url} unreachable ({exc.__class__.__name__})") from None
        if resp.status_code != 200:
            raise ProbeError(f"/api/health/quick answered {resp.status_code}")
        try:
            body = resp.json()
        except ValueError:
            raise ProbeError("/api/health/quick did not return JSON") from None
        if not isinstance(body, dict):
            raise ProbeError("/api/health/quick returned an unexpected shape")
        return body

    def status(self, path: str) -> int:
        try:
            return self._client.get(f"{self.app_url}{path}").status_code
        except httpx.HTTPError:
            return 0

"""CivicPlus SeeClickFix connector (SeeClickFix API v2).

SeeClickFix (acquired by CivicPlus) exposes a documented public REST API:
https://dev.seeclickfix.com — base https://seeclickfix.com/api/v2.

Config:
    api_base       override, default https://seeclickfix.com/api/v2
    place_url      SeeClickFix place slug used to scope pulls (e.g. "springfield")
    request_type   numeric request_type id required to create issues
Credentials:
    username, password    SeeClickFix account with API access (HTTP Basic), OR
    api_key               where CivicPlus has issued a token (sent as Bearer)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.integrations.base import BaseConnector, ConnectorError, ExternalRecord

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://seeclickfix.com/api/v2"


class SeeClickFixConnector(BaseConnector):
    platform = "civicplus"
    capabilities = {"test", "push", "pull"}

    DEFAULT_STATUS_MAP_OUT = {"open": "open", "in_progress": "acknowledged", "closed": "closed"}
    DEFAULT_STATUS_MAP_IN = {
        "open": "open",
        "acknowledged": "in_progress",
        "closed": "closed",
        "archived": "closed",
    }

    @property
    def api_base(self) -> str:
        return (self.config.get("api_base") or DEFAULT_API_BASE).rstrip("/")

    def _auth_kwargs(self) -> Dict[str, Any]:
        if self.credentials.get("api_key"):
            return {"headers": {"Authorization": f"Bearer {self.credentials['api_key']}"}}
        if self.credentials.get("username") and self.credentials.get("password"):
            return {"auth": (self.credentials["username"], self.credentials["password"])}
        return {}

    def _record_from_issue(self, issue: Dict[str, Any]) -> ExternalRecord:
        raw_status = issue.get("status")
        updated_dt = None
        if issue.get("updated_at"):
            try:
                updated_dt = datetime.fromisoformat(str(issue["updated_at"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        return ExternalRecord(
            external_id=str(issue.get("id") or ""),
            status=self.map_status_in(raw_status),
            raw_status=raw_status,
            status_notes=None,
            updated_at=updated_dt,
            raw=issue,
        )

    async def test_connection(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {"per_page": 1}
        if self.config.get("place_url"):
            params["place_url"] = self.config["place_url"]
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.get(f"{self.api_base}/issues", params=params)
            self._raise_for_status(resp, "SeeClickFix issues probe")
            body = resp.json()
        total = (body.get("metadata") or {}).get("pagination", {}).get("entries")
        scope = self.config.get("place_url") or "global"
        return {"ok": True, "detail": f"Connected — scope '{scope}', {total if total is not None else 'unknown'} issue(s) visible"}

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        if payload.get("lat") is None or payload.get("long") is None:
            raise ConnectorError("SeeClickFix requires lat/long to create an issue")
        body: Dict[str, Any] = {
            "summary": (payload.get("service_name") or "Service Request")[:120],
            "description": payload.get("description") or "",
            "lat": payload["lat"],
            "lng": payload["long"],
            "address": payload.get("address") or "",
            "anonymize_reporter": not payload.get("email"),
        }
        if self.config.get("request_type"):
            body["request_type"] = self.config["request_type"]
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.post(f"{self.api_base}/issues", json=body)
            self._raise_for_status(resp, "SeeClickFix create issue")
            issue = resp.json()
        if not issue.get("id"):
            raise ConnectorError(f"SeeClickFix create returned no issue id: {str(issue)[:300]}")
        return self._record_from_issue(issue)

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        params: Dict[str, Any] = {"per_page": 100, "sort": "updated_at", "sort_direction": "DESC"}
        if self.config.get("place_url"):
            params["place_url"] = self.config["place_url"]
        if since:
            params["updated_at_after"] = since.isoformat()
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.get(f"{self.api_base}/issues", params=params)
            self._raise_for_status(resp, "SeeClickFix list issues")
            body = resp.json()
        issues = body.get("issues") or []
        return [self._record_from_issue(i) for i in issues if i.get("id")]

    async def fetch_record(self, external_id: str) -> Optional[ExternalRecord]:
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.get(f"{self.api_base}/issues/{external_id}")
            if resp.status_code == 404:
                return None
            self._raise_for_status(resp, "SeeClickFix get issue")
            return self._record_from_issue(resp.json())

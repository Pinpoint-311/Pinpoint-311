"""Generic Open311 GeoReport v2 client.

Works against any spec-compliant endpoint (http://wiki.open311.org/GeoReport_v2),
which covers a large slice of the govtech market: Tyler Technologies 311,
CivicPlus SeeClickFix, Cityworks, QAlert, and many municipal in-house systems
expose GeoReport v2 endpoints.

Config:
    base_url          e.g. https://city.example.gov/open311/v2  (required)
    jurisdiction_id   optional jurisdiction_id query param
Credentials:
    api_key           vendor-issued Open311 api_key (required for POST on most servers)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.integrations.base import BaseConnector, ConnectorError, ExternalRecord

logger = logging.getLogger(__name__)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Open311Connector(BaseConnector):
    platform = "open311"
    capabilities = {"test", "push", "pull"}

    DEFAULT_STATUS_MAP_OUT = {"open": "open", "in_progress": "open", "closed": "closed"}
    DEFAULT_STATUS_MAP_IN = {"open": "open", "closed": "closed"}

    @property
    def base_url(self) -> str:
        url = (self.config.get("base_url") or "").rstrip("/")
        if not url:
            raise ConnectorError("Open311 connector requires config.base_url")
        return url

    def _common_params(self) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if self.credentials.get("api_key"):
            params["api_key"] = self.credentials["api_key"]
        if self.config.get("jurisdiction_id"):
            params["jurisdiction_id"] = self.config["jurisdiction_id"]
        return params

    def _record_from_open311(self, item: Dict[str, Any]) -> ExternalRecord:
        raw_status = item.get("status")
        return ExternalRecord(
            external_id=str(item.get("service_request_id") or item.get("token") or ""),
            status=self.map_status_in(raw_status),
            raw_status=raw_status,
            status_notes=item.get("status_notes"),
            updated_at=_parse_dt(item.get("updated_datetime")),
            raw=item,
        )

    async def test_connection(self) -> Dict[str, Any]:
        async with self._client() as client:
            resp = await client.get(f"{self.base_url}/services.json", params=self._common_params())
            self._raise_for_status(resp, "Open311 services list")
            services = resp.json()
            count = len(services) if isinstance(services, list) else 0
            return {"ok": True, "detail": f"Connected — endpoint advertises {count} service(s)"}

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        data = dict(self._common_params())
        data.update({
            "service_code": self.config.get("default_service_code") or payload.get("service_code"),
            "description": payload.get("description") or "",
        })
        if payload.get("lat") is not None and payload.get("long") is not None:
            data["lat"] = str(payload["lat"])
            data["long"] = str(payload["long"])
        elif payload.get("address"):
            data["address_string"] = payload["address"]
        if payload.get("address"):
            data.setdefault("address_string", payload["address"])
        for ours, theirs in (("first_name", "first_name"), ("last_name", "last_name"),
                             ("email", "email"), ("phone", "phone")):
            if payload.get(ours):
                data[theirs] = payload[ours]
        media = [u for u in (payload.get("media_urls") or []) if isinstance(u, str) and u.startswith("http")]
        if media:
            data["media_url"] = media[0]
        # Cross-reference back to Pinpoint
        data["attribute[external_id]"] = payload.get("service_request_id", "")

        async with self._client() as client:
            resp = await client.post(f"{self.base_url}/requests.json", data=data)
            self._raise_for_status(resp, "Open311 create request")
            body = resp.json()

        # Spec: response is a list with one entry containing service_request_id or token
        entry = body[0] if isinstance(body, list) and body else (body if isinstance(body, dict) else {})
        external_id = entry.get("service_request_id") or entry.get("token")
        if not external_id:
            raise ConnectorError(f"Open311 create returned no id/token: {str(body)[:300]}")
        return self._record_from_open311({**entry, "service_request_id": external_id})

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        params = dict(self._common_params())
        if since:
            # updated_after is a common extension; start_date is in the base spec
            params["updated_after"] = since.isoformat()
            params["start_date"] = since.isoformat()
        async with self._client() as client:
            resp = await client.get(f"{self.base_url}/requests.json", params=params)
            self._raise_for_status(resp, "Open311 list requests")
            items = resp.json()
        if not isinstance(items, list):
            return []
        return [self._record_from_open311(i) for i in items if i.get("service_request_id")]

    async def fetch_record(self, external_id: str) -> Optional[ExternalRecord]:
        async with self._client() as client:
            resp = await client.get(
                f"{self.base_url}/requests/{external_id}.json", params=self._common_params()
            )
            if resp.status_code == 404:
                return None
            self._raise_for_status(resp, "Open311 get request")
            body = resp.json()
        entry = body[0] if isinstance(body, list) and body else (body if isinstance(body, dict) else None)
        return self._record_from_open311(entry) if entry else None

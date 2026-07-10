"""Accela Civic Platform connector (Construct API v4).

Uses Accela's documented public REST API (https://developer.accela.com):
  - OAuth2 token:  POST https://auth.accela.com/oauth2/token
  - Records:       https://apis.accela.com/v4/records

Config:
    agency_name       Accela agency identifier (required)
    environment       e.g. PROD / TEST / SUPP (default PROD)
    record_type       Accela record type alias/id for created records
                      (e.g. "ServiceRequest/General/Complaint/NA")
    api_base          override, default https://apis.accela.com
    auth_base         override, default https://auth.accela.com
Credentials:
    client_id, client_secret        from your Accela developer app
    username, password              agency citizen/agency account for password grant
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import json

from app.integrations.base import BaseConnector, ConnectorError, ExternalComment, ExternalRecord

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://apis.accela.com"
DEFAULT_AUTH_BASE = "https://auth.accela.com"


class AccelaConnector(BaseConnector):
    platform = "accela"
    capabilities = {"test", "push", "push_status", "pull", "comments", "documents", "assets", "work_orders"}

    DEFAULT_STATUS_MAP_OUT = {"open": "Open", "in_progress": "In Progress", "closed": "Closed"}
    DEFAULT_STATUS_MAP_IN = {
        "open": "open", "submitted": "open", "received": "open",
        "in progress": "in_progress", "in review": "in_progress", "assigned": "in_progress",
        "closed": "closed", "complete": "closed", "completed": "closed", "resolved": "closed",
    }

    @property
    def api_base(self) -> str:
        return (self.config.get("api_base") or DEFAULT_API_BASE).rstrip("/")

    @property
    def auth_base(self) -> str:
        return (self.config.get("auth_base") or DEFAULT_AUTH_BASE).rstrip("/")

    async def _get_token(self) -> str:
        required = ["client_id", "client_secret", "username", "password"]
        missing = [k for k in required if not self.credentials.get(k)]
        if missing:
            raise ConnectorError(f"Accela credentials missing: {', '.join(missing)}")
        if not self.config.get("agency_name"):
            raise ConnectorError("Accela config requires agency_name")

        data = {
            "grant_type": "password",
            "client_id": self.credentials["client_id"],
            "client_secret": self.credentials["client_secret"],
            "username": self.credentials["username"],
            "password": self.credentials["password"],
            "scope": "records",
            "agency_name": self.config["agency_name"],
            "environment": self.config.get("environment", "PROD"),
        }
        async with self._client() as client:
            resp = await client.post(
                f"{self.auth_base}/oauth2/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            self._raise_for_status(resp, "Accela OAuth2 token")
            token = resp.json().get("access_token")
        if not token:
            raise ConnectorError("Accela token endpoint returned no access_token")
        return token

    def _headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": token, "Content-Type": "application/json"}

    def _record_from_accela(self, item: Dict[str, Any]) -> ExternalRecord:
        raw_status = (item.get("status") or {}).get("text") if isinstance(item.get("status"), dict) else item.get("status")
        updated = item.get("updateDate") or item.get("statusDate")
        updated_dt = None
        if updated:
            try:
                updated_dt = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            except ValueError:
                pass  # unparseable vendor timestamp — leave as None

        def _text(v):
            return v.get("text") if isinstance(v, dict) else (str(v) if v is not None else None)

        def _accela_dt(v):
            if not v:
                return None
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except ValueError:
                return None

        return ExternalRecord(
            external_id=str(item.get("id") or item.get("customId") or ""),
            status=self.map_status_in(raw_status),
            raw_status=raw_status,
            status_notes=item.get("statusReason", {}).get("text") if isinstance(item.get("statusReason"), dict) else None,
            updated_at=updated_dt,
            # Work-order fields from the Accela record
            work_order_id=str(item.get("customId")) if item.get("customId") else None,
            priority=_text(item.get("priority")),
            assigned_to=_text(item.get("assignedUser")) or _text(item.get("assignedTo")),
            assigned_department=_text(item.get("assignedToDepartment")) or _text(item.get("assignedDepartment")),
            scheduled_datetime=_accela_dt(item.get("scheduledDate") or item.get("assignedDate")),
            due_datetime=_accela_dt(item.get("dueDate") or item.get("estimatedDueDate")),
            resolution=_text(item.get("statusReason")) if self.map_status_in(raw_status) == "closed" else None,
            raw=item,
        )

    async def test_connection(self) -> Dict[str, Any]:
        token = await self._get_token()
        async with self._client() as client:
            resp = await client.get(
                f"{self.api_base}/v4/records", params={"limit": 1}, headers=self._headers(token)
            )
            self._raise_for_status(resp, "Accela records probe")
        return {"ok": True, "detail": f"Authenticated with agency {self.config['agency_name']}"}

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        record_type = self.config.get("record_type")
        if not record_type:
            raise ConnectorError("Accela config requires record_type (e.g. 'ServiceRequest/General/Complaint/NA')")
        token = await self._get_token()

        body: Dict[str, Any] = {
            "type": {"alias": record_type} if "/" not in record_type else {
                # "Module/Type/Subtype/Category" form
                key: val for key, val in zip(
                    ("module", "type", "subType", "category"), record_type.split("/")
                )
            },
            "description": payload.get("description") or "",
            "name": (payload.get("service_name") or "Service Request")[:100],
        }
        if payload.get("address") or payload.get("lat") is not None:
            address: Dict[str, Any] = {}
            if payload.get("address"):
                address["streetAddress"] = payload["address"][:255]
            if payload.get("lat") is not None:
                address["xCoordinate"] = payload["long"]
                address["yCoordinate"] = payload["lat"]
            body["addresses"] = [address]
        if payload.get("email") or payload.get("first_name"):
            body["contacts"] = [{
                "firstName": payload.get("first_name") or "",
                "lastName": payload.get("last_name") or "",
                "email": payload.get("email") or "",
                "phone1": payload.get("phone") or "",
                "type": {"value": "Complainant"},
            }]

        async with self._client() as client:
            resp = await client.post(
                f"{self.api_base}/v4/records", json=body, headers=self._headers(token)
            )
            self._raise_for_status(resp, "Accela create record")
            result = resp.json().get("result") or []
        if not result:
            raise ConnectorError("Accela create record returned an empty result")
        return self._record_from_accela(result[0])

    async def push_status(self, external_id: str, status: str, notes: Optional[str] = None) -> None:
        token = await self._get_token()
        body = {"status": {"text": self.map_status_out(status)}}
        if notes:
            body["statusReason"] = {"text": notes[:255]}
        async with self._client() as client:
            resp = await client.put(
                f"{self.api_base}/v4/records/{external_id}", json=body, headers=self._headers(token)
            )
            self._raise_for_status(resp, "Accela update record status")

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        token = await self._get_token()
        params: Dict[str, Any] = {"limit": 100}
        if since:
            params["updateDateFrom"] = since.strftime("%Y-%m-%d")
        async with self._client() as client:
            resp = await client.get(
                f"{self.api_base}/v4/records", params=params, headers=self._headers(token)
            )
            self._raise_for_status(resp, "Accela list records")
            result = resp.json().get("result") or []
        return [self._record_from_accela(item) for item in result if item.get("id")]

    async def fetch_record(self, external_id: str) -> Optional[ExternalRecord]:
        token = await self._get_token()
        async with self._client() as client:
            resp = await client.get(
                f"{self.api_base}/v4/records/{external_id}", headers=self._headers(token)
            )
            if resp.status_code == 404:
                return None
            self._raise_for_status(resp, "Accela get record")
            result = resp.json().get("result") or []
        return self._record_from_accela(result[0]) if result else None

    # ---- Comments (Accela record comments API) ----

    async def push_comment(self, external_id: str, author: str, content: str) -> Optional[str]:
        token = await self._get_token()
        body = [{"text": f"{author}: {content}" if author else content}]
        async with self._client() as client:
            resp = await client.post(
                f"{self.api_base}/v4/records/{external_id}/comments",
                json=body, headers=self._headers(token),
            )
            self._raise_for_status(resp, "Accela create comment")
            result = resp.json().get("result") or []
        return str(result[0]["id"]) if result and result[0].get("id") is not None else None

    async def pull_comments(self, external_id: str) -> List[ExternalComment]:
        token = await self._get_token()
        async with self._client() as client:
            resp = await client.get(
                f"{self.api_base}/v4/records/{external_id}/comments",
                params={"limit": 100}, headers=self._headers(token),
            )
            if resp.status_code == 404:
                return []
            self._raise_for_status(resp, "Accela list comments")
            result = resp.json().get("result") or []
        comments = []
        for item in result:
            created = None
            if item.get("createdDate"):
                try:
                    created = datetime.fromisoformat(str(item["createdDate"]).replace("Z", "+00:00"))
                except ValueError:
                    pass  # unparseable vendor timestamp — leave as None
            comments.append(ExternalComment(
                external_id=str(item.get("id") or ""),
                content=item.get("text") or "",
                author=(item.get("createdBy") or {}).get("text") if isinstance(item.get("createdBy"), dict) else item.get("createdBy"),
                created_at=created,
                raw=item,
            ))
        return [c for c in comments if c.external_id and c.content]

    # ---- Documents (Accela record documents API, multipart) ----

    async def push_document(self, external_id: str, filename: str,
                            content: bytes, content_type: str) -> None:
        token = await self._get_token()
        file_info = json.dumps([{
            "serviceProviderCode": self.config.get("agency_name", ""),
            "fileName": filename,
            "type": content_type,
            "description": "Uploaded from Pinpoint 311",
        }])
        async with self._client() as client:
            resp = await client.post(
                f"{self.api_base}/v4/records/{external_id}/documents",
                headers={"Authorization": token},
                data={"fileInfo": file_info},
                files={"uploadedFile": (filename, content, content_type)},
            )
            self._raise_for_status(resp, "Accela upload document")

    # ---- Assets (Accela asset management API) ----

    async def pull_assets(self) -> List[Dict[str, Any]]:
        token = await self._get_token()
        features: List[Dict[str, Any]] = []
        offset = 0
        async with self._client() as client:
            while offset < 10000:  # hard ceiling
                params: Dict[str, Any] = {"limit": 100, "offset": offset}
                if self.config.get("asset_group"):
                    params["group"] = self.config["asset_group"]
                resp = await client.get(
                    f"{self.api_base}/v4/assets", params=params, headers=self._headers(token)
                )
                self._raise_for_status(resp, "Accela list assets")
                result = resp.json().get("result") or []
                if not result:
                    break
                for item in result:
                    lat = item.get("yCoordinate")
                    lng = item.get("xCoordinate")
                    if lat is None or lng is None:
                        continue  # only mappable assets become layer features
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(lng), float(lat)]},
                        "properties": {
                            "asset_id": str(item.get("assetId") or item.get("id") or ""),
                            "name": item.get("description") or str(item.get("assetId") or ""),
                            "type": (item.get("type") or {}).get("text") if isinstance(item.get("type"), dict) else item.get("type"),
                            "status": (item.get("status") or {}).get("text") if isinstance(item.get("status"), dict) else item.get("status"),
                        },
                    })
                if len(result) < 100:
                    break
                offset += 100
        return features

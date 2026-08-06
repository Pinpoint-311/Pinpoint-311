"""Accela Civic Platform connector (Construct API v4).

Uses Accela's documented public REST API (https://developer.accela.com):
  - OAuth2 token:  POST https://auth.accela.com/oauth2/token
  - Records:       https://apis.accela.com/v4/records

Two ways to authenticate, in preference order:

  1. **Authorization code + refresh token.** The admin signs in at Accela once
     (see app/integrations/accela_oauth.py) and we store only the refresh token.
     Every access token comes from exchanging it; Accela rotates the refresh
     token on each exchange, so the new one is written back to the vault
     immediately or the next call is locked out.
  2. **Password grant.** The historical path, kept for towns whose Accela
     administrator prefers issuing a service account. Needs client_id,
     client_secret, username and password in the vault.

Config:
    agency_name       Accela agency identifier (required)
    environment       e.g. PROD / TEST / SUPP (default PROD)
    record_type       Accela record type alias/id for created records
                      (e.g. "ServiceRequest/General/Complaint/NA")
    scope             override the requested scope groups (default "records assets")
    api_base          override, default https://apis.accela.com
    auth_base         override, default https://auth.accela.com
Credentials:
    refresh_token                   from the authorization-code sign-in
    client_id, client_secret        only for the password-grant fallback (or to
                                    override the deployment-level app)
    username, password              only for the password-grant fallback
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import json

from app.integrations import accela_oauth
from app.integrations.base import BaseConnector, ConnectorError, ExternalComment, ExternalRecord

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://apis.accela.com"
DEFAULT_AUTH_BASE = "https://auth.accela.com"

# Access tokens are cached per agency/environment for their advertised lifetime.
# This is not just a latency win: a refresh rotates the refresh token, so an
# uncached connector would rotate once per operation, and two operations
# overlapping would race — the slower one's token invalidated mid-flight. The
# lock serializes refreshes for a given agency within the process.
_token_cache: Dict[str, Tuple[str, float]] = {}
_token_locks: Dict[str, asyncio.Lock] = {}

# Refresh a little before the advertised expiry so a token doesn't die in transit.
_TOKEN_EXPIRY_SKEW = 120.0


def _clear_token_cache() -> None:
    """Drop cached access tokens (used by tests and after a re-authorization)."""
    _token_cache.clear()


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

    @property
    def scope(self) -> str:
        return accela_oauth.scope_for(self.config)

    @property
    def _cache_key(self) -> str:
        return "|".join([
            self.auth_base,
            str(self.config.get("agency_name") or ""),
            str(self.config.get("environment") or "PROD").upper(),
            self.scope,
        ])

    async def _get_token(self) -> str:
        if not self.config.get("agency_name"):
            raise ConnectorError("Accela config requires agency_name")

        key = self._cache_key
        cached = _token_cache.get(key)
        if cached and cached[1] > time.time():
            return cached[0]

        lock = _token_locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another coroutine may have refreshed while we waited on the lock.
            cached = _token_cache.get(key)
            if cached and cached[1] > time.time():
                return cached[0]

            if self.credentials.get("refresh_token"):
                token, expires_in = await self._token_from_refresh()
            else:
                token, expires_in = await self._token_from_password()

            _token_cache[key] = (token, time.time() + max(60.0, expires_in - _TOKEN_EXPIRY_SKEW))
            return token

    async def _post_token(self, data: Dict[str, str], context: str) -> Dict[str, Any]:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if data.get("client_id"):
            headers["x-accela-appid"] = data["client_id"]
        async with self._client() as client:
            resp = await client.post(
                f"{self.auth_base}/oauth2/token", data=data, headers=headers
            )
            self._raise_for_status(resp, context)
            return resp.json()

    async def _app_credentials(self) -> Tuple[str, str]:
        """The developer-portal app to authenticate as: the town's own if it
        supplied one, otherwise this deployment's registered Pinpoint app."""
        client_id = self.credentials.get("client_id")
        client_secret = self.credentials.get("client_secret")
        if client_id and client_secret:
            return client_id, client_secret
        client_id, client_secret = await accela_oauth.app_credentials()
        if not (client_id and client_secret):
            raise ConnectorError(
                "Accela credentials missing: no client_id/client_secret, and this "
                "deployment has no Accela app configured (ACCELA_CLIENT_ID / "
                "ACCELA_CLIENT_SECRET)."
            )
        return client_id, client_secret

    async def _token_from_refresh(self) -> Tuple[str, float]:
        client_id, client_secret = await self._app_credentials()
        result = await self._post_token({
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": self.credentials["refresh_token"],
        }, "Accela OAuth2 refresh")

        token = result.get("access_token")
        if not token:
            raise ConnectorError("Accela refresh returned no access_token")

        # Accela hands back a *new* refresh token and retires the old one. If we
        # don't persist it, this connection works exactly once more.
        rotated = result.get("refresh_token")
        if rotated and rotated != self.credentials.get("refresh_token"):
            self.credentials["refresh_token"] = rotated
            if self.persist_credentials:
                await self.persist_credentials({"refresh_token": rotated})
            else:
                logger.warning(
                    "[Accela] Refresh token rotated but no persistence hook is "
                    "attached — the stored token is now stale."
                )
        return token, float(result.get("expires_in") or 3600)

    async def _token_from_password(self) -> Tuple[str, float]:
        required = ["client_id", "client_secret", "username", "password"]
        missing = [k for k in required if not self.credentials.get(k)]
        if missing:
            raise ConnectorError(
                "Accela is not signed in. Reconnect it from Settings, or fill in "
                f"the username/password fallback (missing: {', '.join(missing)})."
            )
        result = await self._post_token({
            "grant_type": "password",
            "client_id": self.credentials["client_id"],
            "client_secret": self.credentials["client_secret"],
            "username": self.credentials["username"],
            "password": self.credentials["password"],
            "scope": self.scope,
            "agency_name": self.config["agency_name"],
            "environment": self.config.get("environment", "PROD"),
        }, "Accela OAuth2 token")
        token = result.get("access_token")
        if not token:
            raise ConnectorError("Accela token endpoint returned no access_token")
        return token, float(result.get("expires_in") or 3600)

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
        how = "signed in" if self.credentials.get("refresh_token") else "using the saved username and password"
        return {"ok": True, "detail": f"Connected to agency {self.config['agency_name']} — {how}."}

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

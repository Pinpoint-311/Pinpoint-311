"""Configurable REST connector.

Several govtech vendors (SDL/Spatial Data Logic, Edmunds GovTech, GovPilot,
FastTrackGov, Polimorphic) issue REST API endpoints and keys per customer
through their support/partner channels rather than publishing a universal
public API. This connector speaks plain JSON-over-HTTPS and lets each vendor's
customer-specific endpoint shape be described in config, so a working
end-to-end connection only needs the URL + key the vendor issues — no code
changes.

Config:
    base_url            required, e.g. https://api.vendor.com/v1
    create_path         default "/requests"       (POST, JSON body)
    get_path            default "/requests/{id}"  (GET)
    list_path           default "/requests"       (GET, ?updated_since=ISO8601)
    status_path         default "/requests/{id}/status"  (PUT {status, notes})
    auth_style          "bearer" (default) | "api_key_header" | "basic" | "query"
    auth_header         header name when auth_style=api_key_header (default X-API-Key)
    auth_query_param    query param name when auth_style=query (default api_key)
    id_field            response field holding the external id (default "id")
    status_field        response field holding status (default "status")
    updated_field       response field holding updated timestamp (default "updated_at")
    field_map           optional {pinpoint_field: vendor_field} overrides for the create body
Credentials:
    api_key             used by bearer / api_key_header / query styles
    username, password  used by basic style
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.integrations.base import BaseConnector, ConnectorError, ExternalComment, ExternalRecord

logger = logging.getLogger(__name__)

# Default create-body mapping: pinpoint field -> vendor field
DEFAULT_FIELD_MAP = {
    "service_request_id": "external_reference",
    "service_code": "category_code",
    "service_name": "category",
    "description": "description",
    "address": "address",
    "lat": "latitude",
    "long": "longitude",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "phone": "phone",
    "media_urls": "attachments",
    "requested_datetime": "submitted_at",
}


class GenericRestConnector(BaseConnector):
    platform = "generic_rest"
    capabilities = {"test", "push", "push_status", "pull", "comments", "documents", "assets"}

    DEFAULT_STATUS_MAP_OUT = {"open": "open", "in_progress": "in_progress", "closed": "closed"}
    DEFAULT_STATUS_MAP_IN = {
        "open": "open", "new": "open", "submitted": "open", "received": "open",
        "in_progress": "in_progress", "in progress": "in_progress",
        "assigned": "in_progress", "acknowledged": "in_progress", "pending": "in_progress",
        "closed": "closed", "resolved": "closed", "complete": "closed", "completed": "closed",
    }

    @property
    def base_url(self) -> str:
        url = (self.config.get("base_url") or "").rstrip("/")
        if not url:
            raise ConnectorError(
                f"{self.platform}: no API base URL configured. Enter the endpoint issued "
                f"by the vendor for your account (see the integration's setup notes)."
            )
        return url

    def _request_kwargs(self) -> Dict[str, Any]:
        style = self.config.get("auth_style", "bearer")
        kwargs: Dict[str, Any] = {"headers": {"Accept": "application/json"}}
        api_key = self.credentials.get("api_key")
        if style == "bearer" and api_key:
            kwargs["headers"]["Authorization"] = f"Bearer {api_key}"
        elif style == "api_key_header" and api_key:
            kwargs["headers"][self.config.get("auth_header", "X-API-Key")] = api_key
        elif style == "basic" and self.credentials.get("username"):
            kwargs["auth"] = (self.credentials.get("username", ""), self.credentials.get("password", ""))
        return kwargs

    def _query_auth(self) -> Dict[str, str]:
        if self.config.get("auth_style") == "query" and self.credentials.get("api_key"):
            return {self.config.get("auth_query_param", "api_key"): self.credentials["api_key"]}
        return {}

    def _url(self, key: str, default: str, external_id: Optional[str] = None) -> str:
        path = self.config.get(key, default)
        if external_id is not None:
            path = path.replace("{id}", str(external_id))
        return f"{self.base_url}{path}"

    def _record_from_response(self, item: Dict[str, Any]) -> ExternalRecord:
        id_field = self.config.get("id_field", "id")
        status_field = self.config.get("status_field", "status")
        updated_field = self.config.get("updated_field", "updated_at")
        raw_status = item.get(status_field)
        updated_dt = None
        if item.get(updated_field):
            try:
                updated_dt = datetime.fromisoformat(str(item[updated_field]).replace("Z", "+00:00"))
            except ValueError:
                pass
        # Reverse field_map so pulled records can be imported as new requests
        field_map = {**DEFAULT_FIELD_MAP, **(self.config.get("field_map") or {})}
        def theirs(ours: str, fallback: str) -> Any:
            return item.get(field_map.get(ours) or fallback)
        lat = theirs("lat", "latitude")
        lng = theirs("long", "longitude")
        return ExternalRecord(
            external_id=str(item.get(id_field) or ""),
            status=self.map_status_in(raw_status) if raw_status is not None else None,
            raw_status=str(raw_status) if raw_status is not None else None,
            updated_at=updated_dt,
            description=theirs("description", "description"),
            service_name=theirs("service_name", "category"),
            address=theirs("address", "address"),
            lat=float(lat) if lat is not None else None,
            long=float(lng) if lng is not None else None,
            raw=item,
        )

    def _build_create_body(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        field_map = {**DEFAULT_FIELD_MAP, **(self.config.get("field_map") or {})}
        body: Dict[str, Any] = {}
        for ours, theirs in field_map.items():
            if not theirs:
                continue  # mapping a field to null/"" omits it
            value = payload.get(ours)
            if value is not None and value != []:
                body[theirs] = value
        extra = self.config.get("static_fields") or {}
        body.update(extra)
        return body

    async def test_connection(self) -> Dict[str, Any]:
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.get(
                self._url("list_path", "/requests"),
                params={**self._query_auth(), "limit": 1},
            )
            self._raise_for_status(resp, f"{self.platform} API probe")
        return {"ok": True, "detail": f"Connected to {self.base_url}"}

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        body = self._build_create_body(payload)
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.post(
                self._url("create_path", "/requests"), params=self._query_auth(), json=body
            )
            self._raise_for_status(resp, f"{self.platform} create request")
            item = resp.json()
        if isinstance(item, list):
            item = item[0] if item else {}
        record = self._record_from_response(item if isinstance(item, dict) else {})
        if not record.external_id:
            raise ConnectorError(
                f"{self.platform} create response had no '{self.config.get('id_field', 'id')}' field: "
                f"{str(item)[:300]}"
            )
        return record

    async def push_status(self, external_id: str, status: str, notes: Optional[str] = None) -> None:
        body = {"status": self.map_status_out(status)}
        if notes:
            body["notes"] = notes
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.put(
                self._url("status_path", "/requests/{id}/status", external_id),
                params=self._query_auth(),
                json=body,
            )
            self._raise_for_status(resp, f"{self.platform} status update")

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        params: Dict[str, Any] = {**self._query_auth(), "limit": 100}
        if since:
            params["updated_since"] = since.isoformat()
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.get(self._url("list_path", "/requests"), params=params)
            self._raise_for_status(resp, f"{self.platform} list requests")
            body = resp.json()
        items = body if isinstance(body, list) else body.get(self.config.get("list_items_field", "results"), body.get("data", []))
        if not isinstance(items, list):
            return []
        records = [self._record_from_response(i) for i in items if isinstance(i, dict)]
        return [r for r in records if r.external_id]

    async def fetch_record(self, external_id: str) -> Optional[ExternalRecord]:
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.get(
                self._url("get_path", "/requests/{id}", external_id), params=self._query_auth()
            )
            if resp.status_code == 404:
                return None
            self._raise_for_status(resp, f"{self.platform} get request")
            item = resp.json()
        return self._record_from_response(item if isinstance(item, dict) else {})

    # ---- Comments ----
    # Config: comments_path (default "/requests/{id}/comments"),
    #         comment_id_field/comment_text_field/comment_author_field/comment_created_field

    async def push_comment(self, external_id: str, author: str, content: str) -> Optional[str]:
        body = {
            self.config.get("comment_text_field", "content"): content,
            self.config.get("comment_author_field", "author"): author or "Pinpoint 311",
        }
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.post(
                self._url("comments_path", "/requests/{id}/comments", external_id),
                params=self._query_auth(), json=body,
            )
            self._raise_for_status(resp, f"{self.platform} create comment")
            item = resp.json()
        if isinstance(item, dict):
            cid = item.get(self.config.get("comment_id_field", "id"))
            return str(cid) if cid is not None else None
        return None

    async def pull_comments(self, external_id: str) -> List[ExternalComment]:
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.get(
                self._url("comments_path", "/requests/{id}/comments", external_id),
                params=self._query_auth(),
            )
            if resp.status_code == 404:
                return []
            self._raise_for_status(resp, f"{self.platform} list comments")
            body = resp.json()
        items = body if isinstance(body, list) else body.get(
            self.config.get("comments_items_field", "comments"), body.get("results", [])
        )
        id_field = self.config.get("comment_id_field", "id")
        text_field = self.config.get("comment_text_field", "content")
        author_field = self.config.get("comment_author_field", "author")
        created_field = self.config.get("comment_created_field", "created_at")
        comments = []
        for item in (items or []):
            if not isinstance(item, dict) or item.get(id_field) is None or not item.get(text_field):
                continue
            created = None
            if item.get(created_field):
                try:
                    created = datetime.fromisoformat(str(item[created_field]).replace("Z", "+00:00"))
                except ValueError:
                    pass
            comments.append(ExternalComment(
                external_id=str(item[id_field]),
                content=str(item[text_field]),
                author=item.get(author_field),
                created_at=created,
                raw=item,
            ))
        return comments

    # ---- Documents ----
    # Config: documents_path (default "/requests/{id}/documents"),
    #         document_file_field (default "file")

    async def push_document(self, external_id: str, filename: str,
                            content: bytes, content_type: str) -> None:
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.post(
                self._url("documents_path", "/requests/{id}/documents", external_id),
                params=self._query_auth(),
                files={self.config.get("document_file_field", "file"): (filename, content, content_type)},
            )
            self._raise_for_status(resp, f"{self.platform} upload document")

    # ---- Assets ----
    # Config: assets_path (default "/assets"). The endpoint may return a GeoJSON
    # FeatureCollection directly, or a JSON list mapped via asset_*_field keys.

    async def pull_assets(self) -> List[Dict[str, Any]]:
        async with self._client(**self._request_kwargs()) as client:
            resp = await client.get(
                self._url("assets_path", "/assets", None), params=self._query_auth()
            )
            self._raise_for_status(resp, f"{self.platform} list assets")
            body = resp.json()
        # Native GeoJSON FeatureCollection
        if isinstance(body, dict) and body.get("type") == "FeatureCollection":
            return [f for f in body.get("features", []) if isinstance(f, dict) and f.get("geometry")]
        items = body if isinstance(body, list) else body.get(
            self.config.get("assets_items_field", "results"), body.get("data", [])
        )
        id_field = self.config.get("asset_id_field", "id")
        name_field = self.config.get("asset_name_field", "name")
        type_field = self.config.get("asset_type_field", "type")
        lat_field = self.config.get("asset_lat_field", "latitude")
        lng_field = self.config.get("asset_long_field", "longitude")
        features = []
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            lat, lng = item.get(lat_field), item.get(lng_field)
            if lat is None or lng is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lng), float(lat)]},
                "properties": {
                    "asset_id": str(item.get(id_field) or ""),
                    "name": item.get(name_field) or str(item.get(id_field) or ""),
                    "type": item.get(type_field),
                },
            })
        return features

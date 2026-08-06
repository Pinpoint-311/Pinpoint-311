"""Esri ArcGIS Feature Service connector.

Speaks the ArcGIS REST API directly against one hosted (or ArcGIS Enterprise)
feature layer:
  - metadata:    GET  {layer_url}?f=json
  - create:      POST {layer_url}/applyEdits   (adds=[...])
  - update:      POST {layer_url}/applyEdits   (updates=[...])
  - poll:        POST {layer_url}/query        (where on the edit-date field)
  - photos:      POST {layer_url}/{objectId}/addAttachment  (multipart)

Docs: https://developers.arcgis.com/rest/services-reference/apply-edits-feature-service-.htm
      https://developers.arcgis.com/documentation/mapping-apis-and-services/security/api-keys/

Two ArcGIS quirks drive the shape of this module:

1. ArcGIS answers HTTP 200 with an ``{"error": {...}}`` body for most failures,
   including a bad token. Status-code checks alone would report success on a
   dead connection, so every response goes through ``_arcgis_json``.
2. Requests are form-encoded, not JSON — the JSON structures (``adds``,
   ``updates``) travel as ``f=json`` string parameters inside a form body.

Config:
    layer_url           required, the feature LAYER url (ends in /FeatureServer/0)
    portal_url          for username/password tokens; default https://www.arcgis.com
    field_map           {pinpoint_field: layer_field} overrides for attributes
    static_fields       {layer_field: value} written on every new feature
    wkid                spatial reference of the geometry sent; default 4326
    object_id_field     override the layer's own OBJECTID field name
    external_id_field   attribute to use as the external id; default the object id
    edit_date_field     override the layer's editFieldsInfo.editDateField
    status_notes_field  layer field to write status notes into
    asset_layer_url     a second layer polled for the asset inventory
    reuse_maps_api_key  "false" to stop falling back to the maps ARCGIS_API_KEY
Credentials:
    api_key             an ArcGIS API key (used as the `token` parameter)
    username, password  an ArcGIS account; exchanged for a token via generateToken
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.integrations.base import BaseConnector, ConnectorError, ExternalRecord

logger = logging.getLogger(__name__)

DEFAULT_PORTAL = "https://www.arcgis.com"
DEFAULT_WKID = 4326
# Esri's own default for a hosted feature layer's last-edited column.
DEFAULT_EDIT_DATE_FIELD = "EditDate"
# ArcGIS error codes meaning "your token is missing, expired, or not allowed here".
_TOKEN_ERROR_CODES = {498, 499, 403}

# Default attribute mapping: pinpoint payload field -> layer field name.
# These follow the field names in Esri's own 311/citizen-request solution
# templates, so a layer built from an Esri template often needs no field_map
# at all. Anything else is one config entry per differing column.
DEFAULT_FIELD_MAP = {
    "service_request_id": "reqid",
    "service_name": "reqcategory",
    "service_code": "reqtype",
    "description": "details",
    "address": "address",
    "status": "status",
    "requested_datetime": "submitdt",
    "first_name": "firstname",
    "last_name": "lastname",
    "email": "email",
    "phone": "phone",
    # lat/long are not attributes — they become the feature's geometry.
}


def _epoch_ms(value: Any) -> Optional[int]:
    """ArcGIS date fields are epoch milliseconds; payload timestamps are ISO."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _from_epoch_ms(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, str):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


class ArcGISConnector(BaseConnector):
    platform = "arcgis"
    capabilities = {"test", "push", "push_status", "pull", "documents", "assets"}

    # A feature layer has no status vocabulary of its own — the town's domain
    # list does. These are the values Esri's citizen-request templates ship
    # with; a town whose layer uses different ones sets status_map_out/in.
    DEFAULT_STATUS_MAP_OUT = {"open": "Submitted", "in_progress": "Assigned", "closed": "Completed"}
    DEFAULT_STATUS_MAP_IN = {
        "submitted": "open", "unassigned": "open", "received": "open", "new": "open", "open": "open",
        "assigned": "in_progress", "in progress": "in_progress", "in_progress": "in_progress",
        "acknowledged": "in_progress", "scheduled": "in_progress", "dispatched": "in_progress",
        "completed": "closed", "complete": "closed", "closed": "closed", "resolved": "closed",
        "cancelled": "closed", "canceled": "closed", "rejected": "closed",
    }

    def __init__(self, config: Dict[str, Any], credentials: Dict[str, Any]):
        super().__init__(config, credentials)
        self._token: Optional[str] = None
        self._metadata: Optional[Dict[str, Any]] = None

    # ---- URLs -----------------------------------------------------------

    @property
    def layer_url(self) -> str:
        url = (self.config.get("layer_url") or "").rstrip("/")
        if not url:
            raise ConnectorError(
                "ArcGIS: no feature layer URL configured. Paste the layer address "
                "from ArcGIS — it ends in /FeatureServer/0."
            )
        return url

    @property
    def portal_url(self) -> str:
        return (self.config.get("portal_url") or DEFAULT_PORTAL).rstrip("/")

    # ---- Auth -----------------------------------------------------------

    async def _maps_api_key(self) -> Optional[str]:
        """The ArcGIS key already saved for the maps capability.

        A town that set up Esri maps has an org API key on file; making them
        paste it a second time to connect the same org's feature layer is
        friction with no security benefit. Opt out with reuse_maps_api_key=false.
        """
        if str(self.config.get("reuse_maps_api_key", "true")).strip().lower() in ("0", "false", "no", "off"):
            return None
        try:
            from app.services.secret_manager import get_secret
            return await get_secret("ARCGIS_API_KEY")
        except Exception as e:  # secret manager unavailable — not fatal
            logger.debug("[ArcGIS] Could not read the maps ARCGIS_API_KEY: %s", e)
            return None

    async def _generate_token(self) -> str:
        """Exchange an ArcGIS username/password for a short-lived token.

        client=requestip binds the token to this server's address, which is
        what a server-to-server integration wants — a referer-bound token
        would require us to claim a browser origin we don't have.
        """
        async with self._client() as client:
            resp = await client.post(
                f"{self.portal_url}/sharing/rest/generateToken",
                data={
                    "username": self.credentials["username"],
                    "password": self.credentials["password"],
                    "client": "requestip",
                    "expiration": 60,
                    "f": "json",
                },
            )
            self._raise_for_status(resp, "ArcGIS generateToken")
            body = self._arcgis_json(resp, "ArcGIS generateToken")
        token = body.get("token")
        if not token:
            raise ConnectorError("ArcGIS generateToken returned no token")
        return str(token)

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        api_key = self.credentials.get("api_key")
        if api_key:
            self._token = str(api_key)
        elif self.credentials.get("username") and self.credentials.get("password"):
            self._token = await self._generate_token()
        else:
            reused = await self._maps_api_key()
            if not reused:
                raise ConnectorError(
                    "ArcGIS credentials missing: provide an API key, or a username "
                    "and password, or save an ArcGIS API key under the maps settings "
                    "for this connection to reuse."
                )
            self._token = reused
        return self._token

    # ---- Response handling ----------------------------------------------

    @staticmethod
    def _arcgis_json(response: Any, context: str) -> Dict[str, Any]:
        """Parse an ArcGIS response, raising on the error-in-a-200 bodies.

        ArcGIS reports almost everything — bad token, missing layer, rejected
        edit — as HTTP 200 with an `error` object, so a status-code check alone
        would read a hard failure as success.
        """
        try:
            body = response.json()
        except ValueError:
            raise ConnectorError(f"{context} returned a non-JSON response: {response.text[:200]}")
        if not isinstance(body, dict):
            raise ConnectorError(f"{context} returned an unexpected response: {str(body)[:200]}")
        error = body.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message") or "unknown error"
            details = "; ".join(str(d) for d in (error.get("details") or []) if d)
            if code in _TOKEN_ERROR_CODES:
                raise ConnectorError(
                    f"{context} failed: HTTP 403 — ArcGIS rejected the credentials "
                    f"({message}). Check the API key's privileges, or that the layer "
                    f"is shared with the account. {details}".strip()
                )
            raise ConnectorError(f"{context} failed: ArcGIS error {code} — {message} {details}".strip())
        return body

    # ---- Layer metadata --------------------------------------------------

    async def _layer_metadata(self, url: Optional[str] = None) -> Dict[str, Any]:
        """Describe the layer. Cached per connector instance (one operation)."""
        if url is None and self._metadata is not None:
            return self._metadata
        token = await self._get_token()
        target = url or self.layer_url
        async with self._client() as client:
            resp = await client.get(target, params={"f": "json", "token": token})
            self._raise_for_status(resp, "ArcGIS layer metadata")
            body = self._arcgis_json(resp, "ArcGIS layer metadata")
        if url is None:
            self._metadata = body
        return body

    @staticmethod
    def _can(metadata: Dict[str, Any], capability: str) -> bool:
        caps = str(metadata.get("capabilities") or "")
        return capability.lower() in [c.strip().lower() for c in caps.split(",")]

    async def _object_id_field(self) -> str:
        configured = self.config.get("object_id_field")
        if configured:
            return str(configured)
        metadata = await self._layer_metadata()
        return str(metadata.get("objectIdField") or "OBJECTID")

    async def _edit_date_field(self) -> Optional[str]:
        """The layer column ArcGIS stamps on every edit — what a pull filters on."""
        configured = self.config.get("edit_date_field")
        if configured:
            return str(configured)
        metadata = await self._layer_metadata()
        edit_info = metadata.get("editFieldsInfo")
        if isinstance(edit_info, dict) and edit_info.get("editDateField"):
            return str(edit_info["editDateField"])
        # Editor tracking is off on this layer — fall back to Esri's default
        # column name only if the layer actually has it, so a bogus WHERE
        # clause doesn't turn every poll into an ArcGIS error.
        names = {str(f.get("name")) for f in (metadata.get("fields") or []) if isinstance(f, dict)}
        return DEFAULT_EDIT_DATE_FIELD if DEFAULT_EDIT_DATE_FIELD in names else None

    # ---- Field mapping ---------------------------------------------------

    def _field_map(self) -> Dict[str, str]:
        return {**DEFAULT_FIELD_MAP, **(self.config.get("field_map") or {})}

    async def _build_attributes(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Map the Pinpoint payload onto the layer's own columns.

        Only columns the layer actually has are sent: ArcGIS rejects the whole
        edit if an attribute name is unknown, so a field_map that drifts from
        the layer would otherwise break every push rather than one field.
        """
        metadata = await self._layer_metadata()
        date_fields, known = set(), set()
        for field in (metadata.get("fields") or []):
            if not isinstance(field, dict) or not field.get("name"):
                continue
            known.add(str(field["name"]))
            if field.get("type") == "esriFieldTypeDate":
                date_fields.add(str(field["name"]))

        attributes: Dict[str, Any] = {}
        for ours, theirs in self._field_map().items():
            if not theirs:
                continue  # mapping a field to blank omits it
            value = payload.get(ours)
            if value is None or value == [] or value == "":
                continue
            if ours == "status":
                value = self.map_status_out(str(value))
            if theirs in date_fields:
                value = _epoch_ms(value)
                if value is None:
                    continue
            attributes[str(theirs)] = value
        attributes.update(self.config.get("static_fields") or {})

        unknown = [name for name in attributes if known and name not in known]
        for name in unknown:
            logger.warning("[ArcGIS] Layer has no field %r — omitting it from the edit", name)
            attributes.pop(name)
        return attributes

    def _geometry(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        lat, lng = payload.get("lat"), payload.get("long")
        if lat is None or lng is None:
            return None
        try:
            wkid = int(self.config.get("wkid", DEFAULT_WKID))
        except (TypeError, ValueError):
            wkid = DEFAULT_WKID
        return {"x": float(lng), "y": float(lat), "spatialReference": {"wkid": wkid}}

    async def _record_from_feature(self, feature: Dict[str, Any]) -> ExternalRecord:
        attributes = feature.get("attributes") or {}
        oid_field = await self._object_id_field()
        id_field = str(self.config.get("external_id_field") or oid_field)
        field_map = self._field_map()

        raw_status = attributes.get(field_map.get("status") or "status")
        edit_field = await self._edit_date_field()
        updated = _from_epoch_ms(attributes.get(edit_field)) if edit_field else None

        geometry = feature.get("geometry") or {}
        lat = geometry.get("y")
        lng = geometry.get("x")

        def attr(ours: str) -> Optional[str]:
            key = field_map.get(ours)
            value = attributes.get(key) if key else None
            return str(value) if value is not None else None

        external_id = attributes.get(id_field)
        return ExternalRecord(
            external_id=str(external_id) if external_id is not None else "",
            status=self.map_status_in(raw_status) if raw_status is not None else None,
            raw_status=str(raw_status) if raw_status is not None else None,
            status_notes=attributes.get(self.config.get("status_notes_field")) if self.config.get("status_notes_field") else None,
            updated_at=updated,
            description=attr("description"),
            service_name=attr("service_name"),
            address=attr("address"),
            lat=float(lat) if isinstance(lat, (int, float)) else None,
            long=float(lng) if isinstance(lng, (int, float)) else None,
            raw=attributes,
        )

    # ---- Operations ------------------------------------------------------

    async def test_connection(self) -> Dict[str, Any]:
        metadata = await self._layer_metadata()
        name = metadata.get("name") or "(unnamed layer)"
        can_create = self._can(metadata, "create")
        can_update = self._can(metadata, "update")
        can_query = self._can(metadata, "query")

        parts = [f"Connected to the layer \"{name}\"."]
        if can_create and can_update:
            parts.append("It accepts new reports and status updates.")
        elif can_create:
            parts.append(
                "It accepts new reports, but not edits — status changes made in "
                "Pinpoint will not write back. Ask your GIS staff to enable Update "
                "on the layer if you want two-way status."
            )
        else:
            parts.append(
                "Note: this layer is read-only for us, so new reports cannot be "
                "written to it. Ask your GIS staff to turn on editing (Create) for "
                "the account or API key this connection uses."
            )
        if not can_query:
            parts.append("It also does not allow querying, so status cannot be polled back.")
        parts.append(
            "Photos will attach to each feature."
            if metadata.get("hasAttachments") else
            "Attachments are turned off on this layer, so resident photos will not be copied over."
        )
        if not await self._edit_date_field():
            parts.append(
                "Editor tracking is off, so status polling will re-read the whole "
                "layer each time instead of only what changed."
            )
        return {"ok": True, "detail": " ".join(parts)}

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        token = await self._get_token()
        feature: Dict[str, Any] = {"attributes": await self._build_attributes(payload)}
        geometry = self._geometry(payload)
        if geometry:
            feature["geometry"] = geometry

        async with self._client() as client:
            resp = await client.post(
                f"{self.layer_url}/applyEdits",
                data={"f": "json", "token": token, "rollbackOnFailure": "true",
                      "adds": json.dumps([feature])},
            )
            self._raise_for_status(resp, "ArcGIS applyEdits (add)")
            body = self._arcgis_json(resp, "ArcGIS applyEdits (add)")

        results = body.get("addResults") or []
        if not results:
            raise ConnectorError("ArcGIS applyEdits returned no addResults")
        result = results[0]
        if not result.get("success"):
            error = result.get("error") or {}
            raise ConnectorError(
                f"ArcGIS rejected the new feature: {error.get('description') or error.get('code') or 'unknown reason'}"
            )
        object_id = result.get("objectId")
        if object_id is None:
            raise ConnectorError("ArcGIS applyEdits succeeded but returned no objectId")

        # applyEdits echoes only the id back. When the external id is a
        # different column (e.g. GlobalID), read it off the created feature.
        if self.config.get("external_id_field"):
            fetched = await self.fetch_record(str(object_id), by_object_id=True)
            if fetched and fetched.external_id:
                return fetched
        local_status = payload.get("status") or "open"
        return ExternalRecord(
            external_id=str(object_id),
            status=local_status,
            raw_status=self.map_status_out(local_status),
            raw={"objectId": object_id, "globalId": result.get("globalId")},
        )

    async def push_status(self, external_id: str, status: str, notes: Optional[str] = None) -> None:
        token = await self._get_token()
        oid_field = await self._object_id_field()
        object_id = await self._resolve_object_id(external_id)
        field_map = self._field_map()
        attributes: Dict[str, Any] = {
            oid_field: object_id,
            (field_map.get("status") or "status"): self.map_status_out(status),
        }
        notes_field = self.config.get("status_notes_field")
        if notes and notes_field:
            attributes[str(notes_field)] = notes[:1000]

        async with self._client() as client:
            resp = await client.post(
                f"{self.layer_url}/applyEdits",
                data={"f": "json", "token": token, "rollbackOnFailure": "true",
                      "updates": json.dumps([{"attributes": attributes}])},
            )
            self._raise_for_status(resp, "ArcGIS applyEdits (update)")
            body = self._arcgis_json(resp, "ArcGIS applyEdits (update)")
        results = body.get("updateResults") or []
        if results and not results[0].get("success"):
            error = results[0].get("error") or {}
            raise ConnectorError(
                f"ArcGIS rejected the status update: {error.get('description') or error.get('code') or 'unknown reason'}"
            )

    async def _resolve_object_id(self, external_id: str) -> Any:
        """Edits address a feature by OBJECTID. When the town's external id is
        a different column, look the object id up first."""
        id_field = self.config.get("external_id_field")
        if not id_field:
            try:
                return int(external_id)
            except (TypeError, ValueError):
                return external_id
        oid_field = await self._object_id_field()
        features = await self._query(
            where=f"{id_field} = {self._sql_literal(external_id)}",
            out_fields=f"{oid_field},{id_field}",
            return_geometry=False,
        )
        if not features:
            raise ConnectorError(f"ArcGIS: no feature found with {id_field} = {external_id}")
        return (features[0].get("attributes") or {}).get(oid_field)

    @staticmethod
    def _sql_literal(value: str) -> str:
        """Quote a value for an ArcGIS WHERE clause. Numeric ids pass bare;
        anything else is single-quoted with quotes doubled, so an id can't
        break out of the clause."""
        text = str(value)
        try:
            float(text)
            return text
        except ValueError:
            return "'" + text.replace("'", "''") + "'"

    async def _query(self, where: str, out_fields: str = "*", return_geometry: bool = True,
                     layer_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """Run a layer query, paging until the service stops saying there's more."""
        token = await self._get_token()
        target = (layer_url or self.layer_url).rstrip("/")
        try:
            page_size = max(1, int(self.config.get("page_size", 1000)))
        except (TypeError, ValueError):
            page_size = 1000
        try:
            max_pages = max(1, int(self.config.get("max_pull_pages", 20)))
        except (TypeError, ValueError):
            max_pages = 20

        features: List[Dict[str, Any]] = []
        offset = 0
        async with self._client() as client:
            for _ in range(max_pages):
                # GET, not POST: a query is a read, and only idempotent methods
                # get the base transport's retries on a rate limit or gateway blip.
                resp = await client.get(f"{target}/query", params={
                    "f": "json",
                    "token": token,
                    "where": where,
                    "outFields": out_fields,
                    "returnGeometry": "true" if return_geometry else "false",
                    "outSR": DEFAULT_WKID,  # always hand back lat/long
                    "resultOffset": offset,
                    "resultRecordCount": page_size,
                })
                self._raise_for_status(resp, "ArcGIS query")
                body = self._arcgis_json(resp, "ArcGIS query")
                page = [f for f in (body.get("features") or []) if isinstance(f, dict)]
                features.extend(page)
                if not body.get("exceededTransferLimit") or not page:
                    break
                offset += len(page)
        return features

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        edit_field = await self._edit_date_field()
        if since and edit_field:
            # ArcGIS standardized SQL wants a UTC `timestamp 'YYYY-MM-DD HH:MM:SS'`
            # literal here, not the epoch milliseconds the field returns. A naive
            # `since` comes from the sync log, which stores UTC.
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            where = f"{edit_field} >= timestamp '{stamp}'"
        else:
            where = "1=1"
        features = await self._query(where=where)
        records = []
        for feature in features:
            record = await self._record_from_feature(feature)
            if record.external_id:
                records.append(record)
        return records

    async def fetch_record(self, external_id: str, by_object_id: bool = False) -> Optional[ExternalRecord]:
        id_field = await self._object_id_field() if by_object_id else str(
            self.config.get("external_id_field") or await self._object_id_field()
        )
        features = await self._query(where=f"{id_field} = {self._sql_literal(external_id)}")
        if not features:
            return None
        return await self._record_from_feature(features[0])

    # ---- Attachments (capability "documents") ---------------------------

    async def push_document(self, external_id: str, filename: str,
                            content: bytes, content_type: str) -> None:
        metadata = await self._layer_metadata()
        if not metadata.get("hasAttachments"):
            raise ConnectorError(
                f"ArcGIS layer \"{metadata.get('name') or self.layer_url}\" does not have "
                "attachments enabled, so photos cannot be copied over. Your GIS staff can "
                "turn attachments on for the layer."
            )
        token = await self._get_token()
        object_id = await self._resolve_object_id(external_id)
        async with self._client() as client:
            resp = await client.post(
                f"{self.layer_url}/{object_id}/addAttachment",
                data={"f": "json", "token": token},
                files={"attachment": (filename, content, content_type)},
            )
            self._raise_for_status(resp, "ArcGIS addAttachment")
            body = self._arcgis_json(resp, "ArcGIS addAttachment")
        result = body.get("addAttachmentResult") or {}
        if not result.get("success"):
            error = result.get("error") or {}
            raise ConnectorError(
                f"ArcGIS rejected the attachment: {error.get('description') or 'unknown reason'}"
            )

    # ---- Assets (capability "assets") -----------------------------------

    async def pull_assets(self) -> List[Dict[str, Any]]:
        """Mirror a second feature layer (hydrants, signs, lights) onto a
        Pinpoint map layer for asset-linked intake."""
        asset_url = (self.config.get("asset_layer_url") or "").rstrip("/")
        if not asset_url:
            raise ConnectorError(
                "ArcGIS asset sync needs an asset layer URL — the /FeatureServer/N "
                "address of the layer holding your asset inventory."
            )
        metadata = await self._layer_metadata(url=asset_url)
        oid_field = str(metadata.get("objectIdField") or "OBJECTID")
        id_field = self.config.get("asset_id_field") or oid_field
        name_field = self.config.get("asset_name_field")
        type_field = self.config.get("asset_type_field")

        features = await self._query(where="1=1", layer_url=asset_url)
        out: List[Dict[str, Any]] = []
        for feature in features:
            geometry = feature.get("geometry") or {}
            x, y = geometry.get("x"), geometry.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue  # only mappable points become layer features
            attributes = feature.get("attributes") or {}
            asset_id = attributes.get(id_field)
            out.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
                "properties": {
                    "asset_id": str(asset_id) if asset_id is not None else "",
                    "name": str(attributes.get(name_field) or asset_id or ""),
                    "type": str(attributes.get(type_field)) if type_field and attributes.get(type_field) is not None else metadata.get("name"),
                },
            })
        return out

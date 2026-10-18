"""Generic Open311 GeoReport v2 client.

Works against any spec-compliant endpoint (http://wiki.open311.org/GeoReport_v2),
which covers a large slice of the govtech market: Tyler Technologies 311,
CivicPlus SeeClickFix, Cityworks, QAlert, and many municipal in-house systems
expose GeoReport v2 endpoints. The Tyler connector is this class under another
platform name (see connectors/vendors.py), and this is also the supported route
to a SeeClickFix instance now that the vendor-specific connector is retired.

Config:
    base_url              e.g. https://city.example.gov/open311/v2  (required)
    jurisdiction_id       optional jurisdiction_id query param
    service_code_map_out  {local service code: vendor service_code} for pushes
    default_service_code  vendor service_code used when a category has no mapping
    attribute_map         {vendor attribute code: Pinpoint field or custom answer}
    import_new_records    also import records created at the vendor (start_date window)

GeoReport v2 has no way to update a record's status, so status flows one way:
from the vendor to Pinpoint. Status changes on records we filed are read by
polling ``requests.json?service_request_id=a,b,c`` -- the spec's ``start_date``
filters on when a request was *filed*, so a window would never see a status
change on a request older than the window.
Credentials:
    api_key           vendor-issued Open311 api_key (required for POST on most servers)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.integrations.base import (
    PENDING_ID_PREFIX, BaseConnector, ConnectorError, ExternalRecord,
)

logger = logging.getLogger(__name__)

# GeoReport v2: "service_request_id ... overrides all other parameters" and the
# list endpoint returns at most 1000 results over at most 90 days. Batches are
# kept well under any server's URL limit.
LINKED_BATCH_SIZE = 50
MAX_WINDOW = timedelta(days=90)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Open311Connector(BaseConnector):
    platform = "open311"
    capabilities = {"test", "push", "pull", "pull_linked", "lookups"}

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
        lat, lng = item.get("lat"), item.get("long")
        return ExternalRecord(
            external_id=str(item.get("service_request_id") or item.get("token") or ""),
            status=self.map_status_in(raw_status),
            raw_status=raw_status,
            status_notes=item.get("status_notes"),
            updated_at=_parse_dt(item.get("updated_datetime")),
            description=item.get("description"),
            service_name=item.get("service_name"),
            address=item.get("address"),
            lat=float(lat) if lat is not None else None,
            long=float(lng) if lng is not None else None,
            raw=item,
        )

    async def test_connection(self) -> Dict[str, Any]:
        """Confirm the endpoint is a GeoReport v2 server we can read.

        Deliberately reports `verified: False`. GeoReport v2 has no
        authenticated read endpoint -- `/services.json` answers anonymously on
        essentially every server, and the `api_key` only starts mattering on the
        POST that creates a record, which a connection check must not do. So the
        honest result is "we reached them, and nothing here has exercised your
        key". Returning a bare `ok` made the UI say "Connected", which a clerk
        reads as "the credentials work", and the first thing to discover
        otherwise would have been a resident's report failing to arrive.
        """
        async with self._client() as client:
            resp = await client.get(f"{self.base_url}/services.json", params=self._common_params())
            self._raise_for_status(resp, "Open311 services list")
            services = resp.json()
            count = len(services) if isinstance(services, list) else 0
        detail = f"Server reachable — it advertises {count} service type(s). "
        if self.credentials.get("api_key"):
            detail += ("Open311 has no way to check an API key without filing a real "
                       "record, so your key is only exercised on the first push.")
        else:
            detail += ("No API key is saved. Most Open311 servers need one to create "
                       "records, so pushes may be refused until you add it.")
        return {"ok": True, "verified": False, "detail": detail}

    async def pull_lookups(self) -> Dict[str, Any]:
        """This endpoint's service codes, and the status words the spec fixes.

        `/services.json` is the one call GeoReport v2 requires of every server
        and the only one this connector already makes on a connection check, so
        hydrating costs nothing new and needs no endpoint anybody had to guess
        at. The codes it returns are the exact strings a push has to send, which
        is what makes them worth picking from rather than typing.

        The status list is not fetched, because there is nothing to fetch: the
        spec defines the vocabulary as `open` and `closed` and that is the whole
        set. A server that answers with its own words -- and plenty do -- is
        outside the spec, so `status_map_in` still exists for it; what this
        removes is the guesswork on the outbound side, where the spec is
        binding.
        """
        async with self._client() as client:
            resp = await client.get(f"{self.base_url}/services.json",
                                    params=self._common_params())
            self._raise_for_status(resp, "Open311 services list")
            services = resp.json()
        if not isinstance(services, list):
            services = []
        return {
            "services": [
                {"code": str(item.get("service_code")),
                 "name": str(item.get("service_name") or item.get("service_code") or "")}
                for item in services
                if isinstance(item, dict) and item.get("service_code")
            ],
            "statuses": [
                {"code": "open", "name": "Open"},
                {"code": "closed", "name": "Closed"},
            ],
            "_source": {
                "services": f"{self.base_url}/services.json",
                "statuses": "fixed by the GeoReport v2 specification",
            },
        }

    def _service_code_for(self, payload: Dict[str, Any]) -> Optional[str]:
        """The vendor service_code to file under.

        The mapped code first; ``default_service_code`` only when this category
        has no mapping (it used to override every request, filing a pothole and
        a streetlight under one code); our own code as the last resort, which
        is right for the towns whose vendor codes match ours.
        """
        mapped = self.map_service_code_out(payload.get("service_code"))
        return mapped or self.config.get("default_service_code") or payload.get("service_code")

    async def _service_attributes(self, client: Any, service_code: str) -> List[Dict[str, Any]]:
        """The attribute definitions a service declares, or [] when it has none.

        Only services with ``metadata: true`` have a definition; for the rest
        the server answers 404 (or similar), which simply means "no extra
        questions".
        """
        try:
            resp = await client.get(f"{self.base_url}/services/{service_code}.json",
                                    params=self._common_params())
        except Exception as exc:  # a definition we cannot read is not a failed push
            logger.info("[Open311] could not read the service definition for %s: %s",
                        service_code, exc)
            return []
        if resp.status_code >= 400:
            return []
        try:
            body = resp.json()
        except ValueError:
            return []
        if isinstance(body, list):
            body = body[0] if body and isinstance(body[0], dict) else {}
        attrs = body.get("attributes") if isinstance(body, dict) else None
        return [a for a in (attrs or []) if isinstance(a, dict) and a.get("code")]

    def _attribute_value(self, code: str, payload: Dict[str, Any]) -> Any:
        """Where a value for one of the vendor's attribute codes comes from."""
        custom = payload.get("custom_fields") if isinstance(payload.get("custom_fields"), dict) else {}
        source = (self.config.get("attribute_map") or {}).get(code)
        if source:
            source = str(source)
            if source.startswith("custom_fields."):
                return custom.get(source.split(".", 1)[1])
            if source in payload:
                return payload.get(source)
            return custom.get(source)
        if code in custom:
            return custom[code]
        if code == "external_id":
            # The cross-reference home, for servers that ask for it by name.
            return payload.get("service_request_id")
        return None

    def _attribute_fields(self, attributes: List[Dict[str, Any]],
                          payload: Dict[str, Any], service_code: str) -> Dict[str, Any]:
        """``attribute[code]`` form fields, for codes this service defines only.

        Sending an attribute the service never declared is outside the spec,
        and stricter servers reject the whole create for it.
        """
        fields: Dict[str, Any] = {}
        for attr in attributes:
            code = str(attr["code"])
            if attr.get("variable") is False:
                continue  # informational text, not a question
            value = self._attribute_value(code, payload)
            if value in (None, "", []):
                if attr.get("required"):
                    self.warn(
                        f"Service {service_code} requires the answer \"{attr.get('description') or code}\" "
                        f"({code}) and Pinpoint has nothing mapped to it. Add it under Mapping, "
                        "or the vendor may refuse the report."
                    )
                continue
            if isinstance(value, (list, tuple)):
                fields[f"attribute[{code}][]"] = [str(v) for v in value]
            else:
                fields[f"attribute[{code}]"] = str(value)
        return fields

    async def resolve_pending_id(self, external_id: str) -> Optional[str]:
        """``GET tokens/{token}.json`` -> the real service_request_id, if assigned."""
        if not str(external_id).startswith(PENDING_ID_PREFIX):
            return str(external_id)
        token = str(external_id)[len(PENDING_ID_PREFIX):]
        async with self._client() as client:
            return await self._resolve_token(client, token)

    async def _resolve_token(self, client: Any, token: str) -> Optional[str]:
        resp = await client.get(f"{self.base_url}/tokens/{token}.json", params=self._common_params())
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp, "Open311 token lookup")
        try:
            body = resp.json()
        except ValueError:
            return None
        entry = body[0] if isinstance(body, list) and body else (body if isinstance(body, dict) else {})
        real = entry.get("service_request_id") if isinstance(entry, dict) else None
        return str(real) if real else None

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        service_code = self._service_code_for(payload)
        if not service_code:
            raise ConnectorError(
                "Open311: this category has no service code to file under. Map it under "
                "Mapping, or set a default service code."
            )
        data: Dict[str, Any] = dict(self._common_params())
        data.update({
            "service_code": service_code,
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

        async with self._client() as client:
            attributes = await self._service_attributes(client, str(service_code))
            data.update(self._attribute_fields(attributes, payload, str(service_code)))
            resp = await client.post(f"{self.base_url}/requests.json", data=data)
            self._raise_for_status(resp, "Open311 create request")
            body = resp.json()

            # Spec: a one-entry list carrying service_request_id, or a token when
            # the server assigns ids later.
            entry = body[0] if isinstance(body, list) and body else (body if isinstance(body, dict) else {})
            external_id = entry.get("service_request_id")
            token = entry.get("token")
            if not external_id and token:
                # Ask once straight away -- many servers assign within the
                # request. Otherwise the link holds the token and each pull
                # tries again; storing the token as if it were the record id
                # meant every later poll looked for a record that never exists.
                try:
                    external_id = await self._resolve_token(client, str(token))
                except ConnectorError as exc:
                    logger.info("[Open311] token %s not resolvable yet: %s", token, exc)
                    external_id = None
                if not external_id:
                    external_id = f"{PENDING_ID_PREFIX}{token}"
        if not external_id:
            raise ConnectorError(f"Open311 create returned no id/token: {str(body)[:300]}")
        return self._record_from_open311({**entry, "service_request_id": external_id})

    async def pull_linked(self, external_ids: List[str]) -> List[ExternalRecord]:
        """The current state of every record we filed, by id, in batches.

        ``service_request_id=a,b,c`` is the spec's own multi-get, and it
        overrides the date filters -- which is the point: a status change on a
        request filed four months ago is outside any window ``start_date`` can
        express.
        """
        ids = [str(i) for i in external_ids if i and not str(i).startswith(PENDING_ID_PREFIX)]
        records: List[ExternalRecord] = []
        if not ids:
            return records
        async with self._client() as client:
            for start in range(0, len(ids), LINKED_BATCH_SIZE):
                batch = ids[start:start + LINKED_BATCH_SIZE]
                params = {**self._common_params(), "service_request_id": ",".join(batch)}
                resp = await client.get(f"{self.base_url}/requests.json", params=params)
                self._raise_for_status(resp, "Open311 read linked requests")
                items = resp.json()
                if not isinstance(items, list):
                    continue
                records.extend(self._record_from_open311(i) for i in items
                               if isinstance(i, dict) and i.get("service_request_id"))
        return records

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        """Requests filed at the vendor since `since` -- for importing new ones.

        ``start_date`` filters on ``requested_datetime`` and the spec caps the
        span at 90 days, so this is a discovery window, not a change feed.
        Status changes on records we already hold come from ``pull_linked``.
        ``updated_after`` is a common extension and is sent alongside it.
        """
        params = dict(self._common_params())
        if since:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            floor = datetime.now(timezone.utc) - MAX_WINDOW
            if since < floor:
                since = floor
            params["updated_after"] = since.isoformat()
            params["start_date"] = since.isoformat()
        async with self._client() as client:
            resp = await client.get(f"{self.base_url}/requests.json", params=params)
            self._raise_for_status(resp, "Open311 list requests")
            items = resp.json()
        if not isinstance(items, list):
            return []
        return [self._record_from_open311(i) for i in items
                if isinstance(i, dict) and i.get("service_request_id")]

    async def fetch_record(self, external_id: str) -> Optional[ExternalRecord]:
        if str(external_id).startswith(PENDING_ID_PREFIX):
            resolved = await self.resolve_pending_id(external_id)
            if not resolved:
                return None
            external_id = resolved
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

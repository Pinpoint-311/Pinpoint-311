"""Map layers imported straight from an ArcGIS layer link, and kept in sync.

An admin pastes what they have -- a layer's REST address
(`.../FeatureServer/0`), a service with several layers, an ArcGIS Online or
Portal item page, or a Hub dataset page -- and gets the same layer an exported
GeoJSON upload would have produced: inline for points, table-backed for
polygons, clipped to the township, under the same caps. The features go
through the very functions an upload uses (`gis_layers.import_features` and
`gis_layers.build_inline_points`), streamed a page at a time.

Outbound requests are made on an admin's say-so to an address they typed, from
the production server, so every one goes through `GuardedTransport`:

  * https only, on the usual ArcGIS ports;
  * the hostname is resolved here and EVERY address checked: loopback,
    private, link-local (169.254.169.254, the cloud metadata address),
    shared/CGNAT, multicast, reserved, unspecified and any other non-global
    range are refused, including IPv4 hidden in IPv6 (mapped, 6to4, Teredo,
    NAT64). The connection is then made to the address that was checked, with
    the name kept for TLS (SNI and certificate check), so a DNS answer that
    changes between the check and the connect cannot redirect it;
  * redirects are never followed automatically; each hop is re-validated, at
    most three, and a token is never carried to a different host;
  * no credentials in the URL; a token is sent in a header (and the POST body
    for servers that ignore the header), never in a query string, and is
    never stored or logged;
  * connect timeout 5 s, 30 s in total per request, at most MAX_PAGE_BYTES per
    response, JSON content types only;
  * errors are short and plain, and never echo what the server sent.

Automatic sync (`sync_layer`) checks a cheap change marker first and only
re-imports when the source changed, and then only applies the result when it
passes the guardrails in `GUARDRAILS`; otherwise the old features stay and the
layer is marked for review.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import re
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx

from app.services import gis_layers
from app.services.gis_layers import Clip, LayerUploadError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

CONNECT_TIMEOUT_S = 5.0
REQUEST_TIMEOUT_S = 30.0          # total, per request (one page)
MAX_PAGE_BYTES = 32 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_PAGE_RECORDS = 2000           # asked for per page, even if the server allows more
MIN_PAGE_RECORDS = 50             # a page too large is retried at half size down to this
ID_BATCH = 250                    # objectIds per request on servers without pagination
MAX_SERVICE_LAYERS = 50           # layers listed for a service
MAX_COUNTED_LAYERS = 20           # of those, how many get a feature count
ALLOWED_PORTS = (443, 6443, 8443)  # ArcGIS Server's https ports
JSON_TYPES = ("application/json", "application/geo+json", "text/json", "text/plain",
              "application/javascript", "text/javascript")

# Auto-sync guardrails: an automatic run that would do any of these keeps the
# old features and marks the layer for review instead.
SYNC_DROP_RATIO = 0.20            # in-town features fall by more than 20%
SYNC_GROWTH_RATIO = 3.0           # or rise to more than three times as many
SYNC_INTERVALS = {"daily": timedelta(hours=23), "weekly": timedelta(days=7) - timedelta(hours=1)}

# ---------------------------------------------------------------------------
# Plain messages
# ---------------------------------------------------------------------------

NOT_A_LAYER = ("That address isn't an ArcGIS layer. Paste a layer's REST address "
               "(ending in /FeatureServer/0 or /MapServer/0), its service, or its ArcGIS Online item page.")
HTTPS_ONLY = "Only https:// addresses can be imported."
NO_CREDENTIALS = "Remove the user name and password from the address. Use the sign-in token field instead."
TOKEN_IN_URL = "Remove the token from the address and paste it in the sign-in token field instead."
PRIVATE_ADDRESS = "That address points to a private or internal network, which can't be imported."
BAD_PORT = "That address uses a port ArcGIS layers aren't imported from. Use the standard https address."
NO_SUCH_HOST = "Couldn't find a server at that address. Check it for typos."
TOKEN_NEEDED = "The service needs a sign-in token."
TOKEN_INVALID = "The sign-in token is invalid or has expired."
TOKEN_NO_ACCESS = "That sign-in token doesn't give access to this layer."
NOT_FOUND = "Nothing was found at that address. Check the layer number."
TIMED_OUT = "The ArcGIS server took too long to answer. Try again later."
UNREACHABLE = "Couldn't connect to the ArcGIS server. Try again later."
WEB_PAGE = "That address returned a web page, not ArcGIS data. Paste the layer's REST address instead."
HUB_UNRESOLVED = ("That ArcGIS Hub page can't be resolved to a layer. Open the dataset's "
                  "\"I want to use this\" / API panel and paste the layer's REST address instead.")
LINES_UNSUPPORTED = "Line layers can't be imported yet. Pinpoint takes point and polygon layers."
SYNC_NEEDS_PUBLIC = "Auto-sync needs a public service. For secured services, use Refresh from ArcGIS."


class ArcGisError(Exception):
    """A problem the admin can act on. The message is shown as-is.

    `code` is the HTTP or ArcGIS error code where there was one, for the
    callers that branch on it (the f=geojson fallback); it is never shown.
    """

    def __init__(self, message: str, *, code: Optional[int] = None, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class PageTooLarge(ArcGisError):
    pass


def user_agent() -> str:
    """Product and version only -- never an email or anything about a person."""
    try:
        from app.core.config import get_settings

        version = get_settings().app_version or "dev"
    except Exception:
        version = "dev"
    return f"Pinpoint311/{version} (gis-import)"


# ---------------------------------------------------------------------------
# The SSRF guard
# ---------------------------------------------------------------------------

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_REFUSED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".corp")


def ip_refused(addr: str) -> bool:
    """True for any address that is not plainly on the public internet."""
    from app.integrations.base import _is_disallowed_ip

    try:
        ip = ipaddress.ip_address(str(addr).split("%", 1)[0])
    except ValueError:
        return True
    if ip.version == 6:
        embedded = [ip.ipv4_mapped, ip.sixtofour]
        if ip.teredo:
            embedded.append(ip.teredo[1])
        if ip in _NAT64:
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if any(e is not None and ip_refused(str(e)) for e in embedded):
            return True
    # The integrations' own check (private, loopback, link-local, reserved,
    # multicast, unspecified), and then anything else that is not global:
    # shared address space 100.64/10, documentation ranges, 0/8 and the rest.
    return _is_disallowed_ip(str(ip)) or not ip.is_global or ip.is_multicast


def check_hostname(host: Optional[str]) -> None:
    if not host:
        raise ArcGisError(NOT_A_LAYER)
    name = host.strip("[]").lower().rstrip(".")
    try:
        ipaddress.ip_address(name)
        return  # a literal address; checked like any resolved one
    except ValueError:
        pass
    if name == "localhost" or name.endswith(_REFUSED_SUFFIXES) or "." not in name:
        raise ArcGisError(PRIVATE_ADDRESS)


async def resolve_host(host: str, port: int) -> List[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), CONNECT_TIMEOUT_S)
    except (socket.gaierror, asyncio.TimeoutError, UnicodeError, OSError):
        raise ArcGisError(NO_SUCH_HOST)
    return list(dict.fromkeys(info[4][0] for info in infos))


Resolver = Callable[[str, int], Awaitable[List[str]]]


class GuardedTransport(httpx.AsyncBaseTransport):
    """Checks every request's destination, then connects to the checked address.

    The request goes to the IP that passed, with the original name kept as the
    Host header and as the TLS server name (SNI and certificate verification),
    so the check and the connection cannot disagree (no DNS rebinding).
    """

    def __init__(self, inner: Optional[httpx.AsyncBaseTransport] = None,
                 resolver: Optional[Resolver] = None):
        self._inner = inner or httpx.AsyncHTTPTransport(retries=0)
        self._resolve = resolver or resolve_host

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme != "https":
            raise ArcGisError(HTTPS_ONLY)
        if url.userinfo:
            raise ArcGisError(NO_CREDENTIALS)
        host = url.host
        check_hostname(host)
        port = url.port or 443
        if port not in ALLOWED_PORTS:
            raise ArcGisError(BAD_PORT)
        addresses = await self._resolve(host, port)
        if not addresses:
            raise ArcGisError(NO_SUCH_HOST)
        if any(ip_refused(a) for a in addresses):
            raise ArcGisError(PRIVATE_ADDRESS)
        request.url = url.copy_with(host=addresses[0])
        request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------

_REDIRECTS = (301, 302, 303, 307, 308)


def _remote_error(code: Optional[int], has_token: bool) -> ArcGisError:
    if code == 499 or (code in (401, 403) and not has_token):
        return ArcGisError(TOKEN_NEEDED, code=code, status=401)
    if code == 498:
        return ArcGisError(TOKEN_INVALID, code=code, status=401)
    if code in (401, 403):
        return ArcGisError(TOKEN_NO_ACCESS, code=code, status=403)
    if code == 404:
        return ArcGisError(NOT_FOUND, code=code)
    if code == 400:
        return ArcGisError(NOT_A_LAYER, code=code)
    if code is not None and code >= 500:
        return ArcGisError(f"The ArcGIS server had a problem (error {code}). Try again later.",
                           code=code, status=502)
    return ArcGisError(f"The ArcGIS server returned an error (code {code}).", code=code, status=502)


class ArcGisClient:
    """One admin action's worth of requests. The token lives here and nowhere else."""

    def __init__(self, token: Optional[str] = None, *,
                 transport: Optional[httpx.AsyncBaseTransport] = None,
                 resolver: Optional[Resolver] = None):
        self._token = (token or "").strip() or None
        self.requests = 0
        self._http = httpx.AsyncClient(
            transport=GuardedTransport(transport, resolver),
            timeout=httpx.Timeout(REQUEST_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            follow_redirects=False,
            headers={"User-Agent": user_agent(), "Accept": "application/json"},
        )

    @property
    def has_token(self) -> bool:
        return self._token is not None

    async def __aenter__(self) -> "ArcGisClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._token = None
        await self._http.aclose()

    async def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            return await asyncio.wait_for(self._get_json(url, dict(params or {})), REQUEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise ArcGisError(TIMED_OUT, status=504)

    async def _get_json(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        origin = (urlsplit(url).hostname or "").lower()
        method = "POST" if self._token else "GET"
        for _hop in range(MAX_REDIRECTS + 1):
            same_host = (urlsplit(url).hostname or "").lower() == origin
            headers: Dict[str, str] = {}
            data = None
            if method == "POST":
                if not same_host:
                    # Never hand a token to a host the admin did not name.
                    raise ArcGisError("The ArcGIS server redirected to a different address. "
                                      "Paste the address it redirects to.")
                headers["X-Esri-Authorization"] = f"Bearer {self._token}"
                data = {**{k: str(v) for k, v in params.items()}, "token": self._token}
            self.requests += 1
            try:
                request = self._http.build_request(
                    method, url, params=params if method == "GET" else None, data=data, headers=headers)
                response = await self._http.send(request, stream=True)
            except ArcGisError:
                raise
            except httpx.TimeoutException:
                raise ArcGisError(TIMED_OUT, status=504)
            except httpx.HTTPError:
                # The exception text can carry the URL; nothing of it is shown.
                logger.info("[arcgis] request to %s failed", urlsplit(url).hostname, exc_info=False)
                raise ArcGisError(UNREACHABLE, status=502)
            try:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise ArcGisError(NOT_A_LAYER)
                    if method == "POST" and response.status_code not in (307, 308):
                        raise ArcGisError("The ArcGIS server redirected to a different address. "
                                          "Paste the address it redirects to.")
                    url = urljoin(url, location)
                    if method == "GET":
                        params = {}  # the Location carries the query
                    continue
                if response.status_code >= 400:
                    raise _remote_error(response.status_code, self.has_token)
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in JSON_TYPES:
                    raise ArcGisError(WEB_PAGE if "html" in ctype else NOT_A_LAYER)
                size = 0
                chunks: List[bytes] = []
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        raise PageTooLarge(
                            f"The ArcGIS server sent more than {MAX_PAGE_BYTES // 1048576} MB in one answer.",
                            status=502)
                    chunks.append(chunk)
            except httpx.TimeoutException:
                raise ArcGisError(TIMED_OUT, status=504)
            except httpx.HTTPError:
                raise ArcGisError(UNREACHABLE, status=502)
            finally:
                await response.aclose()
            try:
                body = json.loads(b"".join(chunks).decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError):
                raise ArcGisError(WEB_PAGE if b"<html" in b"".join(chunks)[:2000].lower() else NOT_A_LAYER)
            if not isinstance(body, dict):
                raise ArcGisError(NOT_A_LAYER)
            err = body.get("error")
            if isinstance(err, dict):
                try:
                    code = int(err.get("code"))
                except (TypeError, ValueError):
                    code = None
                raise _remote_error(code, self.has_token)
            return body
        raise ArcGisError("The ArcGIS server redirected too many times.")


ClientFactory = Callable[[Optional[str]], ArcGisClient]


def default_client(token: Optional[str] = None) -> ArcGisClient:
    return ArcGisClient(token)


# Swapped in tests for a client on a mocked transport.
client_factory: ClientFactory = default_client


# ---------------------------------------------------------------------------
# What the admin pasted
# ---------------------------------------------------------------------------

_SERVICE_RE = re.compile(
    r"^(?P<svc>/(?:[^?#]*/)?rest/services/(?:[^?#]+/)?[^/?#]+/(?:FeatureServer|MapServer))"
    r"(?:/(?P<layer>\d+))?(?:/[^?#]*)?$", re.I)
_ITEM_PAGE_RE = re.compile(r"^(?P<prefix>/(?:[^?#]*/)?)home/item\.html$", re.I)
_SHARING_ITEM_RE = re.compile(
    r"^(?P<prefix>/(?:[^?#]*/)?)sharing/rest/content/items/(?P<id>[0-9a-f]{32})(?:/.*)?$", re.I)
_HUB_RE = re.compile(r"^/(?:[^?#]*/)?(?:datasets|maps)/(?P<rest>[^/?#]+)", re.I)
_HUB_ID_RE = re.compile(r"^(?P<id>[0-9a-f]{32})(?:_(?P<layer>\d+))?$", re.I)
_ITEM_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
ARCGIS_ONLINE = "https://www.arcgis.com"


@dataclass
class ParsedUrl:
    """kind: "layer", "service", "item" or "hub". `url` is canonical: the layer
    or service REST address (no query, no trailing slash), or for an item the
    portal's sharing/rest items address."""
    kind: str
    url: str
    layer_id: Optional[int] = None
    item_id: Optional[str] = None
    portal: Optional[str] = None


def _origin(parts) -> str:
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port and parts.port != 443 else ""
    return f"https://{host.lower()}{port}"


def parse_url(raw: str) -> ParsedUrl:
    """Classify a pasted address, or ArcGisError with what to paste instead."""
    text = (raw or "").strip()
    if not text or len(text) > 2048 or any(c.isspace() for c in text):
        raise ArcGisError(NOT_A_LAYER)
    if "://" not in text:
        raise ArcGisError(NOT_A_LAYER)
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise ArcGisError(NOT_A_LAYER)
    if parts.scheme.lower() != "https":
        raise ArcGisError(HTTPS_ONLY)
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ArcGisError(NO_CREDENTIALS)
    check_hostname(parts.hostname)
    if port is not None and port not in ALLOWED_PORTS:
        raise ArcGisError(BAD_PORT)
    query = parse_qs(parts.query)
    if any(k.lower() == "token" for k in query):
        raise ArcGisError(TOKEN_IN_URL)
    origin = _origin(parts)
    path = re.sub(r"/{2,}", "/", parts.path or "/")

    m = _SERVICE_RE.match(path.rstrip("/") or "/")
    if m:
        service = origin + m.group("svc")
        if m.group("layer") is not None:
            layer = int(m.group("layer"))
            return ParsedUrl("layer", f"{service}/{layer}", layer_id=layer)
        return ParsedUrl("service", service)

    m = _SHARING_ITEM_RE.match(path)
    if m:
        portal = origin + m.group("prefix").rstrip("/")
        item = m.group("id").lower()
        return ParsedUrl("item", f"{portal}/sharing/rest/content/items/{item}", item_id=item, portal=portal)

    m = _ITEM_PAGE_RE.match(path)
    if m:
        ids = [v for k, vals in query.items() if k.lower() == "id" for v in vals]
        if ids and _ITEM_ID_RE.match(ids[0]):
            portal = origin + m.group("prefix").rstrip("/")
            item = ids[0].lower()
            return ParsedUrl("item", f"{portal}/sharing/rest/content/items/{item}", item_id=item, portal=portal)
        raise ArcGisError(NOT_A_LAYER)

    m = _HUB_RE.match(path)
    if m:
        hub = _HUB_ID_RE.match(m.group("rest"))
        if not hub:
            # "<org>::<slug>" and plain slugs need the Hub's own search API.
            raise ArcGisError(HUB_UNRESOLVED)
        item = hub.group("id").lower()
        layer = int(hub.group("layer")) if hub.group("layer") is not None else None
        return ParsedUrl("hub", f"{ARCGIS_ONLINE}/sharing/rest/content/items/{item}",
                         item_id=item, layer_id=layer, portal=ARCGIS_ONLINE)

    raise ArcGisError(NOT_A_LAYER)


async def resolve_item(client: ArcGisClient, parsed: ParsedUrl) -> ParsedUrl:
    """An item (or Hub dataset) to the service or layer it publishes."""
    body = await client.get_json(parsed.url, {"f": "json"})
    item_type = str(body.get("type") or "")
    url = body.get("url")
    if item_type not in ("Feature Service", "Map Service") or not isinstance(url, str) or not url:
        shown = re.sub(r"[^A-Za-z0-9 ]", "", item_type)[:40] or "not a layer"
        if parsed.kind == "hub":
            raise ArcGisError(HUB_UNRESOLVED)
        raise ArcGisError(f"That ArcGIS item is a {shown}, not a layer. "
                          "Open the layer and paste its address instead.")
    try:
        target = parse_url(url)
    except ArcGisError:
        raise ArcGisError(HUB_UNRESOLVED if parsed.kind == "hub" else NOT_A_LAYER)
    if target.kind not in ("layer", "service"):
        raise ArcGisError(NOT_A_LAYER)
    if parsed.layer_id is not None and target.kind == "service":
        return ParsedUrl("layer", f"{target.url}/{parsed.layer_id}", layer_id=parsed.layer_id)
    return target


# ---------------------------------------------------------------------------
# Describing a layer
# ---------------------------------------------------------------------------

GEOMETRY = {
    "esriGeometryPoint": "point",
    "esriGeometryMultipoint": "point",
    "esriGeometryPolygon": "polygon",
    "esriGeometryEnvelope": "polygon",
    "esriGeometryPolyline": "line",
}


@dataclass
class LayerInfo:
    url: str
    id: Optional[int]
    name: str
    geometry: Optional[str]           # point | polygon | line | None
    esri_geometry: Optional[str]
    fields: List[str]
    max_record_count: int
    supports_pagination: bool
    supports_geojson: bool
    object_id_field: Optional[str]
    can_query: bool
    layer_type: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)
    feature_count: Optional[int] = None
    in_area_count: Optional[int] = None

    @property
    def query_url(self) -> str:
        return f"{self.url}/query"


def _layer_info(url: str, body: Dict[str, Any]) -> LayerInfo:
    if not any(k in body for k in ("geometryType", "fields", "type")) or "layers" in body:
        raise ArcGisError(NOT_A_LAYER)
    adv = body.get("advancedQueryCapabilities") or {}
    formats = str(body.get("supportedQueryFormats") or "").lower()
    caps = str(body.get("capabilities") or "")
    fields = [str(f.get("name")) for f in (body.get("fields") or [])
              if isinstance(f, dict) and f.get("name") and f.get("type") != "esriFieldTypeGeometry"]
    oid = body.get("objectIdField")
    if not oid:
        oid = next((str(f.get("name")) for f in (body.get("fields") or [])
                    if isinstance(f, dict) and f.get("type") == "esriFieldTypeOID"), None)
    try:
        max_records = int(body.get("maxRecordCount") or 1000)
    except (TypeError, ValueError):
        max_records = 1000
    esri_geometry = body.get("geometryType")
    try:
        layer_id = int(body.get("id"))
    except (TypeError, ValueError):
        layer_id = None
    return LayerInfo(
        url=url, id=layer_id, name=str(body.get("name") or "Layer")[:100],
        geometry=GEOMETRY.get(esri_geometry) if esri_geometry else None,
        esri_geometry=esri_geometry, fields=fields[:gis_layers.MAX_AVAILABLE_PROPERTIES],
        max_record_count=max(1, max_records),
        supports_pagination=bool(adv.get("supportsPagination", body.get("supportsPagination", False))),
        supports_geojson="geojson" in formats,
        object_id_field=str(oid) if oid else None,
        can_query="query" in caps.lower() if caps else True,
        layer_type=str(body.get("type") or ""), raw=body,
    )


def envelope_params(bbox: Optional[Tuple[float, float, float, float]]) -> Dict[str, str]:
    """The ArcGIS spatial filter for the township's (buffered) envelope."""
    if not bbox:
        return {}
    w, s, e, n = bbox
    return {
        "geometry": f"{w:.6f},{s:.6f},{e:.6f},{n:.6f}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }


async def count_features(client: ArcGisClient, info: LayerInfo,
                         bbox: Optional[Tuple[float, float, float, float]] = None) -> Optional[int]:
    body = await client.get_json(info.query_url, {
        "where": "1=1", "returnCountOnly": "true", "f": "json", **envelope_params(bbox)})
    try:
        return int(body.get("count"))
    except (TypeError, ValueError):
        return None


async def describe_layer(client: ArcGisClient, url: str, *,
                         bbox: Optional[Tuple[float, float, float, float]] = None,
                         counts: bool = True) -> LayerInfo:
    info = _layer_info(url, await client.get_json(url, {"f": "json"}))
    if counts and info.geometry and info.can_query:
        info.feature_count = await count_features(client, info)
        if bbox:
            info.in_area_count = await count_features(client, info, bbox)
    return info


def layer_problem(info: LayerInfo) -> Optional[str]:
    """Why this layer cannot be imported at all, or None."""
    if info.layer_type == "Group Layer":
        return "That's a group of layers. Pick one of the layers inside it."
    if not info.esri_geometry:
        return "That is a table without locations, so there is nothing to put on a map."
    if info.geometry == "line":
        return LINES_UNSUPPORTED
    if info.geometry is None:
        return "That layer's geometry type can't be imported. Pinpoint takes point and polygon layers."
    if not info.can_query:
        return "That layer doesn't allow its features to be downloaded."
    return None


def limit_for(geometry: Optional[str]) -> int:
    return gis_layers.MAX_INLINE_FEATURES if geometry == "point" else gis_layers.MAX_FEATURES


def count_problem(info: LayerInfo, clip: Clip) -> Optional[str]:
    """'Too many features' when it is certain before downloading anything.

    With a township clip only the in-town count is capped, and the envelope
    count is an upper bound on that, so only a whole-layer count with no clip
    (or an envelope count past the scan ceiling) refuses up front.
    """
    limit = limit_for(info.geometry)
    if clip.applied:
        n = info.in_area_count
        if n is not None and n > gis_layers.MAX_SCAN_FEATURES:
            return f"Too many features: {n:,} in the township's area; the limit is {limit:,}."
        return None
    n = info.feature_count
    if n is not None and n > limit:
        return f"Too many features: {n:,}; the limit is {limit:,}."
    return None


def layer_summary(info: LayerInfo, clip: Clip) -> Dict[str, Any]:
    problem = layer_problem(info) or count_problem(info, clip)
    limit = limit_for(info.geometry)
    in_area = info.in_area_count
    warning = None
    if not problem and clip.applied and in_area is not None and in_area > limit:
        warning = (f"{in_area:,} features are in the township's area; the limit is {limit:,}. "
                   "The import works only if the exact boundary leaves fewer.")
    return {
        "id": info.id, "name": info.name, "url": info.url, "geometry": info.geometry,
        "esri_geometry": info.esri_geometry, "feature_count": info.feature_count,
        "in_area_count": in_area, "fields": info.fields, "limit": limit,
        "importable": problem is None, "problem": problem, "warning": warning,
    }


async def inspect(client: ArcGisClient, raw_url: str, clip: Clip) -> Dict[str, Any]:
    """What a pasted address holds: one layer, or a service's layers to pick from."""
    parsed = parse_url(raw_url)
    kind = parsed.kind
    if kind in ("item", "hub"):
        parsed = await resolve_item(client, parsed)
    bbox = clip.bbox if clip.applied else None
    if parsed.kind == "layer":
        info = await describe_layer(client, parsed.url, bbox=bbox)
        layers = [layer_summary(info, clip)]
    else:
        body = await client.get_json(parsed.url, {"f": "json"})
        entries = body.get("layers")
        if not isinstance(entries, list):
            raise ArcGisError(NOT_A_LAYER)
        layers = []
        sem = asyncio.Semaphore(4)

        async def one(entry: Dict[str, Any], counted: bool) -> Optional[Dict[str, Any]]:
            if not isinstance(entry, dict) or entry.get("subLayerIds"):
                return None  # group layers: their children are listed themselves
            try:
                lid = int(entry.get("id"))
            except (TypeError, ValueError):
                return None
            url = f"{parsed.url}/{lid}"
            async with sem:
                try:
                    info = await describe_layer(client, url, bbox=bbox, counts=counted)
                except ArcGisError as exc:
                    if exc.status == 401:
                        raise
                    return {"id": lid, "name": str(entry.get("name") or f"Layer {lid}")[:100], "url": url,
                            "geometry": GEOMETRY.get(entry.get("geometryType")), "feature_count": None,
                            "in_area_count": None, "fields": [], "importable": False, "problem": str(exc),
                            "warning": None, "limit": limit_for(GEOMETRY.get(entry.get("geometryType")))}
            return layer_summary(info, clip)

        shown = entries[:MAX_SERVICE_LAYERS]
        results = await asyncio.gather(*(one(e, i < MAX_COUNTED_LAYERS) for i, e in enumerate(shown)))
        layers = [r for r in results if r]
        if not layers:
            raise ArcGisError("That service has no layers with locations to import.")
    return {
        "kind": kind,
        "resolved_url": parsed.url,
        "layers": layers,
        "area": (clip.area_name or "your township boundary") if clip.applied else None,
        "clipped": clip.applied,
    }


# ---------------------------------------------------------------------------
# Esri JSON to GeoJSON
# ---------------------------------------------------------------------------

def _ring_area(ring: List[List[float]]) -> float:
    """Signed area (shoelace): negative for a clockwise ring, which Esri uses for outer rings."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _point_in_ring(x: float, y: float, ring: List[List[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def _xy(p: Any) -> Optional[List[float]]:
    if (isinstance(p, (list, tuple)) and len(p) >= 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in p[:2])):
        return [float(p[0]), float(p[1])]
    return None


def esri_to_geojson(geometry: Any) -> Optional[Dict[str, Any]]:
    """An Esri JSON geometry as GeoJSON, or None when it has no usable shape.

    Polygons: Esri lists rings flat, outer rings clockwise and holes
    counter-clockwise. Each outer ring starts a polygon, each hole joins the
    outer ring that contains it (one that fits none becomes an outer ring), and
    the output follows RFC 7946's winding. PostGIS repairs anything odder.
    """
    if not isinstance(geometry, dict):
        return None
    if "x" in geometry:
        p = _xy([geometry.get("x"), geometry.get("y")])
        return {"type": "Point", "coordinates": p} if p else None
    if "points" in geometry:
        pts = [q for q in (_xy(p) for p in geometry.get("points") or []) if q]
        if not pts:
            return None
        return {"type": "Point", "coordinates": pts[0]} if len(pts) == 1 else {"type": "MultiPoint", "coordinates": pts}
    if "paths" in geometry:
        paths = [[q for q in (_xy(p) for p in path) if q] for path in geometry.get("paths") or []]
        paths = [p for p in paths if len(p) >= 2]
        if not paths:
            return None
        return {"type": "LineString", "coordinates": paths[0]} if len(paths) == 1 else {
            "type": "MultiLineString", "coordinates": paths}
    if "rings" in geometry:
        rings = []
        for ring in geometry.get("rings") or []:
            pts = [q for q in (_xy(p) for p in ring) if q]
            if len(pts) < 3:
                continue
            if pts[0] != pts[-1]:
                pts.append(list(pts[0]))
            if len(pts) >= 4:
                rings.append(pts)
        if not rings:
            return None
        outers: List[List[List[List[float]]]] = []
        holes: List[List[List[float]]] = []
        for ring in rings:
            (outers.append([ring[::-1]]) if _ring_area(ring) < 0 else holes.append(ring))
        for hole in holes:
            x, y = hole[0]
            home = next((poly for poly in outers if _point_in_ring(x, y, poly[0])), None)
            if home is None:
                outers.append([hole])  # an unclosed or mis-wound outer ring; already counter-clockwise
            else:
                home.append(hole[::-1])
        if len(outers) == 1:
            return {"type": "Polygon", "coordinates": outers[0]}
        return {"type": "MultiPolygon", "coordinates": outers}
    return None


# ---------------------------------------------------------------------------
# Fetching features
# ---------------------------------------------------------------------------

@dataclass
class FetchStats:
    read: int = 0
    no_geometry: int = 0
    pages: int = 0
    format: str = "geojson"


def _wgs84(sr: Any) -> bool:
    if not isinstance(sr, dict):
        return True
    return 4326 in (sr.get("wkid"), sr.get("latestWkid"))


def _page(body: Dict[str, Any], fmt: str) -> Tuple[List[Dict[str, Any]], bool, int]:
    """(GeoJSON features, exceededTransferLimit, rows in the page) of one answer."""
    raw = body.get("features")
    if not isinstance(raw, list):
        raise ArcGisError(NOT_A_LAYER, code=400)
    exceeded = bool(body.get("exceededTransferLimit")
                    or (body.get("properties") or {}).get("exceededTransferLimit"))
    out: List[Dict[str, Any]] = []
    esri = fmt == "json" or body.get("type") != "FeatureCollection"
    if esri and not _wgs84(body.get("spatialReference")):
        raise ArcGisError("The ArcGIS server didn't return WGS 84 coordinates, so the layer can't be read.")
    for f in raw:
        if not isinstance(f, dict):
            continue
        if esri:
            geom = esri_to_geojson(f.get("geometry"))
            props = f.get("attributes") if isinstance(f.get("attributes"), dict) else {}
        else:
            geom = f.get("geometry") if isinstance(f.get("geometry"), dict) else None
            props = f.get("properties") if isinstance(f.get("properties"), dict) else {}
        out.append({"type": "Feature", "properties": props, "geometry": geom})
    return out, exceeded, len(raw)


async def iter_features(client: ArcGisClient, info: LayerInfo, *,
                        bbox: Optional[Tuple[float, float, float, float]] = None,
                        stats: Optional[FetchStats] = None) -> AsyncIterator[Dict[str, Any]]:
    """Every feature of the layer (inside `bbox` when given), as GeoJSON, a page at a time.

    f=geojson where the server offers it, else f=json converted here; a
    server that refuses f=geojson on the first page is asked again in Esri
    JSON. Pages by resultOffset where supported, else by objectIds. Features
    without a geometry are skipped and counted.
    """
    stats = stats or FetchStats()
    stats.format = "geojson" if info.supports_geojson else "json"
    base = {"where": "1=1", "outFields": "*", "outSR": "4326", "returnGeometry": "true",
            **envelope_params(bbox)}
    page_size = max(1, min(info.max_record_count, MAX_PAGE_RECORDS))

    async def fetch(params: Dict[str, Any], first: bool) -> Tuple[List[Dict[str, Any]], bool, int]:
        nonlocal page_size
        while True:
            try:
                body = await client.get_json(info.query_url, {**params, "f": stats.format})
                return _page(body, stats.format)
            except PageTooLarge:
                if "resultRecordCount" not in params or page_size <= MIN_PAGE_RECORDS:
                    raise
                page_size = max(MIN_PAGE_RECORDS, page_size // 2)
                params = {**params, "resultRecordCount": page_size}
            except ArcGisError as exc:
                if stats.format == "geojson" and first and exc.code == 400:
                    stats.format = "json"
                    continue
                raise

    def emit(features: List[Dict[str, Any]]):
        for f in features:
            if f["geometry"] is None:
                stats.no_geometry += 1
                continue
            stats.read += 1
            yield f

    if info.supports_pagination:
        offset = 0
        while True:
            params = {**base, "resultOffset": offset, "resultRecordCount": page_size}
            if info.object_id_field:
                params["orderByFields"] = info.object_id_field
            features, exceeded, rows = await fetch(params, offset == 0)
            stats.pages += 1
            for f in emit(features):
                yield f
            if rows == 0:
                break
            offset += rows
            if not exceeded and rows < page_size:
                break
    else:
        ids_body = await client.get_json(info.query_url, {
            **{k: v for k, v in base.items() if k not in ("outFields", "outSR", "returnGeometry")},
            "returnIdsOnly": "true", "f": "json"})
        oids = sorted(int(i) for i in (ids_body.get("objectIds") or []) if isinstance(i, (int, float)))
        if len(oids) > gis_layers.MAX_SCAN_FEATURES:
            raise ArcGisError(f"Too many features: {len(oids):,}; the limit is {limit_for(info.geometry):,}.")
        step = min(page_size, ID_BATCH)
        for i in range(0, len(oids), step):
            chunk = oids[i:i + step]
            params = {"objectIds": ",".join(str(o) for o in chunk), "outFields": "*",
                      "outSR": "4326", "returnGeometry": "true"}
            features, _, _ = await fetch(params, i == 0)
            stats.pages += 1
            for f in emit(features):
                yield f


# ---------------------------------------------------------------------------
# Import and refresh
# ---------------------------------------------------------------------------

def kind_of_layer(layer) -> str:
    """"polygons" (table-backed) or "points" (inline) for an existing layer."""
    return "polygons" if (layer.feature_storage or gis_layers.INLINE) == gis_layers.TABLE else "points"


def check_kind(info: LayerInfo, as_kind: str) -> None:
    problem = layer_problem(info)
    if problem:
        raise ArcGisError(problem)
    wanted = "point" if as_kind == "points" else "polygon"
    if info.geometry != wanted:
        raise ArcGisError(
            f"This layer has {info.geometry} features, so it can only be imported as "
            f"{'points' if info.geometry == 'point' else 'polygons'}.")


async def describe_import_target(client: ArcGisClient, raw_url: str, clip: Clip, *,
                                 counts: bool = True) -> LayerInfo:
    """The one layer an import or refresh reads from. A service or item must
    be narrowed to a layer first (the inspect step does that)."""
    parsed = parse_url(raw_url)
    if parsed.kind in ("item", "hub"):
        parsed = await resolve_item(client, parsed)
    if parsed.kind != "layer":
        raise ArcGisError("That address is a service with several layers. Check the link and pick one layer.")
    info = await describe_layer(client, parsed.url, counts=False)
    if counts:
        await add_counts(client, info, clip)
    return info


async def add_counts(client: ArcGisClient, info: LayerInfo, clip: Clip) -> None:
    """Fill in the counts, and refuse a layer certainly over the cap."""
    if info.geometry and info.can_query:
        info.feature_count = await count_features(client, info)
        if clip.applied:
            info.in_area_count = await count_features(client, info, clip.bbox)
    problem = count_problem(info, clip)
    if problem:
        raise ArcGisError(problem)


async def load_into(db, layer, client: ArcGisClient, info: LayerInfo, *, clip: Clip, as_kind: str,
                    progress: Optional[Callable[[int], None]] = None) -> Dict[str, Any]:
    """Download the layer's features into `layer` through the upload code paths.

    Polygons replace the layer's table rows (one transaction, keys stable by
    the ID property or the geometry hash); points become its inline
    FeatureCollection. The caller commits.
    """
    check_kind(info, as_kind)
    stats = FetchStats()
    bbox = clip.bbox if clip.applied else None
    features = iter_features(client, info, bbox=bbox, stats=stats)
    try:
        if as_kind == "polygons":
            summary = await gis_layers.import_features(db, layer, features, clip=clip, progress=progress)
        else:
            geojson, summary = await gis_layers.build_inline_points(db, features, clip=clip, progress=progress)
            layer.geojson = geojson
            layer.layer_type = "point"
            layer.feature_storage = gis_layers.INLINE
            layer.available_properties = summary["properties"]
            layer.feature_count = summary["feature_count"]
            layer.features_imported_at = datetime.now(timezone.utc)
    except LayerUploadError as exc:
        if stats.read == 0:
            # "The file has no features" reads oddly for a link.
            where = " in the township's area" if clip.applied else ""
            raise ArcGisError(f"The layer has no features{where}.")
        raise exc
    finally:
        await features.aclose()
    summary["no_geometry"] = stats.no_geometry
    summary["pages"] = stats.pages
    summary["source"] = "arcgis"
    if stats.no_geometry:
        summary["clip_message"] += (f" {stats.no_geometry:,} feature{'s' if stats.no_geometry != 1 else ''} "
                                    "without a location were left out.")
    layer.source_url = info.url
    layer.source_synced_at = datetime.now(timezone.utc)
    return summary


async def source_marker(client: ArcGisClient, info: LayerInfo) -> str:
    """A cheap "has the source changed" marker.

    The layer's own last data-edit date where it publishes one (editingInfo),
    else the feature count plus the highest object id.
    """
    editing = info.raw.get("editingInfo") if isinstance(info.raw.get("editingInfo"), dict) else {}
    stamp = editing.get("dataLastEditDate") or editing.get("lastEditDate")
    if stamp:
        return f"edit:{stamp}"
    count = info.feature_count if info.feature_count is not None else await count_features(client, info)
    top = None
    if info.object_id_field:
        try:
            body = await client.get_json(info.query_url, {
                "where": "1=1", "f": "json",
                "outStatistics": json.dumps([{"statisticType": "max", "onStatisticField": info.object_id_field,
                                              "outStatisticFieldName": "max_oid"}])})
            feats = body.get("features") or []
            if feats and isinstance(feats[0], dict):
                attrs = feats[0].get("attributes") or {}
                top = next(iter(attrs.values()), None)
        except ArcGisError:
            top = None
    return f"count:{count}:max:{top}"


class SyncHeld(Exception):
    """An automatic sync a guardrail stopped. The message is the reason, shown to admins."""


def guard_before(layer, info: LayerInfo) -> None:
    """Guardrails that need no download: the geometry type and the ID field."""
    expected = "polygon" if kind_of_layer(layer) == "polygons" else "point"
    if info.geometry != expected:
        raise SyncHeld(f"The source's geometry type changed from {expected} to {info.geometry or 'none'}.")
    if layer.feature_id_property and layer.feature_id_property not in info.fields:
        raise SyncHeld(f"The ID field {layer.feature_id_property} is no longer in the source.")


def guard_after(before: Optional[int], after: int) -> None:
    """Guardrails on the counts, in town, before and after."""
    if not before:
        return
    if after <= 0:
        raise SyncHeld(f"The source returned no features in the township; the layer has {before:,}.")
    if after < before * (1 - SYNC_DROP_RATIO):
        raise SyncHeld(f"The feature count would drop from {before:,} to {after:,} "
                       f"(more than {int(SYNC_DROP_RATIO * 100)}%).")
    if after > before * SYNC_GROWTH_RATIO:
        raise SyncHeld(f"The feature count would rise from {before:,} to {after:,} "
                       f"(more than {SYNC_GROWTH_RATIO:g} times).")


def _current_count(layer) -> Optional[int]:
    if layer.feature_count is not None:
        return int(layer.feature_count)
    feats = (layer.geojson or {}).get("features") if isinstance(layer.geojson, dict) else None
    return len(feats) if isinstance(feats, list) else None


@dataclass
class RefreshOutcome:
    applied: bool
    before: Optional[int]
    after: Optional[int]
    summary: Optional[Dict[str, Any]] = None
    held: Optional[str] = None
    unchanged: bool = False


async def refresh_layer(db, layer, client: ArcGisClient, *, guard: bool,
                        progress: Optional[Callable[[int], None]] = None,
                        skip_if_unchanged: bool = False) -> RefreshOutcome:
    """Re-import a layer from its source_url, replacing its features atomically.

    Inside a SAVEPOINT: on any failure, or (with `guard`) when a guardrail
    trips, it is rolled back and the old features stay exactly as they were.
    With `skip_if_unchanged`, a source whose change marker matches the stored
    one is left alone. The caller commits.
    """
    if not layer.source_url:
        raise ArcGisError("This layer wasn't imported from ArcGIS.")
    clip = await gis_layers.load_clip(db)
    before = _current_count(layer)
    try:
        # The change marker first: an unchanged source costs one or two requests.
        info = await describe_import_target(client, layer.source_url, clip, counts=False)
        marker = await source_marker(client, info)
        if skip_if_unchanged and layer.source_last_edit and marker == layer.source_last_edit:
            return RefreshOutcome(applied=False, before=before, after=before, unchanged=True)
        await add_counts(client, info, clip)
    except ArcGisError as exc:
        if guard:
            raise SyncHeld(f"Couldn't read the source: {exc}")
        raise
    if guard:
        guard_before(layer, info)
    as_kind = kind_of_layer(layer)
    savepoint = await db.begin_nested()
    try:
        summary = await load_into(db, layer, client, info, clip=clip, as_kind=as_kind, progress=progress)
        if guard:
            guard_after(before, summary["feature_count"])
    except (SyncHeld, ArcGisError, LayerUploadError, Exception) as exc:
        await savepoint.rollback()
        await db.refresh(layer)
        if not guard:
            raise
        if isinstance(exc, SyncHeld):
            raise
        if isinstance(exc, (ArcGisError, LayerUploadError)):
            raise SyncHeld(f"The update failed: {exc}")
        logger.warning("[arcgis] automatic sync of layer %s failed", layer.id, exc_info=True)
        raise SyncHeld("The update failed with an unexpected error.")
    await savepoint.commit()
    layer.source_last_edit = marker[:100]
    return RefreshOutcome(applied=True, before=before, after=summary["feature_count"], summary=summary)


# ---------------------------------------------------------------------------
# Automatic sync
# ---------------------------------------------------------------------------

class _SyncActor:
    """The audit trail's actor for automatic runs: no user, a clear name."""
    id = None
    username = "arcgis-auto-sync"
    role = "system"


def sync_due(layer, now: datetime) -> bool:
    interval = SYNC_INTERVALS.get(layer.source_sync or "")
    if interval is None or not layer.source_url:
        return False
    last = layer.source_checked_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last >= interval


async def sync_layer(db, layer, *, client_for: Optional[ClientFactory] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """One guarded automatic sync of one layer. Commits. Never raises.

    No token, ever: auto-sync is for public services. A service that wants a
    sign-in is held with SYNC_NEEDS_PUBLIC.
    """
    from app.services.admin_audit import record_admin_action

    now = now or datetime.now(timezone.utc)
    make = client_for or client_factory
    result: Dict[str, Any] = {"layer_id": layer.id, "name": layer.name}
    try:
        async with make(None) as client:
            outcome = await refresh_layer(db, layer, client, guard=True, skip_if_unchanged=True)
    except SyncHeld as held:
        reason = str(held)
        if TOKEN_NEEDED in reason or TOKEN_NO_ACCESS in reason:
            reason = SYNC_NEEDS_PUBLIC
        layer.source_sync_status = "held"
        layer.source_sync_error = reason[:500]
        layer.source_checked_at = now
        await db.commit()
        await record_admin_action(db, event_type="map_layer_sync_held", actor=_SyncActor(), details={
            "layer_id": layer.id, "layer_name": layer.name, "reason": reason[:300]})
        result.update(state="held", reason=reason)
        return result
    except Exception:
        await db.rollback()
        logger.warning("[arcgis] automatic sync of layer %s failed", getattr(layer, "id", None), exc_info=True)
        result.update(state="error")
        return result
    layer.source_checked_at = now
    if outcome.unchanged:
        # A source that has not changed does not clear a hold: the data the
        # guard stopped is still waiting for an admin to look at it.
        if layer.source_sync_status != "held":
            layer.source_sync_status = "ok"
            layer.source_sync_error = None
        await db.commit()
        result.update(state="unchanged")
        return result
    layer.source_sync_status = "updated"
    layer.source_sync_error = None
    await db.commit()
    await record_admin_action(db, event_type="map_layer_sync_applied", actor=_SyncActor(), details={
        "layer_id": layer.id, "layer_name": layer.name, "before": outcome.before, "after": outcome.after})
    result.update(state="updated", before=outcome.before, after=outcome.after)
    return result


async def run_due_syncs(db, *, now: Optional[datetime] = None,
                        client_for: Optional[ClientFactory] = None) -> Dict[str, Any]:
    """Every layer whose auto-sync is due, one after another. Never raises."""
    from sqlalchemy import select
    from app.models import MapLayer

    now = now or datetime.now(timezone.utc)
    rows = (await db.execute(
        select(MapLayer).where(MapLayer.source_url.isnot(None),
                               MapLayer.source_sync.in_(tuple(SYNC_INTERVALS)))
        .order_by(MapLayer.id))).scalars().all()
    results = []
    for layer in rows:
        if sync_due(layer, now):
            results.append(await sync_layer(db, layer, client_for=client_for, now=now))
    return {"checked": len(results), "results": results}


async def held_layers(db) -> List[Tuple[str, str]]:
    """(name, reason) for every auto-synced layer a guardrail is holding."""
    from sqlalchemy import select
    from app.models import MapLayer

    rows = (await db.execute(
        select(MapLayer.name, MapLayer.source_sync_error)
        .where(MapLayer.source_sync_status == "held", MapLayer.source_sync.in_(tuple(SYNC_INTERVALS)))
        .order_by(MapLayer.name))).all()
    return [(name, reason or "") for name, reason in rows]


# ---------------------------------------------------------------------------
# Background jobs (manual imports and refreshes)
# ---------------------------------------------------------------------------
#
# A county parcel layer is hundreds of pages; that is minutes, longer than a
# request should be held open. The import runs as a task in the API process
# and the console polls it. Like the chunked-upload staging, jobs are local to
# the process: a multi-replica deployment needs sticky routing for these
# routes. Finished jobs are forgotten after JOB_TTL.

JOB_TTL = timedelta(hours=1)
MAX_RUNNING_JOBS = 2


@dataclass
class Job:
    id: str
    user_id: Optional[int]
    kind: str
    state: str = "running"            # running | done | failed
    read: int = 0
    expected: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    task: Optional[asyncio.Task] = field(default=None, repr=False)

    def public(self) -> Dict[str, Any]:
        return {"job_id": self.id, "kind": self.kind, "state": self.state, "read": self.read,
                "expected": self.expected, "result": self.result, "error": self.error}


_JOBS: Dict[str, Job] = {}


def _prune_jobs(now: Optional[datetime] = None) -> None:
    now = now or datetime.now(timezone.utc)
    for jid in [j.id for j in _JOBS.values() if j.finished_at and now - j.finished_at > JOB_TTL]:
        _JOBS.pop(jid, None)


def get_job(job_id: str, user_id: Optional[int]) -> Optional[Job]:
    _prune_jobs()
    job = _JOBS.get(job_id)
    return job if job and job.user_id == user_id else None


def start_job(user_id: Optional[int], kind: str,
              work: Callable[[Job], Awaitable[Dict[str, Any]]], *, expected: Optional[int] = None) -> Job:
    """Run `work(job)` in the background. Refuses past the concurrency limits."""
    _prune_jobs()
    running = [j for j in _JOBS.values() if j.state == "running"]
    if any(j.user_id == user_id for j in running):
        raise ArcGisError("An ArcGIS import is already running. Wait for it to finish.", status=409)
    if len(running) >= MAX_RUNNING_JOBS:
        raise ArcGisError("Other ArcGIS imports are running. Try again in a few minutes.", status=429)
    job = Job(id=uuid.uuid4().hex, user_id=user_id, kind=kind, expected=expected)

    async def run() -> None:
        try:
            job.result = await work(job)
            job.state = "done"
        except (ArcGisError, LayerUploadError) as exc:
            job.error = str(exc)
            job.state = "failed"
        except Exception:
            logger.exception("[arcgis] %s job failed", kind)
            job.error = "The import failed, and nothing was changed. Try again, or upload a file instead."
            job.state = "failed"
        finally:
            job.finished_at = datetime.now(timezone.utc)

    _JOBS[job.id] = job
    job.task = asyncio.get_running_loop().create_task(run())
    return job

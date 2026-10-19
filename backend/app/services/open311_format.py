"""GeoReport v2 wire formats: the XML encoding, the error shape, timestamps.

XML is built with ElementTree, which escapes text for us. No element is ever
assembled by string concatenation, and no element NAME is ever taken from
input: names come from the spec (and from our own dict keys, which are checked
against a strict pattern), values go in as text. Characters XML 1.0 cannot
carry at all (NUL and the other C0 controls) are dropped, because escaping
cannot make them legal and one of them in a resident's description would
otherwise make the whole document unparseable.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from fastapi import Response
from fastapi.responses import JSONResponse

XML_MEDIA_TYPE = "text/xml; charset=utf-8"

# The spec's plural -> singular pairs for list containers.
_ITEM_NAMES = {
    "endpoints": "endpoint",
    "formats": "format",
    "attributes": "attribute",
    "values": "value",
    "service_requests": "request",
    "services": "service",
    "errors": "error",
    "departments": "department",
    "translations_available": "language",
}

_NAME_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def wants_xml(path: str) -> bool:
    return path.endswith(".xml")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return w3c(value) or ""
    return _XML_ILLEGAL.sub("", str(value))


def _append(parent: ET.Element, name: str, value: Any) -> None:
    if not _NAME_OK.match(name):
        # Never happens with our own payloads; refusing beats emitting a
        # document a client cannot parse.
        return
    if isinstance(value, dict):
        node = ET.SubElement(parent, name)
        for k, v in value.items():
            _append(node, str(k), v)
    elif isinstance(value, (list, tuple)):
        node = ET.SubElement(parent, name)
        item_name = _ITEM_NAMES.get(name, "item")
        for item in value:
            _append(node, item_name, item)
    else:
        node = ET.SubElement(parent, name)
        node.text = _text(value)


def to_xml(root_name: str, payload: Any) -> bytes:
    """Encode `payload` under `root_name`.

    A list becomes repeated children named for the root (`services` ->
    `service`), a dict becomes child elements, a scalar becomes text.
    """
    root = ET.Element(root_name)
    if isinstance(payload, (list, tuple)):
        item_name = _ITEM_NAMES.get(root_name, "item")
        for item in payload:
            _append(root, item_name, item)
    elif isinstance(payload, dict):
        for k, v in payload.items():
            _append(root, str(k), v)
    else:
        root.text = _text(payload)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render(path: str, root_name: str, payload: Any, status_code: int = 200) -> Response:
    """JSON or XML for the same payload, chosen by the path's extension."""
    if wants_xml(path):
        return Response(content=to_xml(root_name, payload), media_type=XML_MEDIA_TYPE,
                        status_code=status_code)
    return JSONResponse(content=payload, status_code=status_code)


def error_response(path: str, code: int, description: str, headers: Optional[dict] = None) -> Response:
    """The spec's error body: `[{"code": 403, "description": "..."}]` or its XML twin."""
    body = [{"code": int(code), "description": str(description)}]
    if wants_xml(path):
        return Response(content=to_xml("errors", body), media_type=XML_MEDIA_TYPE,
                        status_code=code, headers=headers)
    return JSONResponse(content=body, status_code=code, headers=headers)


def detail_text(detail: Any) -> str:
    """A one-line description from whatever an HTTPException carried."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("error") or "Request failed")
    if isinstance(detail, list):
        return "; ".join(detail_text(d) for d in detail) or "Request failed"
    return "Request failed"


def validation_text(errors: Iterable[dict]) -> str:
    """Name the fields that failed, never the values (they may be anything)."""
    parts = []
    for e in errors:
        loc = [str(p) for p in (e.get("loc") or ()) if p not in ("body", "query", "path")]
        field = ".".join(loc) or "request"
        parts.append(f"{field}: {e.get('msg', 'invalid')}")
    return "; ".join(parts) or "Invalid request"


def w3c(value: Optional[datetime]) -> Optional[str]:
    """W3C/ISO 8601 with an explicit offset, as the spec asks. Naive means UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def parse_w3c(raw: Optional[str]) -> Optional[datetime]:
    """Parse a spec datetime. Raises ValueError on garbage. Naive means UTC."""
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    value = datetime.fromisoformat(s)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


class Open311Error(Exception):
    """Raise from an Open311 route to answer with the spec's error body."""

    def __init__(self, code: int, description: str, headers: Optional[dict] = None):
        super().__init__(description)
        self.code = code
        self.description = description
        self.headers = headers


def spec_route_class():
    """An APIRoute subclass whose errors take the GeoReport v2 shape.

    Only the GeoReport v2 routes use it. HTTPException, request validation and
    rate-limit errors raised anywhere in such a route (its dependencies
    included) come back as `[{"code", "description"}]`, or `<errors>` on an
    `.xml` path. Every other route in the API keeps FastAPI's `{"detail": ...}`.

    Validation failures are reported as 400, the spec's code for a bad
    parameter, and name the field but never echo its value -- the same rule
    app.main's global 422 handler follows.
    """
    from fastapi.exceptions import HTTPException, RequestValidationError
    from fastapi.routing import APIRoute
    from slowapi.errors import RateLimitExceeded
    from starlette.exceptions import HTTPException as StarletteHTTPException

    class Open311Route(APIRoute):
        def get_route_handler(self):
            original = super().get_route_handler()

            async def handler(request):
                path = request.url.path
                try:
                    return await original(request)
                except Open311Error as exc:
                    return error_response(path, exc.code, exc.description, exc.headers)
                except RequestValidationError as exc:
                    return error_response(path, 400, validation_text(exc.errors()))
                except RateLimitExceeded:
                    return error_response(path, 429, "Rate limit exceeded. Try again in a minute.",
                                          {"Retry-After": "60"})
                except (HTTPException, StarletteHTTPException) as exc:
                    headers = getattr(exc, "headers", None)
                    return error_response(path, exc.status_code, detail_text(exc.detail), headers)

            return handler

    return Open311Route

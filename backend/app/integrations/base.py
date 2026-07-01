"""Base connector contract for external govtech platform integrations.

A connector translates between Pinpoint's normalized service-request payload
and a vendor's API. Connectors are stateless: they are constructed per
operation from an IntegrationConfig row (config dict + decrypted credentials).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Default network timeout for all vendor API calls
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class ConnectorError(Exception):
    """Raised when a vendor API call fails in a way the caller should surface."""


@dataclass
class ExternalRecord:
    """Normalized view of a service request as it exists on an external platform."""
    external_id: str
    status: Optional[str] = None          # Normalized: open, in_progress, closed
    raw_status: Optional[str] = None      # The platform's native status string
    status_notes: Optional[str] = None
    updated_at: Optional[datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    # Populated on pulls that can import new records (not just status updates)
    description: Optional[str] = None
    service_name: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    long: Optional[float] = None


@dataclass
class ExternalComment:
    """Normalized comment on an external platform's record."""
    external_id: str                      # platform's comment id (or a stable surrogate)
    content: str
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)


# Normalized outbound payload keys (built by tasks/integrations.py):
#   service_request_id, service_code, service_name, description,
#   address, lat, long, status, requested_datetime,
#   first_name/last_name/email/phone (only when config.share_pii is true),
#   media_urls (http(s) URLs only — base64 blobs are never pushed)


class BaseConnector:
    """Abstract base for platform connectors."""

    platform: str = "base"
    # What this connector supports: subset of {"push", "push_status", "pull", "test"}
    capabilities = {"test"}

    def __init__(self, config: Dict[str, Any], credentials: Dict[str, Any]):
        self.config = config or {}
        self.credentials = credentials or {}

    # ---- Status mapping -------------------------------------------------

    #: default mapping from Pinpoint status -> platform status
    DEFAULT_STATUS_MAP_OUT: Dict[str, str] = {}
    #: default mapping from platform status -> Pinpoint status
    DEFAULT_STATUS_MAP_IN: Dict[str, str] = {}

    def map_status_out(self, status: str) -> str:
        overrides = self.config.get("status_map_out") or {}
        return overrides.get(status) or self.DEFAULT_STATUS_MAP_OUT.get(status, status)

    def map_status_in(self, raw_status: Optional[str]) -> Optional[str]:
        if raw_status is None:
            return None
        key = str(raw_status).strip().lower()
        overrides = {str(k).lower(): v for k, v in (self.config.get("status_map_in") or {}).items()}
        if key in overrides:
            return overrides[key]
        return self.DEFAULT_STATUS_MAP_IN.get(key, "open" if key not in ("closed", "resolved", "archived", "complete", "completed") else "closed")

    # ---- Operations (override in subclasses) ----------------------------

    async def test_connection(self) -> Dict[str, Any]:
        """Verify credentials/reachability. Returns {'ok': bool, 'detail': str}."""
        raise ConnectorError(f"{self.platform} connector does not implement test_connection")

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        """Create the request on the external platform; return its external record."""
        raise ConnectorError(f"{self.platform} connector does not support pushing requests")

    async def push_status(self, external_id: str, status: str, notes: Optional[str] = None) -> None:
        """Propagate a local status change to the external record."""
        raise ConnectorError(f"{self.platform} connector does not support status updates")

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        """Fetch records changed on the platform since `since`."""
        raise ConnectorError(f"{self.platform} connector does not support pulling updates")

    async def fetch_record(self, external_id: str) -> Optional[ExternalRecord]:
        """Fetch a single record by external id (used for per-request refresh)."""
        return None

    # -- Comments (capability "comments") --

    async def push_comment(self, external_id: str, author: str, content: str) -> Optional[str]:
        """Post a comment on the external record. Returns the platform's comment id if available."""
        raise ConnectorError(f"{self.platform} connector does not support comments")

    async def pull_comments(self, external_id: str) -> List[ExternalComment]:
        """Fetch comments on the external record."""
        raise ConnectorError(f"{self.platform} connector does not support comments")

    # -- Documents / attachments (capability "documents") --

    async def push_document(self, external_id: str, filename: str,
                            content: bytes, content_type: str) -> None:
        """Attach a file (photo, document) to the external record."""
        raise ConnectorError(f"{self.platform} connector does not support document upload")

    # -- Asset management (capability "assets") --

    async def pull_assets(self) -> List[Dict[str, Any]]:
        """Fetch infrastructure assets as GeoJSON Feature dicts.

        Features must have geometry (Point) and properties including at least
        an asset id/name so they can populate a Pinpoint map layer for
        asset-linked request intake."""
        raise ConnectorError(f"{self.platform} connector does not support asset sync")

    # ---- HTTP helpers ----------------------------------------------------

    def _client(self, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True, **kwargs)

    @staticmethod
    def _raise_for_status(response: httpx.Response, context: str) -> None:
        if response.status_code >= 400:
            body = response.text[:500]
            raise ConnectorError(f"{context} failed: HTTP {response.status_code} — {body}")

"""Platform catalog and connector factory.

PLATFORM_CATALOG drives both the admin API (what platforms exist, what fields
each needs) and the admin UI (cards with per-vendor setup guidance), so adding
a new platform is: write a connector, add a catalog entry.
"""

from typing import Any, Dict

from app.integrations.base import BaseConnector
from app.integrations.connectors.accela import AccelaConnector
from app.integrations.connectors.open311 import Open311Connector
from app.integrations.connectors.seeclickfix import SeeClickFixConnector
from app.integrations.connectors.vendors import (
    EdmundsConnector,
    FastTrackGovConnector,
    GovPilotConnector,
    PolimorphicConnector,
    SDLConnector,
    TylerConnector,
)

# integration_mode:
#   public_api  — vendor publishes an open, documented API; works out of the box with credentials
#   open311     — standard Open311 GeoReport v2 endpoint (base URL from the jurisdiction)
#   partner_api — vendor issues API endpoint/credentials per customer via support/implementation
PLATFORM_CATALOG: Dict[str, Dict[str, Any]] = {
    "accela": {
        "name": "Accela",
        "vendor": "Accela, Inc.",
        "category": "Permitting, licensing & service requests",
        "integration_mode": "public_api",
        "docs_url": "https://developer.accela.com",
        "description": "Pushes requests into Accela Civic Platform as records via the Construct API v4, pulls status changes back, and mirrors Pinpoint status updates.",
        "capabilities": ["push", "push_status", "pull", "test"],
        "credential_fields": [
            {"key": "client_id", "label": "Client ID", "secret": False},
            {"key": "client_secret", "label": "Client Secret", "secret": True},
            {"key": "username", "label": "Agency Username", "secret": False},
            {"key": "password", "label": "Agency Password", "secret": True},
        ],
        "config_fields": [
            {"key": "agency_name", "label": "Agency Name", "placeholder": "YOURAGENCY", "required": True},
            {"key": "environment", "label": "Environment", "placeholder": "PROD", "required": False},
            {"key": "record_type", "label": "Record Type", "placeholder": "ServiceRequest/General/Complaint/NA", "required": True},
        ],
        "setup_notes": "Create an app at developer.accela.com to get the Client ID/Secret, then use an agency account for the OAuth2 password grant. The record type must exist in your agency configuration.",
    },
    "tyler": {
        "name": "Tyler Technologies",
        "vendor": "Tyler Technologies (Tyler 311 / MyCivic / EnerGov)",
        "category": "Citizen requests & permitting suite",
        "integration_mode": "open311",
        "docs_url": "https://www.tylertech.com/products/my-civic",
        "description": "Connects to Tyler's Open311 GeoReport v2 endpoint for your jurisdiction: pushes new requests and polls for status changes.",
        "capabilities": ["push", "pull", "test"],
        "credential_fields": [
            {"key": "api_key", "label": "Open311 API Key", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "Open311 Base URL", "placeholder": "https://yourcity.tylerapp.com/open311/v2", "required": True},
            {"key": "jurisdiction_id", "label": "Jurisdiction ID", "placeholder": "yourcity.gov", "required": False},
            {"key": "default_service_code", "label": "Default Service Code", "placeholder": "", "required": False},
        ],
        "setup_notes": "Ask your Tyler implementation team for the jurisdiction's Open311 endpoint and an API key with write access.",
    },
    "civicplus": {
        "name": "CivicPlus (SeeClickFix)",
        "vendor": "CivicPlus",
        "category": "311 CRM & citizen requests",
        "integration_mode": "public_api",
        "docs_url": "https://dev.seeclickfix.com",
        "description": "Two-way sync with CivicPlus SeeClickFix via the public SeeClickFix API v2 — creates issues and polls your place for status changes.",
        "capabilities": ["push", "pull", "test"],
        "credential_fields": [
            {"key": "username", "label": "SeeClickFix Username", "secret": False},
            {"key": "password", "label": "SeeClickFix Password", "secret": True},
            {"key": "api_key", "label": "API Token (optional, instead of user/pass)", "secret": True},
        ],
        "config_fields": [
            {"key": "place_url", "label": "Place Slug", "placeholder": "your-town", "required": False},
            {"key": "request_type", "label": "Request Type ID", "placeholder": "1234", "required": False},
        ],
        "setup_notes": "Any SeeClickFix account works for read access; issue creation needs an account (or CivicPlus-issued token) with reporting rights in your place.",
    },
    "sdl": {
        "name": "SDL (Spatial Data Logic)",
        "vendor": "Spatial Data Logic",
        "category": "Municipal operations & code enforcement",
        "integration_mode": "partner_api",
        "docs_url": "https://www.spatialdatalogic.com",
        "description": "Pushes requests into SDL work management and pulls status changes back through SDL's customer REST API.",
        "capabilities": ["push", "push_status", "pull", "test"],
        "credential_fields": [
            {"key": "api_key", "label": "SDL API Key", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "API Base URL", "placeholder": "https://api.spatialdatalogic.com/v1/yourtown", "required": True},
        ],
        "setup_notes": "SDL issues the API endpoint and key per municipality — request 'REST API access for third-party intake' from SDL support. Endpoint paths and field names are configurable if your tenant differs from the defaults.",
    },
    "edmunds": {
        "name": "Edmunds GovTech",
        "vendor": "Edmunds GovTech (MCSJ)",
        "category": "Municipal ERP & work orders",
        "integration_mode": "partner_api",
        "docs_url": "https://edmundsgovtech.com",
        "description": "Sends requests into MCSJ work orders and reads status back via the Edmunds web-service interface enabled for your site.",
        "capabilities": ["push", "push_status", "pull", "test"],
        "credential_fields": [
            {"key": "username", "label": "Service Username", "secret": False},
            {"key": "password", "label": "Service Password", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "API Base URL", "placeholder": "https://mcsj.yourtown.gov/api", "required": True},
        ],
        "setup_notes": "Ask Edmunds support to enable the MCSJ API/web-service module for your license and provision a service account. Field mappings are configurable per tenant.",
    },
    "govpilot": {
        "name": "GovPilot",
        "vendor": "GovPilot",
        "category": "Government management & GIS",
        "integration_mode": "partner_api",
        "docs_url": "https://www.govpilot.com",
        "description": "Pushes requests into GovPilot's report-a-concern module and polls for disposition changes via your customer API key.",
        "capabilities": ["push", "push_status", "pull", "test"],
        "credential_fields": [
            {"key": "api_key", "label": "GovPilot API Key", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "API Base URL", "placeholder": "https://api.govpilot.com/v1", "required": True},
        ],
        "setup_notes": "GovPilot issues API keys through your customer success manager. Grant the key access to the modules you want Pinpoint to write to.",
    },
    "fasttrackgov": {
        "name": "FastTrackGov",
        "vendor": "Harris (MS Govern)",
        "category": "Licensing, permitting & code enforcement",
        "integration_mode": "partner_api",
        "docs_url": "https://www.fasttrackgov.com",
        "description": "Creates cases in FastTrackGov and reads status back through the customer API gateway (subscription-key auth).",
        "capabilities": ["push", "push_status", "pull", "test"],
        "credential_fields": [
            {"key": "api_key", "label": "Subscription Key", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "API Base URL", "placeholder": "https://gateway.fasttrackgov.com/yourtown", "required": True},
        ],
        "setup_notes": "Request an API subscription key from your FastTrackGov/MS Govern representative. The connector's endpoint paths are configurable to match your gateway.",
    },
    "polimorphic": {
        "name": "Polimorphic",
        "vendor": "Polimorphic",
        "category": "AI front desk & constituent CRM",
        "integration_mode": "partner_api",
        "docs_url": "https://www.polimorphic.com",
        "description": "Bidirectional webhooks: Polimorphic's AI phone/chat intake posts new requests to Pinpoint's inbound webhook, and Pinpoint pushes requests/status changes to your Polimorphic workspace endpoint.",
        "capabilities": ["push", "push_status", "pull", "test"],
        "credential_fields": [
            {"key": "api_key", "label": "Workspace API Token", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "Workspace API URL", "placeholder": "https://api.polimorphic.com/workspaces/yourtown", "required": True},
        ],
        "setup_notes": "Give Polimorphic your Pinpoint inbound webhook URL (shown after connecting) so their AI intake can create requests here, and paste their workspace endpoint + token for outbound sync.",
    },
    "open311": {
        "name": "Generic Open311",
        "vendor": "Any GeoReport v2 endpoint",
        "category": "Open standard (works with many vendors)",
        "integration_mode": "open311",
        "docs_url": "http://wiki.open311.org/GeoReport_v2",
        "description": "Connects to any Open311 GeoReport v2 compliant endpoint — a catch-all for vendors and cities not listed above.",
        "capabilities": ["push", "pull", "test"],
        "credential_fields": [
            {"key": "api_key", "label": "API Key", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "Open311 Base URL", "placeholder": "https://city.gov/open311/v2", "required": True},
            {"key": "jurisdiction_id", "label": "Jurisdiction ID", "placeholder": "", "required": False},
            {"key": "default_service_code", "label": "Default Service Code", "placeholder": "", "required": False},
        ],
        "setup_notes": "Point this at any GeoReport v2 endpoint. POSTing usually requires an api_key from the endpoint operator.",
    },
}

_CONNECTOR_CLASSES = {
    "accela": AccelaConnector,
    "tyler": TylerConnector,
    "civicplus": SeeClickFixConnector,
    "sdl": SDLConnector,
    "edmunds": EdmundsConnector,
    "govpilot": GovPilotConnector,
    "fasttrackgov": FastTrackGovConnector,
    "polimorphic": PolimorphicConnector,
    "open311": Open311Connector,
}


def build_connector(platform: str, config: Dict[str, Any], credentials: Dict[str, Any]) -> BaseConnector:
    cls = _CONNECTOR_CLASSES.get(platform)
    if not cls:
        raise ValueError(f"Unknown integration platform: {platform}")
    return cls(config, credentials)

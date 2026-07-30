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
from app.integrations.connectors.generic_rest import GenericRestConnector
from app.integrations.connectors.vendors import TylerConnector

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
        "description": "Full two-way sync with Accela Civic Platform via the Construct API v4: records, status, comments, photo attachments, and asset inventory sync into Pinpoint map layers.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "work_orders", "test"],
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
            {"key": "sync_assets", "label": "Sync Assets (true/false)", "placeholder": "false", "required": False},
            {"key": "asset_group", "label": "Asset Group Filter", "placeholder": "", "required": False},
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
        "description": "Two-way sync with CivicPlus SeeClickFix via the public SeeClickFix API v2 — creates issues, polls your place for status changes, and syncs comment threads both ways.",
        "capabilities": ["push", "pull", "comments", "test"],
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
    "generic_rest": {
        "name": "Other REST System (Generic Connector)",
        "vendor": "Any vendor REST API — you provide the details",
        "category": "Configurable connector for systems not listed above",
        "integration_mode": "generic",
        "docs_url": "https://github.com/Pinpoint-311/Pinpoint-311/blob/main/docs/INTEGRATIONS.md",
        "description": (
            "One configurable connector for any vendor that exposes a JSON REST API but isn't "
            "purpose-built above — for example Trimble Cityworks, SDL (Spatial Data Logic), "
            "Edmunds GovTech / MCSJ, GovPilot, FastTrackGov, or Polimorphic. You supply the base "
            "URL, auth style, and (if the vendor differs from the common defaults) the endpoint "
            "paths and field names from your vendor's API docs. "
            "Note: this is a generic client, not certified against any specific vendor's API — "
            "always run the connection check and a test report before relying on it in production."
        ),
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "work_orders", "test"],
        "credential_fields": [
            {"key": "api_key", "label": "API Key / Token", "secret": True},
            {"key": "username", "label": "Username (only for Basic auth)", "secret": False},
            {"key": "password", "label": "Password (only for Basic auth)", "secret": True},
        ],
        "config_fields": [
            {"key": "base_url", "label": "API Base URL", "placeholder": "https://api.yourvendor.com/v1", "required": True},
            {"key": "auth_style", "label": "Auth style — bearer, api_key_header, basic, or query", "placeholder": "bearer", "required": False},
            {"key": "auth_header", "label": "Header name (only for api_key_header, e.g. X-API-Key)", "placeholder": "X-API-Key", "required": False},
            {"key": "create_path", "label": "Create-request path", "placeholder": "/requests", "required": False},
            {"key": "get_path", "label": "Get-by-id path", "placeholder": "/requests/{id}", "required": False},
            {"key": "list_path", "label": "List / poll-updates path", "placeholder": "/requests", "required": False},
            {"key": "status_path", "label": "Status-update path", "placeholder": "/requests/{id}/status", "required": False},
            {"key": "id_field", "label": "Response field holding the record id", "placeholder": "id", "required": False},
            {"key": "status_field", "label": "Response field holding status", "placeholder": "status", "required": False},
            {"key": "updated_field", "label": "Response field holding the updated timestamp", "placeholder": "updated_at", "required": False},
        ],
        "setup_notes": (
            "Get your API base URL, key, auth style, and endpoint/field details from your vendor's "
            "API documentation or support team. Defaults follow a common REST convention (Bearer "
            "auth, /requests paths, id/status/updated_at fields); override only what your vendor "
            "differs on. For a work-order system (e.g. Cityworks), map your work-order fields "
            "(WorkOrderId, AssignedTo, Status, ScheduledDate) via id_field/status_field/field_map. "
            "This connector is not vendor-certified — verify with the connection check first."
        ),
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

# ---------------------------------------------------------------------------
# Clerk-friendly setup guidance, merged into the catalog below.
#
# plain_summary   one sentence, no jargon, about what connecting does
# what_you_need   plain checklist shown before setup starts
# vendor_ask      ready-to-send email requesting access ({{WEBHOOK_URL}} is
#                 replaced with the connection's inbound webhook address);
#                 None when no vendor request is needed
# field_help      per-field plain-language hints keyed by field key
# recommended_sync_direction   preselected in the setup wizard
# ---------------------------------------------------------------------------
CLERK_GUIDES: Dict[str, Dict[str, Any]] = {
    "accela": {
        "plain_summary": "Reports submitted here automatically become Accela records, photos included. Status changes and comments flow both ways, so staff can work in either system.",
        "what_you_need": [
            "Your Accela agency name (staff who log into Accela will know it — it's on the login screen)",
            "An Accela staff username and password the connection can use",
            "A 'Client ID' and 'Client Secret' — your Accela administrator or Accela support can create these in about 10 minutes",
            "The record type to file reports under (e.g. 'Service Request / Complaint') — ask whoever manages Accela",
        ],
        "vendor_ask": {
            "to_hint": "Your Accela administrator, or Accela support (support@accela.com)",
            "subject": "API access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe are connecting our resident request system (Pinpoint 311) to our Accela Civic Platform account so resident reports appear in Accela automatically.\n\nCould you please:\n1. Create an API app for us at developer.accela.com and send the Client ID and Client Secret\n2. Confirm our agency name and environment (PROD or TEST)\n3. Provide a staff account (username + password) the connection can use\n4. Tell us the record type resident service requests should be filed under (e.g. ServiceRequest/General/Complaint/NA)\n\nThank you!",
        },
        "field_help": {
            "client_id": "A long code your Accela administrator gives you — looks like random letters and numbers.",
            "client_secret": "The matching secret code. Treat it like a password.",
            "username": "The Accela staff account the connection will act as.",
            "password": "That account's password.",
            "agency_name": "Your agency's short name in Accela, usually ALL CAPS (e.g. SPRINGFIELD).",
            "environment": "Leave as PROD unless Accela support says otherwise.",
            "record_type": "Where reports get filed in Accela. Copy this exactly from your Accela administrator.",
            "sync_assets": "Type true to also copy your Accela asset list (hydrants, signs, lights) onto the Pinpoint map each night.",
            "asset_group": "Optional — only sync one group of assets (ask your Accela admin for the group name).",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "tyler": {
        "plain_summary": "Reports submitted here are sent into your Tyler system, and Tyler status updates show up here automatically.",
        "what_you_need": [
            "The 'Open311 web address' for your town's Tyler system",
            "An API key from Tyler that allows creating requests",
        ],
        "vendor_ask": {
            "to_hint": "Your Tyler Technologies account manager or implementation contact",
            "subject": "Open311 access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe are connecting our resident request system (Pinpoint 311) to our Tyler system so resident reports flow in automatically.\n\nCould you please send us:\n1. Our jurisdiction's Open311 (GeoReport v2) endpoint URL\n2. An API key with permission to create service requests\n3. Our jurisdiction ID, if one is required\n\nThank you!",
        },
        "field_help": {
            "api_key": "The key Tyler sends you — a long string of letters and numbers.",
            "base_url": "Paste the web address exactly as Tyler sends it. It usually ends in /open311/v2.",
            "jurisdiction_id": "Only fill this in if Tyler says you need it. Often it looks like yourtown.gov.",
            "default_service_code": "Optional — leave blank unless Tyler asks reports to use one specific category code.",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "civicplus": {
        "plain_summary": "Reports submitted here also appear in SeeClickFix, and SeeClickFix status changes and comments show up here.",
        "what_you_need": [
            "A SeeClickFix account with permission to report in your town (username + password)",
            "Optional: your town's SeeClickFix web address (the part after seeclickfix.com/, e.g. 'springfield')",
        ],
        "vendor_ask": {
            "to_hint": "Your CivicPlus / SeeClickFix account manager",
            "subject": "API access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe are connecting our resident request system (Pinpoint 311) to our SeeClickFix account.\n\nCould you please confirm:\n1. The account (or API token) we should use for creating issues via the SeeClickFix API v2\n2. Our place URL (the seeclickfix.com/... address for our town)\n3. The request type ID resident reports should use\n\nThank you!",
        },
        "field_help": {
            "username": "The email address of the SeeClickFix account to connect.",
            "password": "That account's password.",
            "api_key": "Only needed if CivicPlus gave you a token instead of a username and password.",
            "place_url": "The last part of your town's SeeClickFix page address, e.g. 'springfield' from seeclickfix.com/springfield.",
            "request_type": "A number CivicPlus can give you. Leave blank to use the default.",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "generic_rest": {
        "plain_summary": "A do-it-yourself connector for a vendor system that isn't listed above (Cityworks, SDL, Edmunds/MCSJ, GovPilot, FastTrackGov, Polimorphic, and others). You paste in the web address and key your vendor gives you, plus a few field names from their API guide if they differ from the common defaults.",
        "what_you_need": [
            "Your vendor's API base URL and an API key (or a username + password) — from their API docs or support team",
            "The auth style they use: most are 'bearer'; some use an API-key header or a basic login",
            "Optional: endpoint paths and response field names, if your vendor differs from the common REST defaults",
        ],
        "vendor_ask": {
            "to_hint": "Your vendor's API support or account team",
            "subject": "REST API access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe'd like to connect our resident request system (Pinpoint 311) to your platform via your REST API so resident reports flow in automatically and status updates flow back.\n\nCould you please send us:\n1. Our API base URL\n2. An API key/token (or service account), and the auth style you use (Bearer token, API-key header, or Basic username/password)\n3. The endpoints for creating a request, reading a request by id, listing/polling updates, and updating status — plus any field-name notes if they differ from the usual id/status/updated_at\n4. If you can send us updates by webhook instead of us polling, our inbound address is: {{WEBHOOK_URL}}\n\nThank you!",
        },
        "field_help": {
            "api_key": "The key or token your vendor issues. Treat it like a password. (Leave blank if using Basic username/password.)",
            "username": "Only needed if your vendor uses Basic authentication.",
            "password": "Only needed if your vendor uses Basic authentication.",
            "base_url": "The web address of the vendor's API, e.g. https://api.yourvendor.com/v1.",
            "auth_style": "How the key is sent. Most vendors use 'bearer'. Others use 'api_key_header' (with a header name), 'basic' (username + password), or 'query'.",
            "auth_header": "Only for api_key_header — the exact header name the vendor expects, e.g. X-API-Key or Ocp-Apim-Subscription-Key.",
            "create_path": "Where new requests are sent (POST). Leave blank for the default /requests.",
            "get_path": "Where a single request is read by id. Leave blank for /requests/{id}.",
            "list_path": "Where updated requests are polled. Leave blank for /requests.",
            "status_path": "Where status updates are sent. Leave blank for /requests/{id}/status.",
            "id_field": "The field in the vendor's response holding the record id. Default 'id'.",
            "status_field": "The field holding the record's status. Default 'status'.",
            "updated_field": "The field holding the last-updated timestamp. Default 'updated_at'.",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "open311": {
        "plain_summary": "Connects to any system that speaks the Open311 standard — a fallback for vendors not listed above.",
        "what_you_need": [
            "The system's Open311 web address",
            "An API key from whoever runs that system",
        ],
        "vendor_ask": {
            "to_hint": "Whoever operates the Open311 endpoint",
            "subject": "Open311 access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe would like to connect our resident request system (Pinpoint 311) to your Open311 (GeoReport v2) endpoint.\n\nCould you please send us:\n1. The endpoint base URL\n2. An API key with permission to create service requests\n3. The jurisdiction ID, if required\n\nThank you!",
        },
        "field_help": {
            "api_key": "The key the endpoint operator sends you.",
            "base_url": "The web address of the Open311 endpoint. It usually ends in /v2.",
            "jurisdiction_id": "Only fill this in if the operator says you need it.",
            "default_service_code": "Optional — leave blank unless told otherwise.",
        },
        "recommended_sync_direction": "bidirectional",
    },
}

for _key, _guide in CLERK_GUIDES.items():
    PLATFORM_CATALOG[_key].update(_guide)


_CONNECTOR_CLASSES = {
    "accela": AccelaConnector,
    "tyler": TylerConnector,
    "civicplus": SeeClickFixConnector,
    "generic_rest": GenericRestConnector,
    "open311": Open311Connector,
}


def build_connector(platform: str, config: Dict[str, Any], credentials: Dict[str, Any]) -> BaseConnector:
    cls = _CONNECTOR_CLASSES.get(platform)
    if not cls:
        raise ValueError(f"Unknown integration platform: {platform}")
    return cls(config, credentials)


async def build_connector_for(integration: Any) -> BaseConnector:
    """Build a connector for an IntegrationConfig row, resolving any Secret
    Manager credential references (``@secret:NAME``) to live values first.

    This is the single read path for constructing connectors from stored
    config: it keeps the raw secret out of the application database (the row
    holds only references when an external vault is configured) while giving the
    connector the real values it needs to call the vendor.
    """
    from app.integrations.credentials import resolve_credentials
    creds = await resolve_credentials(integration.credentials or {})
    return build_connector(integration.platform, integration.config or {}, creds)

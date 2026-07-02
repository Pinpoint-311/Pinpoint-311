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
    SandboxConnector,
    SDLConnector,
    TylerConnector,
)

# integration_mode:
#   public_api  — vendor publishes an open, documented API; works out of the box with credentials
#   open311     — standard Open311 GeoReport v2 endpoint (base URL from the jurisdiction)
#   partner_api — vendor issues API endpoint/credentials per customer via support/implementation
PLATFORM_CATALOG: Dict[str, Dict[str, Any]] = {
    "sandbox": {
        "name": "Practice Sandbox",
        "vendor": "Built into Pinpoint — no account needed",
        "category": "Try the whole sync flow safely",
        "integration_mode": "sandbox",
        "docs_url": "https://github.com/Pinpoint-311/Pinpoint-311/blob/main/docs/INTEGRATIONS.md",
        "description": "A pretend town system built into Pinpoint. Connect it to watch reports, photos, comments, status changes, and assets flow both ways — then disconnect when you're done.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "test"],
        "credential_fields": [],
        "config_fields": [
            {"key": "base_url", "label": "Sandbox Address", "placeholder": "auto-detected — leave blank", "required": False},
            {"key": "import_new_records", "label": "Import records that start in the sandbox (true/false)", "placeholder": "true", "required": False},
            {"key": "sync_assets", "label": "Copy practice assets to the map (true/false)", "placeholder": "true", "required": False},
        ],
        "setup_notes": "No vendor, no credentials — the sandbox is part of this Pinpoint installation. Practice data is temporary and disappears when the server restarts.",
    },
    "accela": {
        "name": "Accela",
        "vendor": "Accela, Inc.",
        "category": "Permitting, licensing & service requests",
        "integration_mode": "public_api",
        "docs_url": "https://developer.accela.com",
        "description": "Full two-way sync with Accela Civic Platform via the Construct API v4: records, status, comments, photo attachments, and asset inventory sync into Pinpoint map layers.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "test"],
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
    "sdl": {
        "name": "SDL (Spatial Data Logic)",
        "vendor": "Spatial Data Logic",
        "category": "Municipal operations & code enforcement",
        "integration_mode": "partner_api",
        "docs_url": "https://www.spatialdatalogic.com",
        "description": "Full sync with SDL work management through SDL's customer REST API: requests, status, comments, photo attachments, and asset inventory sync.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "test"],
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
        "description": "Full sync with MCSJ work orders via the Edmunds web-service interface: requests, status, comments, attachments, and asset inventory sync.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "test"],
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
        "description": "Full sync with GovPilot's report-a-concern and records modules: requests, status, comments, attachments, and GIS asset inventory sync.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "test"],
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
        "description": "Full sync with FastTrackGov cases through the customer API gateway: requests, status, comments, attachments, and asset inventory sync.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "test"],
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
        "description": "Bidirectional: Polimorphic's AI phone/chat intake posts new requests and comments to Pinpoint's inbound webhook, while Pinpoint pushes requests, status changes, and comment threads to your workspace endpoint.",
        "capabilities": ["push", "push_status", "pull", "comments", "documents", "assets", "test"],
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
    "sandbox": {
        "plain_summary": "A safe, pretend town system for practice. Reports you submit flow into it, a pretend work crew updates them after a minute or two, and those updates flow back — exactly how a real connection behaves.",
        "what_you_need": [
            "Nothing! The sandbox is built into Pinpoint. Just click through — there are no codes or passwords.",
            "Tip: after connecting, submit a test report from the resident portal, wait ~2 minutes, then press 'Check for updates' and watch the status change on its own.",
        ],
        "vendor_ask": None,
        "field_help": {
            "base_url": "Leave this blank — Pinpoint finds its own sandbox automatically.",
            "import_new_records": "Type true to watch a record that started in the sandbox appear here as a new request.",
            "sync_assets": "Type true to put five practice hydrants and streetlights on your map.",
        },
        "recommended_sync_direction": "bidirectional",
    },
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
    "sdl": {
        "plain_summary": "Reports submitted here become SDL work items with photos attached, and SDL status changes and comments show up here.",
        "what_you_need": [
            "A web address (URL) and API key from SDL — one email to SDL support gets both",
        ],
        "vendor_ask": {
            "to_hint": "SDL support, or your SDL account manager",
            "subject": "API access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe use SDL and are connecting our resident request system (Pinpoint 311) so resident reports flow into SDL automatically and status updates flow back.\n\nCould you please enable REST API access for third-party intake on our account and send us:\n1. Our API base URL\n2. An API key\n3. Any notes on the endpoints for creating requests, updating status, comments, and attachments\n\nIf you can receive updates from us by webhook instead, our address is: {{WEBHOOK_URL}}\n\nThank you!",
        },
        "field_help": {
            "api_key": "The key SDL support sends you — a long string of letters and numbers.",
            "base_url": "Paste the web address exactly as SDL sends it, e.g. https://api.spatialdatalogic.com/v1/yourtown.",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "edmunds": {
        "plain_summary": "Reports submitted here become MCSJ work orders, and work order status changes show up here.",
        "what_you_need": [
            "A service username and password from Edmunds, plus your MCSJ web address — one email to Edmunds support gets all three",
        ],
        "vendor_ask": {
            "to_hint": "Edmunds GovTech support, or your Edmunds account manager",
            "subject": "MCSJ API access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe use MCSJ and are connecting our resident request system (Pinpoint 311) so resident reports create work orders automatically and status updates flow back.\n\nCould you please:\n1. Enable the MCSJ API / web-service module for our license\n2. Create a service account (username + password) for the connection\n3. Send us our API base URL and any notes on the work order endpoints\n\nThank you!",
        },
        "field_help": {
            "username": "The service account name Edmunds creates for this connection.",
            "password": "That account's password.",
            "base_url": "Paste the web address exactly as Edmunds sends it, e.g. https://mcsj.yourtown.gov/api.",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "govpilot": {
        "plain_summary": "Reports submitted here appear in GovPilot, and GovPilot status changes show up here. GovPilot GIS assets can appear on the Pinpoint map.",
        "what_you_need": [
            "An API key and web address from GovPilot — one email to your GovPilot customer success manager gets both",
        ],
        "vendor_ask": {
            "to_hint": "Your GovPilot customer success manager",
            "subject": "API access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe use GovPilot and are connecting our resident request system (Pinpoint 311) so resident reports flow into GovPilot automatically and status updates flow back.\n\nCould you please send us:\n1. An API key with access to the report-a-concern / records modules\n2. Our API base URL\n3. Any notes on the endpoints for creating requests, status, comments, and attachments\n\nIf you can receive updates from us by webhook instead, our address is: {{WEBHOOK_URL}}\n\nThank you!",
        },
        "field_help": {
            "api_key": "The key GovPilot sends you — a long string of letters and numbers.",
            "base_url": "Paste the web address exactly as GovPilot sends it, e.g. https://api.govpilot.com/v1.",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "fasttrackgov": {
        "plain_summary": "Reports submitted here become FastTrackGov cases, and case status changes show up here.",
        "what_you_need": [
            "A subscription key and gateway address from your FastTrackGov / MS Govern representative",
        ],
        "vendor_ask": {
            "to_hint": "Your FastTrackGov / MS Govern representative",
            "subject": "API access for our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe use FastTrackGov and are connecting our resident request system (Pinpoint 311) so resident reports create cases automatically and status updates flow back.\n\nCould you please send us:\n1. An API subscription key\n2. Our API gateway base URL\n3. Any notes on the endpoints for creating cases, status, comments, and attachments\n\nThank you!",
        },
        "field_help": {
            "api_key": "The subscription key your representative sends — a long string of letters and numbers.",
            "base_url": "Paste the web address exactly as your representative sends it.",
        },
        "recommended_sync_direction": "bidirectional",
    },
    "polimorphic": {
        "plain_summary": "Requests taken by Polimorphic's AI phone/chat assistant appear here automatically, and updates made here flow back to Polimorphic.",
        "what_you_need": [
            "A workspace API token and address from Polimorphic",
            "You'll send Polimorphic a special web address from this page (shown after you connect) so their assistant can file requests here",
        ],
        "vendor_ask": {
            "to_hint": "Your Polimorphic customer success contact",
            "subject": "Connecting Polimorphic to our 311 system (Pinpoint 311)",
            "body": "Hello,\n\nWe want requests taken by our Polimorphic assistant to appear in our resident request system (Pinpoint 311) automatically, and updates to flow back.\n\n1. Please point your outbound webhook for new requests and updates at: {{WEBHOOK_URL}}\n2. Please send us our workspace API URL and an API token so we can push our requests and status changes to Polimorphic\n\nThank you!",
        },
        "field_help": {
            "api_key": "The token Polimorphic sends you — a long string of letters and numbers.",
            "base_url": "Paste the workspace address exactly as Polimorphic sends it.",
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
    "sandbox": SandboxConnector,
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

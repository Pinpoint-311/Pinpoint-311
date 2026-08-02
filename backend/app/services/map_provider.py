"""Which map provider a town renders with, and what that provider needs.

Rendering and geocoding are chosen separately on purpose. A town can draw its
map from its county's own ArcGIS basemap while geocoding against Google, or
render MapLibre and geocode against a county address locator. Forcing them to
move together would make the Esri option nearly pointless, since most of its
value is pointing at data the county already publishes.

Google stays the default. Not because the others are worse, but because it is
the least work for a clerk -- one API key, ten minutes, no account to enrol, no
D-U-N-S number, and imagery residents already recognise from their phones. Every
other provider exists so no town is trapped, not because we expect them to be
chosen.

Credentials resolve through the Secret Manager of record like everything else;
this module only decides which ones are needed and reports whether they are
present. It never returns a secret it was not asked for -- a MapLibre town has
no business receiving a Google key just because one happens to be configured.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "google"

# The Secret Manager key holding the town's choice, matching how every other
# capability records its provider.
MAP_PROVIDER_KEY = "MAP_PROVIDER"
GEOCODE_PROVIDER_KEY = "GEOCODE_PROVIDER"

# Same shape as AI_CATALOG / TRANSLATION_CATALOG / IDENTITY_CATALOG so maps can
# be a fourth capability in the existing Service Providers UI rather than a
# separate picker bolted on beside it. `credential_fields` is what the shared
# save endpoint validates against -- a field not declared here cannot be written
# through it, which is what stops that endpoint becoming an arbitrary secret
# writer.
MAP_CATALOG: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google Maps",
        "description": (
            "The default. One API key, about ten minutes to set up, and the "
            "imagery residents already recognise from their phones."
        ),
        "boundary": "Commercial (Google Cloud)",
        "credential_fields": [
            {"key": "GOOGLE_MAPS_API_KEY", "label": "Maps API key", "secret": True, "required": True},
            {"key": "GOOGLE_MAPS_MAP_ID", "label": "Map ID (optional)", "secret": False, "required": False},
        ],
        "field_help": {
            "GOOGLE_MAPS_API_KEY": (
                "Google Cloud Console -> APIs & Services -> Credentials -> Create "
                "credentials -> API key. Enable 'Maps JavaScript API', 'Geocoding "
                "API' and 'Places API (New)' -- the last one is a separate product "
                "from the older 'Places API', and the address box needs the new "
                "one. Restrict the key to your site's domain before saving it "
                "anywhere."
            ),
            "GOOGLE_MAPS_MAP_ID": (
                "Optional. Google Cloud Console -> Google Maps Platform -> Map "
                "Management -> Create Map ID (type: JavaScript, Vector). Enables "
                "tilt and rotation. Leave blank for a standard raster map."
            ),
        },
    },
    "esri": {
        "name": "Esri / ArcGIS",
        "description": (
            "What most New Jersey counties and NJDOT already run. Lets a town use "
            "its own authoritative basemap and its county's address locator."
        ),
        "boundary": "Commercial (ArcGIS Online) or your own ArcGIS Enterprise",
        "credential_fields": [
            {"key": "ARCGIS_API_KEY", "label": "ArcGIS API key", "secret": True, "required": True},
            {"key": "ARCGIS_BASEMAP_ID", "label": "Basemap ID (optional)", "secret": False, "required": False},
            {"key": "ARCGIS_LOCATOR_URL", "label": "Address locator URL (optional)", "secret": False, "required": False},
        ],
        "field_help": {
            "ARCGIS_API_KEY": (
                "ArcGIS Developers -> Dashboard -> API keys -> New API key. Scope "
                "it to 'Basemaps' and 'Geocoding'. If your organisation has an "
                "ArcGIS Online account, your GIS staff can issue this."
            ),
            "ARCGIS_BASEMAP_ID": (
                "Optional. Use your county's published basemap instead of Esri's "
                "default -- ask your county GIS office for the item ID."
            ),
            "ARCGIS_LOCATOR_URL": (
                "Optional but worth asking for. A county address locator geocodes "
                "against the same address points dispatch uses, which is more "
                "accurate locally than any world geocoding service."
            ),
        },
    },
    "azure": {
        "name": "Azure Maps",
        "description": "Fits a town already standardised on Azure for its other services.",
        "boundary": "Commercial (Microsoft Azure)",
        "credential_fields": [
            {"key": "AZURE_MAPS_KEY", "label": "Subscription key", "secret": True, "required": True},
        ],
        "field_help": {
            "AZURE_MAPS_KEY": (
                "Azure Portal -> Create a resource -> Azure Maps -> Create. Once "
                "deployed, open the resource -> Authentication -> Primary Key."
            ),
        },
    },
    "apple": {
        "name": "Apple Maps",
        "description": (
            "A very large free allowance, but enrolment is heavier: an Apple "
            "Developer Program membership, which government entities can have "
            "the fee waived for."
        ),
        "boundary": "Commercial (Apple Developer Program)",
        "credential_fields": [
            {"key": "APPLE_MAPKIT_TEAM_ID", "label": "Team ID", "secret": False, "required": True},
            {"key": "APPLE_MAPKIT_KEY_ID", "label": "Key ID", "secret": False, "required": True},
            {"key": "APPLE_MAPKIT_PRIVATE_KEY", "label": "MapKit private key (.p8)", "secret": True, "required": True},
        ],
        "field_help": {
            "APPLE_MAPKIT_TEAM_ID": (
                "developer.apple.com -> Account -> Membership details -> Team ID. "
                "Ten characters."
            ),
            "APPLE_MAPKIT_KEY_ID": (
                "developer.apple.com -> Certificates, Identifiers & Profiles -> "
                "Keys -> create a key with 'MapKit JS' enabled. The Key ID is "
                "shown after creation."
            ),
            "APPLE_MAPKIT_PRIVATE_KEY": (
                "The .p8 file downloaded when you created that key -- paste its "
                "whole contents including the BEGIN and END lines. Apple lets you "
                "download it once. Pinpoint signs a short-lived token with it on "
                "the server; the key itself never reaches a browser."
            ),
        },
    },
}

# Providers that cannot geocode at all, so a separate geocoder is required.
# Every provider currently offered can, but the fallback it drives -- Pinpoint's
# own backend geocoder -- is what a render-only provider would need, and
# dropping the distinction would hide that requirement.
GEOCODING_CAPABLE = {"google", "esri", "apple", "azure"}


# Secret keys are vendor-shaped (GOOGLE_MAPS_API_KEY); the browser wants a
# neutral name it can pass to any adapter.
_FIELD_ALIASES = {
    "GOOGLE_MAPS_API_KEY": "apiKey",
    "GOOGLE_MAPS_MAP_ID": "styleId",
    "ARCGIS_API_KEY": "apiKey",
    "ARCGIS_BASEMAP_ID": "styleId",
    "ARCGIS_LOCATOR_URL": "locatorUrl",
    "AZURE_MAPS_KEY": "apiKey",
    "APPLE_MAPKIT_TEAM_ID": "teamId",
    "APPLE_MAPKIT_KEY_ID": "keyId",
}


def _client_field(secret_key: str) -> str:
    return _FIELD_ALIASES.get(secret_key, secret_key.lower())


def catalog_for_api() -> List[Dict[str, Any]]:
    """Provider list in the shape the shared Service Providers UI expects."""
    return [
        {
            "provider": provider_id,
            "name": spec["name"],
            "description": spec["description"],
            "boundary": spec["boundary"],
            "credential_fields": spec["credential_fields"],
            "field_help": spec.get("field_help", {}),
        }
        for provider_id, spec in MAP_CATALOG.items()
    ]


def normalize_provider(value: Optional[str]) -> str:
    """An unknown or missing provider is Google.

    Falling back rather than erroring matters: a settings row written by a newer
    version, or a typo, must not leave a town with no map at all.
    """
    candidate = (value or "").strip().lower()
    return candidate if candidate in MAP_CATALOG else DEFAULT_PROVIDER


def geocoder_for(render_provider: str, configured: Optional[str]) -> str:
    """Which provider answers address lookups.

    Defaults to the renderer when it can geocode. MapLibre cannot, so a town
    that picked it gets Pinpoint's own backend geocoder unless they chose
    otherwise -- never a silent no-op that leaves address search dead.
    """
    explicit = (configured or "").strip().lower()
    if explicit in MAP_CATALOG or explicit == "backend":
        return explicit
    return render_provider if render_provider in GEOCODING_CAPABLE else "backend"


async def resolve_credentials(provider: str, get_secret) -> Dict[str, Optional[str]]:
    """Fetch only the secrets this provider actually uses.

    `get_secret` is injected so this stays testable and so the caller controls
    which secret backend is in play. A missing secret is None, not an
    exception -- the caller reports "not configured" rather than failing.
    """
    spec = MAP_CATALOG.get(provider) or MAP_CATALOG[DEFAULT_PROVIDER]
    resolved: Dict[str, Optional[str]] = {}
    for field in spec["credential_fields"]:
        # The private key is deliberately never resolved here: Apple's token is
        # signed server-side and only the signed token is sent to a browser.
        if field.get("secret") and field["key"].endswith("PRIVATE_KEY"):
            continue
        try:
            resolved[_client_field(field["key"])] = await get_secret(field["key"])
        except Exception as exc:
            logger.warning("could not read %s for provider %s: %s", field["key"], provider, exc)
            resolved[_client_field(field["key"])] = None
    return resolved


def missing_requirements(provider: str, credentials: Dict[str, Optional[str]]) -> List[str]:
    """Required credentials this provider is missing."""
    spec = MAP_CATALOG.get(provider) or MAP_CATALOG[DEFAULT_PROVIDER]
    missing = []
    for field in spec["credential_fields"]:
        if not field.get("required"):
            continue
        if field["key"].endswith("PRIVATE_KEY"):
            continue  # server-side only; presence is reported by the token mint
        if not credentials.get(_client_field(field["key"])):
            missing.append(_client_field(field["key"]))
    return missing


def catalog() -> List[Dict[str, Any]]:
    """Compact provider list for the map-config endpoint, recommended first."""
    entries = [
        {
            "id": provider_id,
            "label": spec["name"],
            "recommended": provider_id == DEFAULT_PROVIDER,
            "requires": [
                _client_field(f["key"]) for f in spec["credential_fields"] if f.get("required")
            ],
            "can_geocode": provider_id in GEOCODING_CAPABLE,
            "setup": spec["description"],
        }
        for provider_id, spec in MAP_CATALOG.items()
    ]
    return sorted(entries, key=lambda e: (not e["recommended"], e["label"]))

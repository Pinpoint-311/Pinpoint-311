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

# What each provider needs before it can render. `secrets` are Secret Manager
# keys; `required` means the provider cannot work without them.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "google": {
        "label": "Google Maps",
        "recommended": True,
        "secrets": {"apiKey": "GOOGLE_MAPS_API_KEY", "styleId": "GOOGLE_MAPS_MAP_ID"},
        "required": ["apiKey"],
        "setup": "Create an API key in Google Cloud Console and restrict it to your domain.",
    },
    "maplibre": {
        "label": "MapLibre (open source)",
        "recommended": False,
        # Nothing required: MapLibre needs no account at all. A town may point
        # at its own tile server, otherwise a free public one is used.
        "secrets": {"styleId": "MAPLIBRE_STYLE_URL"},
        "required": [],
        "setup": "No account needed. Optionally supply your own tile style URL.",
    },
    "esri": {
        "label": "Esri / ArcGIS",
        "recommended": False,
        "secrets": {"apiKey": "ARCGIS_API_KEY", "styleId": "ARCGIS_BASEMAP_ID"},
        "required": ["apiKey"],
        "setup": (
            "Use your ArcGIS Online organisation's API key. If your county "
            "publishes its own basemap or address locator, point at those."
        ),
    },
    "apple": {
        "label": "Apple Maps",
        "recommended": False,
        # MapKit JS authenticates with a short-lived JWT the server signs, not a
        # static key. The private key never reaches the browser.
        "secrets": {"token": "APPLE_MAPKIT_TOKEN"},
        "required": ["token"],
        "setup": (
            "Requires an Apple Developer Program membership. Government "
            "entities and nonprofits can have the fee waived."
        ),
    },
    "azure": {
        "label": "Azure Maps",
        "recommended": False,
        "secrets": {"apiKey": "AZURE_MAPS_KEY"},
        "required": ["apiKey"],
        "setup": "Create an Azure Maps account and use its subscription key.",
    },
}

# Providers that cannot geocode at all, so a separate geocoder is required.
GEOCODING_CAPABLE = {"google", "esri", "apple", "azure"}


def normalize_provider(value: Optional[str]) -> str:
    """An unknown or missing provider is Google.

    Falling back rather than erroring matters: a settings row written by a newer
    version, or a typo, must not leave a town with no map at all.
    """
    candidate = (value or "").strip().lower()
    return candidate if candidate in PROVIDERS else DEFAULT_PROVIDER


def geocoder_for(render_provider: str, configured: Optional[str]) -> str:
    """Which provider answers address lookups.

    Defaults to the renderer when it can geocode. MapLibre cannot, so a town
    that picked it gets Pinpoint's own backend geocoder unless they chose
    otherwise -- never a silent no-op that leaves address search dead.
    """
    explicit = (configured or "").strip().lower()
    if explicit in PROVIDERS or explicit == "backend":
        return explicit
    return render_provider if render_provider in GEOCODING_CAPABLE else "backend"


async def resolve_credentials(provider: str, get_secret) -> Dict[str, Optional[str]]:
    """Fetch only the secrets this provider actually uses.

    `get_secret` is injected so this stays testable and so the caller controls
    which secret backend is in play. A missing secret is None, not an
    exception -- the caller reports "not configured" rather than failing.
    """
    spec = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    resolved: Dict[str, Optional[str]] = {}
    for field, secret_name in (spec.get("secrets") or {}).items():
        try:
            resolved[field] = await get_secret(secret_name)
        except Exception as exc:
            logger.warning("could not read %s for provider %s: %s", secret_name, provider, exc)
            resolved[field] = None
    return resolved


def missing_requirements(provider: str, credentials: Dict[str, Optional[str]]) -> List[str]:
    """Required credentials this provider is missing."""
    spec = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    return [field for field in spec.get("required", []) if not credentials.get(field)]


def catalog() -> List[Dict[str, Any]]:
    """Provider list for the admin console, recommended first."""
    entries = [
        {
            "id": provider_id,
            "label": spec["label"],
            "recommended": spec["recommended"],
            "requires": spec["required"],
            "can_geocode": provider_id in GEOCODING_CAPABLE,
            "setup": spec["setup"],
        }
        for provider_id, spec in PROVIDERS.items()
    ]
    return sorted(entries, key=lambda e: (not e["recommended"], e["label"]))

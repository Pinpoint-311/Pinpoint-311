"""Official CDC/ATSDR Social Vulnerability Index lookup.

The research portal previously shipped a home-grown "SVI" computed from a few
ACS variables. That is not the CDC index: the real SVI ranks every US census
tract against every other, across 16 variables in 4 themes. This module fetches
the genuine published value so exports can carry the real thing.

Source
------
CDC/ATSDR publishes SVI as an ArcGIS FeatureServer on CDC OneMap (public, no key):
    https://onemap.cdc.gov/onemapservices/rest/services/SVI/
        CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer

Key fields (per the CDC SVI data dictionary):
    FIPS         census tract FIPS, text (leading zeros preserved)
    RPL_THEMES   overall percentile ranking, 0-1, higher = more vulnerable
    RPL_THEME1   Socioeconomic Status
    RPL_THEME2   Household Characteristics
    RPL_THEME3   Racial & Ethnic Minority Status
    RPL_THEME4   Housing Type & Transportation
    -999         missing / not calculable (must NOT be treated as a real value)

Design notes
------------
* The tract layer id is discovered at runtime rather than hardcoded, so a CDC
  renumbering degrades to "unavailable" instead of silently querying the wrong
  geography (county-level values would look plausible and be wrong).
* We request all fields and read what is present, so a field rename shows up as
  a missing sub-score rather than silently nulling everything.
* Failures return None and are NOT negatively cached, so one timeout can't
  permanently blank the column.
* Callers must record which source produced a value (`svi_source`) — an official
  CDC percentile and a local approximation must never be conflated.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_SVI_SERVICE = (
    "https://onemap.cdc.gov/onemapservices/rest/services/SVI/"
    "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer"
)

# CDC's sentinel for "unavailable / not calculable".
MISSING = -999

THEME_FIELDS = {
    "RPL_THEME1": "socioeconomic_status",
    "RPL_THEME2": "household_characteristics",
    "RPL_THEME3": "racial_ethnic_minority_status",
    "RPL_THEME4": "housing_type_transportation",
}

_tract_layer_id: Optional[int] = None
_layer_lookup_failed = False
_svi_cache: Dict[str, Optional[dict]] = {}


def _service_url() -> str:
    """Service URL, overridable so a deployment can pin a vintage or mirror."""
    try:
        from app.core.config import get_settings
        return getattr(get_settings(), "cdc_svi_service_url", None) or DEFAULT_SVI_SERVICE
    except Exception:
        return DEFAULT_SVI_SERVICE


def clean_value(raw: Any) -> Optional[float]:
    """Convert a CDC field value to a float, mapping the -999 sentinel to None.

    Treating -999 as a real percentile would place every unmeasurable tract at
    the extreme low end and quietly skew any regression built on this column.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= MISSING:
        return None
    # Percentile rankings are 0-1; anything outside that isn't a ranking.
    if not (0.0 <= value <= 1.0):
        return None
    return round(value, 4)


def parse_svi_attributes(attributes: dict) -> Optional[dict]:
    """Turn a CDC feature's attributes into our SVI record, or None if unusable.

    Pure — unit-tested against fixture payloads so the -999 handling and field
    mapping can't regress without a test failing.
    """
    if not attributes:
        return None
    overall = clean_value(attributes.get("RPL_THEMES"))
    if overall is None:
        return None
    themes = {}
    for field, name in THEME_FIELDS.items():
        value = clean_value(attributes.get(field))
        if value is not None:
            themes[name] = value
    return {"overall": overall, "themes": themes}


def _is_tract_layer(layer: dict) -> bool:
    name = (layer.get("name") or "").lower()
    return "tract" in name and "county" not in name


async def _discover_tract_layer(client, base: str) -> Optional[int]:
    """Find the tract-level layer id from the service metadata."""
    global _tract_layer_id, _layer_lookup_failed
    if _tract_layer_id is not None:
        return _tract_layer_id
    if _layer_lookup_failed:
        return None
    try:
        resp = await client.get(f"{base}?f=json", timeout=6)
        if resp.status_code != 200:
            return None
        layers = (resp.json() or {}).get("layers") or []
        for layer in layers:
            if _is_tract_layer(layer):
                _tract_layer_id = layer.get("id")
                logger.info(f"[CDC SVI] using tract layer {_tract_layer_id} ({layer.get('name')})")
                return _tract_layer_id
        # Reachable but no tract layer — the service shape changed. Don't guess.
        logger.warning("[CDC SVI] no tract layer found in service metadata")
        _layer_lookup_failed = True
    except Exception as e:
        logger.warning(f"[CDC SVI] layer discovery failed: {e}")
    return None


async def get_cdc_svi(census_geoid: str) -> Optional[dict]:
    """Fetch the official CDC SVI for a tract GEOID.

    Returns {"overall": float, "themes": {...}} or None when unavailable.
    None means "we don't know" — callers must not substitute a number.
    """
    if not census_geoid:
        return None
    if census_geoid in _svi_cache:
        return _svi_cache[census_geoid]

    base = _service_url()
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            layer_id = await _discover_tract_layer(client, base)
            if layer_id is None:
                return None
            resp = await client.get(
                f"{base}/{layer_id}/query",
                params={
                    # FIPS is text in the CDC schema, so quote the literal.
                    "where": f"FIPS='{census_geoid}'",
                    "outFields": "*",
                    "returnGeometry": "false",
                    "f": "json",
                },
                timeout=8,
            )
        if resp.status_code != 200:
            return None
        features = (resp.json() or {}).get("features") or []
        if not features:
            # A clean response with no match is a real answer for this tract.
            _svi_cache[census_geoid] = None
            return None
        record = parse_svi_attributes(features[0].get("attributes") or {})
        if record is not None:
            _svi_cache[census_geoid] = record
        return record
    except Exception as e:
        # Transient: do not cache, so a blip can't permanently blank the column.
        logger.warning(f"[CDC SVI] lookup failed for {census_geoid}: {e}")
        return None

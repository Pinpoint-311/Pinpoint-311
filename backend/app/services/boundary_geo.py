"""Where a town is, worked out from its boundary.

Separate from `road_data` because that module needs SQLAlchemy and Celery to
import and none of this does, which is what lets it be tested in CI.

The state matters more than it looks. It picks which road centreline file a town
gets, and a state's own NG911 layer is materially better than the national
fallback: it knows the street names, the address ranges and the subdivisions
built last year. Matching a resident's report to a street is the whole job, so
resolving to the wrong state is not a cosmetic error.

It used to be read out of the boundary's *name*. That works for a boundary found
through the built-in search, because those names come from OpenStreetMap and
read "Montclair, Essex County, New Jersey, United States". It does not work for
a file a town uploads, which is called `montclair.geojson` and whose properties
are a FIPS code -- so every uploaded boundary quietly fell back to the national
layer and nothing said so.

The coordinates are the part that is actually true, so they are asked first --
but not with a bounding-box table. I tried that: it was wrong for eleven of
twenty-six real towns, Montclair among them. State bounding boxes overlap so
heavily that any box test picks a neighbour for exactly the border towns where
being wrong matters most, and a plausible wrong answer is worse here than none.
So the lookup is a real point-in-polygon query against the Census TIGERweb state
layer -- the same public service the road centrelines already come from, so it
adds no new dependency and nothing to configure.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Census TIGERweb, state polygons. Public, unauthenticated, same host as the
# road data itself.
STATE_LAYER_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/State_County/MapServer/0/query"
)
LOOKUP_TIMEOUT = 15.0


def extract_boundary_geometry(boundary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(boundary, dict):
        return None
    btype = boundary.get("type")
    if btype in ("Polygon", "MultiPolygon", "GeometryCollection"):
        return boundary
    if btype == "Feature":
        return boundary.get("geometry")
    if btype == "FeatureCollection" and boundary.get("features"):
        features = boundary["features"]
        if len(features) == 1:
            return features[0].get("geometry")
        return {
            "type": "GeometryCollection",
            "geometries": [f.get("geometry") for f in features if f.get("geometry")],
        }
    return None


def boundary_bbox(geojson: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """(minx, miny, maxx, maxy) of a boundary, for the fetch envelope."""
    coordinates: List[List[float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) == 2 and all(isinstance(v, (int, float)) for v in node):
                coordinates.append([float(node[0]), float(node[1])])
            else:
                for child in node:
                    walk(child)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(geojson)
    if not coordinates:
        return None
    xs = [c[0] for c in coordinates]
    ys = [c[1] for c in coordinates]
    return min(xs), min(ys), max(xs), max(ys)


def boundary_centre(boundary: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    """(lon, lat) at the middle of a boundary, for the state lookup.

    The centre of the bounding box rather than a true centroid. For a municipal
    boundary the two are close enough that no state disagrees, and a real
    centroid needs a polygon library this module deliberately does not have.
    """
    if isinstance(boundary, dict) and isinstance(boundary.get("center"), dict):
        centre = boundary["center"]
        lat, lng = centre.get("lat"), centre.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lng), float(lat)
    bbox = boundary_bbox(boundary) if boundary else None
    if not bbox:
        return None
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


async def state_from_coordinates(lon: float, lat: float, *, client=None) -> Optional[str]:
    """The state containing a point, from the Census state layer. Never raises.

    None means "could not tell" -- the service was unreachable, or the point is
    outside the United States. The caller falls back rather than guessing.
    """
    import httpx

    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "STUSAB",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT) as own:
                response = await own.get(STATE_LAYER_URL, params=params)
        else:
            response = await client.get(STATE_LAYER_URL, params=params)
        payload = response.json()
    except Exception as exc:
        logger.info("state lookup failed for %s,%s: %s", lon, lat, exc)
        return None

    features = payload.get("features") or []
    if not features:
        return None
    code = (features[0].get("attributes") or {}).get("STUSAB")
    if isinstance(code, str) and len(code.strip()) == 2:
        return code.strip().upper()
    return None


def state_from_name(boundary: Optional[Dict[str, Any]]) -> Optional[str]:
    """A state named in the boundary's own properties, if there is one."""
    display = ""
    if isinstance(boundary, dict):
        if boundary.get("features"):
            props = boundary["features"][0].get("properties") or {}
            display = props.get("display_name") or props.get("name") or ""
        display = display or boundary.get("display_name") or boundary.get("name") or ""
    upper = display.upper()
    for name, code in STATE_NAME_MAP.items():
        if name in upper:
            return code
    return None


async def resolve_state(
    boundary: Optional[Dict[str, Any]],
    settings_state: Optional[str] = None,
    *,
    lookup: Optional[Callable[[float, float], Awaitable[Optional[str]]]] = None,
) -> Optional[str]:
    """The two-letter state for a boundary, coordinates first.

    The order is deliberate:

      1. the coordinates, against real state polygons. The only step that is a
         fact rather than an inference, and the one that makes an uploaded file
         work as well as a search result.
      2. a state named in the boundary's properties, for when the lookup cannot
         be reached -- an air-gapped deployment, or the Census service down.
      3. a two-letter code saved in settings, last.

    Returns None rather than a guess. The caller's fallback is a national layer
    that covers every state, so "could not tell" costs a town the better local
    data; a confident wrong answer would hand it a neighbouring state's streets,
    which is worse and far harder to notice.
    """
    centre = boundary_centre(boundary)
    if centre:
        probe = lookup or state_from_coordinates
        try:
            found = await probe(centre[0], centre[1])
        except Exception as exc:  # a caller-supplied probe may raise
            logger.info("state lookup raised: %s", exc)
            found = None
        if found:
            return found

    named = state_from_name(boundary)
    if named:
        return named

    saved = (settings_state or "").strip()
    return saved.upper() if len(saved) == 2 else None


STATE_NAME_MAP = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
}

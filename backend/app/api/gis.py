from app.tasks.road_data import seed_roads_for_boundary
import asyncio
"""
GIS and Geocoding API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import json
import httpx

from app.db.session import get_db
from app.models import User, SystemSettings
from app.core.auth import get_current_admin
from app.services.geocoding import (
    get_geocoding_service, get_boundary_service
)

router = APIRouter()

# Where a map opens when the town has not drawn its boundary yet.
#
# The geographic centre of the contiguous states, at a zoom that shows all of
# them. Deliberately not a town, a state or a region: the previous default was
# central New Jersey labelled "a central location", which silently made every
# other deployment's map wrong in a way that looked deliberate. A country-wide
# view is obviously provisional, so nobody mistakes it for the town.
CONTINENTAL_US_CENTER = (39.8283, -98.5795)
CONTINENTAL_US_ZOOM = 4


async def get_google_api_key(db: AsyncSession) -> Optional[str]:
    """Get Google Maps API key from Secret Manager (decrypted).

    This is the SERVER-SIDE key. It bills the town's account for geocoding
    (services/geocode_dispatch) and translation (services/translation) and must
    never reach a browser -- see BROWSER_KEY_FOR below for the key /config is
    allowed to publish instead.
    """
    try:
        from app.services.secret_manager import get_secret
        return await get_secret("GOOGLE_MAPS_API_KEY")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not get Google Maps API Key: {e}")
        return None


# ---------------------------------------------------------------------------
# Browser-delivered credentials
# ---------------------------------------------------------------------------
#
# /config has no authentication and cannot have any: a resident's map has to be
# configured before the resident has done anything. It was answering the public
# internet with GOOGLE_MAPS_API_KEY, ARCGIS_API_KEY and AZURE_MAPS_KEY -- the
# same secrets the server uses for billed calls. Anyone who loaded the site
# could copy the Google key and spend the town's geocoding and translation
# budget from their own machine, and there is no way to notice except the bill.
#
# A map key delivered to a browser IS public; that part is unavoidable. What is
# avoidable is it being the SAME key as the server's. So the endpoint only ever
# reads the browser-scoped secret name, and the server-side name is not
# reachable from here at all:
#
#   GOOGLE_MAPS_BROWSER_API_KEY   HTTP-referrer restricted to the town's domain
#   ARCGIS_BROWSER_API_KEY        referrer-restricted ArcGIS key
#   AZURE_MAPS_BROWSER_KEY        Azure Maps key restricted to the town's origin
#
# A town that has configured only the server key gets NO key here and an
# explicit note saying which one to create. That fails safe in the honest
# direction: a blank map with an admin-visible explanation is recoverable in
# ten minutes, and a published server key is not recoverable at all -- it has
# to be rotated, and every call made with it in the meantime is billed.
#
# A town that genuinely wants one key for both writes the same value into the
# browser-scoped name. That is a deliberate, recorded choice by an
# administrator, which is exactly the difference from publishing it by default.
BROWSER_KEY_FOR = {
    "GOOGLE_MAPS_API_KEY": "GOOGLE_MAPS_BROWSER_API_KEY",
    "ARCGIS_API_KEY": "ARCGIS_BROWSER_API_KEY",
    "AZURE_MAPS_KEY": "AZURE_MAPS_BROWSER_KEY",
}


def browser_secret_reader(get_secret):
    """Wrap a secret reader so billed keys resolve to their browser twin only.

    Passed to map_provider.resolve_credentials in place of the raw reader, so
    there is no code path from that call to a server-side key -- the
    substitution happens before the lookup rather than as a filter afterwards,
    because a filter is one forgotten field away from leaking again.
    """

    async def read(key: str):
        return await get_secret(BROWSER_KEY_FOR.get(key, key))

    return read



@router.get("/geocode")
async def geocode_address(
    address: str,
    db: AsyncSession = Depends(get_db)
):
    """Geocode an address to coordinates, using the town's own geocoder.

    Was hardwired to Google-then-OpenStreetMap and biased to nowhere, so an Esri
    town's county address locator went unused and a search for a common street
    name answered from the other side of the continent.
    """
    from app.services import geocode_dispatch

    result = await geocode_dispatch.geocode(db, address)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not geocode address"
        )
    
    return {
        "lat": result.lat,
        "lng": result.lng,
        "formatted_address": result.formatted_address,
        "place_id": result.place_id
    }


@router.get("/reverse-geocode")
async def reverse_geocode(
    lat: float,
    lng: float,
    db: AsyncSession = Depends(get_db)
):
    """Convert coordinates to address, using the town's own geocoder."""
    from app.services import geocode_dispatch

    result = await geocode_dispatch.reverse_geocode(db, lat, lng)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Could not reverse geocode coordinates"
        )
    
    return {
        "lat": result.lat,
        "lng": result.lng,
        "formatted_address": result.formatted_address
    }


@router.get("/boundaries")
async def list_boundaries(
    db: AsyncSession = Depends(get_db)
):
    """List all configured boundaries"""
    service = get_boundary_service()
    
    boundaries = service.get_all_boundaries()
    return [
        {
            "name": b.name,
            "bounds": b.bounds
        }
        for b in boundaries
    ]


@router.get("/boundaries/{name}")
async def get_boundary(
    name: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific boundary with full geometry"""
    service = get_boundary_service()
    
    boundary = service.get_boundary(name)
    if not boundary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Boundary not found"
        )
    
    return {
        "name": boundary.name,
        "geometry": boundary.geometry,
        "bounds": boundary.bounds
    }


async def persist_boundary(db, geojson_data: dict, name: str = None,
                           center_lat: float = None, center_lng: float = None) -> dict:
    """Store a boundary and fetch the roads inside it.

    Three endpoints accept a boundary -- an uploaded file, a Census lookup, and
    the built-in search -- and only the last one did this. The other two loaded
    the shape into an in-memory helper and returned "success", which meant the
    boundary vanished on the next restart and no roads were ever fetched for it.
    Nothing said so: the map drew, because the browser had the file it had just
    uploaded, and the roads were missing only later, when a resident's report
    could not be matched to a street.

    So all three go through here.
    """
    from app.models import SystemSettings

    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = SystemSettings()
        db.add(settings)

    boundary_data = normalize_boundary(geojson_data, name)
    if center_lat is not None and center_lng is not None:
        boundary_data["center"] = {"lat": center_lat, "lng": center_lng}

    settings.township_boundary = boundary_data
    await db.commit()

    # Roads follow the boundary, always. Queued when a worker is available so
    # the upload returns promptly; run inline otherwise, because a deployment
    # without Celery should still end up with roads rather than silently not.
    try:
        from app.tasks.road_data import seed_roads
        seed_roads.delay(force=True)
        seeding = "queued"
    except Exception as exc:
        logger.warning("Could not queue road seeding, running inline: %s", exc)
        try:
            outcome = await seed_roads_for_boundary(db, force=True)
            seeding = "done" if outcome.get("ok") else f"failed: {outcome.get('reason')}"
        except Exception as inline_exc:
            logger.warning("Inline road seeding failed: %s", inline_exc)
            seeding = "failed"

    return {"boundary": boundary_data, "seeding": seeding}


def normalize_boundary(geojson_data: dict, name: str = None) -> dict:
    """Any of the shapes a boundary arrives in, as a FeatureCollection."""
    if not isinstance(geojson_data, dict) or "type" not in geojson_data:
        return geojson_data
    if geojson_data["type"] in ("Polygon", "MultiPolygon"):
        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": geojson_data,
                "properties": {"name": name or "Township Boundary"},
            }],
        }
    if geojson_data["type"] == "Feature":
        return {"type": "FeatureCollection", "features": [geojson_data]}
    return geojson_data


# This decorator had come adrift. It was sitting two functions up, on
# `persist_boundary` -- an internal helper that takes a raw session and has no
# `Depends` on it at all -- which meant POST /api/gis/boundaries was served by
# an unauthenticated function that writes `settings.township_boundary` and
# commits. A town's boundary decides which roads are fetched, how reports are
# matched to streets, and what the map draws, and anyone who could reach the
# API could replace it.
#
# The consequence in the other direction was just as bad and much quieter: the
# admin-guarded handler below had no route at all, so the boundary upload an
# administrator is supposed to use had silently not existed.
@router.post("/boundaries")
async def upload_boundary(
    name: str,
    file: UploadFile = File(...),
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Upload a GeoJSON boundary file (admin only)"""
    try:
        content = await file.read()
        geojson = json.loads(content.decode())
        
        service = get_boundary_service()
        service.load_boundary_from_geojson(name, geojson)

        outcome = await persist_boundary(db, geojson, name)
        return {
            "status": "success",
            "message": f"Boundary '{name}' loaded",
            "road_seeding": outcome["seeding"],
        }
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid GeoJSON file"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/check-boundary")
async def check_point_in_boundary(
    lat: float,
    lng: float,
    boundary_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Check if a point is within a boundary"""
    service = get_boundary_service()
    
    is_inside = service.point_in_boundary(lat, lng, boundary_name)
    
    return {
        "lat": lat,
        "lng": lng,
        "boundary": boundary_name,
        "is_inside": is_inside
    }


@router.get("/config")
async def get_maps_config(db: AsyncSession = Depends(get_db)):
    """Get maps configuration for the browser.

    Unauthenticated by necessity, so everything it returns is public. Only
    browser-scoped credentials are readable from here; see BROWSER_KEY_FOR.
    """
    
    # Get Map ID for vector maps (enables 45° tilt, rotation, 3D buildings)
    map_id = None
    try:
        from app.services.secret_manager import get_secret
        map_id = await get_secret("GOOGLE_MAPS_MAP_ID")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not get Google Maps Map ID: {e}")
    
    # Get township settings
    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    
    # Which provider this town renders with, and only the credentials that
    # provider actually needs. A MapLibre town has no business receiving a
    # Google key just because one happens to be configured.
    from app.services import map_provider as mp
    from app.services.secret_manager import get_secret as _get_secret

    # Selection lives in Secret Manager beside every other capability's choice,
    # rather than in the modules blob, so switching a map works the same way as
    # switching an AI or translation provider.
    render_provider = mp.normalize_provider(await _get_secret(mp.MAP_PROVIDER_KEY))
    geocode_provider = mp.geocoder_for(
        render_provider, await _get_secret(mp.GEOCODE_PROVIDER_KEY)
    )
    # Browser-scoped reader, not `_get_secret`: this response goes to anyone
    # who asks, so a server-side key must not be reachable from this call.
    _get_browser_secret = browser_secret_reader(_get_secret)
    # Legacy Google fields below are fed from the browser key too, so a client
    # still reading them cannot be handed the server key by the back door.
    try:
        google_browser_key = await _get_browser_secret("GOOGLE_MAPS_API_KEY")
    except Exception as exc:  # a secret-store hiccup must not blank the config
        import logging
        logging.getLogger(__name__).warning("Could not read browser map key: %s", exc)
        google_browser_key = None
    credentials = await mp.resolve_credentials(render_provider, _get_browser_secret)
    missing = mp.missing_requirements(render_provider, credentials)

    # A town with only the server key configured lands here: nothing to publish,
    # and a sentence saying which secret to create rather than a blank map with
    # no explanation.
    browser_key_needed = []
    for server_key, browser_key in BROWSER_KEY_FOR.items():
        spec = mp.MAP_CATALOG.get(render_provider) or {}
        if server_key not in {f["key"] for f in spec.get("credential_fields", [])}:
            continue
        if await _get_browser_secret(server_key):
            continue
        if await _get_secret(server_key):
            browser_key_needed.append(browser_key)

    # Apple is the one provider that cannot be authenticated with a static key:
    # MapKit JS wants an ES256-signed JWT, and the signing key must never leave
    # the server. Mint a short-lived token instead.
    if render_provider == "apple":
        from app.services.apple_mapkit import get_token

        token = await get_token(_get_secret)
        credentials["token"] = token
        if not token:
            missing = sorted(set(missing) | {"token"})

    from app.services.boundary_geo import boundary_centre

    boundary = settings.township_boundary if settings else None
    centre = boundary_centre(boundary)
    center = (
        {"lat": centre[1], "lng": centre[0]} if centre
        else {"lat": CONTINENTAL_US_CENTER[0], "lng": CONTINENTAL_US_CENTER[1]}
    )

    return {
        # Legacy fields. The frontend still reads these until every component
        # goes through resolveMapProviderConfig(); they stay accurate for
        # Google and are null elsewhere, which is the honest answer.
        # The browser key, never the server key. `has_google_maps` answers
        # "can the browser draw a Google map", which is what the frontend is
        # asking, not "does this town have a Google account".
        "has_google_maps": bool(google_browser_key),
        "google_maps_api_key": google_browser_key or None,
        "google_maps_map_id": map_id,

        "map_provider": render_provider,
        "geocode_provider": geocode_provider,
        "map_credentials": credentials,
        # Non-empty means the town picked a provider it has not finished
        # configuring. Reported rather than silently falling back, so an admin
        # can see why their map is blank.
        "map_provider_missing": missing,
        # Secret names an administrator has to create before the map can draw,
        # because only the server-side twin exists. Surfaced rather than
        # silently publishing the server key.
        "browser_key_needed": browser_key_needed,
        "browser_key_note": (
            "This town has a server-side map key but no browser key. A key sent "
            "to a browser is public, so it must be a separate, referrer-"
            "restricted key: create "
            + ", ".join(browser_key_needed)
            + " in the secret store."
        ) if browser_key_needed else None,

        "township_boundary": boundary,
        # The middle of the town, when the town has said where it is.
        #
        # This was 40.4168,-74.5430 — commented "a central location", which it
        # is only if the town is in New Jersey. Every other deployment opened
        # its map over Monmouth County and had to be dragged somewhere useful,
        # and a resident dropping a pin started three states away from the
        # pothole. Falling back to the whole country is not a better guess; it
        # is an honest one, and at zoom 4 it reads as "we don't know yet"
        # rather than as a wrong answer.
        "default_center": center,
        "default_zoom": 12 if centre else CONTINENTAL_US_ZOOM,
    }


@router.get("/providers")
async def list_map_providers():
    """Map providers a town can choose, for the admin console."""
    from app.services import map_provider as mp

    return {"providers": mp.catalog(), "default": mp.DEFAULT_PROVIDER}




# State FIPS codes for Census API
STATE_FIPS = {
    'AL': '01', 'AK': '02', 'AZ': '04', 'AR': '05', 'CA': '06', 'CO': '08', 'CT': '09',
    'DE': '10', 'FL': '12', 'GA': '13', 'HI': '15', 'ID': '16', 'IL': '17', 'IN': '18',
    'IA': '19', 'KS': '20', 'KY': '21', 'LA': '22', 'ME': '23', 'MD': '24', 'MA': '25',
    'MI': '26', 'MN': '27', 'MS': '28', 'MO': '29', 'MT': '30', 'NE': '31', 'NV': '32',
    'NH': '33', 'NJ': '34', 'NM': '35', 'NY': '36', 'NC': '37', 'ND': '38', 'OH': '39',
    'OK': '40', 'OR': '41', 'PA': '42', 'RI': '44', 'SC': '45', 'SD': '46', 'TN': '47',
    'TX': '48', 'UT': '49', 'VT': '50', 'VA': '51', 'WA': '53', 'WV': '54', 'WI': '55', 'WY': '56'
}


@router.get("/census-boundary-search")
async def search_census_boundary(
    town_name: str,
    state_abbr: str,
    layer_type: str = "township",  # township, city, county
    _: User = Depends(get_current_admin)
):
    """Search for a township/city/county boundary from Census TIGERweb API"""
    
    # Layer IDs for TIGERweb
    layers = {
        "county": 84,
        "city": 24,       # Incorporated Places
        "township": 26    # County Subdivisions
    }
    
    layer_id = layers.get(layer_type, 26)
    state_fips = STATE_FIPS.get(state_abbr.upper(), "00")
    
    if state_fips == "00":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid state abbreviation: {state_abbr}"
        )
    
    # Build query
    base_url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
    where_clause = f"UPPER(BASENAME) LIKE '%{town_name.upper()}%' AND STATE = '{state_fips}'"
    
    params = {
        "f": "geojson",
        "where": where_clause,
        "outFields": "*",
        "outSR": "4326"
    }
    
    url = f"{base_url}/{layer_id}/query"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to connect to Census API"
            )
        
        data = response.json()
        
        if not data.get("features"):
            return {"results": [], "message": "No boundaries found. Try a different name or layer type."}
        
        # Return search results (simplified for selection)
        results = []
        for feature in data["features"]:
            props = feature.get("properties", {})
            results.append({
                "name": props.get("BASENAME") or props.get("NAME"),
                "full_name": props.get("NAME") or props.get("BASENAME"),
                "geoid": props.get("GEOID"),
                "state": state_abbr.upper(),
                "layer_type": layer_type,
                "geometry": feature.get("geometry")  # Include full geometry for saving
            })
        
        return {"results": results}


@router.post("/boundaries/save-census")
async def save_census_boundary(
    name: str,
    geojson_data: dict,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Save a Census boundary as the township boundary"""
    try:
        service = get_boundary_service()
        
        # Convert single geometry/feature to GeoJSON FeatureCollection if needed
        if "type" in geojson_data and geojson_data["type"] in ["Polygon", "MultiPolygon"]:
            geojson_data = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": geojson_data,
                    "properties": {"name": name}
                }]
            }
        elif "type" in geojson_data and geojson_data["type"] == "Feature":
            geojson_data = {
                "type": "FeatureCollection",
                "features": [geojson_data]
            }
        
        service.load_boundary_from_geojson(name, geojson_data)

        outcome = await persist_boundary(db, geojson_data, name)
        return {
            "status": "success",
            "message": f"Boundary '{name}' saved successfully",
            "road_seeding": outcome["seeding"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ========== OSM / Nominatim Township Boundary Endpoints ==========

@router.get("/osm/search")
async def search_osm_township(
    query: str,
    _: User = Depends(get_current_admin)
):
    """Search for a township/city boundary using OpenStreetMap Nominatim"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Search Nominatim for the location with polygon output
            nominatim_url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": query,
                "format": "json",
                "limit": "5",
                "addressdetails": "1",
                "polygon_geojson": "1",  # Include GeoJSON boundary directly
                "polygon_threshold": "0.0"  # Full detail boundary
            }
            headers = {
                "User-Agent": "Township311/1.0 (township311-service)"
            }
            
            response = await client.get(nominatim_url, params=params, headers=headers)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to connect to Nominatim"
                )
            
            results = response.json()
            
            # Filter to only include results that are relations (have boundaries)
            filtered_results = []
            for r in results:
                if r.get("osm_type") == "relation":
                    filtered_results.append({
                        "osm_id": r.get("osm_id"),
                        "display_name": r.get("display_name"),
                        "type": r.get("type"),
                        "class": r.get("class"),
                        "lat": r.get("lat"),
                        "lon": r.get("lon"),
                        "boundingbox": r.get("boundingbox"),
                        "geojson": r.get("geojson")  # Include boundary GeoJSON directly
                    })
            
            return {"results": filtered_results}
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to search Nominatim: {str(e)}"
        )


@router.get("/osm/boundary/{osm_id}")
async def fetch_osm_boundary(
    osm_id: int,
    _: User = Depends(get_current_admin)
):
    """Fetch GeoJSON boundary from polygons.openstreetmap.fr for an OSM relation"""
    # Validate osm_id to prevent SSRF
    if not isinstance(osm_id, int) or osm_id < 1 or osm_id > 999_999_999:
        raise HTTPException(status_code=400, detail="Invalid OSM ID")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Fetch GeoJSON from polygons.openstreetmap.fr
            polygon_url = f"https://polygons.openstreetmap.fr/get_geojson.py?id={osm_id}"
            
            response = await client.get(polygon_url)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to fetch boundary from OpenStreetMap. The boundary may not be available."
                )
            
            geojson = response.json()
            
            return {"geojson": geojson, "osm_id": osm_id}
            
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch boundary from OpenStreetMap"
        )


@router.post("/township-boundary")
async def save_township_boundary(
    geojson_data: dict,
    name: str = None,
    center_lat: float = None,
    center_lng: float = None,
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Save the township boundary GeoJSON to system settings"""
    try:
        # Get or create system settings
        result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = SystemSettings()
            db.add(settings)

        # Handle clearing boundary
        if not geojson_data or geojson_data == {} or geojson_data.get("type") is None:
            settings.township_boundary = None
            from app.models import RoadSegment
            from sqlalchemy import delete
            await db.execute(delete(RoadSegment))
            await db.commit()
            return {"status": "success", "message": "Township boundary and road segments cleared"}
        
        # One implementation for all three boundary paths -- see
        # persist_boundary for why the other two used to skip the roads.
        outcome = await persist_boundary(db, geojson_data, name, center_lat, center_lng)
        return {
            "status": "success",
            "message": "Township boundary saved successfully",
            "road_seeding": outcome["seeding"],
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

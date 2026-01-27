"""
GIS and Geocoding API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
import json
import httpx

from app.db.session import get_db
from app.models import User, SystemSecret, SystemSettings
from app.core.auth import get_current_admin, get_current_staff
from app.core.encryption import decrypt_safe
from app.services.geocoding import (
    GeocodingService, BoundaryService,
    get_geocoding_service, get_boundary_service
)

router = APIRouter()


async def get_google_api_key(db: AsyncSession) -> Optional[str]:
    """Get Google Maps API key from secrets (decrypted)"""
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name == "GOOGLE_MAPS_API_KEY")
    )
    secret = result.scalar_one_or_none()
    if secret and secret.is_configured and secret.key_value:
        # Decrypt the key if it's encrypted
        return decrypt_safe(secret.key_value)
    return None


@router.get("/geocode")
async def geocode_address(
    address: str,
    db: AsyncSession = Depends(get_db)
):
    """Geocode an address to coordinates"""
    api_key = await get_google_api_key(db)
    service = get_geocoding_service(api_key)
    
    result = await service.geocode(address)
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
    """Convert coordinates to address"""
    api_key = await get_google_api_key(db)
    service = get_geocoding_service(api_key)
    
    result = await service.reverse_geocode(lat, lng)
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
    api_key = await get_google_api_key(db)
    service = get_boundary_service(api_key)
    
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
    api_key = await get_google_api_key(db)
    service = get_boundary_service(api_key)
    
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
        
        api_key = await get_google_api_key(db)
        service = get_boundary_service(api_key)
        service.load_boundary_from_geojson(name, geojson)
        
        return {"status": "success", "message": f"Boundary '{name}' loaded"}
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
    api_key = await get_google_api_key(db)
    service = get_boundary_service(api_key)
    
    is_inside = service.point_in_boundary(lat, lng, boundary_name)
    
    return {
        "lat": lat,
        "lng": lng,
        "boundary": boundary_name,
        "is_inside": is_inside
    }


@router.get("/config")
async def get_maps_config(db: AsyncSession = Depends(get_db)):
    """Get maps configuration for frontend"""
    api_key = await get_google_api_key(db)
    
    # Get township settings
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    
    return {
        "has_google_maps": bool(api_key),
        "google_maps_api_key": api_key if api_key else None,
        "township_boundary": settings.township_boundary if settings else None,
        "default_center": {
            "lat": 40.4168,  # Default to a central location
            "lng": -74.5430
        },
        "default_zoom": 12
    }




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
        api_key = await get_google_api_key(db)
        service = get_boundary_service(api_key)
        
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
        
        return {"status": "success", "message": f"Boundary '{name}' saved successfully"}
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
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch boundary: {str(e)}"
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
        result = await db.execute(select(SystemSettings).limit(1))
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = SystemSettings()
            db.add(settings)
        
        # Normalize to FeatureCollection if needed
        boundary_data = geojson_data
        if "type" in geojson_data:
            if geojson_data["type"] in ["Polygon", "MultiPolygon"]:
                boundary_data = {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "geometry": geojson_data,
                        "properties": {"name": name or "Township Boundary"}
                    }]
                }
            elif geojson_data["type"] == "Feature":
                boundary_data = {
                    "type": "FeatureCollection",
                    "features": [geojson_data]
                }
        
        # Add center coordinates if provided
        if center_lat is not None and center_lng is not None:
            boundary_data["center"] = {"lat": center_lat, "lng": center_lng}
        
        settings.township_boundary = boundary_data
        await db.commit()
        
        return {"status": "success", "message": "Township boundary saved successfully"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

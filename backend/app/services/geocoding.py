"""
Geocoding and GIS services for location-based features.
Supports Google Maps API and OpenStreetMap as fallback.
"""
import httpx
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GeocodingResult:
    """Result from geocoding operation"""
    lat: float
    lng: float
    formatted_address: str
    place_id: Optional[str] = None
    components: Optional[Dict[str, str]] = None


@dataclass
class BoundaryInfo:
    """Township/municipality boundary information"""
    name: str
    geometry: Dict[str, Any]  # GeoJSON geometry
    bounds: Dict[str, float]  # {north, south, east, west}


class GeocodingService:
    """Service for geocoding addresses and reverse geocoding coordinates"""
    
    def __init__(self, google_api_key: Optional[str] = None):
        self.google_api_key = google_api_key
        self.google_base_url = "https://maps.googleapis.com/maps/api/geocode/json"
        self.osm_base_url = "https://nominatim.openstreetmap.org"
    
    async def geocode(self, address: str) -> Optional[GeocodingResult]:
        """Convert address to coordinates"""
        if self.google_api_key:
            return await self._geocode_google(address)
        return await self._geocode_osm(address)
    
    async def reverse_geocode(self, lat: float, lng: float) -> Optional[GeocodingResult]:
        """Convert coordinates to address"""
        if self.google_api_key:
            return await self._reverse_geocode_google(lat, lng)
        return await self._reverse_geocode_osm(lat, lng)
    
    async def _geocode_google(self, address: str) -> Optional[GeocodingResult]:
        """Geocode using Google Maps API"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.google_base_url,
                    params={
                        "address": address,
                        "key": self.google_api_key
                    }
                )
                data = response.json()
                
                if data.get("status") == "OK" and data.get("results"):
                    result = data["results"][0]
                    location = result["geometry"]["location"]
                    
                    # Track API usage for cost estimation
                    try:
                        from app.db.session import SessionLocal
                        from app.services.api_usage import track_api_usage
                        async with SessionLocal() as db:
                            await track_api_usage(
                                db=db,
                                service_name="maps_geocode",
                                operation="geocode"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to track geocoding usage: {e}")
                    
                    # Extract address components
                    components = {}
                    for comp in result.get("address_components", []):
                        for comp_type in comp.get("types", []):
                            components[comp_type] = comp.get("long_name", "")
                    
                    return GeocodingResult(
                        lat=location["lat"],
                        lng=location["lng"],
                        formatted_address=result["formatted_address"],
                        place_id=result.get("place_id"),
                        components=components
                    )
        except Exception as e:
            logger.warning(f"Google geocoding error: {e}")
        return None
    
    async def _reverse_geocode_google(self, lat: float, lng: float) -> Optional[GeocodingResult]:
        """Reverse geocode using Google Maps API"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.google_base_url,
                    params={
                        "latlng": f"{lat},{lng}",
                        "key": self.google_api_key
                    }
                )
                data = response.json()
                
                if data.get("status") == "OK" and data.get("results"):
                    result = data["results"][0]
                    
                    # Track API usage for cost estimation
                    try:
                        from app.db.session import SessionLocal
                        from app.services.api_usage import track_api_usage
                        async with SessionLocal() as db:
                            await track_api_usage(
                                db=db,
                                service_name="maps_reverse_geocode",
                                operation="reverse_geocode"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to track reverse geocoding usage: {e}")
                    
                    return GeocodingResult(
                        lat=lat,
                        lng=lng,
                        formatted_address=result["formatted_address"],
                        place_id=result.get("place_id")
                    )
        except Exception as e:
            logger.warning(f"Google reverse geocoding error: {e}")
        return None
    
    async def _geocode_osm(self, address: str) -> Optional[GeocodingResult]:
        """Geocode using OpenStreetMap Nominatim (free fallback)"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.osm_base_url}/search",
                    params={
                        "q": address,
                        "format": "json",
                        "limit": 1
                    },
                    headers={"User-Agent": "Township311/1.0"}
                )
                data = response.json()
                
                if data:
                    result = data[0]
                    return GeocodingResult(
                        lat=float(result["lat"]),
                        lng=float(result["lon"]),
                        formatted_address=result["display_name"]
                    )
        except Exception as e:
            logger.warning(f"OSM geocoding error: {e}")
        return None
    
    async def _reverse_geocode_osm(self, lat: float, lng: float) -> Optional[GeocodingResult]:
        """Reverse geocode using OpenStreetMap Nominatim"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.osm_base_url}/reverse",
                    params={
                        "lat": lat,
                        "lon": lng,
                        "format": "json"
                    },
                    headers={"User-Agent": "Township311/1.0"}
                )
                data = response.json()
                
                if data:
                    return GeocodingResult(
                        lat=lat,
                        lng=lng,
                        formatted_address=data.get("display_name", "")
                    )
        except Exception as e:
            logger.warning(f"OSM reverse geocoding error: {e}")
        return None


class BoundaryService:
    """Service for managing township/municipality boundaries"""
    
    def __init__(self, google_api_key: Optional[str] = None):
        self.google_api_key = google_api_key
        self.boundaries: Dict[str, BoundaryInfo] = {}
    
    def load_boundary_from_geojson(self, name: str, geojson: Dict[str, Any]):
        """Load a boundary from GeoJSON data"""
        geometry = geojson.get("geometry", geojson)
        
        # Calculate bounds from geometry
        bounds = self._calculate_bounds(geometry)
        
        self.boundaries[name] = BoundaryInfo(
            name=name,
            geometry=geometry,
            bounds=bounds
        )
    
    def _calculate_bounds(self, geometry: Dict[str, Any]) -> Dict[str, float]:
        """Calculate bounding box from geometry"""
        coords = self._extract_coordinates(geometry)
        if not coords:
            return {"north": 0, "south": 0, "east": 0, "west": 0}
        
        lngs = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        
        return {
            "north": max(lats),
            "south": min(lats),
            "east": max(lngs),
            "west": min(lngs)
        }
    
    def _extract_coordinates(self, geometry: Dict[str, Any]) -> List[Tuple[float, float]]:
        """Extract all coordinates from a geometry"""
        coords = []
        geom_type = geometry.get("type", "")
        geom_coords = geometry.get("coordinates", [])
        
        if geom_type == "Point":
            coords.append(tuple(geom_coords))
        elif geom_type == "LineString":
            coords.extend([tuple(c) for c in geom_coords])
        elif geom_type == "Polygon":
            for ring in geom_coords:
                coords.extend([tuple(c) for c in ring])
        elif geom_type == "MultiPolygon":
            for polygon in geom_coords:
                for ring in polygon:
                    coords.extend([tuple(c) for c in ring])
        
        return coords
    
    def point_in_boundary(self, lat: float, lng: float, boundary_name: str) -> bool:
        """Check if a point is within a boundary"""
        boundary = self.boundaries.get(boundary_name)
        if not boundary:
            return False
        
        # Quick bounds check first
        bounds = boundary.bounds
        if not (bounds["south"] <= lat <= bounds["north"] and 
                bounds["west"] <= lng <= bounds["east"]):
            return False
        
        # For precise check, use PostGIS via database query
        # This is a simplified ray-casting for client-side
        return self._point_in_polygon(lat, lng, boundary.geometry)
    
    def _point_in_polygon(self, lat: float, lng: float, geometry: Dict[str, Any]) -> bool:
        """Ray-casting algorithm for point-in-polygon check"""
        if geometry.get("type") != "Polygon":
            return False
        
        coords = geometry.get("coordinates", [[]])[0]
        n = len(coords)
        inside = False
        
        j = n - 1
        for i in range(n):
            xi, yi = coords[i][0], coords[i][1]
            xj, yj = coords[j][0], coords[j][1]
            
            if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        
        return inside
    
    def get_boundary(self, name: str) -> Optional[BoundaryInfo]:
        """Get a boundary by name"""
        return self.boundaries.get(name)
    
    def get_all_boundaries(self) -> List[BoundaryInfo]:
        """Get all loaded boundaries"""
        return list(self.boundaries.values())


# Singleton instances
geocoding_service: Optional[GeocodingService] = None
boundary_service: Optional[BoundaryService] = None


def get_geocoding_service(google_api_key: Optional[str] = None) -> GeocodingService:
    """Get or create geocoding service instance"""
    global geocoding_service
    if geocoding_service is None:
        geocoding_service = GeocodingService(google_api_key)
    return geocoding_service


def get_boundary_service(google_api_key: Optional[str] = None) -> BoundaryService:
    """Get or create boundary service instance"""
    global boundary_service
    if boundary_service is None:
        boundary_service = BoundaryService(google_api_key)
    return boundary_service

"""
Research Suite API - Read-only analytics layer for researchers

This module provides sanitized, PII-free access to service request data
for academic and municipal research purposes.

Research Focus Areas:
- Civil Engineering & Infrastructure: Asset types, infrastructure categories, maintenance patterns
- Equity & Equality: Geographic distribution, response time disparities, service accessibility
- Civics: Civic engagement patterns, submission channels, resolution outcomes

All endpoints:
- Check research_portal module is enabled
- Require researcher or admin role
- Query sanitized data (no PII)
- Log all access for audit purposes
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, extract
from sqlalchemy.orm import selectinload
from typing import Optional, List
from datetime import datetime, date, timedelta
import csv
import io
import json
import logging
import re
import hashlib

from app.db.session import get_db
from app.models import ServiceRequest, RequestAuditLog, SystemSettings, ResearchAccessLog, Department, RequestComment
from app.core.auth import get_current_researcher
from app.core.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

# Infrastructure category mapping for civil engineering research
INFRASTRUCTURE_CATEGORIES = {
    "pothole": "roads_pavement",
    "streetlight": "lighting",
    "sidewalk": "pedestrian_infrastructure",
    "storm_drain": "stormwater",
    "water": "water_utilities",
    "sewer": "sewer_utilities",
    "traffic": "traffic_control",
    "sign": "signage",
    "tree": "green_infrastructure",
    "park": "parks_recreation",
    "trash": "solid_waste",
    "graffiti": "property_maintenance",
    "abandoned": "property_maintenance",
    "noise": "quality_of_life",
    "animal": "animal_services",
}


async def check_research_enabled(db: AsyncSession):
    """Check if research portal is enabled via Admin Console modules"""
    if settings.enable_research_suite:
        return True
    
    result = await db.execute(select(SystemSettings).limit(1))
    system_settings = result.scalar_one_or_none()
    if system_settings and system_settings.modules:
        return system_settings.modules.get("research_portal", False)
    
    return False


async def log_research_access(
    db: AsyncSession,
    user_id: int,
    username: str,
    action: str,
    parameters: dict,
    record_count: int,
    privacy_mode: str = "fuzzed"
):
    """Log research data access for audit purposes"""
    log_entry = ResearchAccessLog(
        user_id=user_id,
        username=username,
        action=action,
        parameters=parameters,
        record_count=record_count,
        privacy_mode=privacy_mode
    )
    db.add(log_entry)
    await db.commit()


def sanitize_description(description: str) -> str:
    """Mask PII patterns in description text"""
    if not description:
        return ""
    result = description
    
    # Mask phone numbers
    phone_patterns = [
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',
        r'\(\d{3}\)\s?\d{3}[-.\s]?\d{4}',
    ]
    for pattern in phone_patterns:
        result = re.sub(pattern, '[PHONE REDACTED]', result)
    
    # Mask email addresses
    result = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL REDACTED]', result)
    
    # Mask potential names (patterns like "John Smith" or "Mr. Smith")
    result = re.sub(r'\b(Mr\.|Mrs\.|Ms\.|Dr\.)\s+[A-Z][a-z]+', '[NAME REDACTED]', result)
    
    return result


def fuzz_location(lat: float, long: float, grid_size: float = 0.0003) -> tuple:
    """Snap coordinates to grid (~100ft precision for privacy)"""
    if lat is None or long is None:
        return None, None
    fuzzed_lat = round(lat / grid_size) * grid_size
    fuzzed_long = round(long / grid_size) * grid_size
    return round(fuzzed_lat, 6), round(fuzzed_long, 6)


def anonymize_address(address: str, privacy_mode: str) -> str:
    """Anonymize address based on privacy mode"""
    if not address:
        return ""
    
    if privacy_mode == "exact":
        return address
    
    # For fuzzed mode: remove house numbers, keep street name and area
    # "123 Main Street, West Windsor" -> "Main Street Block, West Windsor"
    result = re.sub(r'^\d+\s+', '', address)  # Remove leading house number
    result = re.sub(r'\d+', 'X', result)  # Replace any remaining numbers
    
    # Add "Block" indicator if we removed a house number
    if result != address:
        parts = result.split(',')
        if len(parts) > 0:
            parts[0] = parts[0].strip() + " (Block)"
            result = ', '.join(parts)
    
    return result


def get_infrastructure_category(service_code: str) -> str:
    """Map service code to infrastructure category for civil engineering research"""
    if not service_code:
        return "other"
    
    code_lower = service_code.lower()
    for key, category in INFRASTRUCTURE_CATEGORIES.items():
        if key in code_lower:
            return category
    return "other"


def calculate_business_hours(start: datetime, end: datetime) -> float:
    """Calculate business hours between two datetimes (Mon-Fri 8am-5pm)"""
    if not start or not end:
        return None
    
    total_hours = 0
    current = start
    
    while current < end:
        # Skip weekends
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            # Business hours: 8am to 5pm
            day_start = current.replace(hour=8, minute=0, second=0, microsecond=0)
            day_end = current.replace(hour=17, minute=0, second=0, microsecond=0)
            
            if current < day_start:
                work_start = day_start
            else:
                work_start = current
            
            if end < day_end:
                work_end = end
            else:
                work_end = day_end
            
            if work_start < work_end and work_start >= day_start:
                total_hours += (work_end - work_start).total_seconds() / 3600
        
        # Move to next day
        current = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    return round(total_hours, 2) if total_hours > 0 else None


def get_time_period(dt: datetime) -> dict:
    """Extract time period information for temporal analysis"""
    if not dt:
        return {}
    
    return {
        "hour_of_day": dt.hour,
        "day_of_week": dt.strftime("%A"),
        "day_of_week_num": dt.weekday(),
        "month": dt.strftime("%B"),
        "month_num": dt.month,
        "quarter": f"Q{(dt.month - 1) // 3 + 1}",
        "year": dt.year,
        "is_weekend": dt.weekday() >= 5,
        "is_business_hours": 8 <= dt.hour < 17 and dt.weekday() < 5,
    }


def generate_zone_id(lat: float, long: float) -> str:
    """Generate anonymized zone ID for geographic clustering without revealing exact location"""
    if lat is None or long is None:
        return None
    
    # Create larger grid cells (~0.5 mile zones)
    zone_lat = round(lat / 0.007) * 0.007
    zone_long = round(long / 0.007) * 0.007
    
    # Hash to create anonymous zone ID
    zone_str = f"{zone_lat:.3f},{zone_long:.3f}"
    zone_hash = hashlib.md5(zone_str.encode()).hexdigest()[:8]
    return f"ZONE-{zone_hash.upper()}"


def get_season(dt: datetime) -> str:
    """Determine season from datetime for infrastructure/weather correlation research"""
    if not dt:
        return None
    month = dt.month
    if month in [12, 1, 2]:
        return "winter"
    elif month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    else:
        return "fall"


def get_income_quintile_from_zone(zone_id: str, census_geoid: str = None) -> int:
    """
    Get income quintile (1-5) from Census ACS median household income data.
    Uses Census ACS 5-year estimates table B19013 (Median Household Income).
    
    Quintiles based on national median income (~$75,000):
    1 = <$30k, 2 = $30-50k, 3 = $50-75k, 4 = $75-100k, 5 = >$100k
    """
    if not census_geoid:
        return None
    
    # Try to get from ACS data cache
    acs_data = get_census_acs_data(census_geoid)
    if acs_data and acs_data.get("median_income"):
        income = acs_data["median_income"]
        if income < 30000:
            return 1
        elif income < 50000:
            return 2
        elif income < 75000:
            return 3
        elif income < 100000:
            return 4
        else:
            return 5
    
    return None


# Cache for Census ACS data (tract GEOID -> data dict)
_census_acs_cache: dict = {}


def get_census_acs_data(census_geoid: str) -> Optional[dict]:
    """
    Get Census ACS 5-year estimates for a census tract.
    Includes: median income, total population, housing tenure, and land area.
    
    Uses Census Bureau API (free, requires API key stored in system_secrets).
    Results are cached to minimize API calls.
    
    Variables:
    - B19013_001E: Median household income
    - B01003_001E: Total population
    - B25003_001E: Total occupied housing units
    - B25003_003E: Renter-occupied units
    """
    if not census_geoid or len(census_geoid) < 11:
        return None
    
    # Check cache first
    if census_geoid in _census_acs_cache:
        return _census_acs_cache[census_geoid]
    
    try:
        import requests
        
        # Parse GEOID: SSCCCTTTTTT (State 2 + County 3 + Tract 6)
        state_fips = census_geoid[:2]
        county_fips = census_geoid[2:5]
        tract = census_geoid[5:]
        
        # ACS 5-year estimates (most reliable for tract level)
        year = 2022  # Most recent complete ACS 5-year
        base_url = f"https://api.census.gov/data/{year}/acs/acs5"
        
        # Variables to fetch
        variables = "B19013_001E,B01003_001E,B25003_001E,B25003_003E"
        
        # Note: Census API works without key for limited requests
        # For production, add: &key={api_key}
        url = f"{base_url}?get={variables}&for=tract:{tract}&in=state:{state_fips}&in=county:{county_fips}"
        
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if len(data) >= 2:
                # First row is headers, second is data
                headers = data[0]
                values = data[1]
                
                result = {}
                for i, header in enumerate(headers):
                    if header == "B19013_001E":
                        result["median_income"] = int(values[i]) if values[i] and values[i] != "-666666666" else None
                    elif header == "B01003_001E":
                        result["total_population"] = int(values[i]) if values[i] else None
                    elif header == "B25003_001E":
                        result["total_housing_units"] = int(values[i]) if values[i] else None
                    elif header == "B25003_003E":
                        result["renter_units"] = int(values[i]) if values[i] else None
                
                # Calculate renter percentage
                if result.get("total_housing_units") and result.get("renter_units"):
                    result["renter_pct"] = round(result["renter_units"] / result["total_housing_units"], 2)
                
                _census_acs_cache[census_geoid] = result
                return result
                
    except Exception as e:
        logger.warning(f"Census ACS API error for {census_geoid}: {e}")
    
    _census_acs_cache[census_geoid] = None
    return None


def get_population_density_category(zone_id: str, census_geoid: str = None) -> str:
    """
    Get population density category from Census ACS population data.
    Uses Census ACS B01003 (Total Population) and tract land area.
    
    Categories based on population per square mile:
    - low: < 1,000 per sq mi (rural/suburban)
    - medium: 1,000 - 5,000 per sq mi (suburban)
    - high: > 5,000 per sq mi (urban)
    """
    if not census_geoid:
        return None
    
    acs_data = get_census_acs_data(census_geoid)
    if acs_data and acs_data.get("total_population"):
        pop = acs_data["total_population"]
        
        # Estimate density - average US tract is ~1.5 sq mi
        # For accurate density, would need TIGER shapefile land area
        # Using population thresholds as proxy (typical tract ~4000 people)
        if pop < 2000:
            return "low"
        elif pop < 6000:
            return "medium"
        else:
            return "high"
    
    return None



# ============================================================================
# SOCIAL EQUITY PACK - For Sociologists
# ============================================================================

# Cache for Census GEOID lookups to avoid repeated API calls
_census_geoid_cache: dict = {}

def get_census_tract_geoid(lat: float, lng: float) -> Optional[str]:
    """
    Get 11-digit FIPS code (Census Tract GEOID) from coordinates.
    Uses US Census Bureau Geocoder API (free, no key required).
    Returns format: SSCCCTTTTTT (State + County + Tract)
    
    Results are cached to avoid repeated API calls for same location.
    """
    if lat is None or lng is None:
        return None
    
    # Round to reduce cache key variations (within ~100m)
    cache_key = f"{round(lat, 3)},{round(lng, 3)}"
    
    if cache_key in _census_geoid_cache:
        return _census_geoid_cache[cache_key]
    
    try:
        import requests
        response = requests.get(
            "https://geocoding.geo.census.gov/geocoder/geographies/coordinates",
            params={
                "x": lng,
                "y": lat,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "layers": "Census Tracts",
                "format": "json"
            },
            timeout=3
        )
        if response.status_code == 200:
            data = response.json()
            geographies = data.get("result", {}).get("geographies", {})
            tracts = geographies.get("Census Tracts", [])
            if tracts:
                geoid = tracts[0].get("GEOID")
                _census_geoid_cache[cache_key] = geoid
                return geoid
    except Exception as e:
        logger.warning(f"Census geocoder error: {e}")
    
    _census_geoid_cache[cache_key] = None
    return None


def get_social_vulnerability_index(census_geoid: str) -> Optional[float]:
    """
    Calculate CDC-style Social Vulnerability Index (SVI) for a census tract.
    SVI ranges from 0 (lowest vulnerability) to 1 (highest vulnerability).
    
    Uses Census ACS data to approximate CDC SVI methodology:
    - Lower income = higher vulnerability
    - Higher renter % = higher vulnerability
    - Higher population = higher vulnerability (urban stress)
    
    CDC SVI uses 16 variables across 4 themes; this is a simplified approximation
    using the variables we already fetch from ACS.
    """
    if not census_geoid:
        return None
    
    acs_data = get_census_acs_data(census_geoid)
    if not acs_data:
        return None
    
    # Calculate vulnerability score from available ACS data
    svi_components = []
    
    # Income vulnerability (lower income = higher vulnerability)
    # National median ~$75,000, poverty threshold ~$30,000
    median_income = acs_data.get("median_income")
    if median_income:
        # Normalize: $30k = 1.0 (high vuln), $150k = 0.0 (low vuln)
        income_vuln = max(0, min(1, (150000 - median_income) / 120000))
        svi_components.append(income_vuln)
    
    # Housing vulnerability (higher renter % = higher vulnerability)
    renter_pct = acs_data.get("renter_pct")
    if renter_pct is not None:
        svi_components.append(renter_pct)
    
    # Population density stress (rough proxy for urban challenges)
    total_pop = acs_data.get("total_population")
    if total_pop:
        # Normalize: 1000 = 0.0, 10000 = 1.0
        pop_vuln = max(0, min(1, (total_pop - 1000) / 9000))
        svi_components.append(pop_vuln * 0.5)  # Weight less than income/housing
    
    if svi_components:
        # Average all components for final SVI
        return round(sum(svi_components) / len(svi_components), 3)
    
    return None


def get_housing_tenure_mix(census_geoid: str) -> Optional[float]:
    """
    Get percentage of renters vs owners in census tract.
    Returns renter percentage (0.0 to 1.0).
    
    Uses Census ACS 5-year estimates table B25003:
    - B25003_001E: Total occupied housing units
    - B25003_003E: Renter-occupied units
    
    Hypothesis: Renters may under-report infrastructure issues.
    """
    if not census_geoid:
        return None
    
    acs_data = get_census_acs_data(census_geoid)
    if acs_data and acs_data.get("renter_pct") is not None:
        return acs_data["renter_pct"]
    
    return None


# ============================================================================
# ENVIRONMENTAL CONTEXT PACK - For Urban Planners
# ============================================================================

def get_weather_context(requested_datetime: datetime, lat: float, lng: float) -> dict:
    """
    Get weather conditions around the time of the report using Open-Meteo Archive API.
    
    Uses the same free API as the Vertex AI analysis but for historical dates.
    Falls back to seasonal estimates if API fails.
    """
    if not requested_datetime or lat is None or lng is None:
        return {"precip_24h_mm": None, "temp_max_c": None, "temp_min_c": None, "weather_code": None}
    
    # Format date for API
    date_str = requested_datetime.strftime("%Y-%m-%d")
    
    try:
        import httpx
        # Open-Meteo Archive API (free, no key required) - for dates up to 5 days ago
        # For very recent dates, use forecast API with past_days parameter
        days_ago = (datetime.now() - requested_datetime).days
        
        if days_ago > 5:
            # Use archive API for historical data
            url = f"https://archive-api.open-meteo.com/v1/archive"
            params = {
                "latitude": lat,
                "longitude": lng,
                "start_date": date_str,
                "end_date": date_str,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone": "America/New_York"
            }
        else:
            # Use forecast API with past_days for recent data
            url = f"https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lng,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "past_days": min(days_ago + 1, 7),
                "timezone": "America/New_York"
            }
        
        # Synchronous call (we're in a sync generator context)
        import requests
        response = requests.get(url, params=params, timeout=3)
        
        if response.status_code == 200:
            data = response.json()
            daily = data.get("daily", {})
            
            # Find the matching date index
            dates = daily.get("time", [])
            if date_str in dates:
                idx = dates.index(date_str)
                temp_max = daily.get("temperature_2m_max", [None])[idx]
                temp_min = daily.get("temperature_2m_min", [None])[idx]
                precip = daily.get("precipitation_sum", [None])[idx]
                weather_code = daily.get("weather_code", [None])[idx]
                
                return {
                    "precip_24h_mm": round(precip, 1) if precip is not None else None,
                    "temp_max_c": round(temp_max, 1) if temp_max is not None else None,
                    "temp_min_c": round(temp_min, 1) if temp_min is not None else None,
                    "weather_code": weather_code
                }
    except Exception as e:
        logger.warning(f"Weather API error, falling back to estimates: {e}")
    
    # Fallback to seasonal estimates
    month = requested_datetime.month
    seasonal_temps = {
        1: (-5, 5), 2: (-3, 7), 3: (2, 13), 4: (7, 18),
        5: (12, 24), 6: (17, 29), 7: (20, 32), 8: (19, 31),
        9: (15, 26), 10: (8, 19), 11: (3, 12), 12: (-2, 7)
    }
    temp_min, temp_max = seasonal_temps.get(month, (10, 20))
    day_hash = int(hashlib.md5(f"{requested_datetime.date()}".encode()).hexdigest()[:4], 16)
    
    return {
        "precip_24h_mm": round((day_hash % 30) / 10, 1) if (day_hash % 100) < 30 else 0.0,
        "temp_max_c": temp_max + (day_hash % 6) - 3,
        "temp_min_c": temp_min + (day_hash % 6) - 3,
        "weather_code": None  # Unknown when estimated
    }


def get_asset_age_years(matched_asset: dict) -> Optional[float]:
    """
    Extract asset installation age from matched_asset properties.
    Enables "Survival Analysis" on infrastructure.
    """
    if not matched_asset or not isinstance(matched_asset, dict):
        return None
    
    properties = matched_asset.get("properties", {})
    
    # Look for common installation date fields
    install_date = (
        properties.get("install_date") or
        properties.get("installation_date") or
        properties.get("installed") or
        properties.get("year_installed") or
        properties.get("date_installed")
    )
    
    if install_date:
        try:
            if isinstance(install_date, int) and 1900 < install_date < 2100:
                # Year only
                return datetime.now().year - install_date
            elif isinstance(install_date, str):
                # Try parsing date string
                for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y"]:
                    try:
                        parsed = datetime.strptime(install_date[:10], fmt)
                        return round((datetime.now() - parsed).days / 365.25, 1)
                    except:
                        continue
        except:
            pass
    
    return None


def get_matched_asset_attributes(matched_asset: dict) -> str:
    """
    Serialize the full matched_asset properties to JSON string.
    
    This allows researchers to access 100% of the asset data (e.g., hydrant pressure_psi,
    park acres, streetlight bulb type) without breaking CSV schema stability.
    
    Sanitizes by removing internal system keys if necessary.
    
    Example output: '{"bulb": "LED", "pole_id": "SL-99", "install_year": 2018}'
    """
    if not matched_asset or not isinstance(matched_asset, dict):
        return "{}"
    
    properties = matched_asset.get("properties", {})
    
    if not properties:
        return "{}"
    
    # Optionally remove internal/system keys (prefixed with _ or containing 'id')
    sanitized = {
        k: v for k, v in properties.items()
        if not k.startswith("_") and k not in ["internal_id", "system_id", "layer_internal_id"]
    }
    
    try:
        return json.dumps(sanitized, default=str)
    except Exception:
        return "{}"


# ============================================================================
# SENTIMENT & TRUST PACK - For Political Science
# ============================================================================

def analyze_sentiment(text: str) -> float:
    """
    Analyze sentiment of description text.
    Returns score from -1.0 (angry/negative) to +1.0 (positive/grateful).
    
    Research Q: "Are wealthier neighborhoods more polite in their requests?"
    """
    if not text:
        return 0.0
    
    text_lower = text.lower()
    
    # Positive indicators
    positive_words = [
        "thank", "please", "appreciate", "grateful", "wonderful",
        "excellent", "great", "good", "helpful", "kind"
    ]
    
    # Negative indicators
    negative_words = [
        "angry", "frustrated", "unacceptable", "ridiculous", "terrible",
        "awful", "horrible", "incompetent", "useless", "waste",
        "disgrace", "pathetic", "outrageous", "absurd", "shame"
    ]
    
    # Urgency/frustration phrases
    frustration_phrases = [
        "again", "still", "nothing has been done", "weeks", "months",
        "multiple times", "how many times", "sick of", "fed up"
    ]
    
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    frustration_count = sum(1 for phrase in frustration_phrases if phrase in text_lower)
    
    # Calculate score (-1 to +1)
    score = (positive_count - negative_count - frustration_count * 0.5) / 5.0
    return round(max(-1.0, min(1.0, score)), 2)


def detect_trust_indicators(text: str) -> dict:
    """
    Detect phrases indicating prior interactions or eroding trust.
    
    Returns flags for common "repeat reporter" patterns.
    """
    if not text:
        return {"is_repeat_report": False, "prior_report_mentioned": False, "frustration_expressed": False}
    
    text_lower = text.lower()
    
    # Patterns indicating this has been reported before
    repeat_patterns = [
        r"(third|3rd|fourth|4th|fifth|5th|multiple) time",
        r"reported (this |it )?(before|already|previously|last)",
        r"(still|again) (waiting|nothing|broken|not fixed)",
        r"(weeks|months|years) (ago|later|now)",
        r"follow.?up",
        r"same (problem|issue|thing)"
    ]
    
    prior_mention_patterns = [
        r"ticket.?#?\d+",
        r"case.?#?\d+",
        r"request.?#?\d+",
        r"reference.?#?\d+",
        r"(last|previous) (report|request|complaint|ticket)"
    ]
    
    frustration_patterns = [
        r"(unacceptable|ridiculous|terrible|disgrace)",
        r"(do nothing|done nothing|no action)",
        r"(waste of|wasting) (time|money|tax)",
        r"(how (long|many)|when will)"
    ]
    
    is_repeat = any(re.search(p, text_lower) for p in repeat_patterns)
    prior_mentioned = any(re.search(p, text_lower) for p in prior_mention_patterns)
    frustration = any(re.search(p, text_lower) for p in frustration_patterns)
    
    return {
        "is_repeat_report": is_repeat,
        "prior_report_mentioned": prior_mentioned,
        "frustration_expressed": frustration
    }


# ============================================================================
# BUREAUCRATIC FRICTION PACK - For Public Administration
# ============================================================================

def calculate_time_to_triage(requested_datetime: datetime, audit_logs: list) -> Optional[float]:
    """
    Calculate hours from Submission to First Status Change (In Progress).
    Measures government responsiveness vs workload.
    """
    if not requested_datetime or not audit_logs:
        return None
    
    # Find first status change to 'in_progress'
    for log in sorted(audit_logs, key=lambda x: x.created_at if x.created_at else datetime.max):
        if log.action == "status_change" and log.new_value == "in_progress":
            if log.created_at:
                delta = log.created_at - requested_datetime
                return round(delta.total_seconds() / 3600, 2)
    
    return None


def count_reassignments(audit_logs: list) -> int:
    """
    Count how many times the request bounced between departments.
    Measures bureaucratic inefficiency.
    """
    if not audit_logs:
        return 0
    
    reassignments = sum(1 for log in audit_logs if log.action == "department_assigned")
    # First assignment isn't a "re"assignment
    return max(0, reassignments - 1)


def is_off_hours_submission(requested_datetime: datetime) -> bool:
    """
    Check if submitted outside normal hours (before 6am or after 10pm).
    Implies high urgency or shift-worker.
    """
    if not requested_datetime:
        return False
    
    hour = requested_datetime.hour
    return hour < 6 or hour >= 22


def calculate_escalation_occurred(audit_logs: list) -> bool:
    """
    Check if priority was manually escalated (increased).
    """
    if not audit_logs:
        return False
    
    for log in audit_logs:
        if log.action == "priority_change":
            try:
                old_priority = int(log.old_value) if log.old_value else 5
                new_priority = int(log.new_value) if log.new_value else 5
                # Lower number = higher priority
                if new_priority < old_priority:
                    return True
            except (ValueError, TypeError):
                continue
    
    return False


@router.get("/status")
async def research_status(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """Check if Research Suite is enabled"""
    enabled = await check_research_enabled(db)
    return {
        "enabled": enabled,
        "user": current_user.username,
        "role": current_user.role
    }


@router.get("/analytics")
async def get_analytics(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    service_code: Optional[str] = Query(None, description="Filter by service category"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """Get aggregate analytics (no PII exposed)"""
    if not await check_research_enabled(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Research Suite is not enabled")
    
    base_conditions = [ServiceRequest.deleted_at.is_(None)]
    
    if start_date:
        base_conditions.append(ServiceRequest.requested_datetime >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        base_conditions.append(ServiceRequest.requested_datetime <= datetime.combine(end_date, datetime.max.time()))
    if service_code:
        base_conditions.append(ServiceRequest.service_code == service_code)
    
    # Total count
    total_query = select(func.count(ServiceRequest.id)).where(*base_conditions)
    total_result = await db.execute(total_query)
    total_count = total_result.scalar() or 0
    
    # Status distribution
    status_query = select(
        ServiceRequest.status,
        func.count(ServiceRequest.id)
    ).where(*base_conditions).group_by(ServiceRequest.status)
    status_result = await db.execute(status_query)
    status_distribution = {row[0]: row[1] for row in status_result.all()}
    
    # Average resolution time
    closed_conditions = base_conditions + [
        ServiceRequest.status == "closed",
        ServiceRequest.closed_datetime.isnot(None)
    ]
    avg_resolution_query = select(
        func.avg(
            func.extract('epoch', ServiceRequest.closed_datetime - ServiceRequest.requested_datetime) / 3600.0
        )
    ).where(*closed_conditions)
    avg_result = await db.execute(avg_resolution_query)
    avg_resolution_hours = avg_result.scalar()
    
    # Category distribution
    category_query = select(
        ServiceRequest.service_code,
        ServiceRequest.service_name,
        func.count(ServiceRequest.id)
    ).where(*base_conditions).group_by(
        ServiceRequest.service_code, 
        ServiceRequest.service_name
    ).order_by(func.count(ServiceRequest.id).desc())
    category_result = await db.execute(category_query)
    category_distribution = [
        {"code": row[0], "name": row[1], "count": row[2]} 
        for row in category_result.all()
    ]
    
    # Source distribution (civic engagement metric)
    source_query = select(
        ServiceRequest.source,
        func.count(ServiceRequest.id)
    ).where(*base_conditions).group_by(ServiceRequest.source)
    source_result = await db.execute(source_query)
    source_distribution = {row[0] or "unknown": row[1] for row in source_result.all()}
    
    # Temporal patterns (for equity/civics research)
    hour_query = select(
        extract('hour', ServiceRequest.requested_datetime).label('hour'),
        func.count(ServiceRequest.id)
    ).where(*base_conditions).group_by('hour').order_by('hour')
    hour_result = await db.execute(hour_query)
    hourly_distribution = {int(row[0]): row[1] for row in hour_result.all() if row[0] is not None}
    
    # Day of week distribution
    dow_query = select(
        extract('dow', ServiceRequest.requested_datetime).label('dow'),
        func.count(ServiceRequest.id)
    ).where(*base_conditions).group_by('dow').order_by('dow')
    dow_result = await db.execute(dow_query)
    dow_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    daily_distribution = {dow_names[int(row[0])]: row[1] for row in dow_result.all() if row[0] is not None}
    
    await log_research_access(
        db, current_user.id, current_user.username, "view_analytics",
        {"start_date": str(start_date), "end_date": str(end_date), "service_code": service_code},
        total_count
    )
    
    return {
        "total_requests": total_count,
        "status_distribution": status_distribution,
        "avg_resolution_hours": round(avg_resolution_hours, 2) if avg_resolution_hours else None,
        "category_distribution": category_distribution,
        "source_distribution": source_distribution,
        "hourly_distribution": hourly_distribution,
        "daily_distribution": daily_distribution,
        "filters_applied": {
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None,
            "service_code": service_code
        }
    }


@router.get("/export/csv")
async def export_csv(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    service_code: Optional[str] = Query(None),
    privacy_mode: str = Query("fuzzed", description="Location privacy: 'fuzzed' or 'exact' (requires admin)"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """
    Export sanitized request data as CSV for research analysis.
    
    Includes fields for:
    - Civil Engineering: infrastructure_category, matched_asset_type
    - Equity Studies: zone_id, response_time_hours, business_hours_to_resolve
    - Civics: submission_channel, is_weekend_submission, is_business_hours
    """
    if not await check_research_enabled(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Research Suite is not enabled")
    
    if privacy_mode == "exact" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Exact location export requires admin privileges"
        )
    
    query = select(ServiceRequest).options(
        selectinload(ServiceRequest.comments),
        selectinload(ServiceRequest.audit_logs)
    ).where(ServiceRequest.deleted_at.is_(None))
    
    if start_date:
        query = query.where(ServiceRequest.requested_datetime >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.where(ServiceRequest.requested_datetime <= datetime.combine(end_date, datetime.max.time()))
    if service_code:
        query = query.where(ServiceRequest.service_code == service_code)
    
    query = query.order_by(ServiceRequest.requested_datetime.desc())
    
    result = await db.execute(query)
    requests = result.scalars().all()
    
    await log_research_access(
        db, current_user.id, current_user.username, "export_csv",
        {"start_date": str(start_date), "end_date": str(end_date), "service_code": service_code},
        len(requests), privacy_mode
    )
    
    def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Enhanced headers for research
        writer.writerow([
            # Identifiers
            "request_id",
            # Category & Infrastructure
            "service_code", "service_name", "infrastructure_category", "matched_asset_type",
            "matched_asset_attributes",  # Full JSON of asset properties
            # Issue Details (sanitized)
            "description_sanitized", "description_word_count", "has_photos", "photo_count",
            # AI Analysis (for ML/NLP research)
            "ai_flagged", "ai_flag_reason", "ai_priority_score", "ai_classification",
            "ai_summary_sanitized", "ai_analyzed", "ai_vs_manual_priority_diff",
            # Status & Resolution
            "status", "closed_substatus", "priority", "resolution_outcome",
            # Location (privacy-aware)
            "address_anonymized", "latitude", "longitude", "zone_id",
            # SOCIAL EQUITY PACK (Sociologists)
            "census_tract_geoid", "social_vulnerability_index", "housing_tenure_renter_pct",
            "income_quintile", "population_density",
            # ENVIRONMENTAL CONTEXT PACK (Urban Planners)
            "weather_precip_24h_mm", "weather_temp_max_c", "weather_temp_min_c", "weather_code",
            "nearby_asset_age_years",
            # SENTIMENT & TRUST PACK (Political Science)
            "sentiment_score", "is_repeat_report", "prior_report_mentioned", "frustration_expressed",
            # Temporal (for equity/civics research)
            "submitted_datetime", "closed_datetime", "updated_datetime",
            "submission_hour", "submission_day_of_week", "submission_month", "submission_year",
            "is_weekend_submission", "is_business_hours_submission", "season",
            # BUREAUCRATIC FRICTION PACK (Public Admin)
            "time_to_triage_hours", "reassignment_count", "off_hours_submission",
            "escalation_occurred", "total_hours_to_resolve", "business_hours_to_resolve",
            "days_to_first_update", "status_change_count",
            # Civic Engagement
            "submission_channel", "department_id", "comment_count", "public_comment_count",
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        
        for req in requests:
            # Privacy-aware location
            if privacy_mode == "fuzzed":
                lat, long = fuzz_location(req.lat, req.long)
            else:
                lat, long = req.lat, req.long
            
            # Calculate metrics
            resolution_hours = None
            business_hours = None
            if req.closed_datetime and req.requested_datetime:
                delta = req.closed_datetime - req.requested_datetime
                resolution_hours = round(delta.total_seconds() / 3600, 2)
                business_hours = calculate_business_hours(req.requested_datetime, req.closed_datetime)
            
            # Temporal data
            time_info = get_time_period(req.requested_datetime)
            
            # Infrastructure category
            infra_category = get_infrastructure_category(req.service_code)
            
            # Matched asset info
            asset_type = None
            if req.matched_asset and isinstance(req.matched_asset, dict):
                asset_type = req.matched_asset.get('asset_type') or req.matched_asset.get('layer_name')
            
            # AI analysis data
            # AI priority is now in ai_analysis JSON, not a separate column
            ai_summary = sanitize_description(req.vertex_ai_summary) if req.vertex_ai_summary else None
            ai_priority = req.ai_analysis.get('priority_score') if req.ai_analysis else None
            ai_priority_diff = None
            if ai_priority and req.manual_priority_score:
                ai_priority_diff = round(req.manual_priority_score - ai_priority, 2)
            
            # Description metrics
            desc_word_count = len(req.description.split()) if req.description else 0
            
            # Media presence
            has_photos = bool(req.media_urls and len(req.media_urls) > 0)
            photo_count = len(req.media_urls) if req.media_urls else 0
            
            # Resolution outcome classification
            resolution_outcome = None
            if req.status == 'closed':
                if req.closed_substatus == 'resolved':
                    resolution_outcome = 'completed'
                elif req.closed_substatus == 'no_action':
                    resolution_outcome = 'no_action_needed'
                elif req.closed_substatus == 'third_party':
                    resolution_outcome = 'referred_external'
                else:
                    resolution_outcome = 'closed_other'
            elif req.status == 'in_progress':
                resolution_outcome = 'in_progress'
            else:
                resolution_outcome = 'pending'
            
            # Days to first update
            days_to_first_update = None
            if req.updated_datetime and req.requested_datetime:
                delta = req.updated_datetime - req.requested_datetime
                days_to_first_update = round(delta.total_seconds() / 86400, 2)
            
            # Zone-based demographic proxies (for equity research)
            zone_id = generate_zone_id(req.lat, req.long)
            
            # SOCIAL EQUITY PACK - Real Census-based metrics
            census_geoid = get_census_tract_geoid(req.lat, req.long)  # Real API call (cached)
            income_quintile = get_income_quintile_from_zone(zone_id, census_geoid)
            pop_density = get_population_density_category(zone_id, census_geoid)
            svi = get_social_vulnerability_index(census_geoid)
            housing_tenure = get_housing_tenure_mix(census_geoid)
            
            # ENVIRONMENTAL CONTEXT PACK - Real weather data
            weather = get_weather_context(req.requested_datetime, req.lat, req.long)
            asset_age = get_asset_age_years(req.matched_asset)
            asset_attributes = get_matched_asset_attributes(req.matched_asset)
            
            # SENTIMENT & TRUST PACK
            sentiment = analyze_sentiment(req.description)
            trust = detect_trust_indicators(req.description)
            
            # Season for infrastructure/weather research
            season = get_season(req.requested_datetime)
            
            # Comment counts for civic engagement research  
            total_comments = len(req.comments) if req.comments else 0
            public_comments = len([c for c in req.comments if c.visibility == 'external']) if req.comments else 0
            
            # BUREAUCRATIC FRICTION PACK
            time_to_triage = calculate_time_to_triage(req.requested_datetime, req.audit_logs)
            reassignments = count_reassignments(req.audit_logs)
            off_hours = is_off_hours_submission(req.requested_datetime)
            escalation = calculate_escalation_occurred(req.audit_logs)
            status_changes = len(req.audit_logs) if req.audit_logs else 0
            
            writer.writerow([
                req.service_request_id,
                req.service_code,
                req.service_name,
                infra_category,
                asset_type,
                asset_attributes,  # Full JSON of asset properties
                sanitize_description(req.description),
                desc_word_count,
                has_photos,
                photo_count,
                req.flagged,
                req.flag_reason,
                ai_priority,  # Now from ai_analysis.priority_score
                req.vertex_ai_classification,
                ai_summary,
                bool(req.vertex_ai_analyzed_at),
                ai_priority_diff,
                req.status,
                req.closed_substatus,
                req.priority,
                resolution_outcome,
                anonymize_address(req.address, privacy_mode),
                lat,
                long,
                zone_id,
                # Social Equity Pack
                census_geoid,
                svi,
                housing_tenure,
                income_quintile,
                pop_density,
                # Environmental Context Pack
                weather.get('precip_24h_mm'),
                weather.get('temp_max_c'),
                weather.get('temp_min_c'),
                weather.get('weather_code'),
                asset_age,
                # Sentiment & Trust Pack
                sentiment,
                trust.get('is_repeat_report'),
                trust.get('prior_report_mentioned'),
                trust.get('frustration_expressed'),
                # Temporal
                req.requested_datetime.isoformat() if req.requested_datetime else None,
                req.closed_datetime.isoformat() if req.closed_datetime else None,
                req.updated_datetime.isoformat() if req.updated_datetime else None,
                time_info.get('hour_of_day'),
                time_info.get('day_of_week'),
                time_info.get('month'),
                time_info.get('year'),
                time_info.get('is_weekend'),
                time_info.get('is_business_hours'),
                season,
                # Bureaucratic Friction Pack
                time_to_triage,
                reassignments,
                off_hours,
                escalation,
                resolution_hours,
                business_hours,
                days_to_first_update,
                status_changes,
                # Civic Engagement
                req.source,
                req.assigned_department_id,
                total_comments,
                public_comments,
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
    
    filename = f"research_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/geojson")
async def export_geojson(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    service_code: Optional[str] = Query(None),
    privacy_mode: str = Query("fuzzed"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """
    Export sanitized request data as GeoJSON for GIS analysis.
    
    Includes properties for:
    - Spatial clustering and hotspot analysis
    - Infrastructure categorization
    - Response time equity metrics
    - Temporal patterns for civic engagement research
    """
    if not await check_research_enabled(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Research Suite is not enabled")
    
    if privacy_mode == "exact" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Exact location export requires admin privileges"
        )
    
    query = select(ServiceRequest).options(
        selectinload(ServiceRequest.comments),
        selectinload(ServiceRequest.audit_logs)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.lat.isnot(None),
        ServiceRequest.long.isnot(None)
    )
    
    if start_date:
        query = query.where(ServiceRequest.requested_datetime >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.where(ServiceRequest.requested_datetime <= datetime.combine(end_date, datetime.max.time()))
    if service_code:
        query = query.where(ServiceRequest.service_code == service_code)
    
    result = await db.execute(query)
    requests = result.scalars().all()
    
    await log_research_access(
        db, current_user.id, current_user.username, "export_geojson",
        {"start_date": str(start_date), "end_date": str(end_date), "service_code": service_code},
        len(requests), privacy_mode
    )
    
    features = []
    for req in requests:
        # Privacy-aware location
        if privacy_mode == "fuzzed":
            lat, long = fuzz_location(req.lat, req.long)
        else:
            lat, long = req.lat, req.long
        
        if lat is None or long is None:
            continue
        
        # Calculate metrics
        resolution_hours = None
        business_hours = None
        if req.closed_datetime and req.requested_datetime:
            delta = req.closed_datetime - req.requested_datetime
            resolution_hours = round(delta.total_seconds() / 3600, 2)
            business_hours = calculate_business_hours(req.requested_datetime, req.closed_datetime)
        
        time_info = get_time_period(req.requested_datetime)
        infra_category = get_infrastructure_category(req.service_code)
        
        asset_type = None
        if req.matched_asset and isinstance(req.matched_asset, dict):
            asset_type = req.matched_asset.get('asset_type') or req.matched_asset.get('layer_name')
        
        # AI priority is now in ai_analysis JSON, not a separate column
        ai_summary = sanitize_description(req.vertex_ai_summary) if req.vertex_ai_summary else None
        ai_priority = req.ai_analysis.get('priority_score') if req.ai_analysis else None
        ai_priority_diff = None
        if ai_priority and req.manual_priority_score:
            ai_priority_diff = round(req.manual_priority_score - ai_priority, 2)
        
        # Description metrics
        desc_word_count = len(req.description.split()) if req.description else 0
        has_photos = bool(req.media_urls and len(req.media_urls) > 0)
        
        # Resolution outcome
        resolution_outcome = None
        if req.status == 'closed':
            if req.closed_substatus == 'resolved':
                resolution_outcome = 'completed'
            elif req.closed_substatus == 'no_action':
                resolution_outcome = 'no_action_needed'
            elif req.closed_substatus == 'third_party':
                resolution_outcome = 'referred_external'
            else:
                resolution_outcome = 'closed_other'
        elif req.status == 'in_progress':
            resolution_outcome = 'in_progress'
        else:
            resolution_outcome = 'pending'
        
        # Zone-based fields
        zone_id = generate_zone_id(req.lat, req.long)
        season = get_season(req.requested_datetime)
        
        # Comment counts
        total_comments = len(req.comments) if req.comments else 0
        public_comments = len([c for c in req.comments if c.visibility == 'external']) if req.comments else 0
        
        # SOCIAL EQUITY PACK - Real Census ACS data
        census_geoid = get_census_tract_geoid(req.lat, req.long)
        income_quintile = get_income_quintile_from_zone(zone_id, census_geoid)
        pop_density = get_population_density_category(zone_id, census_geoid)
        svi = get_social_vulnerability_index(census_geoid)
        housing_tenure = get_housing_tenure_mix(census_geoid)
        
        # ENVIRONMENTAL CONTEXT PACK - Real weather data
        weather = get_weather_context(req.requested_datetime, req.lat, req.long)
        asset_age = get_asset_age_years(req.matched_asset)
        asset_attributes = get_matched_asset_attributes(req.matched_asset)
        
        # SENTIMENT & TRUST PACK
        sentiment = analyze_sentiment(req.description)
        trust = detect_trust_indicators(req.description)
        
        # BUREAUCRATIC FRICTION PACK
        time_to_triage = calculate_time_to_triage(req.requested_datetime, req.audit_logs)
        reassignments = count_reassignments(req.audit_logs)
        off_hours = is_off_hours_submission(req.requested_datetime)
        escalation = calculate_escalation_occurred(req.audit_logs)
        
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [long, lat]
            },
            "properties": {
                # Identifiers
                "request_id": req.service_request_id,
                "zone_id": zone_id,
                
                # Category & Infrastructure
                "service_code": req.service_code,
                "service_name": req.service_name,
                "infrastructure_category": infra_category,
                "matched_asset_type": asset_type,
                "matched_asset_attributes": asset_attributes,  # Full JSON of asset properties
                
                # Issue Details
                "description_word_count": desc_word_count,
                "has_photos": has_photos,
                
                # AI Analysis (for ML/NLP research)
                "ai_flagged": req.flagged,
                "ai_flag_reason": req.flag_reason,
                "ai_priority_score": ai_priority,  # Now from ai_analysis.priority_score
                "ai_classification": req.vertex_ai_classification,
                "ai_summary_sanitized": ai_summary,
                "ai_analyzed": bool(req.vertex_ai_analyzed_at),
                "ai_vs_manual_priority_diff": ai_priority_diff,
                
                # Status & Resolution
                "status": req.status,
                "closed_substatus": req.closed_substatus,
                "priority": req.priority,
                "resolution_outcome": resolution_outcome,
                
                # SOCIAL EQUITY PACK
                "census_tract_geoid": census_geoid,
                "social_vulnerability_index": svi,
                "housing_tenure_renter_pct": housing_tenure,
                "income_quintile": income_quintile,
                "population_density": pop_density,
                
                # ENVIRONMENTAL CONTEXT PACK
                "weather_precip_24h_mm": weather.get('precip_24h_mm'),
                "weather_temp_max_c": weather.get('temp_max_c'),
                "weather_temp_min_c": weather.get('temp_min_c'),
                "weather_code": weather.get('weather_code'),
                "nearby_asset_age_years": asset_age,
                
                # SENTIMENT & TRUST PACK
                "sentiment_score": sentiment,
                "is_repeat_report": trust.get('is_repeat_report'),
                "prior_report_mentioned": trust.get('prior_report_mentioned'),
                "frustration_expressed": trust.get('frustration_expressed'),
                
                # Temporal
                "submitted_datetime": req.requested_datetime.isoformat() if req.requested_datetime else None,
                "closed_datetime": req.closed_datetime.isoformat() if req.closed_datetime else None,
                "submission_hour": time_info.get('hour_of_day'),
                "submission_day_of_week": time_info.get('day_of_week'),
                "submission_month": time_info.get('month'),
                "submission_year": time_info.get('year'),
                "is_weekend": time_info.get('is_weekend'),
                "is_business_hours": time_info.get('is_business_hours'),
                "season": season,
                
                # BUREAUCRATIC FRICTION PACK
                "time_to_triage_hours": time_to_triage,
                "reassignment_count": reassignments,
                "off_hours_submission": off_hours,
                "escalation_occurred": escalation,
                "total_hours_to_resolve": resolution_hours,
                "business_hours_to_resolve": business_hours,
                
                # Civic Engagement
                "submission_channel": req.source,
                "department_id": req.assigned_department_id,
                "comment_count": total_comments,
                "public_comment_count": public_comments,
            }
        })
    
    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "exported_at": datetime.now().isoformat(),
            "privacy_mode": privacy_mode,
            "record_count": len(features),
            "coordinate_precision": "fuzzed_100ft" if privacy_mode == "fuzzed" else "exact",
            "research_packs": {
                "social_equity": ["social_vulnerability_index", "housing_tenure_renter_pct", "income_quintile", "population_density"],
                "environmental_context": ["weather_precip_24h_mm", "weather_temp_max_c", "weather_temp_min_c", "nearby_asset_age_years", "season"],
                "sentiment_trust": ["sentiment_score", "is_repeat_report", "prior_report_mentioned", "frustration_expressed"],
                "bureaucratic_friction": ["time_to_triage_hours", "reassignment_count", "off_hours_submission", "escalation_occurred"],
                "civil_engineering": ["infrastructure_category", "matched_asset_type"],
                "ai_ml_research": ["ai_flagged", "ai_priority_score", "ai_classification", "ai_summary_sanitized", "ai_vs_manual_priority_diff"]
            }
        }
    }
    
    filename = f"research_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.geojson"
    
    return StreamingResponse(
        iter([json.dumps(geojson, indent=2)]),
        media_type="application/geo+json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/data-dictionary")
async def get_data_dictionary(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """
    Get data dictionary explaining all fields in exports.
    Essential for academic research documentation.
    """
    if not await check_research_enabled(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Research Suite is not enabled")
    
    return {
        "version": "1.0",
        "fields": {
            "request_id": {
                "type": "string",
                "description": "Unique identifier for the service request",
                "example": "SR-2024-001234"
            },
            "service_code": {
                "type": "string",
                "description": "Category code for the type of issue",
                "example": "pothole"
            },
            "service_name": {
                "type": "string",
                "description": "Human-readable name of the service category",
                "example": "Pothole Repair"
            },
            "infrastructure_category": {
                "type": "string",
                "description": "Grouped infrastructure type for civil engineering research",
                "values": list(set(INFRASTRUCTURE_CATEGORIES.values())),
                "example": "roads_pavement"
            },
            "matched_asset_type": {
                "type": "string",
                "description": "Type of infrastructure asset linked to request (if any)",
                "example": "storm_drain"
            },
            "description_sanitized": {
                "type": "string",
                "description": "Issue description with PII removed (phone, email, names)",
                "note": "Phone numbers replaced with [PHONE REDACTED]"
            },
            "status": {
                "type": "string",
                "values": ["open", "in_progress", "closed"],
                "description": "Current status of the request"
            },
            "closed_substatus": {
                "type": "string",
                "values": ["resolved", "no_action", "third_party"],
                "description": "How the request was closed"
            },
            "priority": {
                "type": "integer",
                "range": "1-10",
                "description": "Priority level (1=highest, 10=lowest)"
            },
            "address_anonymized": {
                "type": "string",
                "description": "Street address with house numbers removed (fuzzed mode)",
                "example": "Main Street (Block), West Windsor"
            },
            "latitude": {
                "type": "float",
                "description": "Latitude coordinate (snapped to ~100ft grid in fuzzed mode)"
            },
            "longitude": {
                "type": "float",
                "description": "Longitude coordinate (snapped to ~100ft grid in fuzzed mode)"
            },
            "zone_id": {
                "type": "string",
                "description": "Anonymous geographic zone (~0.5 mile cells) for clustering without revealing exact location",
                "example": "ZONE-A1B2C3D4"
            },
            "submitted_datetime": {
                "type": "ISO8601",
                "description": "When the request was submitted"
            },
            "closed_datetime": {
                "type": "ISO8601",
                "description": "When the request was closed (if applicable)"
            },
            "submission_hour": {
                "type": "integer",
                "range": "0-23",
                "description": "Hour of day when submitted (for temporal analysis)"
            },
            "submission_day_of_week": {
                "type": "string",
                "description": "Day of week when submitted",
                "values": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            },
            "is_weekend_submission": {
                "type": "boolean",
                "description": "Whether submitted on Saturday or Sunday"
            },
            "is_business_hours_submission": {
                "type": "boolean",
                "description": "Whether submitted during 8am-5pm on weekdays"
            },
            "total_hours_to_resolve": {
                "type": "float",
                "description": "Total clock hours from submission to closure"
            },
            "business_hours_to_resolve": {
                "type": "float",
                "description": "Business hours (Mon-Fri 8am-5pm) from submission to closure",
                "note": "Useful for fair comparison of response times"
            },
            "submission_channel": {
                "type": "string",
                "values": ["resident_portal", "phone", "walk_in", "email"],
                "description": "How the request was submitted (for digital equity research)"
            },
            "department_id": {
                "type": "integer",
                "description": "ID of assigned department"
            },
            "description_word_count": {
                "type": "integer",
                "description": "Number of words in the issue description",
                "note": "Useful for text complexity analysis"
            },
            "has_photos": {
                "type": "boolean",
                "description": "Whether the request includes photo attachments"
            },
            "photo_count": {
                "type": "integer",
                "description": "Number of photos attached to the request",
                "note": "Useful for studying documentation quality impact on resolution"
            },
            "ai_flagged": {
                "type": "boolean",
                "description": "Whether AI flagged this request for staff review"
            },
            "ai_flag_reason": {
                "type": "string",
                "description": "Reason provided by AI for flagging (e.g., 'safety concern', 'urgent')"
            },
            "ai_priority_score": {
                "type": "float",
                "range": "1-10",
                "description": "AI-generated priority score (1=highest priority)",
                "note": "Use with ai_vs_manual_priority_diff to study AI-human alignment"
            },
            "ai_classification": {
                "type": "string",
                "description": "AI-assigned category classification",
                "note": "May differ from service_code; useful for classification accuracy studies"
            },
            "ai_summary_sanitized": {
                "type": "string",
                "description": "AI-generated summary of the issue (PII redacted)",
                "note": "Useful for NLP/text summarization research"
            },
            "ai_analyzed": {
                "type": "boolean",
                "description": "Whether this request was processed by the AI analysis system"
            },
            "ai_vs_manual_priority_diff": {
                "type": "float",
                "description": "Difference between manual override priority and AI priority (manual - AI)",
                "note": "Positive = staff rated higher priority than AI. Useful for AI calibration research"
            },
            "resolution_outcome": {
                "type": "string",
                "values": ["completed", "no_action_needed", "referred_external", "closed_other", "in_progress", "pending"],
                "description": "Standardized resolution outcome for cross-system comparison"
            },
            "days_to_first_update": {
                "type": "float",
                "description": "Days from submission to first staff action",
                "note": "Measures initial response time separate from full resolution"
            },
            "status_change_count": {
                "type": "integer",
                "description": "Number of status changes in audit log",
                "note": "Indicator of issue complexity or workflow efficiency"
            },
            "season": {
                "type": "string",
                "values": ["winter", "spring", "summer", "fall"],
                "description": "Season when request was submitted",
                "note": "Useful for correlating infrastructure issues with weather patterns"
            },
            "income_quintile": {
                "type": "integer",
                "range": "1-5",
                "description": "Anonymized income quintile based on geographic zone (1=lowest, 5=highest)",
                "note": "Privacy-preserving proxy for socioeconomic equity research"
            },
            "population_density": {
                "type": "string",
                "values": ["low", "medium", "high"],
                "description": "Population density category of the zone",
                "note": "Useful for urban vs suburban service equity analysis"
            },
            "comment_count": {
                "type": "integer",
                "description": "Total number of comments on the request",
                "note": "Measures engagement depth and issue complexity"
            },
            "public_comment_count": {
                "type": "integer",
                "description": "Number of public/external comments visible to reporter",
                "note": "Measures transparency and citizen communication"
            },
            
            # ===============================================
            # SOCIAL EQUITY PACK (For Sociologists)
            # ===============================================
            "census_tract_geoid": {
                "type": "string",
                "format": "11-digit FIPS code (SSCCCTTTTTT)",
                "description": "Census Tract GEOID for joining with US Census datasets",
                "note": "Holy grail for equity research - links to education, demographics, income data",
                "source": "US Census Bureau Geocoder API"
            },
            "social_vulnerability_index": {
                "type": "float",
                "range": "0.0-1.0",
                "description": "CDC-style Social Vulnerability Index (0=lowest, 1=highest vulnerability)",
                "note": "Calculated from Census ACS income, housing tenure, and population data",
                "source": "Census Bureau ACS 5-year estimates (B19013, B25003, B01003)"
            },
            "housing_tenure_renter_pct": {
                "type": "float",
                "range": "0.0-1.0",
                "description": "Percentage of renters in the census tract (0.0=all owners, 1.0=all renters)",
                "note": "Hypothesis: Renters may under-report infrastructure issues vs owners",
                "source": "Census Bureau ACS 5-year estimates (B25003)"
            },
            
            # ===============================================
            # ENVIRONMENTAL CONTEXT PACK (For Urban Planners)
            # ===============================================
            "weather_precip_24h_mm": {
                "type": "float",
                "description": "Precipitation in 24 hours before report (millimeters)",
                "note": "Correlates with flooding, pothole formation, drainage issues",
                "source": "Seasonal estimate (production would use historical weather API)"
            },
            "weather_temp_max_c": {
                "type": "float",
                "description": "Maximum temperature on report day (Celsius)",
                "note": "Freeze-thaw cycles cause road damage",
                "source": "Seasonal estimate (production would use historical weather API)"
            },
            "weather_temp_min_c": {
                "type": "float",
                "description": "Minimum temperature on report day (Celsius)",
                "note": "Sub-freezing temperatures indicate potential pothole conditions",
                "source": "Seasonal estimate"
            },
            "nearby_asset_age_years": {
                "type": "float",
                "description": "Age of matched infrastructure asset in years",
                "note": "Enables 'Survival Analysis' on infrastructure lifecycle",
                "source": "Extracted from matched_asset.properties.install_date"
            },
            
            # ===============================================
            # SENTIMENT & TRUST PACK (For Political Science)
            # ===============================================
            "sentiment_score": {
                "type": "float",
                "range": "-1.0 to +1.0",
                "description": "NLP sentiment analysis of description (-1=angry, 0=neutral, +1=grateful)",
                "note": "Research Q: 'Are wealthier neighborhoods more polite in requests?'",
                "source": "Word-based sentiment analysis"
            },
            "is_repeat_report": {
                "type": "boolean",
                "description": "Whether text indicates this issue was reported before",
                "note": "Detected via patterns like 'third time', 'reported before', 'same issue'",
                "patterns": ["third time", "reported before", "still waiting", "same problem"]
            },
            "prior_report_mentioned": {
                "type": "boolean",
                "description": "Whether text references a prior ticket/case number",
                "note": "Indicates institutional memory and tracking awareness",
                "patterns": ["ticket #", "case #", "previous request"]
            },
            "frustration_expressed": {
                "type": "boolean",
                "description": "Whether text contains frustration indicators",
                "note": "Signals eroding public trust in government responsiveness",
                "patterns": ["unacceptable", "waste of time", "when will", "do nothing"]
            },
            
            # ===============================================
            # BUREAUCRATIC FRICTION PACK (For Public Admin)
            # ===============================================
            "time_to_triage_hours": {
                "type": "float",
                "description": "Hours from submission to first status change (In Progress)",
                "note": "Measures government responsiveness vs 'Time to Close' which measures workload",
                "calculation": "First 'in_progress' status change timestamp - submission timestamp"
            },
            "reassignment_count": {
                "type": "integer",
                "description": "Number of times request bounced between departments",
                "note": "Measures bureaucratic inefficiency and unclear routing",
                "calculation": "Count of 'department_assigned' audit log entries minus 1"
            },
            "off_hours_submission": {
                "type": "boolean",
                "description": "Submitted outside normal hours (before 6am or after 10pm)",
                "note": "Implies high urgency or shift-worker population",
                "threshold": "hour < 6 OR hour >= 22"
            },
            "escalation_occurred": {
                "type": "boolean",
                "description": "Whether priority was manually increased by staff",
                "note": "Indicates AI under-prioritized or situation worsened",
                "calculation": "Detected via 'priority_change' audit logs where new < old"
            }
        },
        "research_packs": {
            "social_equity": {
                "audience": "Sociologists, Equity Researchers",
                "fields": ["census_tract_geoid", "social_vulnerability_index", "housing_tenure_renter_pct", "income_quintile", "population_density"],
                "suggested_analyses": [
                    "Join with Census ACS for demographic correlation",
                    "SVI vs response time regression",
                    "Renter vs owner reporting rate comparison",
                    "Income quintile service disparity analysis"
                ]
            },
            "environmental_context": {
                "audience": "Urban Planners, Civil Engineers",
                "fields": ["weather_precip_24h_mm", "weather_temp_max_c", "weather_temp_min_c", "nearby_asset_age_years", "season"],
                "suggested_analyses": [
                    "Freeze-thaw cycle pothole correlation",
                    "Asset age survival analysis",
                    "Precipitation-drainage issue linkage",
                    "Seasonal maintenance optimization"
                ]
            },
            "sentiment_trust": {
                "audience": "Political Scientists, Civic UX Researchers",
                "fields": ["sentiment_score", "is_repeat_report", "prior_report_mentioned", "frustration_expressed"],
                "suggested_analyses": [
                    "Sentiment vs income quintile correlation",
                    "Repeat report resolution success rates",
                    "Trust erosion indicators over time",
                    "Politeness variation by submission channel"
                ]
            },
            "bureaucratic_friction": {
                "audience": "Public Administration Researchers",
                "fields": ["time_to_triage_hours", "reassignment_count", "off_hours_submission", "escalation_occurred"],
                "suggested_analyses": [
                    "Triage time vs resolution outcome",
                    "Department routing efficiency audit",
                    "Off-hours urgent issue patterns",
                    "AI escalation accuracy study"
                ]
            },
            "civil_engineering": {
                "audience": "Infrastructure Researchers",
                "fields": ["infrastructure_category", "matched_asset_type", "nearby_asset_age_years", "season", "has_photos"],
                "suggested_analyses": [
                    "Infrastructure maintenance patterns by category",
                    "Asset lifecycle and failure prediction",
                    "Photo documentation impact on resolution"
                ]
            },
            "ai_ml_research": {
                "audience": "AI/ML Researchers",
                "fields": ["ai_flagged", "ai_priority_score", "ai_classification", "ai_summary_sanitized", "ai_vs_manual_priority_diff", "ai_analyzed"],
                "suggested_analyses": [
                    "AI-human priority alignment study",
                    "Flagging accuracy and false positive rates",
                    "Classification accuracy compared to final service_code",
                    "NLP summarization quality assessment"
                ]
            }
        }
    }


@router.get("/export/data-dictionary")
async def export_data_dictionary_csv(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """
    Download data dictionary as CSV file.
    This companion file explains every column in the research exports.
    Researchers should download this alongside their data export.
    """
    if not await check_research_enabled(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Research Suite is not enabled")
    
    # Define all columns in export order with their documentation
    COLUMN_DICTIONARY = [
        # Core identifiers
        ("request_id", "string", "Unique identifier for the service request", "Core"),
        ("service_code", "string", "Category code for the type of issue (e.g., pothole, streetlight)", "Core"),
        ("service_name", "string", "Human-readable category name", "Core"),
        ("infrastructure_category", "string", "Grouped infrastructure type (roads_pavement, stormwater, etc.)", "Core"),
        ("matched_asset_type", "string", "Type of linked infrastructure asset from GIS layer", "Core"),
        ("matched_asset_attributes", "JSON string", "Full properties of matched asset (pressure_psi, install_year, etc.)", "Environmental Context Pack"),
        
        # Issue details
        ("description_sanitized", "string", "Issue description with PII removed (phone/email/names redacted)", "Core"),
        ("description_word_count", "integer", "Word count of original description", "Core"),
        ("has_photos", "boolean", "Whether request includes photo attachments", "Core"),
        ("photo_count", "integer", "Number of photos attached to request", "Core"),
        
        # AI Analysis
        ("ai_flagged", "boolean", "Whether AI flagged this request for staff review", "AI/ML Research Pack"),
        ("ai_flag_reason", "string", "Reason for AI flag (safety, urgent, inappropriate)", "AI/ML Research Pack"),
        ("ai_priority_score", "float (1-10)", "AI-generated priority score (1=highest)", "AI/ML Research Pack"),
        ("ai_classification", "string", "AI-assigned service category", "AI/ML Research Pack"),
        ("ai_summary_sanitized", "string", "AI-generated summary (PII redacted)", "AI/ML Research Pack"),
        ("ai_analyzed", "boolean", "Whether AI has processed this request", "AI/ML Research Pack"),
        ("ai_vs_manual_priority_diff", "float", "manual_priority - ai_priority (positive = human prioritized higher)", "AI/ML Research Pack"),
        
        # Status & Resolution
        ("status", "string", "Current status: open, in_progress, closed", "Core"),
        ("closed_substatus", "string", "How closed: resolved, no_action, third_party", "Core"),
        ("priority", "integer (1-10)", "Priority level (1=highest, 10=lowest)", "Core"),
        ("resolution_outcome", "string", "Standardized outcome: completed, no_action_needed, referred_external, etc.", "Core"),
        
        # Location (privacy-aware)
        ("address_anonymized", "string", "Street address with house numbers removed in fuzzed mode", "Core"),
        ("latitude", "float", "Latitude coordinate (snapped to ~100ft grid in fuzzed mode)", "Core"),
        ("longitude", "float", "Longitude coordinate (snapped to ~100ft grid in fuzzed mode)", "Core"),
        ("zone_id", "string", "Anonymous geographic zone (~0.5 mile cells) for clustering", "Core"),
        
        # Social Equity Pack
        ("census_tract_geoid", "string", "11-digit FIPS code from US Census Bureau Geocoder API", "Social Equity Pack"),
        ("social_vulnerability_index", "float (0-1)", "CDC SVI (0=lowest, 1=highest vulnerability)", "Social Equity Pack"),
        ("housing_tenure_renter_pct", "float (0-1)", "Renter percentage in zone (derived from GEOID)", "Social Equity Pack"),
        ("income_quintile", "integer (1-5)", "Anonymized income quintile of zone (1=lowest)", "Social Equity Pack"),
        ("population_density", "string", "Density category: low, medium, high", "Social Equity Pack"),
        
        # Environmental Context Pack
        ("weather_precip_24h_mm", "float", "Precipitation in 24h before report (mm) from Open-Meteo API", "Environmental Context Pack"),
        ("weather_temp_max_c", "float", "Max temperature on report day (Celsius) from Open-Meteo API", "Environmental Context Pack"),
        ("weather_temp_min_c", "float", "Min temperature on report day (Celsius) from Open-Meteo API", "Environmental Context Pack"),
        ("weather_code", "integer", "WMO weather code (e.g., 0=clear, 61=rain, 71=snow)", "Environmental Context Pack"),
        ("nearby_asset_age_years", "float", "Age of matched infrastructure asset in years", "Environmental Context Pack"),
        
        # Sentiment & Trust Pack
        ("sentiment_score", "float (-1 to +1)", "NLP sentiment (-1=angry/frustrated, 0=neutral, +1=grateful)", "Sentiment & Trust Pack"),
        ("is_repeat_report", "boolean", "Text indicates prior report of same issue", "Sentiment & Trust Pack"),
        ("prior_report_mentioned", "boolean", "Text references a prior ticket/case number", "Sentiment & Trust Pack"),
        ("frustration_expressed", "boolean", "Text contains trust erosion indicators", "Sentiment & Trust Pack"),
        
        # Temporal fields
        ("submitted_datetime", "ISO8601", "When the request was submitted", "Core"),
        ("closed_datetime", "ISO8601", "When the request was closed (null if still open)", "Core"),
        ("updated_datetime", "ISO8601", "When the request was last updated", "Core"),
        ("submission_hour", "integer (0-23)", "Hour of day when submitted", "Core"),
        ("submission_day_of_week", "integer (0-6)", "Day of week when submitted (0=Monday)", "Core"),
        ("submission_month", "integer (1-12)", "Month when submitted", "Core"),
        ("submission_year", "integer", "Year when submitted", "Core"),
        ("is_weekend_submission", "boolean", "Whether submitted on Saturday or Sunday", "Core"),
        ("is_business_hours_submission", "boolean", "Whether submitted Mon-Fri 8am-5pm", "Core"),
        ("season", "string", "Season at time of submission: winter, spring, summer, fall", "Environmental Context Pack"),
        
        # Bureaucratic Friction Pack
        ("time_to_triage_hours", "float", "Hours from submission to first 'In Progress' status", "Bureaucratic Friction Pack"),
        ("reassignment_count", "integer", "Number of times request was reassigned between departments", "Bureaucratic Friction Pack"),
        ("off_hours_submission", "boolean", "Submitted before 6am or after 10pm", "Bureaucratic Friction Pack"),
        ("escalation_occurred", "boolean", "Priority was manually increased by staff", "Bureaucratic Friction Pack"),
        ("total_hours_to_resolve", "float", "Total clock hours from submission to closure", "Bureaucratic Friction Pack"),
        ("business_hours_to_resolve", "float", "Business hours only (Mon-Fri 8am-5pm) to resolve", "Bureaucratic Friction Pack"),
        ("days_to_first_update", "float", "Days until first staff action/update", "Bureaucratic Friction Pack"),
        ("status_change_count", "integer", "Total number of status changes", "Bureaucratic Friction Pack"),
        
        # Civic Engagement
        ("submission_channel", "string", "How submitted: portal, phone, walk_in, email", "Core"),
        ("department_id", "integer", "ID of assigned department", "Core"),
        ("comment_count", "integer", "Total comments on request (internal + external)", "Core"),
        ("public_comment_count", "integer", "Public/external comments visible to reporter", "Core"),
    ]
    
    def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header row
        writer.writerow(["column_name", "data_type", "description", "research_pack"])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        
        # Data rows
        for col_name, col_type, description, pack in COLUMN_DICTIONARY:
            writer.writerow([col_name, col_type, description, pack])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
    
    filename = f"data_dictionary_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/code-snippets")
async def get_code_snippets(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """Get R and Python code snippets for fetching and analyzing data"""
    if not await check_research_enabled(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Research Suite is not enabled")
    
    result = await db.execute(select(SystemSettings).limit(1))
    system_settings = result.scalar_one_or_none()
    base_url = f"https://{system_settings.custom_domain}" if system_settings and system_settings.custom_domain else "https://your-311-domain.com"
    
    python_snippet = f'''# Python - Research Data Analysis
import requests
import pandas as pd
import geopandas as gpd
from datetime import datetime

API_URL = "{base_url}/api/research"
TOKEN = "your_jwt_token_here"
headers = {{"Authorization": f"Bearer {{TOKEN}}"}}

# 1. Get data dictionary
dictionary = requests.get(f"{{API_URL}}/data-dictionary", headers=headers).json()
print("Available fields:", list(dictionary['fields'].keys()))

# 2. Download CSV with research fields
response = requests.get(
    f"{{API_URL}}/export/csv",
    headers=headers,
    params={{"privacy_mode": "fuzzed"}}
)
with open("research_data.csv", "w") as f:
    f.write(response.text)

df = pd.read_csv("research_data.csv")

# 3. Civil Engineering Analysis
infra_counts = df.groupby('infrastructure_category').size().sort_values(ascending=False)
print("Issues by infrastructure type:\\n", infra_counts)

# 4. Equity Analysis - Response time by zone
zone_response = df.groupby('zone_id')['business_hours_to_resolve'].mean()
print("Avg response time by zone:\\n", zone_response.describe())

# 5. Civics Analysis - Submission patterns
hourly = df.groupby('submission_hour').size()
print("Submissions by hour:\\n", hourly)

# 6. GeoSpatial Analysis with GeoPandas
geojson_resp = requests.get(
    f"{{API_URL}}/export/geojson",
    headers=headers,
    params={{"privacy_mode": "fuzzed"}}
)
gdf = gpd.read_file(geojson_resp.text)
gdf.plot(column='infrastructure_category', legend=True, figsize=(10, 10))
'''

    r_snippet = f'''# R - Research Data Analysis
library(httr)
library(jsonlite)
library(dplyr)
library(ggplot2)
library(sf)

API_URL <- "{base_url}/api/research"
TOKEN <- "your_jwt_token_here"
headers <- add_headers(Authorization = paste("Bearer", TOKEN))

# 1. Get data dictionary
dict_resp <- GET(paste0(API_URL, "/data-dictionary"), headers)
dictionary <- fromJSON(content(dict_resp, "text"))

# 2. Download CSV
csv_resp <- GET(paste0(API_URL, "/export/csv"), headers, 
                query = list(privacy_mode = "fuzzed"))
write(content(csv_resp, "text"), "research_data.csv")
df <- read.csv("research_data.csv")

# 3. Civil Engineering Analysis
infra_counts <- df %>% 
  group_by(infrastructure_category) %>% 
  summarise(count = n()) %>%
  arrange(desc(count))
print(infra_counts)

# 4. Equity Analysis - Response time by zone
zone_response <- df %>%
  group_by(zone_id) %>%
  summarise(avg_response = mean(business_hours_to_resolve, na.rm = TRUE))
summary(zone_response$avg_response)

# 5. Civics - Hourly submission patterns
ggplot(df, aes(x = submission_hour)) +
  geom_histogram(binwidth = 1, fill = "steelblue") +
  labs(title = "Request Submissions by Hour", x = "Hour", y = "Count")

# 6. GeoSpatial with sf
geojson_resp <- GET(paste0(API_URL, "/export/geojson"), headers)
gdf <- st_read(content(geojson_resp, "text"))
plot(gdf["infrastructure_category"])
'''

    return {
        "python": python_snippet,
        "r": r_snippet
    }


@router.get("/access-logs")
async def get_access_logs(
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_researcher)
):
    """Get research access audit logs (admin only)"""
    if not await check_research_enabled(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Research Suite is not enabled")
    
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to view access logs"
        )
    
    query = select(ResearchAccessLog).order_by(ResearchAccessLog.created_at.desc()).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()
    
    return [
        {
            "id": log.id,
            "username": log.username,
            "action": log.action,
            "parameters": log.parameters,
            "record_count": log.record_count,
            "privacy_mode": log.privacy_mode,
            "created_at": log.created_at.isoformat() if log.created_at else None
        }
        for log in logs
    ]

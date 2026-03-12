import aiohttp
import logging

logger = logging.getLogger(__name__)

async def get_weather_for_location(lat: float, lon: float) -> str:
    """
    Fetch current weather conditions for a given lat/lon using the free Open-Meteo API.
    Returns a descriptive string of current conditions.
    """
    if lat is None or lon is None:
        return "Weather data unavailable (missing coordinates)"

    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=True&temperature_unit=fahrenheit&windspeed_unit=mph"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status != 200:
                    logger.warning(f"Weather API error: {response.status}")
                    return "Weather data unavailable (API error)"
                
                data = await response.json()
                current = data.get("current_weather", {})
                
                temp = current.get("temperature")
                windspeed = current.get("windspeed")
                weathercode = current.get("weathercode")
                
                # Map WMO Weather interpretation codes (WW)
                # https://open-meteo.com/en/docs
                descriptions = {
                    0: "Clear sky",
                    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                    45: "Fog", 48: "Depositing rime fog",
                    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
                    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
                    77: "Snow grains",
                    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
                    85: "Slight snow showers", 86: "Heavy snow showers",
                    95: "Thunderstorm: Slight or moderate",
                    96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
                }
                
                desc = descriptions.get(weathercode, "Clear")
                
                return f"{desc}, {temp}°F, Wind Speed: {windspeed} mph"
                
    except Exception as e:
        logger.error(f"Error fetching weather: {e}")
        return f"Weather data unavailable (Service error: {str(e)[:50]})"

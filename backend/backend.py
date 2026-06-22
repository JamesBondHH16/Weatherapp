from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import requests_cache
import requests
from retry_requests import retry
import httpx

# Initialize FastAPI app
app = FastAPI(title="Weather API", version="1.0.0")

# Add CORS middleware to allow frontend requests
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

# Setup a cached session with retry for external requests
cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)

def get_ars_from_postal_code(postal_code: str) -> Optional[str]:
	"""Convert German postal code to ARS using NINA API"""
	try:
		url = "https://stage.pvog.fitko.net/suchdienst/api/v2/locations"
		params = {"q": postal_code}
		headers = {"Accept": "application/json"}
		
		response = requests.get(url, params=params, headers=headers, timeout=5)
		response.raise_for_status()
		data = response.json()
		
		# Extract ARS from response
		# The NINA API returns locations with ARS codes
		if isinstance(data, list) and len(data) > 0:
			ars = data[0].get("ars")
			return ars
		elif isinstance(data, dict):
			ars = data.get("ars")
			return ars
		
		return None
		
	except Exception as e:
		print(f"Error getting ARS from postal code: {e}")
		return None

# Pydantic models for responses
class CurrentWeather(BaseModel):
	time: str
	temperature_2m: float
	showers: float

class HourlyWeatherPoint(BaseModel):
	date: str
	temperature_2m: float
	showers: float

class WeatherResponse(BaseModel):
	latitude: float
	longitude: float
	elevation: float
	timezone_offset_seconds: int
	postal_code: Optional[str] = None
	ars: Optional[str] = None
	current: CurrentWeather
	hourly: List[HourlyWeatherPoint]

def fetch_weather(latitude: float, longitude: float) -> WeatherResponse:
	"""Fetch weather data from Open-Meteo API"""
	url = "https://api.open-meteo.com/v1/forecast"
	params = {
		"latitude": latitude,
		"longitude": longitude,
		"hourly": "temperature_2m,showers",
		"current_weather": True,
		"timezone": "auto",
	}

	response = retry_session.get(url, params=params, timeout=10)
	response.raise_for_status()
	payload = response.json()

	current_weather = payload.get("current_weather", {})
	hourly = payload.get("hourly", {})
	hourly_times = hourly.get("time", [])
	hourly_temps = hourly.get("temperature_2m", [])
	hourly_showers = hourly.get("showers", [])

	current_time = current_weather.get("time") or (hourly_times[0] if hourly_times else "")
	current_temperature_2m = float(current_weather.get("temperature", 0.0))
	current_showers = 0.0

	if current_time and hourly_times and hourly_showers:
		try:
			index = hourly_times.index(current_time)
			current_showers = float(hourly_showers[index])
		except ValueError:
			current_showers = float(hourly_showers[0]) if hourly_showers else 0.0

	hourly_list = []
	for time_str, temp, shower in zip(hourly_times, hourly_temps, hourly_showers):
		hourly_list.append(HourlyWeatherPoint(
			date=str(time_str),
			temperature_2m=float(temp),
			showers=float(shower)
		))

	# Get postal code and ARS
	postal_code = None
	ars = None
	try:
		response_data = requests.get(
			"https://nominatim.openstreetmap.org/reverse",
			params={
				"lat": latitude,
				"lon": longitude,
				"format": "json",
				"addressdetails": 1,
				"zoom": 18
			},
			headers={"User-Agent": "WeatherApp/1.0"},
			timeout=10
		)
		response_data.raise_for_status()
		data = response_data.json()
		address = data.get("address", {})
		postal_code = address.get("postcode")

		if postal_code:
			ars = get_ars_from_postal_code(postal_code)
	except Exception as e:
		print(f"Error getting postal code: {e}")

	return WeatherResponse(
		latitude=float(payload.get("latitude", latitude)),
		longitude=float(payload.get("longitude", longitude)),
		elevation=float(payload.get("elevation", 0.0)),
		timezone_offset_seconds=int(payload.get("utc_offset_seconds", 0)),
		postal_code=postal_code,
		ars=ars,
		current=CurrentWeather(
			time=current_time,
			temperature_2m=current_temperature_2m,
			showers=current_showers
		),
		hourly=hourly_list
	)

@app.get("/")
def read_root():
	"""Root endpoint"""
	return {"message": "Weather API is running"}

@app.get("/weather", response_model=WeatherResponse)
def get_weather(latitude: float = 52.52, longitude: float = 13.41):
	"""
	Get current and hourly weather data.
	Default location: Berlin, Germany (52.52°N, 13.41°E)
	"""
	return fetch_weather(latitude, longitude)

@app.get("/current", response_model=CurrentWeather)
def get_current_weather(latitude: float = 52.52, longitude: float = 13.41):
	"""Get only current weather data"""
	weather = fetch_weather(latitude, longitude)
	return weather.current

@app.get("/hourly", response_model=List[HourlyWeatherPoint])
def get_hourly_weather(latitude: float = 52.52, longitude: float = 13.41):
	"""Get only hourly weather data"""
	weather = fetch_weather(latitude, longitude)
	return weather.hourly

@app.get("/search")
async def search_location(location: str):
	"""Search for a location and return its coordinates"""
	try:
		# Check if input is coordinates (lat,lon)
		if ',' in location:
			parts = location.split(',')
			if len(parts) == 2:
				try:
					lat = float(parts[0].strip())
					lon = float(parts[1].strip())
					return {
						"success": True,
						"latitude": lat,
						"longitude": lon,
						"name": f"{lat}°N, {lon}°E"
					}
				except ValueError:
					pass
		
		# Use geocoding API to search for city
		async with httpx.AsyncClient() as client:
			response = await client.get(
				"https://geocoding-api.open-meteo.com/v1/search",
				params={
					"name": location,
					"count": 1,
					"language": "de",
					"format": "json"
				}
			)
			data = response.json()
			
			if not data.get("results") or len(data["results"]) == 0:
				return {"success": False, "message": "Location not found"}
			
			result = data["results"][0]
			return {
				"success": True,
				"latitude": result["latitude"],
				"longitude": result["longitude"],
				"name": f"{result['name']}{', ' + result.get('admin1', '') if result.get('admin1') else ''}{', ' + result.get('country', '') if result.get('country') else ''}"
			}
			
	except Exception as e:
			return {"success": False, "message": f"Error searching location: {str(e)}"}

@app.get("/weather-by-location", response_model=WeatherResponse)
async def get_weather_by_location(location: str):
	"""Get weather by city name or coordinates"""
	try:
		# First search for the location
		search_result = await search_location(location)
		
		if not search_result.get("success"):
			raise Exception(search_result.get("message", "Location not found"))
		
		lat = search_result["latitude"]
		lon = search_result["longitude"]
		
		# Fetch weather for the coordinates
		return fetch_weather(lat, lon)
		
	except Exception as e:
		raise Exception(f"Error fetching weather: {str(e)}")
def get_warnings_from_ars(ars: str) -> dict:
    """Fetch weather warnings from NINA API using ARS code"""
    try:
        url = f"https://nina.api.proxy.bund.dev/api31/dashboard/{ars[0:7]}0000000"
        headers = {"Accept": "application/json"}
        
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # Extract relevant warning information
        warnings = data.get("warnings", [])
        events = []
        
        for warning in warnings:
            events.append({
                "id": warning.get("identifier"),
                "event": warning.get("event"),
                "headline": warning.get("headline"),
                "description": warning.get("description"),
                "severity": warning.get("severity"),
                "onset": warning.get("onset"),
                "expires": warning.get("expires"),
                "instruction": warning.get("instruction")
            })
        
        return {
            "success": True,
            "ars": ars,
            "warning_count": len(events),
            "warnings": events
        }
        
    except Exception as e:
        print(f"Error getting warnings from ARS: {e}")
        return {
            "success": False,
            "ars": ars,
            "message": f"Error retrieving warnings: {str(e)}",
            "warnings": []
        }
@app.get("/warnings")
async def get_warnings(latitude: Optional[float] = None, longitude: Optional[float] = None, ars: Optional[str] = None):
    """Get weather warnings by ARS or by coordinates"""
    try:
        # If ARS is provided, use it directly
        if ars:
            return get_warnings_from_ars(ars)
        
        # Otherwise, get ARS from coordinates
        if latitude is not None and longitude is not None:
            # Get postal code first
            try:
                response_data = requests.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={
                        "lat": latitude,
                        "lon": longitude,
                        "format": "json",
                        "addressdetails": 1,
                        "zoom": 18
                    },
                    headers={"User-Agent": "WeatherApp/1.0"},
                    timeout=5
                )
                data = response_data.json()
                postal_code = data.get("address", {}).get("postcode")
                
                if postal_code:
                    ars_code = get_ars_from_postal_code(postal_code)
                    if ars_code:
                        return get_warnings_from_ars(ars_code)
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Error retrieving postal code: {str(e)}",
                    "warnings": []
                }
        
        return {
            "success": False,
            "message": "Please provide either ARS code or coordinates (latitude and longitude)",
            "warnings": []
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error fetching warnings: {str(e)}",
            "warnings": []
        }
	
@app.get("/postal-code")
async def get_postal_code(latitude: float, longitude: float):
	"""Convert coordinates to German postal code and ARS using reverse geocoding"""
	try:
		async with httpx.AsyncClient() as client:
			# Use Nominatim (OpenStreetMap) for reverse geocoding
			response = await client.get(
				"https://nominatim.openstreetmap.org/reverse",
				params={
					"lat": latitude,
					"lon": longitude,
					"format": "json",
					"addressdetails": 1,
					"zoom": 18,
					"accept-language": "de-DE"
				},
				headers={"User-Agent": "WeatherApp/1.0"}
			)
			data = response.json()
			
			# Extract postal code and address information
			address = data.get("address", {})
			postal_code = address.get("postcode")
			country = address.get("country")
			
			# Check if location is in Germany
			if country and country.lower() != "germany":
				return {
					"success": False,
					"message": f"Location is not in Germany (found: {country})",
					"postal_code": None,
					"ars": None,
					"country": country
				}
			
			ars = None
			if postal_code:
				ars = get_ars_from_postal_code(postal_code)
			
			if postal_code:
				return {
					"success": True,
					"postal_code": postal_code,
					"ars": ars,
					"city": address.get("city") or address.get("town") or address.get("village"),
					"country": country,
					"full_address": data.get("address", {}).get("road", "")
				}
			else:
				return {
					"success": False,
					"message": "Postal code not found for this location",
					"postal_code": None,
					"ars": None,
					"country": country
				}
			
	except Exception as e:
		return {
			"success": False,
			"message": f"Error retrieving postal code: {str(e)}",
			"postal_code": None,
			"ars": None
		}

if __name__ == "__main__":
	import uvicorn
	uvicorn.run(app, host="0.0.0.0", port=8000)

"""
Step 3 — Fetch weather/environment per candidate.
Uses Open-Meteo free API for forecast + air quality.
"""

import hashlib
import json
import time
from typing import Dict, List, Optional
import httpx

from app.config import settings
from app.services.recommendation.models import HeritageSite, Forecast, TripRequest

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPENWEATHER_AIR_URL = "https://api.openweathermap.org/data/2.5/air_pollution"


def _cache_key(coords: List[tuple], start_date: str, end_date: str) -> str:
    raw = f"{sorted(coords)}|{start_date}|{end_date}"
    return hashlib.md5(raw.encode()).hexdigest()


class WeatherService:
    """Fetches weather forecast from Open-Meteo (free, no API key)."""

    def __init__(self, cache: Optional[Dict] = None):
        self._cache: Dict[str, List[Forecast]] = cache or {}

    async def fetch_forecasts(
        self,
        sites: List[HeritageSite],
        trip: TripRequest,
    ) -> Dict[str, List[Forecast]]:
        """
        Fetch hourly forecasts for each unique coordinate grid point.
        Returns dict of site_id -> list of Forecast per day/hour.
        """
        if not sites:
            return {}

        unique_coords = list(set((round(s.lat, 3), round(s.lng, 3)) for s in sites))
        ck = _cache_key(unique_coords, trip.start_date, trip.end_date)
        if ck in self._cache:
            return self._rebuild_site_forecasts(sites, self._cache[ck])

        # Use centroid coordinate for the area forecast (avoids multi-coord complexity)
        avg_lat = sum(c[0] for c in unique_coords) / len(unique_coords)
        avg_lng = sum(c[1] for c in unique_coords) / len(unique_coords)

        params = {
            "latitude": avg_lat,
            "longitude": avg_lng,
            "hourly": "temperature_2m,precipitation_probability,uv_index",
            "timezone": "Asia/Ho_Chi_Minh",
            "forecast_days": max(trip.duration_days, 3),
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(OPEN_METEO_FORECAST_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                air_quality = await self._fetch_air_quality(client, avg_lat, avg_lng)
        except Exception:
            return {s.id: [Forecast(date=trip.start_date, hour=10)] for s in sites}

        forecasts = self._parse_forecast_response(data, unique_coords, trip)
        if air_quality:
            for items in forecasts.values():
                for forecast in items:
                    forecast.pm2_5 = air_quality.get("pm2_5", forecast.pm2_5)
                    forecast.aqi_level = air_quality.get("aqi_level", forecast.aqi_level)
        # Cache under the grid key
        flat = []
        for fl in forecasts.values():
            flat.extend(fl)
        self._cache[ck] = flat

        return self._rebuild_site_forecasts(sites, flat)

    def _parse_forecast_response(
        self, data, coords: List[tuple], trip: TripRequest
    ) -> Dict[tuple, List[Forecast]]:
        result: Dict[tuple, List[Forecast]] = {}
        default = [Forecast(date=trip.start_date, hour=10)] if coords else []

        if isinstance(data, list):
            # Multi-coordinate response: array of per-coordinate dicts
            for ci, entry in enumerate(data):
                coord = coords[ci] if ci < len(coords) else coords[0]
                key = (coord[0], coord[1])
                result[key] = self._parse_single_hourly(entry, trip)
            # Fill missing coords
            for ci in range(len(data), len(coords)):
                result[coords[ci]] = default[:]
            return result

        hourly = data.get("hourly", {}) if isinstance(data, dict) else {}
        for ci, coord in enumerate(coords):
            key = (coord[0], coord[1])
            result[key] = self._parse_single_hourly(data, trip) if hourly else default[:]
        return result

    def _parse_single_hourly(self, entry: dict, trip: TripRequest) -> List[Forecast]:
        hourly = entry.get("hourly", {}) if isinstance(entry, dict) else {}
        times = hourly.get("time", [])
        if not times:
            return [Forecast(date=trip.start_date, hour=10)]

        temps = hourly.get("temperature_2m", [None] * len(times))
        rain_probs = hourly.get("precipitation_probability", [None] * len(times))
        uv_indices = hourly.get("uv_index", [None] * len(times))

        forecasts = []
        for ti in range(min(len(times), 72)):
            date_str = times[ti][:10] if isinstance(times[ti], str) else ""
            hour = int(times[ti][11:13]) if isinstance(times[ti], str) and len(times[ti]) > 12 else 10
            forecasts.append(Forecast(
                date=date_str,
                hour=hour,
                temperature_c=float(temps[ti]) if ti < len(temps) and temps[ti] is not None else 25.0,
                rain_probability=float(rain_probs[ti]) if ti < len(rain_probs) and rain_probs[ti] is not None else 0.0,
                uv_index=float(uv_indices[ti]) if ti < len(uv_indices) and uv_indices[ti] is not None else 5.0,
            ))
        return forecasts

    async def _fetch_air_quality(self, client: httpx.AsyncClient, lat: float, lng: float) -> Optional[dict]:
        if not settings.openweather_api_key:
            return None
        try:
            resp = await client.get(OPENWEATHER_AIR_URL, params={"lat": lat, "lon": lng, "appid": settings.openweather_api_key}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            item = (data.get("list") or [{}])[0]
            components = item.get("components") or {}
            aqi = (item.get("main") or {}).get("aqi")
            labels = {1: "good", 2: "fair", 3: "moderate", 4: "poor", 5: "very_poor"}
            return {"pm2_5": float(components.get("pm2_5", 15.0)), "aqi_level": labels.get(aqi, "good")}
        except Exception:
            return None

    def _rebuild_site_forecasts(
        self, sites: List[HeritageSite], flat_forecasts: List[Forecast]
    ) -> Dict[str, List[Forecast]]:
        return {s.id: flat_forecasts[:8] for s in sites}


weather_service = WeatherService()

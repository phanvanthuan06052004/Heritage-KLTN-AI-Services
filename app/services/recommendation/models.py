"""
Domain entity models matching the canonical schema from §2 of the architecture spec.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional
from datetime import date


class Review(BaseModel):
    author: str = ""
    rating: int = 4
    text: str = ""
    source: str = ""


class HeritageSite(BaseModel):
    id: str
    name: str
    province: str
    lat: float
    lng: float
    categories: List[str] = Field(default_factory=list)
    description: str = ""
    long_description: str = ""
    visit_tips: str = ""
    reference_url: str = ""
    opening_hours: str = "08:00-17:00"
    estimated_visit_minutes: int = 60
    indoor_score: float = 0.5
    outdoor_score: float = 0.5
    suitable_for_children: bool = True
    suitable_for_elderly: bool = True
    ticket_price: int = 0
    popularity_score: float = 0.5
    historical_importance_score: float = 0.5


class Restaurant(BaseModel):
    id: str
    name: str
    lat: float
    lng: float
    province: str
    specialty_tags: List[str] = Field(default_factory=list)
    rating: float = 4.0
    review_count: int = 0
    price_level: int = 2
    opening_hours: str = "06:00-22:00"
    source: str = "manual"
    distance_to_nearest_heritage_m: float = 0.0


class TripRequest(BaseModel):
    destination_area: str = "Hà Nội"
    destination_provinces: List[str] = Field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    duration_days: int = 1
    number_of_people: int = 1
    interests: List[str] = Field(default_factory=lambda: ["history", "architecture", "local_food"])
    pace: str = "moderate"
    travel_mode: str = "mixed"
    budget_level: str = "medium"
    constraints: List[str] = Field(default_factory=list)
    must_visit_site_ids: List[str] = Field(default_factory=list)
    start_location: Optional[dict] = None
    end_location: Optional[dict] = None


class ItineraryItem(BaseModel):
    time: str = "08:00-09:00"
    type: str = "heritage"
    ref_id: str = ""
    name: str = ""
    reason: str = ""
    travel_from_previous_minutes: int = 0
    distance_from_previous_m: float = 0.0


class DayPlan(BaseModel):
    day: int
    date: str = ""
    items: List[ItineraryItem] = Field(default_factory=list)


class Itinerary(BaseModel):
    itinerary_id: str = ""
    summary: str = ""
    total_score: float = 0.0
    total_distance_km: float = 0.0
    days: List[DayPlan] = Field(default_factory=list)
    route_geometries: List[List[List[float]]] = Field(default_factory=list)


class ScoredSite(BaseModel):
    site: HeritageSite
    score: float = 0.0
    interest_match: float = 0.0
    weather_suitability: float = 1.0


class Forecast(BaseModel):
    date: str
    hour: int
    temperature_c: float = 25.0
    rain_probability: float = 0.0
    uv_index: float = 5.0
    pm2_5: float = 15.0
    aqi_level: str = "good"


class TripInput(BaseModel):
    """Free-text or structured user input before normalization."""
    raw_text: Optional[str] = None
    destination_area: str = "Hà Nội"
    destination_provinces: List[str] = Field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    duration_days: int = 1
    number_of_people: int = 1
    interests: List[str] = Field(default_factory=lambda: ["history", "local_food"])
    pace: str = "moderate"
    travel_mode: str = "mixed"
    budget_level: str = "medium"
    constraints: List[str] = Field(default_factory=list)
    must_visit_site_ids: List[str] = Field(default_factory=list)
    start_lat: float = 21.0285
    start_lng: float = 105.8542
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None


class PlannerSite(BaseModel):
    id: str
    name: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    open_time: str = "08:00"
    close_time: str = "17:00"
    visit_duration_min: int = 60
    categories: List[str] = Field(default_factory=list)
    popularity_score: float = 0.5
    historical_importance_score: float = 0.5

    @field_validator("open_time", "close_time")
    @classmethod
    def validate_site_time(cls, value: str) -> str:
        _validate_hhmm(value)
        return value

    @field_validator("lat")
    @classmethod
    def validate_site_lat(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not -90 <= value <= 90:
            raise ValueError("lat must be between -90 and 90")
        return value

    @field_validator("lng")
    @classmethod
    def validate_site_lng(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not -180 <= value <= 180:
            raise ValueError("lng must be between -180 and 180")
        return value

    @field_validator("visit_duration_min")
    @classmethod
    def validate_visit_duration(cls, value: int) -> int:
        if value < 0:
            raise ValueError("visit_duration_min must be >= 0")
        return value


class PlannerPoint(BaseModel):
    id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    label: str = ""

    @field_validator("lat")
    @classmethod
    def validate_point_lat(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not -90 <= value <= 90:
            raise ValueError("lat must be between -90 and 90")
        return value

    @field_validator("lng")
    @classmethod
    def validate_point_lng(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not -180 <= value <= 180:
            raise ValueError("lng must be between -180 and 180")
        return value


class PlannerWindow(BaseModel):
    start_time: str = "08:00"
    end_time: str = "17:00"

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_window_time(cls, value: str) -> str:
        _validate_hhmm(value)
        return value


class PlannerConstraints(BaseModel):
    avoid_highways: bool = False
    avoid_tolls: bool = False
    max_total_distance_km: Optional[float] = None
    max_total_duration_min: Optional[int] = None

    @field_validator("max_total_distance_km")
    @classmethod
    def validate_max_distance(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value < 0:
            raise ValueError("max_total_distance_km must be >= 0")
        return value

    @field_validator("max_total_duration_min")
    @classmethod
    def validate_max_duration(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("max_total_duration_min must be >= 0")
        return value


class RoutePlanRequest(BaseModel):
    province: str = ""
    sites: List[PlannerSite]
    start: PlannerPoint
    end: PlannerPoint
    transport_mode: str
    trip_date: str = ""
    available_window: PlannerWindow = Field(default_factory=PlannerWindow)
    num_days: int = 1
    constraints: PlannerConstraints = Field(default_factory=PlannerConstraints)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.transport_mode not in {"driving", "motorbike", "walking", "transit"}:
            raise ValueError("transport_mode must be one of: driving, motorbike, walking, transit")
        if self.num_days < 1:
            raise ValueError("num_days must be >= 1")
        if self.trip_date:
            try:
                date.fromisoformat(self.trip_date)
            except ValueError as exc:
                raise ValueError("trip_date must use YYYY-MM-DD") from exc
        return self


def _validate_hhmm(value: str) -> None:
    import re
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value or ""):
        raise ValueError("time must use HH:MM")


class RoutePlanStop(BaseModel):
    site_id: str
    name: str
    arrival_time: str
    departure_time: str
    travel_from_prev_km: float = 0.0
    travel_from_prev_min: int = 0
    reason: str = ""


class RoutePlanDay(BaseModel):
    day: int
    stops: List[RoutePlanStop] = Field(default_factory=list)
    polyline: str = ""


class RoutePlanResponse(BaseModel):
    status: str
    total_distance_km: float = 0.0
    total_duration_min: int = 0
    days: List[RoutePlanDay] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

"""
Step 4 — Score each site using the scoring formula from §4 Step 4.

site_score =
    0.30 * interest_match_score +
    0.20 * historical_importance_score +
    0.15 * weather_suitability_score +
    0.15 * distance_score +
    0.10 * popularity_score +
    0.05 * accessibility_score +
    0.05 * budget_score
"""

from typing import List, Optional
from app.services.recommendation.models import HeritageSite, TripRequest, Forecast, ScoredSite
import numpy as np


SCORING_WEIGHTS = {
    "interest_match": 0.30,
    "historical_importance": 0.20,
    "weather_suitability": 0.15,
    "distance": 0.15,
    "popularity": 0.10,
    "accessibility": 0.05,
    "budget": 0.05,
}


def compute_interest_match(site: HeritageSite, interests: List[str]) -> float:
    """|site.categories ∩ user.interests| / |user.interests|"""
    if not interests:
        return 0.5
    common = set(c.lower() for c in site.categories) & set(i.lower() for i in interests)
    return len(common) / len(interests)


def compute_weather_suitability(
    site: HeritageSite,
    forecasts: List[Forecast],
    visit_hour: int = 10,
) -> float:
    """Apply weather rule set from §5."""
    score = 1.0

    relevant = [f for f in forecasts if 8 <= f.hour <= 17]
    if not relevant:
        return score

    avg_rain = np.mean([f.rain_probability for f in relevant])
    avg_temp = np.mean([f.temperature_c for f in relevant])
    avg_uv = np.mean([f.uv_index for f in relevant])

    if avg_rain > 70 and site.outdoor_score > 0.6:
        score -= 0.35
    if avg_temp > 35 and site.outdoor_score > 0.6:
        score -= 0.25
    if avg_uv > 8 and 11 <= visit_hour <= 14:
        score -= 0.20
    if avg_temp < 10 and site.outdoor_score > 0.6:
        score -= 0.15

    return max(0.0, min(1.0, score))


def compute_distance_score(
    site: HeritageSite, start_lat: float, start_lng: float, max_dist_km: float = 100.0
) -> float:
    """Normalize distance to [0,1] where closer = higher score."""
    dlat = site.lat - start_lat
    dlng = site.lng - start_lng
    dist_km = np.sqrt(dlat**2 + dlng**2) * 111.32  # Approximate degrees to km
    return max(0.0, 1.0 - dist_km / max_dist_km)


def compute_accessibility(site: HeritageSite, constraints: List[str]) -> float:
    score = 0.5
    if "elderly_friendly" in constraints:
        score += 0.25 if site.suitable_for_elderly else -0.25
    if "child_friendly" in constraints:
        score += 0.25 if site.suitable_for_children else -0.25
    if not constraints:
        score = 0.5 + (0.5 if site.suitable_for_elderly else 0.0)
    return max(0.0, min(1.0, score))


def compute_budget_fit(site: HeritageSite, budget_level: str) -> float:
    budget_thresholds = {"low": (0, 30000), "medium": (0, 100000), "high": (0, 1000000)}
    lo, hi = budget_thresholds.get(budget_level, (0, 100000))
    if site.ticket_price <= lo:
        return 1.0
    if site.ticket_price >= hi:
        return 0.2
    return 1.0 - (site.ticket_price - lo) / (hi - lo)


def score_site(
    site: HeritageSite,
    trip: TripRequest,
    forecasts: List[Forecast],
    start_lat: float = 21.0285,
    start_lng: float = 105.8542,
    visit_hour: int = 10,
) -> ScoredSite:
    """Compute the weighted composite score for a single heritage site."""
    w = SCORING_WEIGHTS

    interest = compute_interest_match(site, trip.interests)
    weather = compute_weather_suitability(site, forecasts, visit_hour)
    distance = compute_distance_score(site, start_lat, start_lng)
    accessibility = compute_accessibility(site, trip.constraints)
    budget = compute_budget_fit(site, trip.budget_level)

    total = (
        w["interest_match"] * interest
        + w["historical_importance"] * site.historical_importance_score
        + w["weather_suitability"] * weather
        + w["distance"] * distance
        + w["popularity"] * site.popularity_score
        + w["accessibility"] * accessibility
        + w["budget"] * budget
    )

    return ScoredSite(
        site=site,
        score=round(total, 4),
        interest_match=round(interest, 4),
        weather_suitability=round(weather, 4),
    )


def score_all_sites(
    candidates: List[HeritageSite],
    trip: TripRequest,
    forecasts_by_site: dict,
) -> List[ScoredSite]:
    """Score all candidate sites and return sorted by descending score."""
    start = trip.start_location or {"lat": 21.0285, "lng": 105.8542}
    scored = []
    for site in candidates:
        fcasts = forecasts_by_site.get(site.id, [])
        sc = score_site(site, trip, fcasts, start["lat"], start["lng"])
        scored.append(sc)
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored

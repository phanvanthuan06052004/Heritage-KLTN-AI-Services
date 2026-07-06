"""
Step 7 — Insert restaurants into itinerary at meal time windows.

For each day, for each meal slot (breakfast 07:00-09:00, lunch 11:00-13:30, dinner 18:00-20:30):
  - Query restaurants near the current route point
  - Score with bayesian rating, specialty match, distance, price fit
"""

from typing import List, Optional
from app.services.recommendation.models import Restaurant, ScoredSite, ItineraryItem, DayPlan
import numpy as np


MEAL_SLOTS = [
    {"name": "breakfast", "time": "07:00-09:00", "start_hour": 7, "end_hour": 9},
    {"name": "lunch", "time": "11:00-13:30", "start_hour": 11, "end_hour": 13},
    {"name": "dinner", "time": "18:00-20:30", "start_hour": 18, "end_hour": 20},
]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lng2 - lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def bayesian_rating(rating: float, review_count: int, area_avg: float = 3.8, m: int = 50) -> float:
    """Bayesian weighted rating: (v/(v+m))*R + (m/(v+m))*C"""
    v = review_count
    return (v / (v + m)) * rating + (m / (v + m)) * area_avg


def find_best_restaurant(
    restaurants: List[Restaurant],
    mid_lat: float,
    mid_lng: float,
    meal_slot: dict,
    specialty_prefs: List[str],
    budget_level: str,
    max_distance_m: float = 3000,
) -> Optional[Restaurant]:
    """Find the best restaurant near a route midpoint for a meal slot."""
    candidates = []
    for r in restaurants:
        dist = haversine_m(mid_lat, mid_lng, r.lat, r.lng)
        if dist > max_distance_m:
            continue

        bayes = bayesian_rating(r.rating, r.review_count)
        specialty_match = (
            len(set(r.specialty_tags) & set(specialty_prefs)) / max(1, len(specialty_prefs))
            if specialty_prefs else 0.5
        )
        distance_score = max(0.0, 1.0 - dist / max_distance_m)
        price_fit = _budget_fit(r.price_level, budget_level)

        score = (
            0.30 * specialty_match
            + 0.25 * bayes / 5.0
            + 0.20 * distance_score
            + 0.15 * 1.0  # opening_hour_score: simplified
            + 0.10 * price_fit
        )
        candidates.append((score, r, dist))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _budget_fit(price_level: int, budget_level: str) -> float:
    mapping = {"low": 1, "medium": 2, "high": 3}
    ideal = mapping.get(budget_level, 2)
    return max(0.1, 1.0 - abs(price_level - ideal) * 0.3)


def insert_restaurants(
    day_plans: List[DayPlan],
    restaurants: List[Restaurant],
    scored_clusters: List[List[ScoredSite]],
    specialty_prefs: List[str],
    budget_level: str = "medium",
) -> List[DayPlan]:
    """
    Insert restaurant stops into each day plan at appropriate meal slots.
    """
    for day_idx, (plan, cluster) in enumerate(zip(day_plans, scored_clusters)):
        if not cluster:
            continue

        items = plan.items
        midpoints = _get_meal_midpoints(cluster, items)

        for slot_idx, slot in enumerate(MEAL_SLOTS):
            mid = midpoints[slot_idx] if slot_idx < len(midpoints) else (
                cluster[-1].site.lat if cluster else 21.0285,
                cluster[-1].site.lng if cluster else 105.8542,
            )

            best = find_best_restaurant(
                restaurants, mid[0], mid[1], slot, specialty_prefs, budget_level
            )
            if best:
                plan.items.append(ItineraryItem(
                    time=slot["time"],
                    type="restaurant",
                    ref_id=best.id,
                    name=best.name,
                    reason=f"Bayesian rating: {bayesian_rating(best.rating, best.review_count):.1f}/5 | {', '.join(best.specialty_tags[:2])}",
                ))

        # Sort items by time
        plan.items.sort(key=lambda it: it.time.split("-")[0] if it.time else "00:00")

    return day_plans


def _get_meal_midpoints(cluster: List[ScoredSite], existing_items: List[ItineraryItem]) -> List[tuple]:
    """Return (lat, lng) midpoints for meal insertion along the route."""
    if not cluster:
        lat = 21.0285
        lng = 105.8542
        for it in existing_items:
            if it.type == "heritage":
                lat = cluster[0].site.lat if cluster else lat
                lng = cluster[0].site.lng if cluster else lng
                break
        return [(lat, lng)] * 3

    n = len(cluster)
    midpoints = []

    # breakfast: near first site
    midpoints.append((cluster[0].site.lat, cluster[0].site.lng))

    # lunch: midpoint of route
    if n >= 2:
        mid_idx = n // 2
        midpoints.append((cluster[mid_idx].site.lat, cluster[mid_idx].site.lng))
    else:
        midpoints.append((cluster[0].site.lat, cluster[0].site.lng))

    # dinner: near last site
    midpoints.append((cluster[-1].site.lat, cluster[-1].site.lng))

    return midpoints

"""
Step 2 — Generate candidates: Filter heritage sites by area, interest, constraints.
MUST-VISIT sites are ALWAYS included with top priority, regardless of filters.
"""

from typing import List, Optional
from app.services.recommendation.models import HeritageSite, TripRequest
import numpy as np


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in meters."""
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lng2 - lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def generate_candidates(
    trip: TripRequest,
    all_sites: List[HeritageSite],
    top_n: int = 30,
) -> List[HeritageSite]:
    """
    Filter heritage sites STRICTLY by selected provinces only.
    Must-visit sites are ALWAYS included with top priority.
    No radius fallback — only sites from target provinces.
    """
    must_visit_ids = set(trip.must_visit_site_ids)
    must_visits: List[HeritageSite] = []
    candidates: List[HeritageSite] = []
    site_map = {s.id: s for s in all_sites}

    # Step 1: Force-include must-visit sites (regardless of province)
    for sid in must_visit_ids:
        if sid in site_map:
            must_visits.append(site_map[sid])

    # Step 2: STRICT province filter — only target provinces
    target_provinces = set(trip.destination_provinces or [trip.destination_area])
    
    for site in all_sites:
        # Skip already-included must-visit sites
        if site.id in must_visit_ids:
            continue

        # STRICT: only include sites from selected provinces
        if site.province not in target_provinces:
            continue

        if not _satisfies_constraints(site, trip.constraints):
            continue

        candidates.append(site)

    # Step 3: Rank by interest overlap
    candidates.sort(
        key=lambda s: _interest_overlap(s, trip.interests),
        reverse=True,
    )

    # Step 4: Combine — must-visit sites FIRST, then top recommended
    remaining_slots = max(0, top_n - len(must_visits))
    result = must_visits + candidates[:remaining_slots]

    return result


def _satisfies_constraints(site: HeritageSite, constraints: List[str]) -> bool:
    if "elderly_friendly" in constraints and not site.suitable_for_elderly:
        return False
    if "child_friendly" in constraints and not site.suitable_for_children:
        return False
    if "prefer_indoor" in constraints and site.indoor_score < 0.4:
        return False
    if "prefer_outdoor" in constraints and site.outdoor_score < 0.4:
        return False
    return True


def _interest_overlap(site: HeritageSite, interests: List[str]) -> float:
    if not interests:
        return 0.0
    common = set(c.lower() for c in site.categories) & set(i.lower() for i in interests)
    return len(common) / len(interests)


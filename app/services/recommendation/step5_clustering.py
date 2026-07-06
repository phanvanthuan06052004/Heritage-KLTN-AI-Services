"""
Step 5 — Split into day-clusters.
Uses geographic k-means clustering, ensuring must-visit sites are distributed.
"""

from typing import List
from app.services.recommendation.models import ScoredSite, HeritageSite, DayPlan, ItineraryItem
import numpy as np

try:
    from sklearn.cluster import KMeans
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


PACE_LIMITS = {
    "relaxed": 3,
    "moderate": 5,
    "packed": 7,
}


def split_into_days(
    scored_sites: List[ScoredSite],
    duration_days: int,
    pace: str = "moderate",
    start_lat: float = None,
    start_lng: float = None,
) -> List[List[ScoredSite]]:
    """
    Split scored sites into day clusters using geographic proximity.
    Sites are grouped by nearest-neighbor geographic clustering,
    ensuring must-visit sites are distributed and nearby sites stay together.
    """
    if not scored_sites:
        return [[] for _ in range(duration_days)]

    max_per_day = PACE_LIMITS.get(pace, 5)
    total_capacity = duration_days * max_per_day

    # Split sites into must-visit and recommended
    must_visit = [s for s in scored_sites if s.score >= 0.99]
    recommended = [s for s in scored_sites]

    if len(must_visit) > total_capacity:
        must_visit = must_visit[:total_capacity]
        recommended = []

    # Remove must-visit from recommended (they're already in must_visit)
    must_ids = {s.site.id for s in must_visit}
    recommended = [s for s in scored_sites if s.site.id not in must_ids]

    if duration_days == 1:
        combined = must_visit + recommended[:max_per_day - len(must_visit)]
        return [combined]

    # Strategy: greedy geographic clustering
    # Start with must-visit sites as seeds for each day
    clusters: List[List[ScoredSite]] = [[] for _ in range(duration_days)]
    
    # Sort must-visit by geographic position (latitude-based for simplicity)
    must_visit_sorted = sorted(must_visit, key=lambda s: (s.site.lat, s.site.lng))

    # Distribute must-visit across days — round-robin by geographic order
    for i, s in enumerate(must_visit_sorted):
        day_idx = i % duration_days
        clusters[day_idx].append(s)

    # For recommended sites, assign to nearest day cluster (by avg center)
    for s in recommended:
        best_day = -1
        best_dist = float('inf')
        for di, cluster in enumerate(clusters):
            if len(cluster) >= max_per_day:
                continue
            if not cluster:
                best_day = di
                break
            # Distance to cluster centroid
            avg_lat = sum(c.site.lat for c in cluster) / len(cluster)
            avg_lng = sum(c.site.lng for c in cluster) / len(cluster)
            d = (s.site.lat - avg_lat)**2 + (s.site.lng - avg_lng)**2
            if d < best_dist:
                best_dist = d
                best_day = di
        if best_day >= 0:
            clusters[best_day].append(s)

    # Sort each cluster by score descending, with must-visit first
    for c in clusters:
        c.sort(key=lambda s: (0 if s.site.id in must_ids else 1, -s.score))

    return clusters


def _simple_geographic_split(coords: np.ndarray, k: int) -> np.ndarray:
    """Fallback split by latitude banding."""
    lats = coords[:, 0]
    sorted_idx = np.argsort(lats)
    labels = np.zeros(len(coords), dtype=int)
    chunk_size = max(1, len(coords) // k)
    for i, idx in enumerate(sorted_idx):
        labels[idx] = min(i // chunk_size, k - 1)
    return labels


def clusters_to_day_plans(
    clusters: List[List[ScoredSite]],
    start_date: str = "",
) -> List[DayPlan]:
    """Convert clusters to DayPlan objects for further processing."""
    from datetime import datetime, timedelta

    days = []
    base_date = datetime.now()
    if start_date:
        try:
            base_date = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            pass

    for day_idx, cluster in enumerate(clusters):
        day_date = (base_date + timedelta(days=day_idx)).strftime("%Y-%m-%d")
        items = []
        for sc in cluster:
            items.append(ItineraryItem(
                type="heritage",
                ref_id=sc.site.id,
                name=sc.site.name,
                reason=f"Score: {sc.score:.2f} | Interest match: {sc.interest_match:.0%}",
            ))
        days.append(DayPlan(day=day_idx + 1, date=day_date, items=items))
    return days

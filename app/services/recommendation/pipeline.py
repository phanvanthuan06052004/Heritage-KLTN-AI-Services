"""
AI Service Pipeline — Orchestrates all 8 steps from the architecture spec.
"""

import asyncio
import time as time_mod
import logging
from typing import List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PIPELINE] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pipeline")

from app.services.recommendation.models import (
    HeritageSite, TripRequest, Itinerary, ScoredSite,
    DayPlan, Forecast, TripInput,
)
from app.services.recommendation.step1_normalizer import parse_trip_request
from app.services.recommendation.step2_candidates import generate_candidates
from app.services.recommendation.step3_weather import weather_service
from app.services.recommendation.step4_scoring import score_all_sites
from app.services.recommendation.step5_clustering import split_into_days, clusters_to_day_plans
from app.services.recommendation.step6_routing import optimize_route
from app.services.recommendation.step8_assembly import assemble_itinerary


class Pipeline:
    """Orchestrates the full 8-step recommendation pipeline."""

    def __init__(self):
        self._sites_cache: List[HeritageSite] = []
        self._forecast_cache: dict = {}

    def load_data(self, sites: List[HeritageSite]):
        self._sites_cache = sites

    async def run(self, raw_input: TripInput) -> Itinerary:
        t_start = time_mod.time()
        log.info("=" * 50)
        log.info("START — Itinerary generation")
        log.info(f"  Input: provinces={raw_input.destination_provinces or raw_input.destination_area}, days={raw_input.duration_days}, interests={raw_input.interests}, pace={raw_input.pace}")
        if raw_input.start_lat: log.info(f"  Start: ({raw_input.start_lat:.4f}, {raw_input.start_lng:.4f})")
        if raw_input.end_lat: log.info(f"  End: ({raw_input.end_lat:.4f}, {raw_input.end_lng:.4f})")
        log.info(f"  Data pool: {len(self._sites_cache)} sites loaded")

        # Step 1: Normalize input
        t0 = time_mod.time()
        trip = parse_trip_request(raw_input)
        log.info(f"STEP 1 — Normalize ({time_mod.time()-t0:.2f}s): dest={trip.destination_area}, provinces={trip.destination_provinces}, days={trip.duration_days}, pace={trip.pace}")

        # Step 2: Generate candidates
        t0 = time_mod.time()
        candidates = generate_candidates(trip, self._sites_cache)
        log.info(f"STEP 2 — Candidates ({time_mod.time()-t0:.2f}s): {len(candidates)} sites from {len(self._sites_cache)} total")

        # Step 3: Fetch weather
        t0 = time_mod.time()
        forecasts = await weather_service.fetch_forecasts(candidates, trip)
        log.info(f"STEP 3 — Weather ({time_mod.time()-t0:.2f}s): {len(forecasts)} forecasts")

        # Step 4: Score each site. Must-visit sites get max score to guarantee inclusion
        t0 = time_mod.time()
        scored = score_all_sites(candidates, trip, forecasts)
        # Force must-visit sites to max score
        must_ids = set(trip.must_visit_site_ids)
        for s in scored:
            if s.site.id in must_ids:
                s.score = 0.99  # Near-max to ensure top priority in clustering
        top5 = [(s.site.name, f"{s.score:.3f}", "★" if s.site.id in must_ids else "") for s in scored[:5]]
        log.info(f"STEP 4 — Scoring ({time_mod.time()-t0:.2f}s): {len(scored)} scored | must-visit: {len(must_ids)} | top: {top5}")

        # Step 5 & 6: TTDP Route Optimization (OR-Tools)
        t0 = time_mod.time()
        
        start_lat = trip.start_location.get('lat') if trip.start_location else 21.0285
        start_lng = trip.start_location.get('lng') if trip.start_location else 105.8542
        end_lat = trip.end_location.get('lat') if trip.end_location else start_lat
        end_lng = trip.end_location.get('lng') if trip.end_location else start_lng
        
        locations = [(start_lat, start_lng), (end_lat, end_lng)]
        scores = [0.0, 0.0]
        durations = [0, 0]
        time_windows = [(0, 100000), (0, 100000)]
        
        for s in scored:
            locations.append((s.site.lat, s.site.lng))
            scores.append(s.score)
            durations.append(s.site.estimated_visit_minutes * 60)
            time_windows.append((0, 100000))

        max_sec_per_day = 8 * 3600
        from app.services.recommendation.ttdp_solver import solve_ttdp
        routes_indices = await asyncio.to_thread(
            solve_ttdp, locations, scores, durations, time_windows,
            trip.duration_days, max_sec_per_day, speed_kmh=40.0, time_limit_sec=2
        )
        
        optimized_clusters = []
        for route_idx in routes_indices:
            cluster = [scored[i - 2] for i in route_idx]
            optimized_clusters.append(cluster)
        if scored and not any(optimized_clusters):
            log.warning("TTDP returned empty routes; falling back to top scored candidates")
            max_sites = min(len(scored), max(3, trip.duration_days * 3))
            selected = scored[:max_sites]
            optimized_clusters = [selected[i::trip.duration_days] for i in range(trip.duration_days)]
              
        log.info(f"STEP 5/6 — TTDP Routing ({time_mod.time()-t0:.2f}s): {len(routes_indices)} days optimized")

        # Geometry fallback
        t0 = time_mod.time()
        from app.services.recommendation.step6_routing import get_route_geometry
        route_tasks = [
            asyncio.to_thread(get_route_geometry, c) if c else asyncio.sleep(0, result=None)
            for c in optimized_clusters
        ]
        route_geoms = await asyncio.gather(*route_tasks)
        log.info(f"STEP 6b — Geometry ({time_mod.time()-t0:.2f}s)")

        # Step 7: Day plans
        t0 = time_mod.time()
        day_plans = clusters_to_day_plans(optimized_clusters, trip.start_date)
        log.info(f"STEP 7 — Day Plans ({time_mod.time()-t0:.2f}s): {sum(len(d.items) for d in day_plans)} items")

        # Step 8: Assemble
        t0 = time_mod.time()
        itinerary = assemble_itinerary(day_plans, optimized_clusters, trip, route_geoms)
        log.info(f"STEP 8 — Assemble ({time_mod.time()-t0:.2f}s): score={itinerary.total_score:.0%}, distance={itinerary.total_distance_km}km, id={itinerary.itinerary_id}")

        total_time = time_mod.time() - t_start
        log.info(f"DONE — Total: {total_time:.2f}s | ID: {itinerary.itinerary_id}")
        log.info("=" * 50)

        return itinerary


pipeline = Pipeline()

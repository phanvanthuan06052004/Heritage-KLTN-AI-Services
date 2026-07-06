"""
Step 6 — Route optimization with OSRM real road routing.
Uses OSRM public API for distance matrix + route geometry.
Fallback to haversine if OSRM is unreachable.
"""

import json
import logging
import urllib.request
from functools import lru_cache
from typing import List, Tuple, Optional
from app.config import settings
from app.services.recommendation.models import ScoredSite
import numpy as np

OSRM_BASE = settings.osrm_base_url.rstrip("/") or "https://router.project-osrm.org"
OSRM_TIMEOUT_SECONDS = 3
log = logging.getLogger("pipeline")


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lng2 - lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def _coords_key(coords: List[Tuple[float, float]]) -> Tuple[Tuple[float, float], ...]:
    return tuple((round(lat, 6), round(lng, 6)) for lat, lng in coords)


@lru_cache(maxsize=512)
def _cached_osrm_request(endpoint: str, coords: Tuple[Tuple[float, float], ...], extra_params: str = "") -> Optional[dict]:
    """Call OSRM API and return parsed JSON."""
    coord_str = ";".join(f"{lng},{lat}" for lat, lng in coords)
    url = f"{OSRM_BASE}/{endpoint}/{coord_str}?annotations=distance,duration{extra_params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "heritage-planner/1.0"})
        with urllib.request.urlopen(req, timeout=OSRM_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.info(f"  OSRM fallback: {endpoint} failed ({type(exc).__name__})")
        return None


def _osrm_request(endpoint: str, coords: List[Tuple[float, float]], extra_params: str = "") -> Optional[dict]:
    return _cached_osrm_request(endpoint, _coords_key(coords), extra_params)


def build_distance_matrix_osrm(
    sites: List[ScoredSite],
) -> Tuple[np.ndarray, List[Tuple[float, float]], Optional[dict]]:
    """
    Build distance matrix using OSRM table API (real road distances).
    Returns (matrix_meters, coords, table_response_or_none).
    """
    coords = [(s.site.lat, s.site.lng) for s in sites]
    n = len(coords)
    if n <= 1:
        return np.zeros((n, n)), coords, None

    result = _osrm_request("table/v1/driving", coords)
    if result and "distances" in result:
        distances = result["distances"]
        matrix = np.array(distances, dtype=float)
        matrix[np.isnan(matrix)] = 999999
        return matrix, coords, result

    # Fallback to haversine
    matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix, coords, None


def get_route_geometry(
    sites: List[ScoredSite],
) -> Optional[list]:
    """
    Get the route LineString geometry from OSRM for a list of ordered sites.
    Returns GeoJSON LineString coordinates [[lng,lat],...] or None.
    """
    if len(sites) < 2:
        return None
    coords = [(s.site.lat, s.site.lng) for s in sites]
    result = _osrm_request("route/v1/driving", coords, extra_params="&geometries=geojson&overview=simplified")
    if result and "routes" in result and len(result["routes"]) > 0:
        geom = result["routes"][0].get("geometry")
        if isinstance(geom, dict):
            return geom.get("coordinates", [])
        # If polyline string, decode
        if isinstance(geom, str) and geom:
            return _decode_polyline(geom)
    return None


def _decode_polyline(polyline_str: str, precision: int = 5) -> list:
    """Decode OSRM polyline string to [[lng,lat],...]"""
    coords = []
    index, lat, lng = 0, 0, 0
    factor = 10 ** precision
    while index < len(polyline_str):
        result = 0; shift = 0
        while True:
            byte = ord(polyline_str[index]) - 63; index += 1
            result |= (byte & 0x1f) << shift; shift += 5
            if byte < 0x20: break
        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat
        result = 0; shift = 0
        while True:
            byte = ord(polyline_str[index]) - 63; index += 1
            result |= (byte & 0x1f) << shift; shift += 5
            if byte < 0x20: break
        dlng = ~(result >> 1) if result & 1 else result >> 1
        lng += dlng
        coords.append([lng / factor, lat / factor])
    return coords


def nearest_neighbor(
    dist_matrix: np.ndarray, start_idx: int = 0
) -> List[int]:
    n = len(dist_matrix)
    unvisited = set(range(n))
    unvisited.discard(start_idx)
    route = [start_idx]
    current = start_idx
    while unvisited:
        next_node = min(unvisited, key=lambda j: dist_matrix[current][j])
        route.append(next_node)
        unvisited.discard(next_node)
        current = next_node
    return route


def two_opt(route: List[int], dist_matrix: np.ndarray, max_iter: int = 200) -> List[int]:
    best = route[:]
    n = len(best)
    def cost(r): return sum(dist_matrix[r[i]][r[(i + 1) % n]] for i in range(n))
    best_cost = cost(best)
    for _ in range(max_iter):
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                new_route = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                new_cost = cost(new_route)
                if new_cost < best_cost - 1e-6:
                    best = new_route
                    best_cost = new_cost
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return best


def optimize_route(
    cluster: List[ScoredSite],
    start_lat: float | None = None,
    start_lng: float | None = None,
) -> Tuple[List[ScoredSite], Optional[list]]:
    """
    Optimize visiting order using OSRM road distances.
    Returns (ordered_sites, route_geometry_or_none).
    """
    if len(cluster) <= 2:
        return cluster, None

    dist_matrix, _, _ = build_distance_matrix_osrm(cluster)
    nn_route = nearest_neighbor(dist_matrix, 0)
    opt_route = two_opt(nn_route, dist_matrix)
    ordered = [cluster[i] for i in opt_route]

    geom = get_route_geometry(ordered)
    return ordered, geom

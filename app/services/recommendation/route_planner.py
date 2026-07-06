"""Spec-compliant route planner from alth.md.

This endpoint solves fixed-start/fixed-end sequencing with OSRM road costs,
then asks OSRM for the final route geometry.
"""

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import numpy as np

from app.config import settings
from app.services.recommendation.models import (
    PlannerPoint,
    PlannerSite,
    RoutePlanDay,
    RoutePlanRequest,
    RoutePlanResponse,
    RoutePlanStop,
)

try:
    from sklearn.cluster import KMeans
except ImportError:  # pragma: no cover - dependency is optional at runtime
    KMeans = None

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
except ImportError:  # pragma: no cover - dependency is optional at runtime
    pywrapcp = None
    routing_enums_pb2 = None


OSRM_BASE = settings.osrm_base_url.rstrip("/")
OSRM_FALLBACK_BASES = [
    "http://heritage_osrm:5000",
    "http://localhost:5000",
    "http://host.docker.internal:5000",
]
REQUEST_TIMEOUT_SECONDS = 15
UNREACHABLE_COST = 10**12
EXACT_TSP_MAX_SITES = 14
EXACT_PARTITION_MAX_SITES = 14
ORTOOLS_TIME_LIMIT_SECONDS = 20


def plan_route(request: RoutePlanRequest) -> RoutePlanResponse:
    warnings: List[str] = []
    if request.transport_mode == "transit":
        return RoutePlanResponse(
            status="error",
            warnings=["transport_mode=transit requires a GTFS routing engine; OSRM cannot serve transit routes"],
        )
    if request.transport_mode in {"motorbike", "walking"}:
        warnings.append(f"transport_mode={request.transport_mode} is routed with OSRM driving profile")
    if request.constraints.avoid_highways or request.constraints.avoid_tolls:
        warnings.append("avoid_highways/avoid_tolls are not supported by the current OSRM car profile")

    try:
        start = _resolve_point(request.start)
        end = _resolve_point(request.end)
        sites = [_resolve_site(site, request.province) for site in request.sites]
    except ValueError as exc:
        return RoutePlanResponse(status="error", warnings=[str(exc)])

    if not sites:
        try:
            route = _fetch_route([start, end])
        except ValueError as exc:
            return RoutePlanResponse(status="error", warnings=[str(exc)])
        distance_km = round(route["distance_m"] / 1000, 2)
        duration_min = math.ceil(route["duration_s"] / 60)
        return RoutePlanResponse(
            status=_status_for_limits(distance_km, duration_min, request, warnings),
            total_distance_km=distance_km,
            total_duration_min=duration_min,
            days=[RoutePlanDay(day=1, stops=[], polyline=route["polyline"])],
            warnings=warnings,
        )

    day_groups = _partition_sites(start, end, sites, request, warnings)
    total_distance_m = 0.0
    total_duration_s = 0.0
    days: List[RoutePlanDay] = []

    for day_index, group in enumerate(day_groups, start=1):
        if not group:
            days.append(RoutePlanDay(day=day_index, stops=[], polyline=""))
            continue

        try:
            ordered, order, durations, distances = _sequence_sites(start, end, group, request, warnings)
        except Exception as exc:
            return RoutePlanResponse(status="error", warnings=warnings + [f"OSRM table request failed: {exc}"])
        route_points = [start] + [_site_point(site) for site in ordered] + [end]
        try:
            route = _fetch_route(route_points)
        except ValueError as exc:
            return RoutePlanResponse(status="error", warnings=warnings + [str(exc)])
        matrix_order = [0] + order + [len(group) + 1]
        leg_distances, leg_durations = _route_legs(route, matrix_order, distances, durations)
        day_stops, day_duration_s = _build_stops(ordered, leg_distances, leg_durations, request.available_window.start_time, warnings)

        total_distance_m += sum(leg_distances)
        total_duration_s += day_duration_s
        days.append(RoutePlanDay(day=day_index, stops=day_stops, polyline=route["polyline"]))

    total_distance_km = round(total_distance_m / 1000, 2)
    total_duration_min = math.ceil(total_duration_s / 60)
    status = _status_for_limits(total_distance_km, total_duration_min, request, warnings)
    return RoutePlanResponse(
        status=status,
        total_distance_km=total_distance_km,
        total_duration_min=total_duration_min,
        days=days,
        warnings=warnings,
    )


def _resolve_point(point: PlannerPoint) -> PlannerPoint:
    if point.lat is not None and point.lng is not None:
        return point
    if point.label:
        resolved = _geocode(point.label)
        if resolved:
            point.lat, point.lng = resolved
            return point
    raise ValueError(f"point '{point.label or point.id or 'unknown'}' must have valid lat/lng or a geocodable label")


def _resolve_site(site: PlannerSite, province: str) -> PlannerSite:
    if site.lat is not None and site.lng is not None:
        return site
    query = f"{site.name} {province} Vietnam" if province else f"{site.name} Vietnam"
    resolved = _geocode(query)
    if resolved:
        site.lat, site.lng = resolved
        return site
    raise ValueError(f"site '{site.name}' must have valid lat/lng or a geocodable name")


def _geocode(query: str) -> Optional[Tuple[float, float]]:
    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1, "countrycodes": "vn"})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "heritage-planner/1.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None
    return None


def _cluster_sites(sites: List[PlannerSite], num_days: int, warnings: List[str]) -> List[List[PlannerSite]]:
    if num_days <= 1:
        return [sites]
    if num_days >= len(sites):
        return [[site] for site in sites] + [[] for _ in range(num_days - len(sites))]
    if KMeans is None:
        warnings.append("sklearn KMeans unavailable; using latitude split for multi-day clustering")
        ordered = sorted(sites, key=lambda site: (site.lat or 0.0, site.lng or 0.0))
        return [ordered[i::num_days] for i in range(num_days)]

    coords = np.array([[site.lat, site.lng] for site in sites], dtype=float)
    labels = KMeans(n_clusters=num_days, random_state=0, n_init=10).fit_predict(coords)
    groups = [[site for site, label in zip(sites, labels) if label == day] for day in range(num_days)]
    return [sorted(group, key=lambda site: (site.lat or 0.0, site.lng or 0.0)) for group in groups]


def _partition_sites(
    start: PlannerPoint,
    end: PlannerPoint,
    sites: List[PlannerSite],
    request: RoutePlanRequest,
    warnings: List[str],
) -> List[List[PlannerSite]]:
    """Split sites across days using road-time costs, not raw lat/lng clusters."""
    num_days = max(1, request.num_days)
    if num_days <= 1:
        return [sites]
    if num_days >= len(sites):
        return [[site] for site in sites] + [[] for _ in range(num_days - len(sites))]

    points = [start] + [_site_point(site) for site in sites] + [end]
    try:
        _, durations = _fetch_table(points)
    except Exception as exc:
        warnings.append(f"road-cost partition failed ({exc}); falling back to geographic clustering")
        return _cluster_sites(sites, num_days, warnings)

    if len(sites) <= EXACT_PARTITION_MAX_SITES:
        return _exact_day_partition(sites, durations, num_days)
    warnings.append("large site set; using greedy insertion day partition instead of exact set partition")
    return _greedy_day_partition(sites, durations, num_days)


def _exact_day_partition(sites: List[PlannerSite], cost: List[List[float]], num_days: int) -> List[List[PlannerSite]]:
    site_count = len(sites)
    used_days = min(num_days, site_count)
    end_idx = site_count + 1
    full_mask = (1 << site_count) - 1

    dp = {}
    parent = {}
    for node in range(1, site_count + 1):
        mask = 1 << (node - 1)
        dp[(mask, node)] = cost[0][node]
        parent[(mask, node)] = 0

    for mask in range(1, full_mask + 1):
        for last in range(1, site_count + 1):
            if not mask & (1 << (last - 1)):
                continue
            prev_mask = mask ^ (1 << (last - 1))
            if prev_mask == 0:
                continue
            best_prev = min(
                (prev for prev in range(1, site_count + 1) if prev_mask & (1 << (prev - 1))),
                key=lambda prev: dp.get((prev_mask, prev), UNREACHABLE_COST) + cost[prev][last],
            )
            dp[(mask, last)] = dp[(prev_mask, best_prev)] + cost[best_prev][last]
            parent[(mask, last)] = best_prev

    subset_cost = [0.0] + [UNREACHABLE_COST] * full_mask
    subset_order: List[List[int]] = [[] for _ in range(full_mask + 1)]
    for mask in range(1, full_mask + 1):
        last = min(
            (node for node in range(1, site_count + 1) if mask & (1 << (node - 1))),
            key=lambda node: dp.get((mask, node), UNREACHABLE_COST) + cost[node][end_idx],
        )
        subset_cost[mask] = dp[(mask, last)] + cost[last][end_idx]
        order = []
        cursor = last
        cursor_mask = mask
        while cursor:
            order.append(cursor)
            prev = parent[(cursor_mask, cursor)]
            cursor_mask ^= 1 << (cursor - 1)
            cursor = prev
        subset_order[mask] = list(reversed(order))

    part_cost = [[UNREACHABLE_COST] * (full_mask + 1) for _ in range(used_days + 1)]
    part_parent: List[List[Optional[int]]] = [[None] * (full_mask + 1) for _ in range(used_days + 1)]
    part_cost[0][0] = 0.0
    for day in range(1, used_days + 1):
        for mask in range(1, full_mask + 1):
            if mask.bit_count() < day:
                continue
            sub = mask
            while sub:
                prev_mask = mask ^ sub
                if prev_mask.bit_count() >= day - 1:
                    candidate = part_cost[day - 1][prev_mask] + subset_cost[sub]
                    if candidate < part_cost[day][mask]:
                        part_cost[day][mask] = candidate
                        part_parent[day][mask] = sub
                sub = (sub - 1) & mask

    groups_masks = []
    mask = full_mask
    for day in range(used_days, 0, -1):
        sub = part_parent[day][mask]
        if sub is None:
            return _greedy_day_partition(sites, cost, num_days)
        groups_masks.append(sub)
        mask ^= sub
    groups_masks.reverse()

    groups = [[sites[node - 1] for node in subset_order[group_mask]] for group_mask in groups_masks]
    return groups + [[] for _ in range(num_days - used_days)]


def _greedy_day_partition(sites: List[PlannerSite], cost: List[List[float]], num_days: int) -> List[List[PlannerSite]]:
    site_count = len(sites)
    used_days = min(num_days, site_count)
    end_idx = site_count + 1
    nodes = list(range(1, site_count + 1))
    nodes.sort(key=lambda node: cost[0][node] + cost[node][end_idx], reverse=True)
    routes = [[node] for node in nodes[:used_days]]

    def route_cost(route: List[int]) -> float:
        path = [0] + route + [end_idx]
        return sum(cost[path[i]][path[i + 1]] for i in range(len(path) - 1))

    for node in nodes[used_days:]:
        best = None
        for day_idx, route in enumerate(routes):
            current = route_cost(route)
            for pos in range(len(route) + 1):
                candidate_route = route[:pos] + [node] + route[pos:]
                new_cost = route_cost(candidate_route)
                balance_penalty = current * 0.05
                score = (new_cost - current) + balance_penalty
                if best is None or score < best[0]:
                    best = (score, day_idx, pos)
        _, day_idx, pos = best
        routes[day_idx] = routes[day_idx][:pos] + [node] + routes[day_idx][pos:]

    optimized = [_two_opt_open(route, cost, end_idx) for route in routes]
    groups = [[sites[node - 1] for node in route] for route in optimized]
    return groups + [[] for _ in range(num_days - used_days)]


def _sequence_sites(
    start: PlannerPoint,
    end: PlannerPoint,
    sites: List[PlannerSite],
    request: RoutePlanRequest,
    warnings: List[str],
) -> Tuple[List[PlannerSite], List[int], List[List[float]], List[List[float]]]:
    points = [start] + [_site_point(site) for site in sites] + [end]
    distances, durations = _fetch_table(points)
    needs_constraints = _has_solver_constraints(request) or _has_time_window_constraints(sites, request)
    if len(sites) <= EXACT_TSP_MAX_SITES and not needs_constraints:
        order = _held_karp(durations, len(sites))
    elif pywrapcp is not None and routing_enums_pb2 is not None:
        order = _ortools_open_path(durations, distances, sites, request, warnings)
    else:
        warnings.append("OR-Tools is not installed; using nearest-neighbor + 2-opt heuristic without solver constraints")
        order = _heuristic_open_path(durations, len(sites))
    return [sites[i - 1] for i in order], order, durations, distances


def _fetch_table(points: List[PlannerPoint]) -> Tuple[List[List[float]], List[List[float]]]:
    coord_str = ";".join(f"{point.lng},{point.lat}" for point in points)
    url = f"{OSRM_BASE}/table/v1/driving/{coord_str}?annotations=distance,duration"
    data = _json_request(url)
    if data.get("code") != "Ok" or "distances" not in data or "durations" not in data:
        raise ValueError("OSRM table request failed")
    return _clean_matrix(data["distances"]), _clean_matrix(data["durations"])


def _fetch_route(points: List[PlannerPoint]) -> dict:
    coord_str = ";".join(f"{point.lng},{point.lat}" for point in points)
    url = f"{OSRM_BASE}/route/v1/driving/{coord_str}?overview=full&geometries=polyline&steps=true"
    data = _json_request(url)
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("OSRM route request failed")
    route = data["routes"][0]
    return {
        "distance_m": float(route.get("distance", 0.0)),
        "duration_s": float(route.get("duration", 0.0)),
        "polyline": route.get("geometry", ""),
        "legs": route.get("legs", []),
    }


def _json_request(url: str) -> dict:
    urls = [url]
    for base in OSRM_FALLBACK_BASES:
        if OSRM_BASE and url.startswith(OSRM_BASE) and base != OSRM_BASE:
            urls.append(base + url[len(OSRM_BASE):])

    last_error: Optional[Exception] = None
    for candidate in dict.fromkeys(urls):
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": "heritage-planner/1.0"})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            last_error = exc
    raise ValueError(str(last_error) if last_error else "request failed")


def _clean_matrix(matrix: List[List[Optional[float]]]) -> List[List[float]]:
    return [[float(value) if value is not None else UNREACHABLE_COST for value in row] for row in matrix]


def _held_karp(cost: List[List[float]], site_count: int) -> List[int]:
    if site_count == 0:
        return []
    full_mask = (1 << site_count) - 1
    dp = {}
    parent = {}
    for idx in range(1, site_count + 1):
        mask = 1 << (idx - 1)
        dp[(mask, idx)] = cost[0][idx]
        parent[(mask, idx)] = 0

    for mask in range(1, full_mask + 1):
        for last in range(1, site_count + 1):
            if not mask & (1 << (last - 1)):
                continue
            prev_mask = mask ^ (1 << (last - 1))
            if prev_mask == 0:
                continue
            best_prev = min(
                (prev for prev in range(1, site_count + 1) if prev_mask & (1 << (prev - 1))),
                key=lambda prev: dp.get((prev_mask, prev), UNREACHABLE_COST) + cost[prev][last],
            )
            dp[(mask, last)] = dp[(prev_mask, best_prev)] + cost[best_prev][last]
            parent[(mask, last)] = best_prev

    end_idx = site_count + 1
    last = min(range(1, site_count + 1), key=lambda idx: dp[(full_mask, idx)] + cost[idx][end_idx])
    order = []
    mask = full_mask
    while last:
        order.append(last)
        prev = parent[(mask, last)]
        mask ^= 1 << (last - 1)
        last = prev
    return list(reversed(order))


def _heuristic_open_path(cost: List[List[float]], site_count: int) -> List[int]:
    unvisited = set(range(1, site_count + 1))
    order = []
    current = 0
    while unvisited:
        nxt = min(unvisited, key=lambda idx: cost[current][idx])
        order.append(nxt)
        unvisited.remove(nxt)
        current = nxt
    return _two_opt_open(order, cost, site_count + 1)


def _ortools_open_path(
    durations: List[List[float]],
    distances: List[List[float]],
    sites: List[PlannerSite],
    request: RoutePlanRequest,
    warnings: List[str],
) -> List[int]:
    site_count = len(sites)
    end_idx = site_count + 1
    manager = pywrapcp.RoutingIndexManager(len(durations), 1, [0], [end_idx])
    routing = pywrapcp.RoutingModel(manager)

    def duration_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        service_seconds = 0
        if 1 <= from_node <= site_count:
            service_seconds = sites[from_node - 1].visit_duration_min * 60
        return int(durations[from_node][to_node] + service_seconds)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(distances[from_node][to_node])

    transit_callback_index = routing.RegisterTransitCallback(duration_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    if request.constraints.max_total_distance_km is not None:
        distance_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.AddDimension(
            distance_callback_index,
            0,
            int(request.constraints.max_total_distance_km * 1000),
            True,
            "Distance",
        )

    start_sec = _time_seconds(request.available_window.start_time)
    end_sec = _time_seconds(request.available_window.end_time)
    if end_sec < start_sec:
        end_sec += 24 * 3600
    latest_end_sec = end_sec
    if request.constraints.max_total_duration_min is not None:
        latest_end_sec = min(latest_end_sec, start_sec + request.constraints.max_total_duration_min * 60)
    horizon = max(latest_end_sec, end_sec, start_sec) + 24 * 3600
    routing.AddDimension(transit_callback_index, horizon, horizon, False, "Time")
    time_dimension = routing.GetDimensionOrDie("Time")
    time_dimension.CumulVar(routing.Start(0)).SetRange(start_sec, start_sec)
    time_dimension.CumulVar(routing.End(0)).SetRange(start_sec, latest_end_sec)
    for node, site in enumerate(sites, start=1):
        open_sec, close_sec = _window_seconds_relative(site.open_time, site.close_time, start_sec)
        latest_arrival_sec = close_sec - site.visit_duration_min * 60
        if latest_arrival_sec < open_sec:
            latest_arrival_sec = close_sec
            warnings.append(f"{site.name} visit_duration exceeds its open_time/close_time window")
        index = manager.NodeToIndex(node)
        try:
            time_dimension.CumulVar(index).SetRange(open_sec, latest_arrival_sec)
        except Exception:
            warnings.append(f"{site.name} has an incompatible time window for OR-Tools; solver may fail")

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.seconds = ORTOOLS_TIME_LIMIT_SECONDS

    solution = routing.SolveWithParameters(search)
    if solution is None:
        warnings.append("OR-Tools did not find a solution; using nearest-neighbor + 2-opt heuristic")
        return _heuristic_open_path(durations, site_count)

    order: List[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if 1 <= node <= site_count:
            order.append(node)
        index = solution.Value(routing.NextVar(index))
    return order


def _has_solver_constraints(request: RoutePlanRequest) -> bool:
    return (
        request.constraints.max_total_distance_km is not None
        or request.constraints.max_total_duration_min is not None
    )


def _has_time_window_constraints(sites: List[PlannerSite], request: RoutePlanRequest) -> bool:
    start_sec = _time_seconds(request.available_window.start_time)
    end_sec = _time_seconds(request.available_window.end_time)
    if end_sec < start_sec:
        end_sec += 24 * 3600
    for site in sites:
        open_sec, close_sec = _window_seconds_relative(site.open_time, site.close_time, start_sec)
        if open_sec > start_sec or close_sec < end_sec:
            return True
    return False


def _two_opt_open(order: List[int], cost: List[List[float]], end_idx: int) -> List[int]:
    def total(seq: List[int]) -> float:
        path = [0] + seq + [end_idx]
        return sum(cost[path[i]][path[i + 1]] for i in range(len(path) - 1))

    best = order[:]
    best_cost = total(best)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                candidate_cost = total(candidate)
                if candidate_cost < best_cost:
                    best = candidate
                    best_cost = candidate_cost
                    improved = True
                    break
            if improved:
                break
    return best


def _route_legs(route: dict, matrix_order: List[int], distances: List[List[float]], durations: List[List[float]]):
    legs = route.get("legs", [])
    expected_count = len(matrix_order) - 1
    if len(legs) == expected_count:
        return [float(leg.get("distance", 0.0)) for leg in legs], [float(leg.get("duration", 0.0)) for leg in legs]
    return (
        [distances[matrix_order[i]][matrix_order[i + 1]] for i in range(expected_count)],
        [durations[matrix_order[i]][matrix_order[i + 1]] for i in range(expected_count)],
    )


def _build_stops(
    ordered: List[PlannerSite],
    leg_distances: List[float],
    leg_durations: List[float],
    start_time: str,
    warnings: List[str],
) -> Tuple[List[RoutePlanStop], float]:
    current = _parse_time(start_time)
    day_start = current
    stops: List[RoutePlanStop] = []
    for idx, site in enumerate(ordered):
        current += timedelta(seconds=leg_durations[idx])
        current = _wait_until_open(current, site.open_time, site.close_time)
        arrival = current
        departure = arrival + timedelta(minutes=site.visit_duration_min)
        if not _within_site_window(arrival, departure, site.open_time, site.close_time):
            warnings.append(f"{site.name} is scheduled outside its open_time/close_time window")
        stops.append(RoutePlanStop(
            site_id=site.id,
            name=site.name,
            arrival_time=arrival.strftime("%H:%M"),
            departure_time=departure.strftime("%H:%M"),
            travel_from_prev_km=round(leg_distances[idx] / 1000, 2),
            travel_from_prev_min=math.ceil(leg_durations[idx] / 60),
            reason=_site_reason(site),
        ))
        current = departure
    if len(leg_durations) > len(ordered):
        current += timedelta(seconds=leg_durations[len(ordered)])
    return stops, max(0.0, (current - day_start).total_seconds())


def _status_for_limits(distance_km: float, duration_min: int, request: RoutePlanRequest, warnings: List[str]) -> str:
    status = "feasible"
    window_min = _window_minutes(request.available_window.start_time, request.available_window.end_time)
    if duration_min > window_min * max(1, request.num_days):
        status = "over_time_budget"
        warnings.append("itinerary exceeds available_window; drop low-priority sites or add another day")
    if request.constraints.max_total_distance_km is not None and distance_km > request.constraints.max_total_distance_km:
        status = "over_time_budget"
        warnings.append("itinerary exceeds max_total_distance_km")
    if request.constraints.max_total_duration_min is not None and duration_min > request.constraints.max_total_duration_min:
        status = "over_time_budget"
        warnings.append("itinerary exceeds max_total_duration_min")
    return status


def _site_point(site: PlannerSite) -> PlannerPoint:
    return PlannerPoint(id=site.id, lat=site.lat, lng=site.lng, label=site.name)


def _site_reason(site: PlannerSite) -> str:
    labels = {
        "history": "giá trị lịch sử",
        "architecture": "kiến trúc đặc sắc",
        "spiritual": "không gian tâm linh",
        "museum": "tư liệu trưng bày",
        "unesco": "giá trị di sản được công nhận",
        "craft_village": "trải nghiệm văn hóa làng nghề",
        "nature": "cảnh quan tự nhiên",
    }
    traits = [labels.get(cat, cat) for cat in site.categories[:2]]
    if site.historical_importance_score >= 0.8:
        traits.append("ý nghĩa lịch sử nổi bật")
    if site.popularity_score >= 0.8:
        traits.append("phù hợp làm điểm nhấn hành trình")
    if not traits:
        traits.append("phù hợp với tuyến di sản đã chọn")
    return "Chọn điểm này vì " + ", ".join(dict.fromkeys(traits)) + "."


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value or "08:00", "%H:%M")


def _window_minutes(start: str, end: str) -> int:
    start_dt = _parse_time(start)
    end_dt = _parse_time(end)
    if end_dt < start_dt:
        end_dt += timedelta(days=1)
    return max(0, int((end_dt - start_dt).total_seconds() // 60))


def _time_seconds(value: str) -> int:
    parsed = _parse_time(value)
    return parsed.hour * 3600 + parsed.minute * 60


def _window_seconds_relative(open_time: str, close_time: str, reference_start_sec: int) -> Tuple[int, int]:
    open_sec = _time_seconds(open_time)
    close_sec = _time_seconds(close_time)
    if close_sec < open_sec:
        close_sec += 24 * 3600
    if close_sec < reference_start_sec:
        open_sec += 24 * 3600
        close_sec += 24 * 3600
    return open_sec, close_sec


def _wait_until_open(current: datetime, open_time: str, close_time: str) -> datetime:
    try:
        open_dt = _parse_time(open_time)
        close_dt = _parse_time(close_time)
    except ValueError:
        return current
    open_dt = current.replace(hour=open_dt.hour, minute=open_dt.minute, second=0, microsecond=0)
    close_dt = current.replace(hour=close_dt.hour, minute=close_dt.minute, second=0, microsecond=0)
    if close_dt < open_dt:
        close_dt += timedelta(days=1)
    if current > close_dt:
        open_dt += timedelta(days=1)
    if current < open_dt:
        return open_dt
    return current


def _within_site_window(arrival: datetime, departure: datetime, open_time: str, close_time: str) -> bool:
    try:
        open_dt = _parse_time(open_time)
        close_dt = _parse_time(close_time)
    except ValueError:
        return True
    open_dt = arrival.replace(hour=open_dt.hour, minute=open_dt.minute, second=0, microsecond=0)
    close_dt = arrival.replace(hour=close_dt.hour, minute=close_dt.minute, second=0, microsecond=0)
    if close_dt < open_dt:
        close_dt += timedelta(days=1)
    return open_dt <= arrival <= close_dt and departure <= close_dt

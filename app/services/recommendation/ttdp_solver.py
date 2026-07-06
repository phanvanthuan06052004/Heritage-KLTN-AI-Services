"""
Tourist Trip Design Problem (TTDP) Solver using Google OR-Tools.
Formulated as an Orienteering Problem with Time Windows (OPTW).
"""
import math
import logging
from typing import List, Tuple, Optional
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import numpy as np

log = logging.getLogger("ttdp_solver")

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def solve_ttdp(
    locations: List[Tuple[float, float]], # 0 is start, 1 is end, 2..N+1 are POIs
    scores: List[float], # score for each node
    durations: List[int], # time to spend at each node (seconds)
    time_windows: List[Tuple[int, int]], # (min_sec, max_sec) for each node
    num_days: int,
    max_time_per_day: int,
    speed_kmh: float = 40.0,
    time_limit_sec: int = 3
) -> List[List[int]]:
    """
    Solves TTDP using OR-Tools Routing.
    Maximizes score collected across `num_days`.
    Returns a list of routes. Each route is a list of node indices (excluding start/end).
    """
    N = len(locations)
    if N <= 2:
        return [[] for _ in range(num_days)]

    # Compute time matrix (seconds)
    time_matrix = np.zeros((N, N), dtype=int)
    for i in range(N):
        for j in range(N):
            if i != j:
                dist_m = haversine(locations[i][0], locations[i][1], locations[j][0], locations[j][1])
                time_s = int((dist_m / 1000.0) / speed_kmh * 3600)
                time_matrix[i][j] = time_s

    manager = pywrapcp.RoutingIndexManager(N, num_days, [0] * num_days, [1] * num_days)
    routing = pywrapcp.RoutingModel(manager)

    # Transit callback
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(time_matrix[from_node][to_node] + durations[from_node])

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    
    # We set arc costs to a small fraction of travel time just so it prefers shorter paths if scores are equal.
    def cost_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(time_matrix[from_node][to_node])
    
    cost_callback_index = routing.RegisterTransitCallback(cost_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(cost_callback_index)

    # Time dimension
    time = "Time"
    routing.AddDimension(
        transit_callback_index,
        3600, # allow waiting time up to 1 hour
        max_time_per_day,
        False, 
        time
    )
    time_dimension = routing.GetDimensionOrDie(time)

    # Time Windows
    for node, (tw_start, tw_end) in enumerate(time_windows):
        index = manager.NodeToIndex(node)
        if index == -1: # Exclude end nodes
            continue
        time_dimension.CumulVar(index).SetRange(tw_start, tw_end)

    # Disjunctions for optional POIs
    # Penalty = Score * 1,000,000. We want to maximize score.
    # Travel cost is just seconds (e.g. 3600). So dropping a node with score 0.5 costs 500,000.
    for node in range(2, N):
        penalty = int(scores[node] * 1000000)
        # Must-visit sites can be simulated by giving them huge penalty or score > 1.0
        routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_parameters.time_limit.seconds = time_limit_sec
    search_parameters.log_search = False

    solution = routing.SolveWithParameters(search_parameters)

    routes = []
    if solution:
        for vehicle_id in range(num_days):
            index = routing.Start(vehicle_id)
            route = []
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0 and node != 1:
                    route.append(node)
                index = solution.Value(routing.NextVar(index))
            routes.append(route)
    else:
        # Fallback if no solution found (e.g., impossible time windows)
        log.warning("OR-Tools failed to find a valid route.")
        routes = [[] for _ in range(num_days)]
    
    return routes

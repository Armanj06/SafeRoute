"""A* route search with an admissible coordinate-scaled heuristic."""
from __future__ import annotations

import heapq
from itertools import count
from typing import Any

from app.algorithms.common import (
    COST_MODELS, coordinate_heuristic_scale, edge_cost, failure,
    heuristic_to_nearest_exit, prepare_graph, reconstruct_result,
)


def find_astar_route(
    building: dict[str, Any], starting_room: str,
    blocked_corridors: set[str] | None = None,
    unavailable_exits: set[str] | None = None,
    unsafe_locations: set[str] | None = None,
    cost_model: str = "distance",
    metrics: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Find a minimum-cost route; incomplete coordinates safely use h(n)=0."""
    if cost_model not in COST_MODELS:
        raise ValueError(f"Unsupported cost model '{cost_model}'. Use distance or travel_time.")
    nodes, adjacency, exits, early_result = prepare_graph(
        building, starting_room, blocked_corridors, unavailable_exits, unsafe_locations
    )
    if early_result:
        return failure(early_result["status"], early_result["message"], "astar", starting_room, cost_model)

    scale = coordinate_heuristic_scale(nodes, adjacency, cost_model)
    heuristic = lambda node_id: heuristic_to_nearest_exit(node_id, exits, nodes, scale)
    order = count()
    queue = [(heuristic(starting_room), next(order), 0.0, starting_room)]
    costs = {starting_room: 0.0}
    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    while queue:
        _, _, current_cost, current = heapq.heappop(queue)
        if current_cost != costs.get(current):
            continue
        if metrics is not None:
            metrics["nodes_expanded"] = metrics.get("nodes_expanded", 0) + 1
        if current in exits:
            return reconstruct_result(building, starting_room, current, previous, "astar", cost_model)
        for neighbor, corridor in adjacency[current]:
            candidate = current_cost + edge_cost(corridor, cost_model)
            if candidate < costs.get(neighbor, float("inf")):
                costs[neighbor] = candidate
                previous[neighbor] = (current, corridor)
                heapq.heappush(queue, (candidate + heuristic(neighbor), next(order), candidate, neighbor))
    return failure("unreachable", "No valid route to an available exit exists.", "astar", starting_room, cost_model)

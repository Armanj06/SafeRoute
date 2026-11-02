"""Dijkstra's minimum-cost route search, implemented with a priority queue."""
from __future__ import annotations

import heapq
from itertools import count
from typing import Any

from app.algorithms.common import COST_MODELS, edge_cost, failure, prepare_graph, reconstruct_result


def find_dijkstra_route(
    building: dict[str, Any], starting_room: str,
    blocked_corridors: set[str] | None = None,
    unavailable_exits: set[str] | None = None,
    unsafe_locations: set[str] | None = None,
    cost_model: str = "distance",
    metrics: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Find the lowest distance or estimated-time route to any available exit."""
    if cost_model not in COST_MODELS:
        raise ValueError(f"Unsupported cost model '{cost_model}'. Use distance or travel_time.")
    nodes, adjacency, exits, early_result = prepare_graph(
        building, starting_room, blocked_corridors, unavailable_exits, unsafe_locations
    )
    if early_result:
        return failure(early_result["status"], early_result["message"], "dijkstra", starting_room, cost_model)

    order = count()
    queue = [(0.0, next(order), starting_room)]
    costs = {starting_room: 0.0}
    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    while queue:
        current_cost, _, current = heapq.heappop(queue)
        if current_cost != costs.get(current):
            continue
        if metrics is not None:
            metrics["nodes_expanded"] = metrics.get("nodes_expanded", 0) + 1
        if current in exits:
            return reconstruct_result(building, starting_room, current, previous, "dijkstra", cost_model)
        for neighbor, corridor in adjacency[current]:
            candidate = current_cost + edge_cost(corridor, cost_model)
            if candidate < costs.get(neighbor, float("inf")):
                costs[neighbor] = candidate
                previous[neighbor] = (current, corridor)
                heapq.heappush(queue, (candidate, next(order), neighbor))
    return failure("unreachable", "No valid route to an available exit exists.", "dijkstra", starting_room, cost_model)

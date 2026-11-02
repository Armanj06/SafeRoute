"""Breadth-first search for a route through an unweighted building graph."""
from collections import deque
from typing import Any

from app.algorithms.common import COST_MODELS, failure, prepare_graph, reconstruct_result


def find_evacuation_route(
    building: dict[str, Any], starting_room: str,
    blocked_corridors: set[str] | None = None,
    unavailable_exits: set[str] | None = None,
    unsafe_locations: set[str] | None = None,
    cost_model: str = "distance",
    metrics: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Return the route with the fewest corridor segments to a usable exit.

    BFS minimizes segment count, irrespective of edge weights. ``cost_model``
    controls the reported total cost; use Dijkstra/A* to minimize that cost.
    """
    if cost_model not in COST_MODELS:
        raise ValueError(f"Unsupported cost model '{cost_model}'. Use distance or travel_time.")
    nodes, adjacency, exits, early_result = prepare_graph(
        building, starting_room, blocked_corridors, unavailable_exits, unsafe_locations
    )
    if early_result:
        return failure(early_result["status"], early_result["message"], "bfs", starting_room, cost_model)

    queue = deque([starting_room])
    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    visited = {starting_room}
    while queue:
        current = queue.popleft()
        if metrics is not None:
            metrics["nodes_expanded"] = metrics.get("nodes_expanded", 0) + 1
        if current in exits:
            return reconstruct_result(building, starting_room, current, previous, "bfs", cost_model)
        for neighbor, corridor in adjacency[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                previous[neighbor] = (current, corridor)
                queue.append(neighbor)
    return failure("unreachable", "No valid route to an available exit exists.", "bfs", starting_room, cost_model)

"""Bounded best-first generation of simple candidate routes by travel time."""
from __future__ import annotations

import heapq
from itertools import count
from typing import Any

from app.algorithms.common import edge_cost, prepare_graph


def generate_candidate_routes(
    building: dict[str, Any], starting_room: str,
    blocked_corridors: set[str] | None = None,
    unavailable_exits: set[str] | None = None,
    unsafe_locations: set[str] | None = None,
    accessibility: dict[str, Any] | None = None,
    candidate_limit: int = 12,
    expansion_limit: int = 5000,
) -> dict[str, Any]:
    """Return up to ``candidate_limit`` simple paths, ordered by travel time.

    The expansion cap makes path search finite even for highly connected
    buildings. Results are candidate alternatives, not an exhaustive path set.
    """
    nodes, adjacency, exits, error = prepare_graph(
        building, starting_room, blocked_corridors, unavailable_exits, unsafe_locations
    )
    if error:
        return {"candidates": [], "complete": True, "message": error["message"], "status": error["status"], "expanded": 0}

    requirements = accessibility or {}
    step_free_required = bool(requirements.get("step_free", False))
    minimum_width = requirements.get("minimum_width_m")

    def corridor_is_accessible(corridor: dict[str, Any]) -> bool:
        if step_free_required and corridor.get("step_free") is not True:
            return False
        if minimum_width is not None:
            try:
                if float(corridor.get("clear_width_m", 0)) < float(minimum_width):
                    return False
            except (TypeError, ValueError):
                return False
        return True

    # Apply access constraints before path enumeration; inaccessible edges are
    # infeasible, not merely assigned a low score.
    filtered: dict[str, list[tuple[str, dict[str, Any]]]] = {
        node_id: [(neighbor, edge) for neighbor, edge in edges if corridor_is_accessible(edge)]
        for node_id, edges in adjacency.items()
    }
    serial = count()
    queue: list[tuple[float, int, tuple[str, ...], tuple[dict[str, Any], ...]]] = [
        (0.0, next(serial), (starting_room,), ())
    ]
    candidates: list[dict[str, Any]] = []
    expanded = 0
    while queue and len(candidates) < candidate_limit and expanded < expansion_limit:
        elapsed, _, route, used_corridors = heapq.heappop(queue)
        current = route[-1]
        expanded += 1
        if current in exits:
            candidates.append({
                "route": list(route),
                "corridors": [edge["id"] for edge in used_corridors],
                "_edges": list(used_corridors),
                "distance": sum(float(edge.get("distance", 0)) for edge in used_corridors),
                "estimated_travel_time_seconds": elapsed,
            })
            continue
        visited = set(route)
        for neighbor, corridor in filtered.get(current, []):
            if neighbor in visited:
                continue
            next_elapsed = elapsed + edge_cost(corridor, "travel_time")
            heapq.heappush(
                queue,
                (next_elapsed, next(serial), (*route, neighbor), (*used_corridors, corridor)),
            )

    return {
        "candidates": candidates,
        "complete": not queue,
        "message": "" if candidates else "No route satisfies the safety and accessibility constraints.",
        "status": "found" if candidates else "no_feasible_route",
        "expanded": expanded,
    }

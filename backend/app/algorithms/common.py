"""Shared graph preparation, costs, and route reconstruction helpers."""
from __future__ import annotations

from math import hypot, isfinite
from typing import Any

COST_MODELS = {"distance", "travel_time"}
DEFAULT_WALKING_SPEED_METERS_PER_SECOND = 1.2


def edge_cost(corridor: dict[str, Any], cost_model: str) -> float:
    if cost_model == "distance":
        value = corridor.get("distance", 0)
    elif cost_model == "travel_time":
        value = corridor.get(
            "travel_time_seconds",
            float(corridor.get("distance", 0)) / DEFAULT_WALKING_SPEED_METERS_PER_SECOND,
        )
    else:
        raise ValueError(f"Unsupported cost model '{cost_model}'. Use distance or travel_time.")
    try:
        cost = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Corridor '{corridor.get('id', '?')}' has an invalid {cost_model} cost.") from error
    if not isfinite(cost) or cost < 0:
        raise ValueError(f"Corridor '{corridor.get('id', '?')}' costs must be finite and non-negative.")
    return cost


def prepare_graph(
    building: dict[str, Any],
    starting_room: str,
    blocked_corridors: set[str] | None = None,
    unavailable_exits: set[str] | None = None,
    unsafe_locations: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, list[tuple[str, dict[str, Any]]]], set[str], dict[str, Any] | None]:
    """Build an undirected adjacency list and validate the requested start."""
    nodes = {node["id"]: node for node in building.get("nodes", [])}
    blocked = blocked_corridors or set()
    unavailable = unavailable_exits or set()
    unsafe = unsafe_locations or set()
    if starting_room not in nodes:
        return nodes, {}, set(), failure("invalid_start", f"Starting room '{starting_room}' was not found.")
    if nodes[starting_room].get("type") not in {"room", "area"}:
        return nodes, {}, set(), failure("invalid_start", f"Starting location '{starting_room}' is not a routable room or functional area.")
    if starting_room in unsafe or nodes[starting_room].get("unsafe"):
        return nodes, {}, set(), failure("unsafe_start", f"Starting room '{starting_room}' is marked unsafe.")

    exits = {
        node_id for node_id, node in nodes.items()
        if node.get("type") == "exit"
        and node_id not in unavailable
        and node_id not in unsafe
        and not node.get("unsafe")
    }
    if not exits:
        return nodes, {}, set(), failure("no_available_exits", "No available exits are configured.")

    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = {node_id: [] for node_id in nodes}
    for corridor in building.get("corridors", []):
        corridor_id = corridor["id"]
        a, b = corridor["from"], corridor["to"]
        if (
            corridor.get("blocked") or corridor.get("unsafe")
            or corridor_id in blocked or corridor_id in unsafe
            or a in unsafe or b in unsafe
            or nodes.get(a, {}).get("unsafe") or nodes.get(b, {}).get("unsafe")
        ):
            continue
        if a in adjacency and b in adjacency:
            adjacency[a].append((b, corridor))
            adjacency[b].append((a, corridor))
    return nodes, adjacency, exits, None


def failure(status: str, message: str, algorithm: str = "", starting_room: str = "", cost_model: str = "distance") -> dict[str, Any]:
    return {
        "found": False,
        "status": status,
        "message": message,
        "algorithm": algorithm,
        "starting_room": starting_room,
        "exit": None,
        "route": [],
        "corridors": [],
        "distance": 0,
        "estimated_travel_time_seconds": 0,
        "total_cost": None,
        "cost_model": cost_model,
        "segments": 0,
    }


def reconstruct_result(
    building: dict[str, Any], starting_room: str, destination: str,
    previous: dict[str, tuple[str, dict[str, Any]]], algorithm: str, cost_model: str,
) -> dict[str, Any]:
    route = [destination]
    used_corridors = []
    current = destination
    while current != starting_room:
        parent, corridor = previous[current]
        used_corridors.append(corridor)
        route.append(parent)
        current = parent
    route.reverse()
    used_corridors.reverse()
    distance = sum(float(corridor.get("distance", 0)) for corridor in used_corridors)
    travel_time = sum(
        edge_cost(corridor, "travel_time") for corridor in used_corridors
    )
    return {
        "found": True,
        "status": "found",
        "message": "Evacuation route found.",
        "algorithm": algorithm,
        "starting_room": starting_room,
        "exit": destination,
        "route": route,
        "corridors": [corridor["id"] for corridor in used_corridors],
        "distance": distance,
        "estimated_travel_time_seconds": travel_time,
        "total_cost": sum(edge_cost(corridor, cost_model) for corridor in used_corridors),
        "cost_model": cost_model,
        "segments": len(used_corridors),
    }


def coordinate_heuristic_scale(
    nodes: dict[str, Any], adjacency: dict[str, list[tuple[str, dict[str, Any]]]],
    cost_model: str,
) -> float:
    """Return a safe cost-per-coordinate-unit lower bound, or zero if unsure.

    Scaling Euclidean coordinate distance by the smallest edge cost / geometric
    edge length keeps the heuristic admissible by the triangle inequality.
    Missing coordinates force the safe Dijkstra-equivalent zero heuristic.
    """
    if not nodes or any(not all(isinstance(node.get(k), (int, float)) for k in ("x", "y")) for node in nodes.values()):
        return 0.0
    ratios: list[float] = []
    checked: set[str] = set()
    for source, neighbors in adjacency.items():
        for target, corridor in neighbors:
            if corridor["id"] in checked:
                continue
            checked.add(corridor["id"])
            geometric = hypot(nodes[source]["x"] - nodes[target]["x"], nodes[source]["y"] - nodes[target]["y"])
            if geometric > 0:
                ratios.append(edge_cost(corridor, cost_model) / geometric)
    return min(ratios, default=0.0)


def heuristic_to_nearest_exit(node_id: str, exits: set[str], nodes: dict[str, Any], scale: float) -> float:
    if scale <= 0:
        return 0.0
    node = nodes[node_id]
    return min(
        hypot(node["x"] - nodes[exit_id]["x"], node["y"] - nodes[exit_id]["y"])
        * scale
        for exit_id in exits
    )

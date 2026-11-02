"""Public route algorithm selection used by the API."""
from typing import Any

from app.algorithms.astar import find_astar_route
from app.algorithms.bfs import find_evacuation_route
from app.algorithms.dijkstra import find_dijkstra_route

ALGORITHMS = {"bfs", "dijkstra", "astar"}


def find_route(building: dict[str, Any], starting_room: str, algorithm: str = "bfs", **options: Any) -> dict[str, Any]:
    normalized = algorithm.lower()
    if normalized not in ALGORITHMS:
        choices = ", ".join(sorted(ALGORITHMS))
        raise ValueError(f"Unsupported algorithm '{algorithm}'. Choose one of: {choices}.")
    search = {
        "bfs": find_evacuation_route,
        "dijkstra": find_dijkstra_route,
        "astar": find_astar_route,
    }[normalized]
    return search(building, starting_room, **options)

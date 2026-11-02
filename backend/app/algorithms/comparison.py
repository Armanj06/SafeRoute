"""Comparable route runs over one graph snapshot and one safety condition set."""
from __future__ import annotations

from time import perf_counter_ns
from typing import Any

from app.agents.utility_agent import choose_utility_route
from app.algorithms.routing import find_route


def compare_routes(
    building: dict[str, Any], starting_room: str, cost_model: str = "distance",
    blocked_corridors: set[str] | None = None,
    unavailable_exits: set[str] | None = None,
    unsafe_locations: set[str] | None = None,
    accessibility: dict[str, Any] | None = None,
    preference_weights: dict[str, float] | None = None,
    candidate_limit: int = 12,
) -> dict[str, Any]:
    """Compare BFS, Dijkstra, A*, and a separately labeled utility strategy.

    `nodes_expanded` counts valid nodes removed from each shortest-path
    frontier. Utility search expands path candidates instead, so it reports
    `candidate_states_expanded` and never calls that count graph nodes.
    """
    common = {
        "blocked_corridors": blocked_corridors or set(),
        "unavailable_exits": unavailable_exits or set(),
        "unsafe_locations": unsafe_locations or set(),
        "cost_model": cost_model,
    }
    results = []
    for algorithm in ("bfs", "dijkstra", "astar"):
        metrics: dict[str, int] = {"nodes_expanded": 0}
        started = perf_counter_ns()
        route = find_route(building, starting_room, algorithm=algorithm, metrics=metrics, **common)
        elapsed_ms = (perf_counter_ns() - started) / 1_000_000
        results.append({
            **route,
            "strategy_type": "shortest_path",
            "nodes_expanded": metrics["nodes_expanded"],
            "duration_ms": elapsed_ms,
        })

    started = perf_counter_ns()
    utility = choose_utility_route(
        building, starting_room,
        accessibility=accessibility,
        preference_weights=preference_weights,
        blocked_corridors=common["blocked_corridors"],
        unavailable_exits=common["unavailable_exits"],
        unsafe_locations=common["unsafe_locations"],
        candidate_limit=candidate_limit,
    )
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    results.append({
        **utility,
        "strategy_type": "utility_agent",
        "nodes_expanded": None,
        "candidate_states_expanded": utility.get("search_states_expanded"),
        "duration_ms": elapsed_ms,
    })
    return {
        "starting_room": starting_room,
        "cost_model": cost_model,
        "results": results,
        "methodology": {
            "graph_snapshot_shared": True,
            "safety_conditions_shared": True,
            "nodes_expanded_definition": "Valid frontier nodes removed before checking whether they are a goal.",
            "duration_definition": "Measured algorithm call time in milliseconds; small graphs may be dominated by timer/runtime noise.",
            "utility_comparison": "Utility agent is a separate bounded multi-factor strategy, not a shortest-path optimum. Its expanded count is candidate states, not graph nodes.",
        },
    }

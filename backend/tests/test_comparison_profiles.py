"""Regression checks for honest route timing and isolated teaching examples."""
from copy import deepcopy

import pytest
from fastapi import HTTPException
from app.api.routes import RouteComparisonRequest, compare_route_algorithms
from app.services.building import load_building


def test_identical_corridor_paths_share_the_same_travel_estimate():
    response = compare_route_algorithms(RouteComparisonRequest(starting_room="room-101"))
    results = response["results"]
    assert len(results) == 4
    assert len({tuple(route["corridors"]) for route in results}) == 1
    assert all(route["distance"] == 60 for route in results)
    assert all(route["estimated_travel_time_seconds"] == 50 for route in results)
    assert all(route["duration_ms"] >= 0 for route in results)


def test_slow_north_example_changes_route_choices_without_mutating_source():
    before = deepcopy(load_building())
    response = compare_route_algorithms(RouteComparisonRequest(
        starting_room="room-101", cost_model="travel_time", comparison_profile="slow_north",
    ))
    routes = {route["algorithm"]: route for route in response["results"]}
    assert routes["bfs"]["exit"] == "exit-north"
    assert routes["bfs"]["estimated_travel_time_seconds"] == pytest.approx(213.33)
    for name in ("dijkstra", "astar"):
        assert routes[name]["exit"] == "exit-south"
        assert routes[name]["distance"] == 88
        assert routes[name]["estimated_travel_time_seconds"] == pytest.approx(73.33)
    assert routes["dijkstra"]["total_cost"] == routes["astar"]["total_cost"]
    assert load_building() == before
    assert response["comparison_profile"] == "slow_north"
    assert "Teaching example" in response["example_description"]
    # A later ordinary request must still see the unmodified baseline time.
    current = compare_route_algorithms(RouteComparisonRequest(starting_room="room-101"))
    assert all(route["estimated_travel_time_seconds"] == 50 for route in current["results"])


def test_teaching_example_requires_the_time_objective():
    with pytest.raises(HTTPException) as raised:
        compare_route_algorithms(RouteComparisonRequest(
            starting_room="room-101", comparison_profile="slow_north", cost_model="distance",
        ))
    assert raised.value.status_code == 422

import pytest

from app.algorithms.astar import find_astar_route
from app.algorithms.bfs import find_evacuation_route
from app.algorithms.dijkstra import find_dijkstra_route
from app.algorithms.routing import find_route


def weighted_graph():
    return {
        "nodes": [
            {"id": "start", "type": "room", "x": 0, "y": 0},
            {"id": "north", "type": "junction", "x": 0, "y": 1},
            {"id": "east", "type": "junction", "x": 1, "y": 1},
            {"id": "exit", "type": "exit", "x": 2, "y": 0},
            {"id": "exit-alt", "type": "exit", "x": 0, "y": 3},
        ],
        "corridors": [
            # BFS prefers this one-edge route; weighted searches should not.
            {"id": "direct", "from": "start", "to": "exit", "distance": 10, "travel_time_seconds": 20},
            {"id": "s-n", "from": "start", "to": "north", "distance": 1, "travel_time_seconds": 1},
            {"id": "n-e", "from": "north", "to": "east", "distance": 1, "travel_time_seconds": 1},
            {"id": "e-exit", "from": "east", "to": "exit", "distance": 1.5, "travel_time_seconds": 1},
            {"id": "n-alt", "from": "north", "to": "exit-alt", "distance": 8, "travel_time_seconds": 9},
        ],
    }


def test_bfs_and_dijkstra_choose_different_routes():
    graph = weighted_graph()
    bfs = find_evacuation_route(graph, "start")
    dijkstra = find_dijkstra_route(graph, "start")
    assert bfs["corridors"] == ["direct"]
    assert dijkstra["corridors"] == ["s-n", "n-e", "e-exit"]
    assert dijkstra["total_cost"] < bfs["total_cost"]


def test_dijkstra_and_astar_find_same_optimal_cost():
    graph = weighted_graph()
    dijkstra = find_dijkstra_route(graph, "start")
    astar = find_astar_route(graph, "start")
    assert astar["total_cost"] == pytest.approx(dijkstra["total_cost"])
    assert astar["route"] == dijkstra["route"]


def test_blocked_and_unsafe_corridors_are_avoided():
    graph = weighted_graph()
    graph["corridors"][1]["blocked"] = True
    result = find_dijkstra_route(graph, "start", unsafe_locations={"e-exit"})
    assert result["found"]
    assert "s-n" not in result["corridors"]
    assert "e-exit" not in result["corridors"]
    assert result["exit"] == "exit"


def test_unavailable_exit_is_not_selected():
    result = find_dijkstra_route(weighted_graph(), "start", unavailable_exits={"exit"})
    assert result["found"]
    assert result["exit"] == "exit-alt"


def test_unreachable_result_has_clear_status_and_message():
    graph = {"nodes": [{"id": "room", "type": "room"}, {"id": "exit", "type": "exit"}], "corridors": []}
    result = find_astar_route(graph, "room")
    assert result["status"] == "unreachable"
    assert "No valid route" in result["message"]
    assert result["route"] == []


def test_route_reconstruction_and_travel_time_cost_model():
    result = find_dijkstra_route(weighted_graph(), "start", cost_model="travel_time")
    assert result["route"] == ["start", "north", "east", "exit"]
    assert result["corridors"] == ["s-n", "n-e", "e-exit"]
    assert result["distance"] == pytest.approx(3.5)
    assert result["estimated_travel_time_seconds"] == pytest.approx(3)
    assert result["total_cost"] == pytest.approx(3)
    assert result["cost_model"] == "travel_time"


def test_zero_cost_edges_are_supported():
    graph = {
        "nodes": [{"id": "room", "type": "room"}, {"id": "hall", "type": "junction"}, {"id": "exit", "type": "exit"}],
        "corridors": [
            {"id": "free", "from": "room", "to": "hall", "distance": 0},
            {"id": "costly", "from": "hall", "to": "exit", "distance": 2},
        ],
    }
    result = find_dijkstra_route(graph, "room")
    assert result["found"]
    assert result["total_cost"] == 2
    assert result["route"] == ["room", "hall", "exit"]


def test_missing_coordinates_use_safe_astar_fallback():
    graph = weighted_graph()
    for node in graph["nodes"]:
        node.pop("x")
        node.pop("y")
    assert find_astar_route(graph, "start")["total_cost"] == pytest.approx(
        find_dijkstra_route(graph, "start")["total_cost"]
    )


def test_unsupported_algorithm_is_rejected():
    with pytest.raises(ValueError, match="Unsupported algorithm"):
        find_route(weighted_graph(), "start", algorithm="floyd-warshall")


def test_unavailable_exit_and_invalid_start_statuses_are_clear():
    no_exits = find_route(weighted_graph(), "start", unavailable_exits={"exit", "exit-alt"})
    invalid = find_route(weighted_graph(), "not-a-room")
    assert no_exits["status"] == "no_available_exits"
    assert invalid["status"] == "invalid_start"


def test_route_api_accepts_algorithm_and_returns_dashboard_fields():
    from app.api.routes import RouteRequest, calculate_route

    result = calculate_route(RouteRequest(starting_room="room-101", algorithm="astar"))
    assert result["found"] is True
    assert result["algorithm"] == "astar"
    assert result["starting_room"] == "room-101"
    assert result["exit"].startswith("exit-")
    assert result["route"][0] == "room-101"
    assert result["distance"] > 0
    assert result["total_cost"] > 0
    assert result["status"] == "found"

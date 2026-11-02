import pytest
from pydantic import ValidationError
from fastapi import HTTPException

from app.agents.utility_agent import DEFAULT_WEIGHTS, choose_utility_route, score_candidate, validate_weights
from app.api.routes import UtilityRouteRequest, calculate_utility_route
from app.services.building import load_building


def parallel_route_graph():
    return {
        "nodes": [
            {"id": "room", "type": "room"},
            {"id": "quick", "type": "junction"},
            {"id": "calm-a", "type": "junction"},
            {"id": "calm-b", "type": "junction"},
            {"id": "exit", "type": "exit"},
        ],
        "corridors": [
            {"id": "quick-in", "from": "room", "to": "quick", "distance": 5, "travel_time_seconds": 5,
             "hazard_risk": 0.7, "crowd_density": 0.9, "capacity": 10, "current_occupancy": 10,
             "step_free": True, "clear_width_m": 1.8},
            {"id": "quick-out", "from": "quick", "to": "exit", "distance": 5, "travel_time_seconds": 5,
             "hazard_risk": 0.0, "crowd_density": 0.9, "capacity": 10, "current_occupancy": 10,
             "step_free": True, "clear_width_m": 1.8},
            {"id": "calm-in", "from": "room", "to": "calm-a", "distance": 8, "travel_time_seconds": 8,
             "hazard_risk": 0.05, "crowd_density": 0.05, "capacity": 20, "current_occupancy": 1,
             "step_free": True, "clear_width_m": 1.8},
            {"id": "calm-mid", "from": "calm-a", "to": "calm-b", "distance": 8, "travel_time_seconds": 8,
             "hazard_risk": 0.05, "crowd_density": 0.05, "capacity": 20, "current_occupancy": 1,
             "step_free": True, "clear_width_m": 1.8},
            {"id": "calm-out", "from": "calm-b", "to": "exit", "distance": 8, "travel_time_seconds": 8,
             "hazard_risk": 0.05, "crowd_density": 0.05, "capacity": 20, "current_occupancy": 1,
             "step_free": True, "clear_width_m": 1.8},
        ],
    }


def test_agent_prefers_longer_route_when_short_route_has_high_hazard_risk():
    result = choose_utility_route(
        parallel_route_graph(), "room",
        preference_weights={"time": 0.2, "safety": 0.8, "crowd": 0, "accessibility": 0},
        candidate_limit=10,
    )
    assert result["found"]
    assert result["route"] == ["room", "calm-a", "calm-b", "exit"]
    assert result["factor_scores"]["safety"] > 0.8


def test_agent_prefers_less_crowded_route_when_crowd_weight_is_high():
    result = choose_utility_route(
        parallel_route_graph(), "room",
        preference_weights={"time": 0.2, "safety": 0, "crowd": 0.8, "accessibility": 0},
        candidate_limit=10,
    )
    assert result["route"][1] == "calm-a"
    assert result["factor_scores"]["crowd"] > 0.9


def test_step_free_requirement_is_a_hard_constraint():
    graph = parallel_route_graph()
    for edge in graph["corridors"]:
        if edge["id"].startswith("calm"):
            edge["step_free"] = False
    result = choose_utility_route(graph, "room", accessibility={"step_free": True})
    assert result["found"]
    assert result["route"] == ["room", "quick", "exit"]


def test_minimum_width_requirement_excludes_narrow_route():
    graph = parallel_route_graph()
    graph["corridors"][0]["clear_width_m"] = 0.8
    graph["corridors"][1]["clear_width_m"] = 0.8
    result = choose_utility_route(graph, "room", accessibility={"minimum_width_m": 1.2})
    assert result["found"]
    assert result["route"][1] == "calm-a"


def test_blocked_corridor_is_excluded_before_scoring():
    graph = parallel_route_graph()
    graph["corridors"][0]["blocked"] = True
    result = choose_utility_route(graph, "room")
    assert result["found"]
    assert "quick-in" not in result["corridors"]
    assert result["route"][1] == "calm-a"


def test_unavailable_exit_is_excluded():
    result = choose_utility_route(load_building(), "room-101", unavailable_exits={"exit-north"})
    assert result["found"]
    assert result["exit"] == "exit-south"


def test_confirmed_unsafe_is_hard_constraint_but_risk_is_soft():
    graph = parallel_route_graph()
    graph["corridors"][0]["unsafe"] = True
    # The risk field is only a score; `unsafe` is the confirmed hard exclusion.
    result = choose_utility_route(
        graph, "room",
        preference_weights={"time": 1, "safety": 0, "crowd": 0, "accessibility": 0},
    )
    assert result["found"]
    assert "quick-in" not in result["corridors"]


def test_no_feasible_route_when_access_constraints_remove_all_edges():
    graph = parallel_route_graph()
    for edge in graph["corridors"]:
        edge["step_free"] = False
    result = choose_utility_route(graph, "room", accessibility={"step_free": True})
    assert result["status"] == "no_feasible_route"
    assert "accessibility constraints" in result["message"]


def test_preference_weights_must_sum_to_one_and_default_weights_are_normalized():
    assert sum(validate_weights(None).values()) == pytest.approx(1.0)
    assert validate_weights(None) == DEFAULT_WEIGHTS
    with pytest.raises(ValueError, match="sum to 1.0"):
        validate_weights({"time": 0.2, "safety": 0.2, "crowd": 0.2, "accessibility": 0.2})
    with pytest.raises(ValueError, match="non-negative"):
        validate_weights({"time": 1.1, "safety": -0.1, "crowd": 0, "accessibility": 0})


def test_utility_formula_returns_expected_normalized_score():
    candidate = {
        "_edges": [{"hazard_risk": 0.1, "crowd_density": 0.2, "step_free": True,
                    "travel_time_seconds": 10, "capacity": 10, "current_occupancy": 2}],
        "estimated_travel_time_seconds": 10,
    }
    weights = {"time": 0.5, "safety": 0.5, "crowd": 0, "accessibility": 0}
    result = score_candidate(candidate, weights, reference_time_seconds=100)
    assert result["factor_scores"]["time"] == pytest.approx(100 / 110)
    assert result["factor_scores"]["safety"] == pytest.approx(0.9)
    assert result["utility_score"] == pytest.approx((100 / 110 + 0.9) / 2)


def test_candidate_limit_is_reported_and_api_response_has_expected_fields():
    request = UtilityRouteRequest(starting_room="room-101", candidate_limit=1)
    response = calculate_utility_route(request)
    assert response["algorithm"] == "utility"
    assert response["status"] == "found"
    assert response["route"][0] == "room-101"
    assert response["exit"].startswith("exit-")
    assert "utility_score" in response and "factor_scores" in response
    assert "preferences" in response and "explanation" in response
    assert response["candidate_count"] == 1
    assert response["candidate_search_complete"] is False


def test_api_rejects_invalid_weights_and_accessibility_values():
    request = UtilityRouteRequest(starting_room="room-101", preference_weights={
        "time": 0.5, "safety": 0.2, "crowd": 0.2, "accessibility": 0.2,
    })
    with pytest.raises(HTTPException, match="sum to 1.0"):
        calculate_utility_route(request)
    with pytest.raises(ValidationError):
        UtilityRouteRequest(starting_room="room-101", accessibility={"minimum_width_m": 0})

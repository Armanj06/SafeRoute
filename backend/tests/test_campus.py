import pytest
from fastapi import HTTPException

from app.algorithms.bfs import find_evacuation_route
from app.api.routes import RouteRequest, building, calculate_route, campus
from app.services.building import load_building, load_campus, validate_building_graph
from app.simulation.scenarios import list_scenarios
from app.simulation.service import SimulationManager


def test_campus_catalog_names_verified_locations_and_discloses_single_illustrative_graph():
    catalog = load_campus()
    names = {location["name"] for location in catalog["locations"]}
    assert {"Vedanta", "Chanakya", "Charak", "Vastu", "Vishveshwarya"} <= names
    assert len(catalog["models"]) == 1
    assert catalog["models"][0]["status"] == "illustrative"
    assert catalog["models"][0]["floors"] == []
    assert "not approved" in catalog["campus"]["endorsement_notice"]


def test_building_loader_attaches_campus_provenance_and_rejects_unknown_models():
    graph = load_building("dit-vedanta-illustrative")
    assert graph["id"] == "dit-vedanta-illustrative"
    assert graph["campus_location"]["name"] == "Vedanta"
    assert graph["model_status"] == "illustrative"
    assert graph["floors"] == []
    with pytest.raises(ValueError, match="not available"):
        load_building("dit-charak-not-modeled")


def test_campus_and_selected_building_api_return_catalog_and_graph():
    catalog = campus()
    graph = building("dit-vedanta-illustrative")
    assert catalog["default_model_id"] == graph["model_id"]
    assert graph["campus_location"]["id"] == "vedanta"
    with pytest.raises(HTTPException) as error:
        building("missing-model")
    assert error.value.status_code == 404


def test_selected_building_id_is_used_for_actual_route_calculation():
    result = calculate_route(RouteRequest(
        starting_room="room-101",
        building_id="dit-vedanta-illustrative",
        algorithm="dijkstra",
    ))
    assert result["found"]
    assert result["starting_room"] == "room-101"
    assert result["algorithm"] == "dijkstra"
    with pytest.raises(HTTPException) as error:
        calculate_route(RouteRequest(starting_room="room-101", building_id="not-configured"))
    assert error.value.status_code == 422


def test_functional_area_node_can_be_used_as_a_routing_start():
    graph = {
        "id": "area-start-test",
        "nodes": [
            {"id": "lab-area", "type": "area"},
            {"id": "exit", "type": "exit"},
        ],
        "corridors": [{"id": "hall", "from": "lab-area", "to": "exit", "distance": 5}],
    }
    result = find_evacuation_route(graph, "lab-area")
    assert result["found"]
    assert result["route"] == ["lab-area", "exit"]


def simple_graph():
    return {
        "id": "valid-test-building",
        "floors": [{"id": "level-1", "name": "Level 1"}],
        "nodes": [
            {"id": "room", "type": "room", "floor_id": "level-1"},
            {"id": "exit", "type": "exit", "floor_id": "level-1"},
        ],
        "corridors": [{"id": "hall", "from": "room", "to": "exit", "distance": 4, "travel_time_seconds": 3}],
        "exit_ids": ["exit"],
    }


@pytest.mark.parametrize("mutation, message", [
    (lambda graph: graph["nodes"].append(dict(graph["nodes"][0])), "Duplicate node"),
    (lambda graph: graph["corridors"][0].update(to="missing"), "unknown node"),
    (lambda graph: graph["corridors"][0].update(distance=-1), "non-negative"),
    (lambda graph: graph["corridors"][0].update(travel_time_seconds=float("inf")), "non-negative"),
    (lambda graph: graph["nodes"][0].update(floor_id="level-9"), "unknown floor"),
    (lambda graph: graph.update(exit_ids=["room"]), "invalid node"),
])
def test_graph_validation_rejects_invalid_references_and_weights(mutation, message):
    graph = simple_graph()
    mutation(graph)
    with pytest.raises(ValueError, match=message):
        validate_building_graph(graph)


def test_campus_demonstration_scenarios_use_existing_deterministic_simulation_engine():
    campus_scenarios = [item for item in list_scenarios() if item["scenario_id"].startswith("ditu-")]
    assert len(campus_scenarios) == 6
    for scenario in campus_scenarios:
        manager = SimulationManager(load_building())
        state = manager.create_scenario(scenario["scenario_id"])
        assert state is not None
        assert state.scenario_name == scenario["name"]
        assert len(state.evacuees) > 0
        manager.start(state.simulation_id)
        for _ in range(100):
            if state.status == "completed":
                break
            manager.advance(state.simulation_id, 1)
        assert state.status == "completed", scenario["scenario_id"]
        assert state.summary()["total_evacuated"] + state.summary()["unable_to_evacuate"] == len(state.evacuees)


def test_campus_fire_scenario_runs_hazard_replanning_and_keeps_hypothetical_assumptions_visible():
    scenario = next(item for item in list_scenarios() if item["scenario_id"] == "ditu-vedanta-fire")
    assert "Hypothetical" in scenario["description"]
    manager = SimulationManager(load_building())
    state = manager.create_scenario("ditu-vedanta-fire")
    assert any(hazard.active and hazard.target_id == "c4" for hazard in state.hazards)
    assert "c4" in manager.conditions(state)["unsafe_corridors"]
    assert any(event.event_type in {"route_replanned", "unable_to_evacuate"} for event in state.event_history)

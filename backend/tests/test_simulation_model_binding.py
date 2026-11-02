"""Synthetic graphs exercise per-run model binding without changing campus data."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest
from fastapi import HTTPException

from app.api import routes
from app.api.routes import (
    RouteComparisonRequest,
    SimulationCreateRequest,
    compare_route_algorithms,
    create_simulation,
    export_simulation_report,
    start_scenario,
)
from app.simulation.models import SimulationSettings
from app.simulation.service import SimulationManager


def graph_a():
    return {
        "id": "test-model-a", "name": "Synthetic A",
        "nodes": [
            {"id": "a-room", "type": "room", "x": 0, "y": 0},
            {"id": "a-junction", "type": "junction", "x": 1, "y": 0},
            {"id": "a-exit", "type": "exit", "x": 2, "y": 0},
        ],
        "corridors": [
            {"id": "a-direct", "from": "a-room", "to": "a-exit", "distance": 20, "travel_time_seconds": 20, "capacity": 1, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
            {"id": "a-detour-1", "from": "a-room", "to": "a-junction", "distance": 2, "travel_time_seconds": 2, "capacity": 2, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
            {"id": "a-detour-2", "from": "a-junction", "to": "a-exit", "distance": 2, "travel_time_seconds": 2, "capacity": 2, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
        ],
    }


def graph_b():
    return {
        "id": "test-model-b", "name": "Synthetic B",
        "nodes": [
            {"id": "b-room", "type": "room", "x": 0, "y": 0},
            {"id": "b-exit", "type": "exit", "x": 1, "y": 0},
            {"id": "b-exit-alt", "type": "exit", "x": 2, "y": 0},
        ],
        "corridors": [
            {"id": "b-main", "from": "b-room", "to": "b-exit", "distance": 5, "travel_time_seconds": 5, "capacity": 2, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
            {"id": "b-alt", "from": "b-room", "to": "b-exit-alt", "distance": 7, "travel_time_seconds": 7, "capacity": 2, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
        ],
    }


def manager_for_test_graphs():
    graphs = {"test-model-a": graph_a(), "test-model-b": graph_b()}

    def load(model_id):
        if model_id is None:
            model_id = "test-model-a"
        if model_id not in graphs:
            raise ValueError(f"Building model '{model_id}' is not available.")
        return deepcopy(graphs[model_id])

    return SimulationManager(graphs["test-model-a"], building_loader=load)


def test_manager_binds_distinct_models_and_keeps_independent_graph_copies():
    manager = manager_for_test_graphs()
    state_a = manager.create(evacuee_specs=[{"starting_room": "a-room"}], building_id="test-model-a")
    state_b = manager.create(evacuee_specs=[{"starting_room": "b-room"}], building_id="test-model-b")

    assert state_a.building_id == "test-model-a"
    assert state_b.building_id == "test-model-b"
    assert manager.serialize(state_a)["building_id"] == "test-model-a"
    assert manager.serialize(state_a)["evacuees"][0]["assigned_exit"] == "a-exit"
    assert manager.serialize(state_b)["evacuees"][0]["assigned_exit"] == "b-exit"
    assert manager.get_engine(state_a.simulation_id).building is not manager.get_engine(state_b.simulation_id).building

    manager.get_engine(state_a.simulation_id).building["corridors"][0]["blocked"] = True
    assert not any(edge.get("blocked") for edge in manager.get_engine(state_b.simulation_id).building["corridors"])


def test_hazards_exit_changes_and_replanning_stay_with_bound_graph():
    manager = manager_for_test_graphs()
    state_a = manager.create(evacuee_specs=[{"starting_room": "a-room"}], building_id="test-model-a")
    state_b = manager.create(evacuee_specs=[{"starting_room": "b-room"}], building_id="test-model-b")

    manager.add_hazard(state_a.simulation_id, hazard_type="fire", target_type="corridor", target_id="a-direct", severity=0.9)
    assert "a-direct" in manager.conditions(state_a)["unsafe_corridors"]
    assert manager.conditions(state_b)["unsafe_corridors"] == []
    assert state_a.evacuees[0].route == ["a-room", "a-junction", "a-exit"]
    with pytest.raises(ValueError, match="Unknown corridor target 'a-direct'"):
        manager.add_hazard(state_b.simulation_id, hazard_type="fire", target_type="corridor", target_id="a-direct", severity=0.9)
    hazard = state_a.hazards[0]
    manager.set_hazard_active(state_a.simulation_id, hazard.hazard_id, False)
    assert manager.conditions(state_a)["unsafe_corridors"] == []
    assert manager.conditions(state_b)["unsafe_corridors"] == []

    manager.set_exit_available(state_a.simulation_id, "a-exit", False)
    assert "a-exit" in manager.conditions(state_a)["unavailable_exits"]
    assert "a-exit" not in manager.conditions(state_b)["unavailable_exits"]
    assert state_a.evacuees[0].assigned_exit is None or state_a.evacuees[0].assigned_exit != "b-exit"


def test_default_model_and_explicit_unknown_model_behavior():
    manager = manager_for_test_graphs()
    default_state = manager.create(number_of_evacuees=1)
    explicit_state = manager.create(number_of_evacuees=1, building_id="test-model-b")
    assert default_state.building_id == "test-model-a"
    assert explicit_state.building_id == "test-model-b"
    with pytest.raises(ValueError, match="not available"):
        manager.create(number_of_evacuees=1, building_id="not-configured")


def test_scenario_uses_requested_graph_and_retains_model_id():
    manager = manager_for_test_graphs()
    state = manager.create_scenario("baseline", building_id="test-model-b")
    assert state is not None
    assert state.building_id == "test-model-b"
    assert state.evacuees[0].starting_room == "b-room"
    assert manager.serialize(state)["building_id"] == "test-model-b"
    with pytest.raises(ValueError, match="Unknown corridor target 'c4'"):
        manager.create_scenario("ditu-vedanta-fire", building_id="test-model-b")
    assert manager.get(state.simulation_id) is state


def test_api_creation_default_unknown_scenario_graph_and_report_metadata(monkeypatch):
    manager = manager_for_test_graphs()
    monkeypatch.setattr(routes, "simulation_manager", manager)

    default = create_simulation(SimulationCreateRequest(number_of_evacuees=1))
    selected = create_simulation(SimulationCreateRequest(number_of_evacuees=1, building_id="test-model-b"))
    assert default["building_id"] == "test-model-a"
    assert selected["building_id"] == "test-model-b"
    with pytest.raises(HTTPException) as error:
        create_simulation(SimulationCreateRequest(number_of_evacuees=1, building_id="not-configured"))
    assert error.value.status_code == 422

    report = export_simulation_report(selected["simulation_id"], "json")
    assert json.loads(report.body)["building"]["id"] == "test-model-b"
    scenario = start_scenario("baseline", building_id="test-model-b")
    assert scenario["building_id"] == "test-model-b"


def test_route_comparison_rejects_model_conflict_and_defaults_to_run_model(monkeypatch):
    manager = manager_for_test_graphs()
    state = manager.create(evacuee_specs=[{"starting_room": "a-room"}], building_id="test-model-a")
    monkeypatch.setattr(routes, "simulation_manager", manager)

    with pytest.raises(HTTPException) as error:
        compare_route_algorithms(RouteComparisonRequest(
            starting_room="a-room", simulation_id=state.simulation_id, building_id="test-model-b",
        ))
    assert error.value.status_code == 422
    assert "conflicts with simulation model" in error.value.detail

    response = compare_route_algorithms(RouteComparisonRequest(
        starting_room="a-room", simulation_id=state.simulation_id,
    ))
    assert response["building_id"] == "test-model-a"
    assert response["results"][0]["route"][0] == "a-room"


def test_simulation_operations_do_not_mutate_other_runs_building_or_state():
    manager = manager_for_test_graphs()
    state_a = manager.create(evacuee_specs=[{"starting_room": "a-room"}], building_id="test-model-a")
    state_b = manager.create(evacuee_specs=[{"starting_room": "b-room"}], building_id="test-model-b")
    before_b = manager.serialize(state_b)

    manager.set_exit_available(state_a.simulation_id, "a-exit", False)
    manager.advance(state_a.simulation_id, 1)
    after_b = manager.serialize(state_b)
    assert after_b["building_id"] == before_b["building_id"]
    assert after_b["effective_conditions"] == before_b["effective_conditions"]
    assert after_b["evacuees"] == before_b["evacuees"]


def test_different_model_runs_keep_agent_timing_and_corridor_occupancy_isolated():
    manager = manager_for_test_graphs()
    settings = SimulationSettings(congestion_penalty=0)
    state_a = manager.create(evacuee_specs=[{
        "starting_room": "a-room", "walking_speed_mps": 1.0,
        "reaction_delay_seconds": 5.0,
    }], settings=settings, building_id="test-model-a")
    state_b = manager.create(evacuee_specs=[{
        "starting_room": "b-room", "walking_speed_mps": 0.5,
        "reaction_delay_seconds": 0.0,
    }], settings=settings, building_id="test-model-b")

    manager.advance(state_a.simulation_id, 1)
    manager.advance(state_b.simulation_id, 1)
    assert state_a.evacuees[0].current_corridor is None
    assert state_a.corridor_occupancy == {"a-direct": 0, "a-detour-1": 0, "a-detour-2": 0}
    assert state_b.evacuees[0].current_corridor == "b-main"
    assert state_b.corridor_occupancy["b-main"] == 1
    assert state_a.building_id == "test-model-a"
    assert state_b.building_id == "test-model-b"

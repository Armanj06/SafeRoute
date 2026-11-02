from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import (
    SimulationCreateRequest,
    SimulationStepRequest,
    create_simulation,
)
from app.services.building import load_building
from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings
from app.simulation.service import SimulationManager


def sample_engine():
    return SimulationEngine(load_building())


def test_create_simulation_assigns_routes_and_starts_paused():
    state = sample_engine().create([{"starting_room": "room-101"}])
    person = state.evacuees[0]
    assert state.status == "paused"
    assert person.status == "waiting"
    assert person.assigned_exit in {"exit-north", "exit-south"}
    assert person.route[0] == "room-101"
    assert any(event.event_type == "route_assigned" for event in state.event_history)


def test_one_step_moves_person_and_tracks_corridor_occupancy():
    engine = sample_engine()
    state = engine.create([{"starting_room": "room-101"}])
    engine.advance(state)
    person = state.evacuees[0]
    assert state.current_step == 1
    assert state.current_time_seconds == 5
    assert person.status == "moving"
    assert person.current_corridor == person.route_corridors[0]
    assert state.corridor_occupancy[person.current_corridor] == 1


def test_evacuees_reach_an_exit_and_statistics_are_correct():
    engine = sample_engine()
    state = engine.create([{"starting_room": "room-101"}, {"starting_room": "room-102"}])
    engine.start(state)
    engine.advance(state, steps=100)
    summary = state.summary()
    assert state.status == "completed"
    assert summary["total_evacuated"] == 2
    assert summary["total_remaining"] == 0
    assert summary["active_remaining"] == 0
    assert summary["unable_to_evacuate"] == 0
    assert summary["simulation_duration_seconds"] > 0
    assert all(person.status == "evacuated" for person in state.evacuees)


def test_competing_people_never_exceed_corridor_capacity():
    graph = load_building()
    graph["corridors"][0]["capacity"] = 1
    engine = SimulationEngine(graph)
    state = engine.create([{"starting_room": "room-101"} for _ in range(5)])
    for _ in range(20):
        engine.advance(state)
        for corridor_id, occupancy in state.corridor_occupancy.items():
            assert occupancy <= engine._capacity(engine.corridors[corridor_id])
            assert occupancy >= 0
    first_corridor = state.evacuees[0].route_corridors[0]
    assert state.corridor_occupancy[first_corridor] <= 1
    assert any(event.event_type == "capacity_wait" for event in state.event_history)


def test_effective_travel_time_increases_with_occupancy_ratio():
    engine = sample_engine()
    edge = {"id": "corridor", "distance": 10, "travel_time_seconds": 10, "capacity": 4, "crowd_density": 0}
    assert engine._effective_time(edge, occupancy=0, penalty=1) == pytest.approx(10)
    assert engine._effective_time(edge, occupancy=2, penalty=1) == pytest.approx(15)
    assert engine._effective_time(edge, occupancy=4, penalty=1) == pytest.approx(20)


def test_replanning_switches_route_when_congestion_changes_costs():
    graph = {
        "nodes": [
            {"id": "room", "type": "room"},
            {"id": "junction", "type": "junction"},
            {"id": "exit", "type": "exit"},
        ],
        "corridors": [
            {"id": "direct", "from": "room", "to": "exit", "distance": 8, "travel_time_seconds": 8,
             "capacity": 1, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
            {"id": "detour-a", "from": "room", "to": "junction", "distance": 5, "travel_time_seconds": 5,
             "capacity": 2, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
            {"id": "detour-b", "from": "junction", "to": "exit", "distance": 5, "travel_time_seconds": 5,
             "capacity": 2, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
        ],
    }
    settings = SimulationSettings(
        replan_on_congestion=True,
        replan_interval_steps=1,
        preference_weights={"time": 1, "safety": 0, "crowd": 0, "accessibility": 0},
    )
    engine = SimulationEngine(graph)
    state = engine.create([{"starting_room": "room"}], settings)
    assert state.evacuees[0].route_corridors == ["direct"]
    # Simulate a full corridor occupancy observation from the current state.
    state.corridor_occupancy["direct"] = 1
    engine.advance(state)
    person = state.evacuees[0]
    assert person.route_corridors == ["detour-a", "detour-b"]
    assert any(event.event_type == "route_replanned" for event in state.event_history)


def test_blocked_start_access_and_unavailable_exit_are_honored():
    engine = sample_engine()
    blocked = engine.create([{"starting_room": "room-101"}], SimulationSettings(
        blocked_corridors=["c1", "c13"],
    ))
    assert blocked.evacuees[0].status == "unable_to_evacuate"
    assert blocked.evacuees[0].status != "evacuated"

    alternate = engine.create([{"starting_room": "room-101"}], SimulationSettings(
        unavailable_exits=["exit-north"],
    ))
    assert alternate.evacuees[0].assigned_exit == "exit-south"


def test_accessibility_requirement_can_make_person_unable_to_evacuate():
    graph = load_building()
    for edge in graph["corridors"]:
        if edge["id"] not in {"c1", "c3", "c4"}:
            edge["blocked"] = True
    for edge in graph["corridors"]:
        if edge["id"] in {"c1", "c3", "c4"}:
            edge["step_free"] = False
    state = SimulationEngine(graph).create([{
        "starting_room": "room-101",
        "accessibility": {"step_free": True},
    }])
    assert state.evacuees[0].status == "unable_to_evacuate"
    assert state.summary()["unable_to_evacuate"] == 1


def test_reset_clears_clock_occupancy_and_rebuilds_evacuees():
    manager = SimulationManager(load_building())
    created = manager.create(number_of_evacuees=2)
    manager.advance(created.simulation_id, steps=1)
    reset = manager.reset(created.simulation_id)
    assert reset is not None
    assert reset.simulation_id == created.simulation_id
    assert reset.current_step == 0
    assert reset.current_time_seconds == 0
    assert reset.status == "paused"
    assert all(value == 0 for value in reset.corridor_occupancy.values())
    assert all(person.status == "waiting" for person in reset.evacuees)
    assert [event.event_type for event in reset.event_history] == ["simulation_reset"]


def test_create_endpoint_validates_request_and_serializes_state():
    response = create_simulation(SimulationCreateRequest(number_of_evacuees=2))
    assert response["status"] == "paused"
    assert len(response["evacuees"]) == 2
    assert response["statistics"]["total_remaining"] == 2
    assert "corridor_load" in response
    assert response["event_history"]

    with pytest.raises(HTTPException, match="exactly one"):
        create_simulation(SimulationCreateRequest(
            number_of_evacuees=2,
            evacuees=[{"starting_room": "room-101"}],
        ))
    with pytest.raises(ValidationError):
        SimulationCreateRequest(number_of_evacuees=201)
    with pytest.raises(ValidationError):
        SimulationStepRequest(steps=0)


def test_explicit_start_rooms_and_in_memory_summary_and_history():
    manager = SimulationManager(load_building())
    state = manager.create(evacuee_specs=[
        {"starting_room": "room-101", "accessibility": {"step_free": True}},
        {"starting_room": "room-202", "accessibility": {}},
    ])
    assert [person.starting_room for person in state.evacuees] == ["room-101", "room-202"]
    started = manager.start(state.simulation_id)
    assert started.status == "running"
    manager.advance(state.simulation_id, steps=1)
    paused = manager.pause(state.simulation_id)
    assert paused.status == "paused"
    summary = manager.summary(paused)
    assert summary["total_evacuees"] == 2
    events = manager.events(paused, after_sequence=0)
    assert events[0]["event_type"] == "simulation_created"
    assert events[-1]["event_type"] == "simulation_paused"


def test_simulation_does_not_mutate_original_building():
    original = load_building()
    before = deepcopy(original)
    engine = SimulationEngine(original)
    state = engine.create([{"starting_room": "room-101"}])
    engine.advance(state)
    assert original == before

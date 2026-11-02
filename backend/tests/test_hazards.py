from copy import deepcopy

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import HazardCreateRequest, SimulationCreateRequest, create_hazard, create_simulation
from app.simulation.engine import SimulationEngine
from app.simulation.models import effective_conditions
from app.simulation.service import SimulationManager


def diamond_graph():
    return {
        "nodes": [
            {"id": "room", "type": "room", "x": 0, "y": 0},
            {"id": "junction-a", "type": "junction", "x": 1, "y": 0},
            {"id": "junction-b", "type": "junction", "x": 1, "y": 1},
            {"id": "exit-a", "type": "exit", "x": 2, "y": 0},
            {"id": "exit-b", "type": "exit", "x": 2, "y": 1},
        ],
        "corridors": [
            {"id": "fast-a", "from": "room", "to": "junction-a", "distance": 1, "travel_time_seconds": 1, "capacity": 3, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
            {"id": "fast-b", "from": "junction-a", "to": "exit-a", "distance": 1, "travel_time_seconds": 1, "capacity": 3, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
            {"id": "safe-a", "from": "room", "to": "junction-b", "distance": 2, "travel_time_seconds": 2, "capacity": 3, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
            {"id": "safe-b", "from": "junction-b", "to": "exit-b", "distance": 2, "travel_time_seconds": 2, "capacity": 3, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
        ],
    }


def test_fire_on_corridor_excludes_it_and_immediately_replans():
    building = diamond_graph()
    original = deepcopy(building)
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}])
    person = state.evacuees[0]
    assert person.route == ["room", "junction-a", "exit-a"]

    hazard = engine.add_hazard(state, "fire", "corridor", "fast-b", 0.9)

    assert hazard.active
    assert person.route == ["room", "junction-b", "exit-b"]
    assert "fast-b" in effective_conditions(building, state)["blocked_corridors"]
    assert building == original
    assert any(event.event_type == "route_replanned" for event in state.event_history)


def test_flood_on_node_removes_node_from_routes():
    building = diamond_graph()
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}])
    engine.add_hazard(state, "flood", "node", "junction-a", 0.7)
    conditions = effective_conditions(building, state)
    assert "junction-a" in conditions["unsafe_nodes"]
    assert state.evacuees[0].route == ["room", "junction-b", "exit-b"]


def test_invalid_hazard_target_and_type_are_rejected():
    engine = SimulationEngine(diamond_graph())
    state = engine.create([{"starting_room": "room"}])
    with pytest.raises(ValueError, match="Unknown corridor"):
        engine.add_hazard(state, "fire", "corridor", "missing", 0.5)
    with pytest.raises(ValueError, match="hazard_type"):
        engine.add_hazard(state, "earthquake", "node", "room", 0.5)
    with pytest.raises(ValueError, match="severity"):
        engine.add_hazard(state, "fire", "node", "room", 1.1)
    with pytest.raises(ValidationError):
        HazardCreateRequest(hazard_type="fire", target_type="node", target_id="room", severity=2)


def test_unavailable_exit_replans_and_restore_does_not_override_hazard():
    building = diamond_graph()
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}])
    engine.set_exit_available(state, "exit-a", False)
    assert state.evacuees[0].assigned_exit == "exit-b"
    engine.add_hazard(state, "unsafe_area", "node", "exit-a", 1)
    engine.set_exit_available(state, "exit-a", True)
    conditions = effective_conditions(building, state)
    assert "exit-a" in conditions["unavailable_exits"]
    engine.set_hazard_active(state, state.hazards[0].hazard_id, False)
    assert "exit-a" not in effective_conditions(building, state)["unavailable_exits"]


def test_no_safe_alternative_marks_person_unable_not_evacuated():
    graph = {
        "nodes": [
            {"id": "room", "type": "room"}, {"id": "exit", "type": "exit"},
            {"id": "other-room", "type": "room"}, {"id": "other-exit", "type": "exit"},
        ],
        "corridors": [
            {"id": "only", "from": "room", "to": "exit", "distance": 1, "travel_time_seconds": 1, "capacity": 2, "hazard_risk": 0, "crowd_density": 0},
            {"id": "other-route", "from": "other-room", "to": "other-exit", "distance": 1, "travel_time_seconds": 10, "capacity": 2, "hazard_risk": 0, "crowd_density": 0},
        ],
    }
    engine = SimulationEngine(graph)
    state = engine.create([{"starting_room": "room"}, {"starting_room": "other-room"}])
    engine.add_hazard(state, "fire", "corridor", "only", 1)
    person = state.evacuees[0]
    assert person.status == "unable_to_evacuate"
    assert person.status != "evacuated"
    assert state.summary()["unable_to_evacuate"] == 1
    assert state.summary()["active_remaining"] == 1
    engine.set_hazard_active(state, state.hazards[0].hazard_id, False)
    assert state.evacuees[0].status == "waiting"
    assert state.evacuees[0].route == ["room", "exit"]
    assert state.status != "completed"


def test_newly_unsafe_corridor_is_never_entered_after_activation():
    engine = SimulationEngine(diamond_graph())
    state = engine.create([{"starting_room": "room"}])
    person = state.evacuees[0]
    endangered_corridor = person.route_corridors[0]
    engine.add_hazard(state, "fire", "corridor", endangered_corridor, 1)
    engine.advance(state)
    assert person.current_corridor != endangered_corridor
    assert person.route_corridors[0] != endangered_corridor
    assert state.corridor_occupancy[endangered_corridor] == 0


def test_speed_and_reaction_delay_preserve_hazard_replanning_before_movement():
    engine = SimulationEngine(diamond_graph())
    state = engine.create([{
        "starting_room": "room",
        "walking_speed_mps": 1.0,
        "reaction_delay_seconds": 7.0,
    }])
    person = state.evacuees[0]
    assert person.route == ["room", "junction-a", "exit-a"]

    engine.add_hazard(state, "fire", "corridor", "fast-b", 0.9)
    assert person.route == ["room", "junction-b", "exit-b"]
    assert person.remaining_reaction_seconds == 7

    engine.advance(state)
    assert person.current_corridor is None
    assert person.remaining_reaction_seconds == 2
    engine.advance(state)
    assert person.current_corridor is None
    assert person.remaining_reaction_seconds == 0
    engine.advance(state)
    assert person.current_node == "junction-b"
    assert "fast-b" not in person.route_corridors


def test_overlapping_hazards_only_clear_the_resolved_hazard():
    building = diamond_graph()
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}])
    first = engine.add_hazard(state, "fire", "corridor", "fast-b", 0.8)
    second = engine.add_hazard(state, "unsafe_area", "corridor", "fast-b", 0.5)
    engine.set_hazard_active(state, first.hazard_id, False)
    assert "fast-b" in effective_conditions(building, state)["blocked_corridors"]
    engine.set_hazard_active(state, second.hazard_id, False)
    assert "fast-b" not in effective_conditions(building, state)["blocked_corridors"]


def test_resolving_hazard_does_not_clear_independent_static_block():
    building = diamond_graph()
    building["corridors"][1]["blocked"] = True
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}])
    hazard = engine.add_hazard(state, "fire", "corridor", "fast-b", 0.9)
    engine.set_hazard_active(state, hazard.hazard_id, False)
    assert "fast-b" in effective_conditions(building, state)["blocked_corridors"]


def test_hazard_and_route_changes_are_recorded_in_history():
    engine = SimulationEngine(diamond_graph())
    state = engine.create([{"starting_room": "room"}])
    hazard = engine.add_hazard(state, "fire", "corridor", "fast-b", 1)
    engine.set_hazard_active(state, hazard.hazard_id, False)
    event_types = [event.event_type for event in state.event_history]
    assert "hazard_activated" in event_types
    assert "route_replanned" in event_types
    assert "hazard_resolved" in event_types
    assert "routes_recalculated" in event_types


def test_propagation_is_optional_connected_and_deterministic():
    building = diamond_graph()
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}])
    hazard = engine.add_hazard(
        state, "fire", "node", "junction-a", 0.6,
        propagation_enabled=True, propagation_interval_steps=1, max_spread=1,
    )
    assert not hazard.propagated_targets
    engine.advance(state)
    propagated_ids = {target["target_id"] for target in hazard.propagated_targets}
    assert {"fast-a", "fast-b"}.issubset(propagated_ids)
    assert "safe-b" not in propagated_ids
    assert "fast-a" in effective_conditions(building, state)["blocked_corridors"]
    assert any(event.event_type == "hazard_propagated" for event in state.event_history)


def test_hazard_inside_corridor_strands_without_teleporting_or_releasing_occupancy():
    graph = diamond_graph()
    graph["nodes"].append({"id": "safe-room", "type": "room", "x": 0, "y": 2})
    graph["corridors"].append({
        "id": "safe-route", "from": "safe-room", "to": "exit-b", "distance": 2,
        "travel_time_seconds": 100, "capacity": 3, "hazard_risk": 0,
        "crowd_density": 0, "step_free": True,
    })
    engine = SimulationEngine(graph)
    state = engine.create([{"starting_room": "room"}, {"starting_room": "safe-room"}])
    engine.corridors[state.evacuees[0].route_corridors[0]]["travel_time_seconds"] = 100
    engine.advance(state)
    person = state.evacuees[0]
    occupied = person.current_corridor
    assert occupied
    old_node = person.current_node
    engine.add_hazard(state, "fire", "corridor", occupied, 1)
    assert person.status == "unable_to_evacuate"
    assert person.current_node == old_node
    assert person.current_corridor == occupied
    assert state.corridor_occupancy[occupied] == 1
    engine.set_hazard_active(state, state.hazards[0].hazard_id, False)
    assert person.status == "moving"
    assert person.current_corridor == occupied
    assert state.corridor_occupancy[occupied] == 1


def test_reset_clears_hazards_exit_overrides_and_rebuilds_routes():
    manager = SimulationManager(diamond_graph())
    state = manager.create(evacuee_specs=[{"starting_room": "room"}])
    manager.add_hazard(state.simulation_id, hazard_type="flood", target_type="node", target_id="junction-a", severity=0.7)
    manager.set_exit_available(state.simulation_id, "exit-a", False)
    reset = manager.reset(state.simulation_id)
    assert reset.hazards == []
    assert reset.manually_unavailable_exits == []
    assert reset.evacuees[0].route == ["room", "junction-a", "exit-a"]


def test_hazard_api_rejects_unknown_target_clearly():
    created = create_simulation(SimulationCreateRequest(number_of_evacuees=1))
    request = HazardCreateRequest(hazard_type="fire", target_type="node", target_id="not-a-node")
    with pytest.raises(HTTPException) as error:
        create_hazard(created["simulation_id"], request)
    assert error.value.status_code == 422
    assert "Unknown node" in error.value.detail

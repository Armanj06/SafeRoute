"""Deterministic tests for optional walking speed and reaction delay."""
import math

import pytest
from pydantic import ValidationError

from app.api import routes
from app.api.routes import EvacueeSpec, SimulationCreateRequest, create_simulation
from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings
from app.simulation.service import SimulationManager
from app.services.building import load_building


def one_corridor_graph():
    return {
        "id": "timing-fixture",
        "nodes": [
            {"id": "timing-room", "type": "room", "x": 0, "y": 0},
            {"id": "timing-exit", "type": "exit", "x": 12, "y": 0},
        ],
        "corridors": [{
            "id": "timing-corridor", "from": "timing-room", "to": "timing-exit",
            "distance": 12, "travel_time_seconds": 6, "capacity": 10,
            "crowd_density": 0, "hazard_risk": 0, "step_free": True,
        }],
    }


def finish(engine, state, limit=20):
    for _ in range(limit):
        if state.status == "completed":
            break
        engine.advance(state)
    assert state.status == "completed"


def test_explicit_speed_zero_delay_and_fractional_traversal_round_up_to_step():
    engine = SimulationEngine(one_corridor_graph())
    state = engine.create([{
        "starting_room": "timing-room",
        "walking_speed_mps": 2.0,
        "reaction_delay_seconds": 0.0,
    }], SimulationSettings(time_step_seconds=5, congestion_penalty=0))
    person = state.evacuees[0]

    assert person.remaining_segment_seconds == 0
    engine.advance(state)
    assert state.current_time_seconds == 5
    assert person.current_corridor == "timing-corridor"
    assert person.remaining_segment_seconds == pytest.approx(1)
    assert person.time_spent_seconds == 5

    engine.advance(state)
    assert person.status == "evacuated"
    assert person.time_spent_seconds == state.current_time_seconds == 10


def test_faster_per_agent_speed_changes_duration_but_omitted_speed_keeps_edge_time():
    engine = SimulationEngine(one_corridor_graph())
    settings = SimulationSettings(time_step_seconds=5, congestion_penalty=0)
    legacy = engine.create([{"starting_room": "timing-room"}], settings)
    fast = engine.create([{
        "starting_room": "timing-room", "walking_speed_mps": 4.0,
    }], settings)

    finish(engine, legacy)
    finish(engine, fast)
    assert legacy.evacuees[0].walking_speed_mps is None
    assert legacy.evacuees[0].time_spent_seconds == 10  # edge estimate is 6s, rounded to 5s steps
    assert fast.evacuees[0].time_spent_seconds == 5  # 12m / 4m/s = 3s


def test_reaction_delay_between_step_boundaries_never_starts_movement_early():
    engine = SimulationEngine(one_corridor_graph())
    state = engine.create([{
        "starting_room": "timing-room",
        "walking_speed_mps": 2.0,
        "reaction_delay_seconds": 7.0,
    }], SimulationSettings(time_step_seconds=5, congestion_penalty=0))
    person = state.evacuees[0]

    engine.advance(state)
    assert state.current_time_seconds == 5
    assert person.current_corridor is None
    assert person.remaining_reaction_seconds == 2
    engine.advance(state)
    assert state.current_time_seconds == 10
    assert person.current_corridor is None
    assert person.remaining_reaction_seconds == 0

    engine.advance(state)
    assert state.current_time_seconds == 15
    assert person.current_corridor == "timing-corridor"
    assert person.remaining_segment_seconds == pytest.approx(1)
    finish(engine, state)
    assert person.time_spent_seconds == 20


@pytest.mark.parametrize("speed", [0, -1, math.inf, -math.inf, math.nan])
def test_invalid_per_agent_walking_speeds_are_rejected(speed):
    engine = SimulationEngine(one_corridor_graph())
    with pytest.raises(ValueError, match="walking_speed_mps"):
        engine.create([{"starting_room": "timing-room", "walking_speed_mps": speed}])


@pytest.mark.parametrize("delay", [-1, math.inf, -math.inf, math.nan])
def test_invalid_per_agent_reaction_delays_are_rejected(delay):
    engine = SimulationEngine(one_corridor_graph())
    with pytest.raises(ValueError, match="reaction_delay_seconds"):
        engine.create([{"starting_room": "timing-room", "reaction_delay_seconds": delay}])


@pytest.mark.parametrize("speed", [0, -1, math.inf, -math.inf, math.nan])
def test_api_rejects_invalid_speed_values(speed):
    with pytest.raises(ValidationError):
        SimulationCreateRequest(number_of_evacuees=1, walking_speed_mps=speed)
    with pytest.raises(ValidationError):
        EvacueeSpec(starting_room="timing-room", walking_speed_mps=speed)


@pytest.mark.parametrize("delay", [-1, math.inf, -math.inf, math.nan])
def test_api_rejects_invalid_reaction_delay_values(delay):
    with pytest.raises(ValidationError):
        SimulationCreateRequest(number_of_evacuees=1, reaction_delay_seconds=delay)
    with pytest.raises(ValidationError):
        EvacueeSpec(starting_room="timing-room", reaction_delay_seconds=delay)


def test_simulation_settings_defaults_preserve_legacy_timing_and_allow_explicit_count_defaults():
    assert SimulationCreateRequest(number_of_evacuees=1).walking_speed_mps is None
    assert SimulationCreateRequest(number_of_evacuees=1).reaction_delay_seconds == 0
    configured = SimulationCreateRequest(
        number_of_evacuees=2, walking_speed_mps=1.5, reaction_delay_seconds=3,
    )
    assert configured.walking_speed_mps == 1.5
    assert configured.reaction_delay_seconds == 3


def test_api_applies_agent_defaults_to_generated_agents_and_allows_explicit_overrides(monkeypatch):
    manager = SimulationManager(load_building())
    monkeypatch.setattr(routes, "simulation_manager", manager)

    generated = create_simulation(SimulationCreateRequest(
        number_of_evacuees=1, walking_speed_mps=1.5, reaction_delay_seconds=7,
    ))
    generated_agent = generated["evacuees"][0]
    assert generated_agent["walking_speed_mps"] == 1.5
    assert generated_agent["reaction_delay_seconds"] == 7
    assert generated_agent["remaining_reaction_seconds"] == 7

    explicit = create_simulation(SimulationCreateRequest(
        evacuees=[{
            "starting_room": "room-101",
            "walking_speed_mps": 2.5,
            "reaction_delay_seconds": 2,
        }],
        walking_speed_mps=1.5,
        reaction_delay_seconds=7,
    ))
    explicit_agent = explicit["evacuees"][0]
    assert explicit_agent["walking_speed_mps"] == 2.5
    assert explicit_agent["reaction_delay_seconds"] == 2

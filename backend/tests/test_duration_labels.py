"""Deterministic tests for complete-evacuation duration label eligibility."""
from copy import deepcopy

import pytest

from app.simulation.duration_labels import duration_label_eligibility
from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings


def graph(throughput=None):
    exit_node = {"id": "exit", "type": "exit", "x": 2, "y": 0}
    if throughput is not None:
        exit_node["throughput_people_per_second"] = throughput
    return {
        "id": "duration-label-fixture",
        "nodes": [
            {"id": "room", "type": "room", "x": 0, "y": 0},
            {"id": "junction", "type": "junction", "x": 1, "y": 0},
            exit_node,
        ],
        "corridors": [
            {"id": "room-junction", "from": "room", "to": "junction", "distance": 1,
             "travel_time_seconds": 1, "capacity": 10, "crowd_density": 0,
             "hazard_risk": 0, "step_free": True},
            {"id": "junction-exit", "from": "junction", "to": "exit", "distance": 1,
             "travel_time_seconds": 1, "capacity": 10, "crowd_density": 0,
             "hazard_risk": 0, "step_free": True},
        ],
    }


def completed_state(count=1):
    engine = SimulationEngine(graph())
    state = engine.create(
        [{"starting_room": "room"} for _ in range(count)],
        SimulationSettings(time_step_seconds=1, congestion_penalty=0),
    )
    engine.advance(state, 10)
    return state


def test_empty_run_is_ineligible_without_a_duration_label():
    state = SimulationEngine(graph()).create([], SimulationSettings(time_step_seconds=1))
    assert duration_label_eligibility(state) == {
        "eligible": False,
        "reason_code": "no_evacuees",
        "target_name": None,
        "target_value_seconds": None,
    }


@pytest.mark.parametrize("status", ["running", "paused"])
def test_running_and_paused_runs_are_not_terminal_labels(status):
    state = SimulationEngine(graph()).create(
        [{"starting_room": "room"}], SimulationSettings(time_step_seconds=1)
    )
    state.status = status
    assert duration_label_eligibility(state)["reason_code"] == "simulation_not_terminated"


def test_one_successful_evacuee_uses_last_successful_completion_time():
    state = completed_state()
    before = state.summary().copy()
    result = duration_label_eligibility(state)
    assert result == {
        "eligible": True,
        "reason_code": "eligible",
        "target_name": "evacuation_duration_seconds",
        "target_value_seconds": state.last_successful_evacuation_time_seconds,
    }
    assert result["target_value_seconds"] == state.summary()["simulation_termination_time_seconds"]
    assert state.summary() == before


def test_multiple_successes_use_the_latest_individual_completion_time():
    state = completed_state(count=3)
    result = duration_label_eligibility(state)
    assert result["eligible"] is True
    assert result["target_value_seconds"] == max(
        person.time_spent_seconds for person in state.evacuees
    )
    assert result["target_value_seconds"] == state.summary()["simulation_termination_time_seconds"]


def test_terminal_run_with_people_remaining_is_not_a_duration_label():
    state = SimulationEngine(graph()).create(
        [{"starting_room": "room"}],
        SimulationSettings(time_step_seconds=1, unavailable_exits=["exit"]),
    )
    assert state.status == "completed"
    result = duration_label_eligibility(state)
    assert result["eligible"] is False
    assert result["reason_code"] == "evacuation_incomplete"
    assert result["target_value_seconds"] is None


def test_contradictory_terminal_metadata_is_rejected():
    state = completed_state()
    state.total_simulation_duration_seconds += 1
    result = duration_label_eligibility(state)
    assert result["eligible"] is False
    assert result["reason_code"] == "inconsistent_completion_metadata"
    assert result["target_value_seconds"] is None


@pytest.mark.parametrize("invalid_value", [None, -1.0, float("inf"), float("nan")])
def test_missing_negative_or_non_finite_terminal_duration_is_rejected(invalid_value):
    state = completed_state()
    state.total_simulation_duration_seconds = invalid_value
    result = duration_label_eligibility(state)
    assert result["eligible"] is False
    assert result["reason_code"] == "inconsistent_completion_metadata"
    assert result["target_value_seconds"] is None


def test_non_finite_last_success_or_person_time_is_rejected():
    state = completed_state()
    broken_success = deepcopy(state)
    broken_success.last_successful_evacuation_time_seconds = float("inf")
    assert duration_label_eligibility(broken_success)["reason_code"] == "inconsistent_completion_metadata"

    broken_person = deepcopy(state)
    broken_person.evacuees[0].time_spent_seconds = float("nan")
    assert duration_label_eligibility(broken_person)["reason_code"] == "inconsistent_completion_metadata"

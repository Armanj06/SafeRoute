"""Deterministic tests for optional per-exit throughput service queues."""
import csv
import io
import math

import pytest

from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings
from app.simulation.reports import build_csv_report, build_report
from app.simulation.service import SimulationManager


def one_exit_graph(throughput=None, model_id="one-exit"):
    exit_node = {"id": "exit-a", "type": "exit", "x": 1, "y": 0}
    if throughput is not None:
        exit_node["throughput_people_per_second"] = throughput
    return {
        "id": model_id,
        "nodes": [
            {"id": "room", "type": "room", "x": 0, "y": 0},
            exit_node,
        ],
        "corridors": [{
            "id": "to-exit", "from": "room", "to": "exit-a",
            "distance": 1, "travel_time_seconds": 0.1, "capacity": 10,
            "crowd_density": 0, "hazard_risk": 0, "step_free": True,
        }],
    }


def evacuees(count):
    return [{"starting_room": "room"} for _ in range(count)]


def test_exit_without_throughput_keeps_immediate_exit_behavior():
    engine = SimulationEngine(one_exit_graph())
    state = engine.create(evacuees(1), SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state)
    person = state.evacuees[0]
    assert person.status == "evacuated"
    assert state.exit_queues["exit-a"] == []
    assert state.last_successful_evacuation_time_seconds == 1


def test_one_person_waits_for_exit_service_and_stats_record_boundary_time():
    engine = SimulationEngine(one_exit_graph(throughput=0.5))
    state = engine.create(evacuees(1), SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state)
    person = state.evacuees[0]
    assert person.status == "waiting_exit_service"
    assert state.summary()["waiting_for_exit_service"] == 1
    assert state.summary()["last_successful_evacuation_time_seconds"] is None

    engine.advance(state)
    assert person.status == "waiting_exit_service"
    assert person.exit_service_remaining_seconds == pytest.approx(1)
    engine.advance(state)
    assert person.status == "evacuated"
    assert person.time_spent_seconds == 3
    assert state.last_successful_evacuation_time_seconds == 3
    assert state.summary()["simulation_termination_time_seconds"] == 3


def test_simultaneous_arrivals_use_stable_fifo_order_and_respect_throughput():
    engine = SimulationEngine(one_exit_graph(throughput=0.5))
    state = engine.create(evacuees(3), SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state)
    assert state.exit_queues["exit-a"] == ["person-0001", "person-0002", "person-0003"]
    assert state.summary()["total_evacuated"] == 0

    for _ in range(6):
        engine.advance(state)
    assert [person.status for person in state.evacuees] == ["evacuated"] * 3
    assert [event.evacuee_id for event in state.event_history if event.event_type == "exit_service_completed"] == [
        "person-0001", "person-0002", "person-0003",
    ]
    assert state.evacuees[0].time_spent_seconds == 3
    assert state.evacuees[1].time_spent_seconds == 5
    assert state.evacuees[2].time_spent_seconds == 7
    assert state.last_successful_evacuation_time_seconds == 7


def test_fractional_service_duration_rounds_up_to_step_boundary():
    engine = SimulationEngine(one_exit_graph(throughput=1 / 3))
    state = engine.create(evacuees(1), SimulationSettings(time_step_seconds=2, congestion_penalty=0))
    engine.advance(state)
    assert state.evacuees[0].status == "waiting_exit_service"
    engine.advance(state)
    assert state.evacuees[0].status == "waiting_exit_service"
    engine.advance(state)
    assert state.evacuees[0].status == "evacuated"
    assert state.last_successful_evacuation_time_seconds == 6


@pytest.mark.parametrize("throughput", [0, -1, math.inf, -math.inf, math.nan])
def test_invalid_exit_throughput_is_rejected(throughput):
    with pytest.raises(ValueError, match="throughput_people_per_second"):
        SimulationEngine(one_exit_graph(throughput=throughput))


def alternate_exit_graph():
    graph = one_exit_graph(throughput=0.5, model_id="alternate-exits")
    graph["nodes"].insert(1, {"id": "junction", "type": "junction", "x": 1, "y": 0})
    graph["nodes"][2]["x"] = 2
    graph["nodes"][2]["y"] = 1
    graph["nodes"].append({"id": "exit-b", "type": "exit", "x": 2, "y": -1})
    graph["corridors"] = [
        {"id": "room-j", "from": "room", "to": "junction", "distance": 1, "travel_time_seconds": 0.1, "capacity": 10, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
        {"id": "j-a", "from": "junction", "to": "exit-a", "distance": 1, "travel_time_seconds": 0.1, "capacity": 10, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
        {"id": "j-b", "from": "junction", "to": "exit-b", "distance": 2, "travel_time_seconds": 0.2, "capacity": 10, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
    ]
    return graph


def test_exit_closure_cancels_queue_and_replans_to_an_alternative():
    engine = SimulationEngine(alternate_exit_graph())
    state = engine.create(evacuees(1), SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state)
    engine.advance(state)
    person = state.evacuees[0]
    assert person.status == "waiting_exit_service"
    assert state.exit_queues["exit-a"] == [person.evacuee_id]

    engine.set_exit_available(state, "exit-a", False)
    assert state.exit_queues["exit-a"] == []
    assert person.status == "waiting"
    assert person.assigned_exit == "exit-b"
    assert person.route[0] == "exit-a"
    for _ in range(3):
        engine.advance(state)
    assert person.status == "evacuated"
    assert person.current_node == "exit-b"


def test_exit_closure_without_alternative_does_not_count_queued_person_as_evacuated():
    engine = SimulationEngine(one_exit_graph(throughput=0.5))
    state = engine.create(evacuees(1), SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state)
    engine.set_exit_available(state, "exit-a", False)
    assert state.exit_queues["exit-a"] == []
    assert state.evacuees[0].status == "unable_to_evacuate"
    assert state.summary()["total_evacuated"] == 0
    assert state.summary()["unable_to_evacuate"] == 1


def test_hazard_makes_queued_exit_unavailable_and_uses_an_alternative():
    engine = SimulationEngine(alternate_exit_graph())
    state = engine.create(evacuees(1), SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state)
    engine.advance(state)
    person = state.evacuees[0]
    engine.add_hazard(state, "fire", "node", "exit-a", 1)
    assert state.exit_queues["exit-a"] == []
    assert person.status == "waiting"
    assert person.assigned_exit == "exit-b"


def test_model_bound_runs_keep_exit_queues_and_throughput_independent():
    building_a = one_exit_graph(throughput=2, model_id="model-a")
    building_b = one_exit_graph(throughput=0.5, model_id="model-b")
    manager = SimulationManager(building_a, building_loader=lambda model_id: {
        "model-a": building_a, "model-b": building_b,
    }.get(model_id))
    state_a = manager.create(number_of_evacuees=1, settings=SimulationSettings(time_step_seconds=1, congestion_penalty=0), building_id="model-a")
    state_b = manager.create(number_of_evacuees=1, settings=SimulationSettings(time_step_seconds=1, congestion_penalty=0), building_id="model-b")
    manager.advance(state_a.simulation_id)
    manager.advance(state_b.simulation_id)
    manager.advance(state_a.simulation_id)
    manager.advance(state_b.simulation_id)
    assert state_a.building_id == "model-a"
    assert state_b.building_id == "model-b"
    assert state_a.evacuees[0].status == "evacuated"
    assert state_b.evacuees[0].status == "waiting_exit_service"
    assert state_a.exit_queues["exit-a"] == []
    assert state_b.exit_queues["exit-a"] == ["person-0001"]


def test_summary_json_and_csv_report_the_same_exit_queue_state():
    building = one_exit_graph(throughput=0.5)
    engine = SimulationEngine(building)
    state = engine.create(evacuees(2), SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state)
    report = build_report(building, state)
    serialized = state.to_dict(building)
    assert report["analytics"]["waiting_for_exit_service"] == state.summary()["waiting_for_exit_service"] == 2
    assert report["analytics"]["total_evacuated"] == 0
    assert report["exit_service"][0]["queue"] == state.exit_queues["exit-a"]
    assert serialized["statistics"]["waiting_for_exit_service"] == 2
    assert serialized["exit_queues"]["exit-a"] == state.exit_queues["exit-a"]
    rows = list(csv.DictReader(io.StringIO(build_csv_report(report))))
    exit_row = next(row for row in rows if row["record_type"] == "exit")
    assert exit_row["queue_length"] == "2"
    assert exit_row["throughput_people_per_second"] == "0.5"
    summary_row = next(row for row in rows if row["record_type"] == "summary")
    assert '"waiting_for_exit_service": 2' in summary_row["details"]

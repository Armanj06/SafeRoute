"""Regression coverage for simulation timing and terminal-state accounting."""
import csv
import io

from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings
from app.simulation.reports import build_csv_report, build_report


def single_exit_graph(with_alternative=False):
    nodes = [
        {"id": "room", "type": "room", "x": 0, "y": 0},
        {"id": "junction", "type": "junction", "x": 1, "y": 0},
        {"id": "exit-a", "type": "exit", "x": 2, "y": 0, "throughput_people_per_second": 0.5},
    ]
    corridors = [
        {"id": "room-j", "from": "room", "to": "junction", "distance": 1, "travel_time_seconds": 0.1, "capacity": 8, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
        {"id": "j-a", "from": "junction", "to": "exit-a", "distance": 1, "travel_time_seconds": 0.1, "capacity": 8, "crowd_density": 0, "hazard_risk": 0, "step_free": True},
    ]
    if with_alternative:
        nodes.append({"id": "exit-b", "type": "exit", "x": 2, "y": 1, "throughput_people_per_second": 0.5})
        corridors.append({"id": "j-b", "from": "junction", "to": "exit-b", "distance": 2, "travel_time_seconds": 0.2, "capacity": 8, "crowd_density": 0, "hazard_risk": 0, "step_free": True})
    return {"id": "lifecycle-fixture", "nodes": nodes, "corridors": corridors}


def assert_status_accounting(state, building):
    counts = {
        "evacuated": sum(person.status == "evacuated" for person in state.evacuees),
        "unable": sum(person.status == "unable_to_evacuate" for person in state.evacuees),
        "active": sum(person.status in {"waiting", "moving", "waiting_exit_service"} for person in state.evacuees),
    }
    assert sum(counts.values()) == len(state.evacuees)
    serialized = state.to_dict(building)
    assert sum(agent["status"] == "evacuated" for agent in serialized["evacuees"]) == counts["evacuated"]
    assert sum(agent["status"] == "unable_to_evacuate" for agent in serialized["evacuees"]) == counts["unable"]
    assert sum(agent["status"] in {"waiting", "moving", "waiting_exit_service"} for agent in serialized["evacuees"]) == counts["active"]
    stats = serialized["statistics"]
    assert stats["total_evacuated"] == counts["evacuated"]
    assert stats["unable_to_evacuate"] == counts["unable"]
    assert stats["active_remaining"] == counts["active"]


def test_temporary_unable_time_is_included_when_another_agent_keeps_run_active():
    building = {
        "id": "recovery-fixture",
        "nodes": [
            {"id": "room-a", "type": "room"}, {"id": "exit-a", "type": "exit"},
            {"id": "room-b", "type": "room"}, {"id": "exit-b", "type": "exit"},
        ],
        "corridors": [
            {"id": "path-a", "from": "room-a", "to": "exit-a", "distance": 1, "travel_time_seconds": 1, "capacity": 4, "crowd_density": 0, "hazard_risk": 0},
            {"id": "path-b", "from": "room-b", "to": "exit-b", "distance": 1, "travel_time_seconds": 10, "capacity": 4, "crowd_density": 0, "hazard_risk": 0},
        ],
    }
    engine = SimulationEngine(building)
    state = engine.create(
        [{"starting_room": "room-a"}, {"starting_room": "room-b"}],
        SimulationSettings(time_step_seconds=1, congestion_penalty=0),
    )
    recovering = state.evacuees[0]
    engine.add_hazard(state, "fire", "corridor", "path-a", 1)
    assert recovering.status == "unable_to_evacuate"
    assert state.status != "completed"

    engine.advance(state, 3)
    assert recovering.time_spent_seconds == 3
    assert state.evacuees[1].status == "moving"
    assert_status_accounting(state, building)

    engine.set_hazard_active(state, state.hazards[0].hazard_id, False)
    assert recovering.status == "waiting"
    engine.advance(state)
    assert recovering.status == "evacuated"
    assert recovering.time_spent_seconds == 4
    assert state.last_successful_evacuation_time_seconds == 4


def test_last_agent_becoming_unable_terminates_immediately_after_exit_closure():
    building = single_exit_graph()
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}], SimulationSettings(time_step_seconds=1))
    assert state.status == "paused"

    engine.set_exit_available(state, "exit-a", False)

    summary = state.summary()
    assert state.evacuees[0].status == "unable_to_evacuate"
    assert state.status == "completed"
    assert summary["simulation_terminated"] is True
    assert summary["outcome"] == "terminated_with_people_remaining"
    assert summary["active_remaining"] == 0
    assert summary["simulation_termination_time_seconds"] == 0
    assert summary["last_successful_evacuation_time_seconds"] is None
    assert [event.event_type for event in state.event_history].count("simulation_terminated") == 1
    assert_status_accounting(state, building)


def test_exit_closure_cancels_partially_completed_service_without_crediting_it_again():
    building = single_exit_graph(with_alternative=True)
    engine = SimulationEngine(building)
    state = engine.create([{"starting_room": "room"}], SimulationSettings(time_step_seconds=1, congestion_penalty=0))
    engine.advance(state, 2)  # arrives at exit-a at t=2; service starts next interval
    engine.advance(state)  # one second of the two-second service has elapsed
    person = state.evacuees[0]
    assert person.status == "waiting_exit_service"
    assert person.exit_service_remaining_seconds == 1
    assert person.time_spent_seconds == 3

    engine.set_exit_available(state, "exit-a", False)
    assert person.status == "waiting"
    assert person.current_node == "exit-a"
    assert person.assigned_exit == "exit-b"
    assert person.time_spent_seconds == 3
    assert state.exit_queues["exit-a"] == []
    assert state.exit_service_remaining_seconds["exit-a"] is None
    assert state.summary()["total_evacuated"] == 0
    assert state.summary()["waiting_for_exit_service"] == 0
    assert_status_accounting(state, building)

    interim_report = build_report(building, state)
    assert interim_report["analytics"]["total_evacuated"] == 0
    assert interim_report["exit_service"][0]["queue"] == []
    interim_csv = list(csv.DictReader(io.StringIO(build_csv_report(interim_report))))
    exit_a_row = next(row for row in interim_csv if row["record_type"] == "exit" and row["exit_id"] == "exit-a")
    assert exit_a_row["queue_length"] == "0"

    engine.advance(state, 4)
    assert person.status == "evacuated"
    assert person.current_node == "exit-b"
    assert person.time_spent_seconds == 7  # old partial service was canceled; exit-b service is a fresh 2s
    assert state.last_successful_evacuation_time_seconds == 7
    assert state.summary()["simulation_termination_time_seconds"] == 7
    assert state.exit_queues["exit-a"] == state.exit_queues["exit-b"] == []
    assert_status_accounting(state, building)


def test_empty_direct_engine_simulation_completes_consistently_at_time_zero():
    building = single_exit_graph()
    engine = SimulationEngine(building)
    state = engine.create([], SimulationSettings(time_step_seconds=1))
    summary = state.summary()
    assert state.status == "completed"
    assert summary["total_evacuees"] == 0
    assert summary["total_remaining"] == 0
    assert summary["total_evacuated"] == 0
    assert summary["evacuation_complete"] is False
    assert summary["simulation_terminated"] is True
    assert summary["outcome"] == "no_evacuees"
    assert summary["simulation_duration_seconds"] == 0
    assert summary["simulation_termination_time_seconds"] == 0
    assert summary["last_successful_evacuation_time_seconds"] is None
    assert state.event_history[-1].event_type == "simulation_completed"

    reset = engine.reset(state)
    assert reset.status == "completed"
    assert reset.summary()["simulation_termination_time_seconds"] == 0
    assert [event.event_type for event in reset.event_history] == [
        "simulation_reset", "simulation_completed",
    ]

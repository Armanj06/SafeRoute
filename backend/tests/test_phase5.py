import csv
import io
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.algorithms.comparison import compare_routes
from app.api.routes import (
    RouteComparisonRequest,
    SimulationCreateRequest,
    create_simulation,
    export_simulation_report,
    start_scenario,
)
from app.services.building import load_building
from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings
from app.simulation.scenarios import list_scenarios
from app.simulation.service import SimulationManager


def weighted_graph():
    return {
        "nodes": [
            {"id": "room", "type": "room"}, {"id": "hub", "type": "junction"},
            {"id": "exit-a", "type": "exit"}, {"id": "exit-b", "type": "exit"},
        ],
        "corridors": [
            {"id": "short-1", "from": "room", "to": "exit-a", "distance": 20, "travel_time_seconds": 20, "capacity": 5, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
            {"id": "long-1", "from": "room", "to": "hub", "distance": 4, "travel_time_seconds": 4, "capacity": 5, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
            {"id": "long-2", "from": "hub", "to": "exit-b", "distance": 4, "travel_time_seconds": 4, "capacity": 5, "hazard_risk": 0, "crowd_density": 0, "step_free": True},
        ],
    }


def test_algorithm_comparison_uses_same_conditions_and_measured_metrics():
    comparison = compare_routes(weighted_graph(), "room", cost_model="distance")
    results = {result["algorithm"]: result for result in comparison["results"]}
    assert results["bfs"]["route"] == ["room", "exit-a"]
    assert results["dijkstra"]["total_cost"] == results["astar"]["total_cost"] == 8
    for algorithm in ("bfs", "dijkstra", "astar"):
        assert isinstance(results[algorithm]["nodes_expanded"], int)
        assert results[algorithm]["duration_ms"] >= 0
    utility = results["utility"]
    assert utility["strategy_type"] == "utility_agent"
    assert utility["nodes_expanded"] is None
    assert utility["candidate_states_expanded"] > 0
    assert comparison["methodology"]["safety_conditions_shared"] is True


def test_algorithm_comparison_reports_no_route_for_all_strategies():
    result = compare_routes(weighted_graph(), "room", blocked_corridors={"short-1", "long-1"})
    assert all(not item["found"] for item in result["results"])
    assert all(item["route"] == [] for item in result["results"])


def test_comparison_request_validates_cost_model_and_candidate_limit():
    with pytest.raises(ValidationError):
        RouteComparisonRequest(starting_room="room", cost_model="unsafe")
    with pytest.raises(ValidationError):
        RouteComparisonRequest(starting_room="room", candidate_limit=0)


def test_analytics_distinguish_successful_evacuation_from_termination_with_people_remaining():
    engine = SimulationEngine(load_building())
    successful = engine.create([{"starting_room": "room-101"}], SimulationSettings(time_step_seconds=60))
    engine.advance(successful, 20)
    good_stats = successful.summary()
    assert good_stats["evacuation_complete"] is True
    assert good_stats["completion_percentage"] == 100
    assert good_stats["average_evacuation_duration_seconds"] == successful.evacuees[0].time_spent_seconds
    assert good_stats["outcome"] == "evacuated"

    stranded = engine.create([{"starting_room": "room-101"}], SimulationSettings(blocked_corridors=["c1", "c13"]))
    bad_stats = stranded.summary()
    assert bad_stats["simulation_terminated"] is True
    assert bad_stats["evacuation_complete"] is False
    assert bad_stats["total_remaining"] == 1
    assert bad_stats["unable_to_evacuate"] == 1
    assert bad_stats["completion_percentage"] == 0
    assert bad_stats["outcome"] == "terminated_with_people_remaining"


def test_scenarios_are_repeatable_and_reset_restores_initial_conditions():
    manager = SimulationManager(load_building())
    scenarios = list_scenarios()
    assert {scenario["scenario_id"] for scenario in scenarios} == {
        "baseline", "corridor-congestion", "fire-corridor", "exit-unavailable",
        "restricted-access", "no-safe-route", "ditu-vedanta-fire",
        "ditu-vedanta-blocked-corridor", "ditu-vedanta-exit-closed",
        "ditu-vedanta-flood", "ditu-vedanta-crowd-near-exit",
        "ditu-vedanta-multiple-hazards",
    }
    state = manager.create_scenario("fire-corridor")
    assert state is not None
    assert state.scenario_id == "fire-corridor"
    assert any(hazard.active and hazard.target_id == "c4" for hazard in state.hazards)
    manager.advance(state.simulation_id, 2)
    manager.add_hazard(state.simulation_id, hazard_type="flood", target_type="node", target_id="junction-e", severity=0.7)
    reset = manager.reset(state.simulation_id)
    assert reset.scenario_id == "fire-corridor"
    assert len(reset.hazards) == 1
    assert reset.hazards[0].target_id == "c4"
    assert reset.current_step == 0
    assert reset.manually_unavailable_exits == []

    closed = manager.create_scenario("exit-unavailable")
    assert "exit-north" in manager.conditions(closed)["unavailable_exits"]
    closed.manually_unavailable_exits.clear()
    restored = manager.reset(closed.simulation_id)
    assert "exit-north" in manager.conditions(restored)["unavailable_exits"]


def test_scenario_endpoints_reject_unknown_scenario():
    with pytest.raises(HTTPException) as error:
        start_scenario("not-a-scenario")
    assert error.value.status_code == 404


def test_json_and_csv_exports_contain_only_the_selected_run():
    selected = create_simulation(SimulationCreateRequest(
        number_of_evacuees=1, walking_speed_mps=1.4, reaction_delay_seconds=7,
    ))
    other = create_simulation(SimulationCreateRequest(number_of_evacuees=2))
    simulation_id = selected["simulation_id"]
    json_response = export_simulation_report(simulation_id, "json")
    csv_response = export_simulation_report(simulation_id, "csv")
    assert simulation_id.encode() in json_response.body
    assert other["simulation_id"].encode() not in json_response.body
    assert b'"campus_location": "Vedanta"' in json_response.body
    assert b'"model_status": "illustrative"' in json_response.body
    assert json_response.headers["content-disposition"].endswith(f'{simulation_id}.json"')
    report_data = json.loads(json_response.body)
    assert report_data["building_id"] == report_data["simulation"]["building_id"] == "dit-vedanta-illustrative"
    assert report_data["evacuees"][0]["walking_speed_mps"] == 1.4
    assert report_data["evacuees"][0]["reaction_delay_seconds"] == 7
    rows = list(csv.DictReader(io.StringIO(csv_response.body.decode())))
    assert {row["simulation_id"] for row in rows} == {simulation_id}
    assert {row["record_type"] for row in rows} >= {"summary", "evacuee", "corridor"}
    evacuee_row = next(row for row in rows if row["record_type"] == "evacuee")
    assert evacuee_row["walking_speed_mps"] == "1.4"
    assert evacuee_row["reaction_delay_seconds"] == "7.0"
    assert all(row["campus_location"] == "Vedanta" for row in rows)
    assert all(row["model_status"] == "illustrative" for row in rows)


def test_report_for_unknown_simulation_is_not_found():
    with pytest.raises(HTTPException) as error:
        export_simulation_report("missing-id", "json")
    assert error.value.status_code == 404

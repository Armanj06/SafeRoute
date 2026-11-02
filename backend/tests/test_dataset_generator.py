"""Tests for reproducible synthetic records created by the existing engine."""
import json
from copy import deepcopy

import pytest

from scripts.generate_simulation_dataset import (
    DATASET_SCHEMA_VERSION,
    expanded_scenario_matrix,
    execute_prepared_run,
    generate_records,
    prepare_run,
    scenario_matrix,
    stable_hash,
    write_jsonl,
)


def small_graph():
    return {
        "id": "synthetic-test-graph",
        "model_status": "test_fixture",
        "nodes": [
            {"id": "room-a", "type": "room", "x": 0, "y": 0},
            {"id": "room-b", "type": "room", "x": 0, "y": 1},
            {"id": "junction", "type": "junction", "x": 1, "y": 0},
            {"id": "exit-a", "type": "exit", "x": 2, "y": 0},
            {"id": "exit-b", "type": "exit", "x": 2, "y": 1},
        ],
        "corridors": [
            {"id": "room-junction", "from": "room-a", "to": "junction", "distance": 1,
             "travel_time_seconds": 1, "capacity": 4, "step_free": True},
            {"id": "room-b-junction", "from": "room-b", "to": "junction", "distance": 1,
             "travel_time_seconds": 1, "capacity": 4, "step_free": True},
            {"id": "junction-exit-a", "from": "junction", "to": "exit-a", "distance": 1,
             "travel_time_seconds": 1, "capacity": 4, "step_free": True},
            {"id": "junction-exit-b", "from": "junction", "to": "exit-b", "distance": 2,
             "travel_time_seconds": 2, "capacity": 4, "step_free": True},
        ],
    }


def scenario(**overrides):
    value = {
        "scenario_family": "test-family",
        "number_of_evacuees": 1,
        "starting_distribution": "round_robin",
        "default_walking_speed_mps": None,
        "default_reaction_delay_seconds": 0.0,
        "settings_overrides": {},
    }
    value.update(overrides)
    return value


def test_canonical_hash_ignores_mapping_order_and_changes_for_input_changes():
    assert stable_hash({"alpha": 1, "beta": {"x": 2}}) == stable_hash({"beta": {"x": 2}, "alpha": 1})
    assert stable_hash({"count": 1}) != stable_hash({"count": 2})


def test_predefined_matrix_is_small_and_has_unique_resolved_inputs():
    building = small_graph()
    matrix = scenario_matrix(building)
    prepared_hashes = {
        prepare_run(building, item)["configuration_hash"] for item in matrix
    }
    assert len(matrix) == 36
    assert len(prepared_hashes) == 36


def test_expanded_matrix_has_diverse_distinct_resolved_inputs():
    building = small_graph()
    matrix = expanded_scenario_matrix(building)
    prepared_hashes = {
        prepare_run(building, item)["configuration_hash"] for item in matrix
    }
    assert len(matrix) == 180
    assert len(prepared_hashes) == 180
    assert {item["number_of_evacuees"] for item in matrix} == {1, 4, 8, 16}
    assert {item["starting_distribution"] for item in matrix} == {
        "round_robin", "concentrated", "last_room_concentrated",
    }
    assert {item["default_walking_speed_mps"] for item in matrix} == {None, 1.0, 1.4}
    assert {item["default_reaction_delay_seconds"] for item in matrix} == {0.0, 5.0, 10.0}


def test_exact_duplicate_configurations_are_skipped_before_second_run():
    config = scenario()
    records, duplicates = generate_records(small_graph(), [config, deepcopy(config)])
    assert len(records) == 1
    assert duplicates == 1


def test_successful_record_uses_duration_label_helper_and_versioned_schema():
    graph = small_graph()
    prepared = prepare_run(graph, scenario())
    record = execute_prepared_run(graph, prepared, run_id_factory=lambda: "test-run-id")
    assert record["metadata"]["dataset_schema_version"] == DATASET_SCHEMA_VERSION
    assert record["metadata"]["run_id"] == "test-run-id"
    assert record["metadata"]["scenario_id"] == f"scenario-{record['metadata']['configuration_sha256']}"
    assert record["metadata"]["building_id"] == graph["id"]
    assert record["metadata"]["graph_content_sha256"] == record["inputs"]["graph_content_sha256"]
    assert record["metadata"]["terminal_status"] == "completed"
    assert record["metadata"]["duration_label_eligible"] is True
    assert record["outcomes"]["duration_label"]["target_value_seconds"] == record["outcomes"]["summary"]["simulation_termination_time_seconds"]
    assert record["outcomes"]["summary"]["total_evacuated"] == 1
    assert "status" not in record["inputs"]["evacuees"][0]
    assert record["inputs"]["starting_room_distribution"] == {"room-a": 1}
    assert len(record["outcomes"]["evacuees"]) == 1
    assert record["outcomes"]["evacuees"][0]["status"] == "evacuated"


def test_incomplete_record_has_null_target_and_preserves_terminal_outcome():
    graph = small_graph()
    config = scenario(settings_overrides={"blocked_corridors": ["room-junction"]})
    prepared = prepare_run(graph, config)
    record = execute_prepared_run(graph, prepared, run_id_factory=lambda: "incomplete-run")
    assert record["metadata"]["outcome_category"] == "incomplete"
    assert record["metadata"]["duration_label_eligible"] is False
    assert record["metadata"]["duration_label_reason_code"] == "evacuation_incomplete"
    assert record["outcomes"]["duration_label"]["target_value_seconds"] is None
    assert record["outcomes"]["summary"]["total_evacuated"] == 0


def test_input_record_captures_resolved_defaults_and_graph_topology():
    prepared = prepare_run(small_graph(), scenario(default_walking_speed_mps=1.0))
    inputs = prepared["inputs"]
    assert inputs["initial_evacuee_count"] == 1
    assert inputs["evacuees"][0]["walking_speed_mps"] == 1.0
    assert inputs["simulation_settings"]["time_step_seconds"]["source"] == "simulator_default"
    assert inputs["simulation_settings"]["default_walking_speed_mps"]["source"] == "scenario_configuration"
    assert inputs["graph_features"]["node_count"] == 5
    assert inputs["graph_features"]["corridor_count"] == 4
    assert inputs["graph_features"]["rooms_with_route_to_available_exit"] == 2
    assert inputs["exits"] == [
        {"exit_id": "exit-a", "throughput_people_per_second": None, "throughput_source": "immediate_service_default"},
        {"exit_id": "exit-b", "throughput_people_per_second": None, "throughput_source": "immediate_service_default"},
    ]


def test_jsonl_round_trip_and_accidental_overwrite_protection(tmp_path):
    graph = small_graph()
    records, _ = generate_records(graph, [scenario()])
    output = tmp_path / "nested" / "records.jsonl"
    write_jsonl(records, output)
    parsed = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert parsed == records
    with pytest.raises(FileExistsError, match="Use --overwrite"):
        write_jsonl(records, output)
    write_jsonl(records, output, overwrite=True)


def test_small_generation_is_reproducible_except_for_run_identity():
    graph = small_graph()
    configs = [scenario(), scenario(default_reaction_delay_seconds=5.0)]
    first, _ = generate_records(graph, configs, run_id_factory=lambda: "stable-run")
    second, _ = generate_records(graph, configs, run_id_factory=lambda: "stable-run")
    assert first == second
    assert len({record["metadata"]["configuration_sha256"] for record in first}) == len(first)


def test_json_serialization_rejects_non_finite_values():
    with pytest.raises(ValueError):
        stable_hash({"bad": float("nan")})

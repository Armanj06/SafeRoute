"""Deterministic tests for offline JSONL dataset validation."""
import json
from copy import deepcopy

from scripts.generate_simulation_dataset import generate_records, stable_hash, write_jsonl
from scripts.validate_simulation_dataset import validate_jsonl, validate_records


def graph():
    return {
        "id": "validation-fixture", "model_status": "test_fixture",
        "nodes": [
            {"id": "room-a", "type": "room", "x": 0, "y": 0},
            {"id": "room-b", "type": "room", "x": 0, "y": 1},
            {"id": "junction", "type": "junction", "x": 1, "y": 0},
            {"id": "exit-a", "type": "exit", "x": 2, "y": 0},
            {"id": "exit-b", "type": "exit", "x": 2, "y": 1},
        ],
        "corridors": [
            {"id": "a-j", "from": "room-a", "to": "junction", "distance": 1,
             "travel_time_seconds": 1, "capacity": 4, "step_free": True},
            {"id": "b-j", "from": "room-b", "to": "junction", "distance": 2,
             "travel_time_seconds": 2, "capacity": 4, "step_free": True},
            {"id": "j-a", "from": "junction", "to": "exit-a", "distance": 1,
             "travel_time_seconds": 1, "capacity": 4, "step_free": True},
            {"id": "j-b", "from": "junction", "to": "exit-b", "distance": 2,
             "travel_time_seconds": 2, "capacity": 4, "step_free": True},
        ],
    }


def scenario(family="baseline", **overrides):
    value = {
        "scenario_family": family,
        "number_of_evacuees": 1,
        "starting_distribution": "round_robin",
        "default_walking_speed_mps": None,
        "default_reaction_delay_seconds": 0.0,
        "settings_overrides": {},
    }
    value.update(overrides)
    return value


def records_fixture():
    return generate_records(graph(), [
        scenario(),
        scenario("first_room_corridor_blocked", settings_overrides={"blocked_corridors": ["a-j"]}),
    ])[0]


def test_valid_records_report_counts_features_and_labels():
    report = validate_records(records_fixture())
    assert report["integrity_errors"] == []
    assert report["record_count"] == 2
    assert report["unique_configuration_hashes"] == 2
    assert report["complete_success_runs"] == 1
    assert report["incomplete_runs"] == 1
    assert report["eligible_duration_labels"] == 1
    assert report["duration_label_coverage"] == 0.5
    assert report["feature_variation"]["initial_evacuee_count"]["numeric"]["unique_values"] == 1
    assert report["feature_variation"]["scenario_family"]["categorical"]["unique_values"] == 2
    assert report["duration_analysis"]["eligible_count"] == 1


def test_mixed_numeric_and_null_feature_values_are_both_reported():
    records = records_fixture()
    records[1]["inputs"]["evacuees"][0]["walking_speed_mps"] = 1.0
    report = validate_records(records)
    speed = report["feature_variation"]["agent_walking_speed_mps"]
    assert speed["kind"] == "mixed"
    assert speed["numeric"]["unique_values"] == 1
    assert speed["numeric"]["minimum"] == speed["numeric"]["maximum"] == 1.0
    assert speed["categorical"]["frequencies"] == {"null": 1}


def test_mismatched_target_and_inconsistent_agent_outcomes_are_reported():
    records = records_fixture()
    broken_target = deepcopy(records[0])
    broken_target["outcomes"]["duration_label"]["target_value_seconds"] += 1
    broken_agents = deepcopy(records[0])
    broken_agents["outcomes"]["evacuees"][0]["status"] = "unable_to_evacuate"
    report = validate_records([broken_target, broken_agents])
    assert any("duration target disagrees" in item for item in report["integrity_errors"])
    assert any("per-agent evacuated count" in item for item in report["integrity_errors"])


def test_duplicate_configuration_hashes_are_integrity_errors():
    record = records_fixture()[0]
    repeated = deepcopy(record)
    repeated["metadata"]["run_id"] = "different-run-id"
    report = validate_records([record, repeated])
    assert report["duplicate_configuration_rows"] == 1
    assert report["duplicate_hash_count"] == 1
    assert any("duplicate configuration row" in item for item in report["integrity_errors"])


def test_jsonl_parser_reports_malformed_lines_and_does_not_rewrite_input(tmp_path):
    path = tmp_path / "dataset.jsonl"
    records = records_fixture()
    write_jsonl(records, path)
    original = path.read_bytes()
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{broken json}\n')
    before_validation = path.read_bytes()
    report = validate_jsonl(path)
    assert any("malformed JSON" in item for item in report["integrity_errors"])
    assert before_validation != original
    assert path.read_bytes() == before_validation


def test_missing_fields_and_negative_inputs_fail_validation():
    record = records_fixture()[0]
    del record["inputs"]["corridors"]
    record["inputs"]["simulation_settings"]["congestion_penalty"]["value"] = -1
    record["metadata"]["configuration_sha256"] = stable_hash(record["inputs"])
    record["metadata"]["scenario_id"] = f"scenario-{record['metadata']['configuration_sha256']}"
    report = validate_records([record])
    assert any("inputs missing field" in item for item in report["integrity_errors"])
    assert any("negative numeric value" in item for item in report["integrity_errors"])


def test_schema_10_legacy_record_warns_when_individual_final_statuses_are_absent():
    record = records_fixture()[0]
    record["metadata"]["dataset_schema_version"] = "1.0"
    record["inputs"].pop("starting_room_distribution")
    record["outcomes"].pop("evacuees")
    record["metadata"]["configuration_sha256"] = stable_hash(record["inputs"])
    record["metadata"]["scenario_id"] = f"scenario-{record['metadata']['configuration_sha256']}"
    report = validate_records([record])
    assert report["integrity_errors"] == []
    assert any("do not contain per-agent final statuses" in item for item in report["warnings"])


def test_ineligible_runs_must_not_contain_duration_target():
    record = records_fixture()[1]
    record["outcomes"]["duration_label"]["target_value_seconds"] = 1
    report = validate_records([record])
    assert any("ineligible duration label must have null" in item for item in report["integrity_errors"])

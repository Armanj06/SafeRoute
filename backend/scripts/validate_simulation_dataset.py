"""Validate and summarize SafeRoute synthetic simulation JSONL datasets.

Run from ``backend/`` with
``python -m scripts.validate_simulation_dataset ../data/synthetic/file.jsonl``.
The input file is read only.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.generate_simulation_dataset import canonical_json, stable_hash


SUPPORTED_SCHEMAS = {"1.0", "1.1"}
REQUIRED_SECTIONS = {"metadata", "inputs", "outcomes"}
REQUIRED_METADATA = {
    "dataset_schema_version", "run_id", "scenario_id", "configuration_sha256",
    "building_id", "graph_content_sha256", "simulator_version", "scenario_family",
    "terminal_status", "outcome_category", "duration_label_eligible",
    "duration_label_reason_code",
}
REQUIRED_INPUTS = {
    "building_id", "graph_content_sha256", "graph_features", "initial_evacuee_count",
    "evacuees", "simulation_settings", "initial_conditions", "corridors", "exits",
}
REQUIRED_SUMMARY = {
    "total_evacuees", "total_evacuated", "total_remaining", "active_remaining",
    "unable_to_evacuate", "completion_percentage", "evacuation_complete",
    "simulation_terminated", "outcome", "simulation_termination_time_seconds",
    "last_successful_evacuation_time_seconds", "completion_status",
}
REQUIRED_LABEL = {"eligible", "reason_code", "target_name", "target_value_seconds"}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_nonnegative(value: Any) -> bool:
    return _is_number(value) and math.isfinite(value) and value >= 0


def _frequency(values: list[Any]) -> dict[str, int]:
    counts = Counter(json.dumps(value, sort_keys=True, ensure_ascii=False, default=repr) for value in values)
    return {key: counts[key] for key in sorted(counts)}


def _walk_numeric(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_numeric(child, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_numeric(child, f"{prefix}[{index}]")
    elif _is_number(value):
        yield prefix, value


def _feature_variation(records: list[dict[str, Any]]) -> dict[str, Any]:
    observations: dict[str, dict[str, list[Any]]] = {}

    def add(name: str, value: Any):
        values = observations.setdefault(name, {"numeric": [], "categorical": []})
        if value is None:
            values["categorical"].append(None)
        elif _is_number(value) and math.isfinite(value):
            values["numeric"].append(float(value))
        else:
            values["categorical"].append(value)

    for record in records:
        meta, inputs = record["metadata"], record["inputs"]
        add("scenario_family", meta.get("scenario_family"))
        add("building_id", inputs.get("building_id"))
        add("initial_evacuee_count", inputs.get("initial_evacuee_count"))
        distribution = inputs.get("starting_room_distribution")
        if distribution is None:
            distribution = dict(sorted(Counter(
                person.get("starting_room") for person in inputs.get("evacuees", [])
            ).items()))
        add("starting_room_distribution", distribution)

        for person in inputs.get("evacuees", []):
            add("agent_walking_speed_mps", person.get("walking_speed_mps"))
            add("agent_walking_speed_mode", person.get("walking_speed_source"))
            add("agent_reaction_delay_seconds", person.get("reaction_delay_seconds"))
        for name, value in inputs.get("graph_features", {}).items():
            add(f"graph.{name}", value)
        for name, setting in inputs.get("simulation_settings", {}).items():
            if isinstance(setting, dict) and "value" in setting:
                add(f"setting.{name}", setting["value"])
                add(f"setting_source.{name}", setting.get("source"))
        for corridor in inputs.get("corridors", []):
            for key in ("distance", "travel_time_seconds", "capacity"):
                if key in corridor:
                    add(f"corridor_{key}", corridor[key])
        for exit_info in inputs.get("exits", []):
            add("exit_throughput_people_per_second", exit_info.get("throughput_people_per_second"))

    result: dict[str, Any] = {}
    for name, groups in sorted(observations.items()):
        numeric_values = groups["numeric"]
        categorical_values = groups["categorical"]
        kinds = [kind for kind, values in groups.items() if values]
        feature: dict[str, Any] = {"kind": kinds[0] if len(kinds) == 1 else "mixed"}
        if numeric_values:
            feature["numeric"] = {
                "observations": len(numeric_values),
                "unique_values": len(set(numeric_values)),
                "minimum": min(numeric_values),
                "maximum": max(numeric_values),
                "frequencies": _frequency(numeric_values),
            }
        if categorical_values:
            feature["categorical"] = {
                "observations": len(categorical_values),
                "unique_values": len({json.dumps(value, sort_keys=True, ensure_ascii=False, default=repr) for value in categorical_values}),
                "frequencies": _frequency(categorical_values),
            }
        result[name] = feature
    return result


def _duration_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        record for record in records
        if isinstance(record.get("outcomes"), dict)
        and isinstance(record["outcomes"].get("duration_label"), dict)
        and record["outcomes"]["duration_label"].get("eligible") is True
        and _valid_nonnegative(record["outcomes"]["duration_label"].get("target_value_seconds"))
    ]
    values = [float(record["outcomes"]["duration_label"]["target_value_seconds"]) for record in eligible]
    frequencies = Counter(values)
    by_family: dict[str, list[float]] = {}
    boundary = 0
    non_boundary = 0
    steps: set[float] = set()
    for record, value in zip(eligible, values):
        family = str(record["metadata"].get("scenario_family", "unknown"))
        by_family.setdefault(family, []).append(value)
        settings = record["inputs"].get("simulation_settings", {})
        step_entry = settings.get("time_step_seconds", {})
        step = step_entry.get("value") if isinstance(step_entry, dict) else None
        if _valid_nonnegative(step) and step > 0:
            steps.add(float(step))
            if math.isclose(value / step, round(value / step), rel_tol=1e-9, abs_tol=1e-9):
                boundary += 1
            else:
                non_boundary += 1

    return {
        "eligible_count": len(values),
        "minimum_seconds": min(values) if values else None,
        "maximum_seconds": max(values) if values else None,
        "mean_seconds": statistics.mean(values) if values else None,
        "median_seconds": statistics.median(values) if values else None,
        "unique_duration_values": len(set(values)),
        "duration_value_frequencies_seconds": {str(value): frequencies[value] for value in sorted(frequencies)},
        "by_scenario_family": {
            family: {
                "count": len(group),
                "minimum_seconds": min(group),
                "maximum_seconds": max(group),
                "mean_seconds": statistics.mean(group),
                "unique_duration_values": len(set(group)),
            }
            for family, group in sorted(by_family.items())
        },
        "simulation_time_step_seconds": sorted(steps),
        "on_step_boundary_count": boundary,
        "off_step_boundary_count": non_boundary,
    }


def validate_records(records: list[dict[str, Any]], source: str = "<memory>") -> dict[str, Any]:
    """Validate record structure and outcome invariants, then summarize data."""
    errors: list[str] = []
    warnings: list[str] = []
    valid_records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    duplicate_hashes: Counter[str] = Counter()
    run_ids: set[str] = set()
    schema_counts: Counter[str] = Counter()
    graph_models: Counter[str] = Counter()
    outcome_categories: Counter[str] = Counter()
    eligible_count = 0
    complete_count = 0
    incomplete_count = 0
    missing_detail_count = 0

    def error(line: int, message: str):
        errors.append(f"line {line}: {message}")

    for index, record in enumerate(records, start=1):
        line = index
        if not isinstance(record, dict):
            error(line, "record must be a JSON object")
            continue
        missing_sections = REQUIRED_SECTIONS - set(record)
        if missing_sections:
            error(line, f"missing top-level section(s): {', '.join(sorted(missing_sections))}")
            continue
        meta, inputs, outcomes = record["metadata"], record["inputs"], record["outcomes"]
        if not all(isinstance(section, dict) for section in (meta, inputs, outcomes)):
            error(line, "metadata, inputs, and outcomes must be JSON objects")
            continue
        schema = str(meta.get("dataset_schema_version", ""))
        schema_counts[schema] += 1
        if schema not in SUPPORTED_SCHEMAS:
            error(line, f"unsupported dataset schema version {schema!r}")
        missing = REQUIRED_METADATA - set(meta)
        if missing:
            error(line, f"metadata missing field(s): {', '.join(sorted(missing))}")
        missing = REQUIRED_INPUTS - set(inputs)
        if schema == "1.1":
            missing |= {"starting_room_distribution"} - set(inputs)
        if missing:
            error(line, f"inputs missing field(s): {', '.join(sorted(missing))}")
        if "summary" not in outcomes or "duration_label" not in outcomes:
            error(line, "outcomes must contain summary and duration_label")
            continue
        summary, label = outcomes["summary"], outcomes["duration_label"]
        if not isinstance(summary, dict) or not isinstance(label, dict):
            error(line, "outcomes.summary and outcomes.duration_label must be JSON objects")
            continue
        missing = REQUIRED_SUMMARY - set(summary)
        if missing:
            error(line, f"summary missing field(s): {', '.join(sorted(missing))}")
        missing = REQUIRED_LABEL - set(label)
        if missing:
            error(line, f"duration_label missing field(s): {', '.join(sorted(missing))}")

        config_hash = meta.get("configuration_sha256")
        if not isinstance(config_hash, str) or len(config_hash) != 64:
            error(line, "configuration_sha256 must be a 64-character SHA-256 hex string")
        else:
            try:
                int(config_hash, 16)
            except ValueError:
                error(line, "configuration_sha256 is not hexadecimal")
            else:
                if config_hash in seen_hashes:
                    duplicate_hashes[config_hash] += 1
                seen_hashes.add(config_hash)
                if meta.get("scenario_id") != f"scenario-{config_hash}":
                    error(line, "scenario_id does not correspond to configuration_sha256")
                try:
                    if stable_hash(inputs) != config_hash:
                        error(line, "configuration_sha256 does not match canonical inputs")
                except (TypeError, ValueError) as exception:
                    error(line, f"inputs cannot be canonically hashed: {exception}")
        if meta.get("building_id") != inputs.get("building_id"):
            error(line, "metadata and inputs building_id disagree")
        if meta.get("graph_content_sha256") != inputs.get("graph_content_sha256"):
            error(line, "metadata and inputs graph_content_sha256 disagree")

        run_id = meta.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            error(line, "run_id must be a non-empty string")
        elif run_id in run_ids:
            error(line, f"duplicate run_id {run_id!r}")
        run_ids.add(run_id)

        graph_models[f"{meta.get('building_id')}|{meta.get('graph_content_sha256')}"] += 1
        category = str(meta.get("outcome_category", "missing"))
        outcome_categories[category] += 1
        terminal_status = meta.get("terminal_status")
        if terminal_status != "completed":
            error(line, "dataset run must have a terminal completed status")
        total = summary.get("total_evacuees")
        evacuated = summary.get("total_evacuated")
        remaining = summary.get("total_remaining")
        unable = summary.get("unable_to_evacuate")
        active = summary.get("active_remaining")
        count_fields = {"total_evacuees": total, "total_evacuated": evacuated,
                        "total_remaining": remaining, "unable_to_evacuate": unable,
                        "active_remaining": active}
        for name, value in count_fields.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                error(line, f"summary.{name} must be a non-negative integer")
        if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in count_fields.values()):
            if evacuated + remaining != total:
                error(line, "total_evacuated + total_remaining does not equal total_evacuees")
            if unable > remaining or active > remaining:
                error(line, "unable/active counts exceed total_remaining")
            if terminal_status == "completed" and active != 0:
                error(line, "completed run has active evacuees")
            if terminal_status == "completed" and remaining != unable:
                error(line, "terminal remaining count does not equal unable_to_evacuate count")
            expected_complete = total > 0 and evacuated == total
            if summary.get("evacuation_complete") is not expected_complete:
                error(line, "evacuation_complete disagrees with total and evacuated counts")
            if total and isinstance(evacuated, int) and not isinstance(evacuated, bool):
                expected_percentage = round(100 * evacuated / total, 2)
                if summary.get("completion_percentage") != expected_percentage:
                    error(line, "completion_percentage disagrees with evacuated/total counts")
            if not _valid_nonnegative(summary.get("simulation_termination_time_seconds")):
                error(line, "terminal simulation time must be finite and non-negative")
            if summary.get("simulation_terminated") is not True:
                error(line, "terminal dataset summary must have simulation_terminated=true")
        if inputs.get("initial_evacuee_count") != total:
            error(line, "inputs.initial_evacuee_count disagrees with summary.total_evacuees")
        if summary.get("completion_status") != terminal_status:
            error(line, "summary completion_status disagrees with metadata terminal_status")
        if summary.get("simulation_terminated") is not (terminal_status == "completed"):
            error(line, "summary simulation_terminated disagrees with terminal_status")
        if summary.get("outcome") == "evacuated":
            complete_count += 1
            if not (total and evacuated == total and remaining == 0 and unable == 0 and active == 0
                    and summary.get("evacuation_complete") is True and category == "complete_success"):
                error(line, "successful outcome contradicts final summary counts/status")
        else:
            incomplete_count += 1
            if summary.get("evacuation_complete") is True:
                error(line, "non-success outcome is marked evacuation_complete")
            if terminal_status == "completed" and category != "incomplete" and total != 0:
                error(line, "terminal partial outcome category must be incomplete")

        target = label.get("target_value_seconds")
        target_eligible = label.get("eligible") is True
        if target_eligible:
            eligible_count += 1
            if meta.get("duration_label_eligible") is not True:
                error(line, "metadata says duration label is ineligible but label says eligible")
            if label.get("reason_code") != "eligible" or meta.get("duration_label_reason_code") != "eligible":
                error(line, "eligible label has an inconsistent reason code")
            if label.get("target_name") != "evacuation_duration_seconds":
                error(line, "eligible label has an unexpected target_name")
            if not _valid_nonnegative(target):
                error(line, "eligible target must be finite and non-negative")
            if summary.get("evacuation_complete") is not True or summary.get("outcome") != "evacuated":
                error(line, "duration target exists for a run that did not fully evacuate")
            for field in ("simulation_termination_time_seconds", "last_successful_evacuation_time_seconds"):
                reference = summary.get(field)
                if not _valid_nonnegative(reference) or not math.isclose(target, reference, rel_tol=1e-9, abs_tol=1e-9):
                    error(line, f"duration target disagrees with summary.{field}")
        else:
            if target is not None or label.get("target_name") is not None:
                error(line, "ineligible duration label must have null target_name and target_value_seconds")
            if meta.get("duration_label_eligible") is not False:
                error(line, "metadata and duration_label eligibility disagree")
            if label.get("reason_code") != meta.get("duration_label_reason_code"):
                error(line, "metadata and duration-label reason codes disagree")
            if summary.get("outcome") == "evacuated":
                error(line, "fully successful run is marked duration-label ineligible")
            if summary.get("outcome") == "terminated_with_people_remaining" and label.get("reason_code") != "evacuation_incomplete":
                error(line, "partial terminal run has an unexpected duration-label reason")

        if schema == "1.1":
            final_agents = outcomes.get("evacuees")
            if not isinstance(final_agents, list):
                error(line, "schema 1.1 requires outcomes.evacuees as an array")
            else:
                if len(final_agents) != total:
                    error(line, "outcomes.evacuees count disagrees with summary.total_evacuees")
                statuses = Counter(agent.get("status") for agent in final_agents if isinstance(agent, dict))
                if len(statuses) == 0 and total:
                    error(line, "outcomes.evacuees has no valid status objects")
                if statuses["evacuated"] != evacuated:
                    error(line, "per-agent evacuated count disagrees with summary")
                if statuses["unable_to_evacuate"] != unable:
                    error(line, "per-agent unable count disagrees with summary")
                active_states = sum(statuses[name] for name in ("waiting", "moving", "waiting_exit_service"))
                if active_states != active:
                    error(line, "per-agent active count disagrees with summary")
                if sum(statuses.values()) != total:
                    error(line, "per-agent statuses do not account for every evacuee")
                times = [agent.get("time_spent_seconds") for agent in final_agents if isinstance(agent, dict)]
                for value in times:
                    if not _valid_nonnegative(value):
                        error(line, "per-agent time_spent_seconds must be finite and non-negative")
                if target_eligible and times and all(_valid_nonnegative(value) for value in times):
                    if not math.isclose(target, max(times), rel_tol=1e-9, abs_tol=1e-9):
                        error(line, "duration target disagrees with latest per-agent completion time")
        elif "evacuees" not in outcomes:
            missing_detail_count += 1

        for scope_name, scope in (("inputs", inputs), ("outcomes", outcomes)):
            for path, value in _walk_numeric(scope, scope_name):
                if not math.isfinite(value):
                    error(line, f"non-finite numeric value at {path}")
                elif value < 0:
                    error(line, f"negative numeric value at {path}")

        valid_records.append(record)

    duplicate_count = sum(duplicate_hashes.values())
    if duplicate_count:
        errors.append(f"dataset contains {duplicate_count} duplicate configuration row(s) across {len(duplicate_hashes)} hash(es)")
    if missing_detail_count:
        warnings.append(
            f"{missing_detail_count} schema 1.0 record(s) do not contain per-agent final statuses; aggregate arithmetic was checked, but counts could not be verified against individual final states"
        )

    feature_variation = _feature_variation(valid_records) if valid_records else {}
    duration = _duration_analysis(valid_records) if valid_records else _duration_analysis([])
    return {
        "source": source,
        "record_count": len(records),
        "valid_record_count": len(valid_records),
        "schema_versions": dict(sorted(schema_counts.items())),
        "unique_configuration_hashes": len(seen_hashes),
        "duplicate_configuration_rows": duplicate_count,
        "duplicate_hash_count": len(duplicate_hashes),
        "unique_run_ids": len(run_ids),
        "outcome_categories": dict(sorted(outcome_categories.items())),
        "complete_success_runs": complete_count,
        "incomplete_runs": incomplete_count,
        "eligible_duration_labels": eligible_count,
        "duration_label_coverage": eligible_count / len(records) if records else None,
        "graph_models": dict(sorted(graph_models.items())),
        "feature_variation": feature_variation,
        "duration_analysis": duration,
        "integrity_errors": errors,
        "warnings": warnings,
    }


def validate_jsonl(path: Path) -> dict[str, Any]:
    """Read JSONL, report malformed lines, and validate parsed records."""
    records: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    with Path(path).open(encoding="utf-8") as source_file:
        for line_number, line in enumerate(source_file, start=1):
            if not line.strip():
                parse_errors.append(f"line {line_number}: blank lines are not valid JSONL records")
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                parse_errors.append(f"line {line_number}: malformed JSON: {error.msg}")
    report = validate_records(records, str(path))
    report["integrity_errors"] = parse_errors + report["integrity_errors"]
    report["record_count"] += len(parse_errors)
    return report


def format_report(report: dict[str, Any]) -> str:
    """Render a readable report, including concise feature summaries."""
    duration = report["duration_analysis"]
    lines = [
        f"Dataset: {report['source']}",
        f"Records: {report['record_count']} ({report['valid_record_count']} parsed JSON objects)",
        f"Schemas: {report['schema_versions']}",
        f"Unique configuration hashes: {report['unique_configuration_hashes']}",
        f"Duplicate rows/hashes: {report['duplicate_configuration_rows']}/{report['duplicate_hash_count']}",
        f"Outcomes: {report['outcome_categories']}",
        f"Complete-success / incomplete: {report['complete_success_runs']} / {report['incomplete_runs']}",
        f"Eligible duration labels: {report['eligible_duration_labels']}",
        f"Label coverage: {report['duration_label_coverage']:.1%}" if report["duration_label_coverage"] is not None else "Label coverage: unavailable",
        f"Graph models: {report['graph_models']}",
        "Duration target (eligible runs): " + json.dumps(duration, sort_keys=True),
        "Feature variation:",
    ]
    for name, summary in report["feature_variation"].items():
        if "numeric" in summary:
            numeric = summary["numeric"]
            lines.append(
                f"  {name}: numeric, observations={numeric['observations']}, "
                f"unique={numeric['unique_values']}, min={numeric['minimum']}, max={numeric['maximum']}"
            )
        if "categorical" in summary:
            categorical = summary["categorical"]
            lines.append(
                f"  {name}: categorical, observations={categorical['observations']}, "
                f"unique={categorical['unique_values']}, frequencies={categorical['frequencies']}"
            )
    lines.append(f"Integrity errors: {len(report['integrity_errors'])}")
    lines.extend(f"  ERROR: {message}" for message in report["integrity_errors"])
    lines.append(f"Warnings: {len(report['warnings'])}")
    lines.extend(f"  WARNING: {message}" for message in report["warnings"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="input JSONL file; it is never modified")
    args = parser.parse_args(argv)
    try:
        report = validate_jsonl(args.dataset)
    except OSError as error:
        print(f"Dataset validation failed: {error}", file=sys.stderr)
        return 2
    print(format_report(report))
    return 1 if report["integrity_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

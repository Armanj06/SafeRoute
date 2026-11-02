"""Generate deterministic synthetic evacuation records from the real engine.

Run from ``backend/`` with ``python -m scripts.generate_simulation_dataset``.
This tool records illustrative simulator outcomes; it does not generate
real-world evacuation evidence or train a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter, deque
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.services.building import load_building
from app.simulation.duration_labels import duration_label_eligibility
from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings, effective_conditions


DATASET_SCHEMA_VERSION = "1.1"
SIMULATOR_VERSION = "saferoute-discrete-engine-v1"
MAX_SIMULATION_STEPS = 10_000
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "synthetic" / "saferoute_duration_v1.jsonl"


def canonical_json(value: Any) -> str:
    """Serialize JSON values consistently and reject non-finite numbers."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def stable_hash(value: Any) -> str:
    """Return the SHA-256 of a canonical JSON value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def graph_connectivity_features(
    building: dict[str, Any], blocked_corridors: set[str],
    unavailable_exits: set[str], unsafe_locations: set[str],
) -> dict[str, Any]:
    """Compute simple undirected reachability features from the selected graph."""
    nodes = building.get("nodes", [])
    corridors = building.get("corridors", [])
    node_by_id = {node["id"]: node for node in nodes}
    exits = {
        node["id"] for node in nodes
        if node.get("type") == "exit" and node["id"] not in unavailable_exits
        and node["id"] not in unsafe_locations and not node.get("unsafe")
    }
    unsafe_nodes = {
        node["id"] for node in nodes
        if node.get("unsafe") or node["id"] in unsafe_locations
    }
    adjacency = {node_id: set() for node_id in node_by_id if node_id not in unsafe_nodes}
    for edge in corridors:
        if edge.get("blocked") or edge.get("unsafe") or edge["id"] in blocked_corridors or edge["id"] in unsafe_locations:
            continue
        source, target = edge["from"], edge["to"]
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)

    components = 0
    visited: set[str] = set()
    for node_id in adjacency:
        if node_id in visited:
            continue
        components += 1
        queue = deque([node_id])
        visited.add(node_id)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current] - visited:
                visited.add(neighbor)
                queue.append(neighbor)

    rooms = [
        node["id"] for node in nodes
        if node.get("type") in {"room", "area"} and node["id"] in adjacency
    ]
    rooms_reaching_exit = 0
    for room_id in rooms:
        queue = deque([room_id])
        reachable = {room_id}
        found_exit = False
        while queue:
            current = queue.popleft()
            if current in exits:
                found_exit = True
                break
            for neighbor in adjacency[current] - reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
        rooms_reaching_exit += found_exit

    return {
        "node_count": len(nodes),
        "corridor_count": len(corridors),
        "room_or_area_count": sum(node.get("type") in {"room", "area"} for node in nodes),
        "exit_count": sum(node.get("type") == "exit" for node in nodes),
        "effective_connected_component_count": components,
        "rooms_with_route_to_available_exit": rooms_reaching_exit,
    }


def scenario_matrix(building: dict[str, Any]) -> list[dict[str, Any]]:
    """Build 36 valid synthetic configurations from supported graph inputs."""
    rooms = [
        node["id"] for node in building.get("nodes", [])
        if node.get("type") in {"room", "area"}
    ]
    exits = [node["id"] for node in building.get("nodes", []) if node.get("type") == "exit"]
    if not rooms:
        raise ValueError(f"Building model '{building.get('id')}' has no room or area nodes.")
    if not exits:
        raise ValueError(f"Building model '{building.get('id')}' has no exit nodes.")

    restrictions: list[tuple[str, dict[str, list[str]]]] = [
        ("baseline", {"blocked_corridors": [], "unavailable_exits": []}),
        ("one_exit_unavailable", {"blocked_corridors": [], "unavailable_exits": [sorted(exits)[0]]}),
    ]
    first_room = rooms[0]
    first_room_corridors = [
        edge["id"] for edge in building.get("corridors", [])
        if first_room in {edge["from"], edge["to"]}
    ]
    if first_room_corridors:
        restrictions.append((
            "first_room_corridor_blocked",
            {"blocked_corridors": [sorted(first_room_corridors)[0]], "unavailable_exits": []},
        ))

    matrix: list[dict[str, Any]] = []
    # A one-person round-robin and concentrated placement resolve to the same
    # agent input, so omit that duplicate by constructing only distinct pairs.
    for count, distribution in ((1, "round_robin"), (8, "round_robin"), (8, "concentrated")):
        for speed in (None, 1.0):
            for reaction in (0.0, 5.0):
                for restriction_name, restriction in restrictions:
                    matrix.append({
                        "scenario_family": restriction_name,
                        "number_of_evacuees": count,
                        "starting_distribution": distribution,
                        "default_walking_speed_mps": speed,
                        "default_reaction_delay_seconds": reaction,
                        "settings_overrides": deepcopy(restriction),
                    })
    return matrix


def expanded_scenario_matrix(building: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a bounded, diverse 180-row matrix from existing engine inputs.

    This deliberately varies only values already accepted by ``SimulationSettings``
    and the engine's evacuee specification. It is not a physical campus model.
    ``scenario_matrix`` remains available for reproducing the original 36-row set.
    """
    rooms = [
        node["id"] for node in building.get("nodes", [])
        if node.get("type") in {"room", "area"}
    ]
    exits = sorted(
        node["id"] for node in building.get("nodes", [])
        if node.get("type") == "exit"
    )
    if not rooms:
        raise ValueError(f"Building model '{building.get('id')}' has no room or area nodes.")
    if len(exits) < 2:
        raise ValueError("Expanded dataset generation requires at least two configured exits.")

    first_room_corridors = sorted(
        edge["id"] for edge in building.get("corridors", [])
        if rooms[0] in {edge["from"], edge["to"]}
    )
    if not first_room_corridors:
        raise ValueError(f"Room '{rooms[0]}' has no connected corridor to block.")

    restrictions: list[tuple[str, dict[str, list[str]]]] = [
        ("baseline", {"blocked_corridors": [], "unavailable_exits": []}),
        ("north_exit_unavailable", {"blocked_corridors": [], "unavailable_exits": [exits[0]]}),
        ("south_exit_unavailable", {"blocked_corridors": [], "unavailable_exits": [exits[1]]}),
        ("first_room_corridor_blocked", {
            "blocked_corridors": [first_room_corridors[0]], "unavailable_exits": [],
        }),
    ]
    # One-person concentrated cases collapse to the same resolved agents as
    # one-person round robin, so only distinct pre-run configurations appear.
    population_profiles = [
        (1, "round_robin"),
        (4, "round_robin"),
        (8, "round_robin"),
        (8, "concentrated"),
        (16, "last_room_concentrated"),
    ]
    matrix: list[dict[str, Any]] = []
    for count, distribution in population_profiles:
        for speed in (None, 1.0, 1.4):
            for reaction in (0.0, 5.0, 10.0):
                for restriction_name, restriction in restrictions:
                    matrix.append({
                        "scenario_family": restriction_name,
                        "number_of_evacuees": count,
                        "starting_distribution": distribution,
                        "default_walking_speed_mps": speed,
                        "default_reaction_delay_seconds": reaction,
                        "settings_overrides": deepcopy(restriction),
                    })
    return matrix


def _agent_specs(building: dict[str, Any], scenario: dict[str, Any]) -> list[dict[str, Any]]:
    rooms = [
        node["id"] for node in building.get("nodes", [])
        if node.get("type") in {"room", "area"}
    ]
    count = scenario["number_of_evacuees"]
    distribution = scenario["starting_distribution"]
    if distribution == "round_robin":
        selected = [rooms[index % len(rooms)] for index in range(count)]
    elif distribution == "concentrated":
        selected = [rooms[0]] * count
    elif distribution == "last_room_concentrated":
        selected = [rooms[-1]] * count
    else:
        raise ValueError(f"Unsupported starting distribution '{distribution}'.")
    return [{"starting_room": room, "accessibility": {}} for room in selected]


def _settings_for(scenario: dict[str, Any]) -> tuple[SimulationSettings, set[str]]:
    overrides = deepcopy(scenario.get("settings_overrides", {}))
    overrides["default_walking_speed_mps"] = scenario["default_walking_speed_mps"]
    overrides["default_reaction_delay_seconds"] = scenario["default_reaction_delay_seconds"]
    return SimulationSettings(**overrides), set(overrides)


def prepare_run(building: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Resolve a scenario into an unadvanced engine state and canonical inputs."""
    engine = SimulationEngine(building)
    settings, configured_settings = _settings_for(scenario)
    state = engine.create(_agent_specs(building, scenario), settings)

    # This first matrix uses static graph conditions and request restrictions;
    # hazard records are represented explicitly as an empty initial list.
    state.initial_hazards = []
    state.initial_unavailable_exits = list(state.settings.unavailable_exits)

    conditions = effective_conditions(engine.building, state)
    summary_settings = {
        key: {
            "value": deepcopy(value),
            "source": "scenario_configuration" if key in configured_settings else "simulator_default",
        }
        for key, value in vars(state.settings).items()
    }
    evacuees = []
    for person in state.evacuees:
        evacuees.append({
            "starting_room": person.starting_room,
            "accessibility": deepcopy(person.accessibility),
            "walking_speed_mps": person.walking_speed_mps,
            "walking_speed_source": (
                "scenario_configuration" if person.walking_speed_mps is not None
                else "corridor_travel_time_or_1_2_mps_fallback"
            ),
            "reaction_delay_seconds": person.reaction_delay_seconds,
            "reaction_delay_source": "scenario_configuration",
        })
    starting_room_distribution = dict(sorted(Counter(agent["starting_room"] for agent in evacuees).items()))

    corridors = []
    for edge in engine.building.get("corridors", []):
        corridors.append({
            "corridor_id": edge["id"],
            "distance": edge["distance"],
            "travel_time_seconds": edge.get("travel_time_seconds"),
            "capacity": engine._capacity(edge),
            "capacity_source": "graph" if "capacity" in edge else "simulator_default",
            "static_blocked": bool(edge.get("blocked")),
            "static_unsafe": bool(edge.get("unsafe")),
        })
    exits = [
        {
            "exit_id": node["id"],
            "throughput_people_per_second": node.get("throughput_people_per_second"),
            "throughput_source": "graph" if node.get("throughput_people_per_second") is not None else "immediate_service_default",
        }
        for node in engine.building.get("nodes", []) if node.get("type") == "exit"
    ]

    inputs = {
        "building_id": state.building_id,
        "graph_content_sha256": stable_hash(engine.building),
        "graph_features": graph_connectivity_features(
            engine.building,
            set(conditions["blocked_corridors"]),
            set(conditions["unavailable_exits"]),
            set(conditions["unsafe_nodes"]),
        ),
        "initial_evacuee_count": len(state.evacuees),
        "starting_room_distribution": starting_room_distribution,
        "evacuees": evacuees,
        "simulation_settings": summary_settings,
        "initial_conditions": {
            "blocked_corridors": conditions["blocked_corridors"],
            "unsafe_corridors": conditions["unsafe_corridors"],
            "unsafe_nodes": conditions["unsafe_nodes"],
            "unavailable_exits": conditions["unavailable_exits"],
            "hazards": [],
        },
        "corridors": corridors,
        "exits": exits,
    }
    return {
        "engine": engine,
        "state": state,
        "inputs": inputs,
        "configuration_hash": stable_hash(inputs),
        "scenario_family": scenario["scenario_family"],
    }


def execute_prepared_run(
    building: dict[str, Any], prepared: dict[str, Any],
    run_id_factory: Callable[[], Any] = uuid4,
    max_steps: int = MAX_SIMULATION_STEPS,
) -> dict[str, Any]:
    """Advance one prepared run and return its versioned input/outcome record."""
    engine: SimulationEngine = prepared["engine"]
    state = prepared["state"]
    if state.status != "completed":
        engine.start(state)
    steps = 0
    while state.status != "completed" and steps < max_steps:
        batch = min(100, max_steps - steps)
        engine.advance(state, batch)
        steps += batch
    if state.status != "completed":
        raise RuntimeError(
            f"Simulation '{state.simulation_id}' did not terminate within {max_steps} steps."
        )

    summary = state.summary()
    eligibility = duration_label_eligibility(state)
    outcome_category = (
        "complete_success" if summary["evacuation_complete"] else "incomplete"
    )
    return {
        "metadata": {
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "run_id": str(run_id_factory()),
            "scenario_id": f"scenario-{prepared['configuration_hash']}",
            "configuration_sha256": prepared["configuration_hash"],
            "building_id": state.building_id,
            "graph_content_sha256": prepared["inputs"]["graph_content_sha256"],
            "simulator_version": SIMULATOR_VERSION,
            "scenario_family": prepared["scenario_family"],
            "data_provenance": "synthetic_simulation_from_illustrative_or_configured_graph",
            "model_status": building.get("model_status", "unspecified"),
            "terminal_status": state.status,
            "outcome_category": outcome_category,
            "duration_label_eligible": eligibility["eligible"],
            "duration_label_reason_code": eligibility["reason_code"],
        },
        "inputs": prepared["inputs"],
        "outcomes": {
            "summary": summary,
            "evacuees": [
                {
                    "evacuee_id": person.evacuee_id,
                    "status": person.status,
                    "time_spent_seconds": person.time_spent_seconds,
                    "current_node": person.current_node,
                    "assigned_exit": person.assigned_exit,
                    "unable_reason": person.unable_reason,
                }
                for person in state.evacuees
            ],
            "duration_label": eligibility,
        },
    }


def generate_records(
    building: dict[str, Any], scenarios: list[dict[str, Any]],
    run_id_factory: Callable[[], Any] = uuid4,
) -> tuple[list[dict[str, Any]], int]:
    """Run scenarios, skipping exact canonical input duplicates before stepping."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for index, scenario in enumerate(scenarios, start=1):
        try:
            prepared = prepare_run(building, scenario)
            config_hash = prepared["configuration_hash"]
            if config_hash in seen:
                duplicates += 1
                continue
            seen.add(config_hash)
            records.append(execute_prepared_run(building, prepared, run_id_factory))
        except Exception as error:
            family = scenario.get("scenario_family", f"scenario-{index}")
            raise RuntimeError(f"Dataset generation stopped at {family} (matrix row {index}): {error}") from error
    return records, duplicates


def write_jsonl(records: list[dict[str, Any]], output: Path, overwrite: bool = False) -> None:
    """Write JSONL atomically; refuse to replace existing data unless requested."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}. Use --overwrite to replace it.")
    contents = "".join(canonical_json(record) + "\n" for record in records)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent,
            prefix=f".{output.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
        if overwrite:
            os.replace(temp_path, output)
        else:
            # A same-filesystem hard link creates the final path exclusively,
            # so a racing process cannot accidentally overwrite another run.
            os.link(temp_path, output)
            temp_path.unlink()
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"JSONL destination (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--limit", type=int, default=None, help="run the first N deterministic matrix rows (default: all rows)")
    parser.add_argument("--building-id", default=None, help="configured building/model ID; defaults to catalog default")
    parser.add_argument(
        "--matrix", choices=("legacy", "expanded"), default="legacy",
        help="legacy reproduces the 36-row matrix; expanded creates the 180-row diverse matrix",
    )
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.output.exists() and not args.overwrite:
        parser.error(f"Output already exists: {args.output}. Use --overwrite to replace it.")
    try:
        building = load_building(args.building_id)
        scenarios = expanded_scenario_matrix(building) if args.matrix == "expanded" else scenario_matrix(building)
        if args.limit is not None:
            if args.limit > len(scenarios):
                parser.error(f"--limit cannot exceed the {len(scenarios)} available matrix configurations")
            scenarios = scenarios[:args.limit]
        records, duplicates = generate_records(building, scenarios)
        write_jsonl(records, args.output, overwrite=args.overwrite)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Dataset generation failed: {error}", file=sys.stderr)
        return 2

    categories = Counter(record["metadata"]["outcome_category"] for record in records)
    eligible = sum(record["metadata"]["duration_label_eligible"] for record in records)
    total = len(records)
    print(f"Configurations generated: {total}")
    print(f"Exact duplicates skipped: {duplicates}")
    print(f"Complete-success runs: {categories['complete_success']}")
    print(f"Incomplete runs: {categories['incomplete']}")
    print("Invalid or failed runs: 0 (generation fails fast; no output is committed on a run error)")
    print(f"Eligible duration labels: {eligible}")
    print(f"Duration-label coverage: {eligible / total:.1%}" if total else "Duration-label coverage: unavailable")
    print(f"Output: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

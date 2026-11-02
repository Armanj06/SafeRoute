"""Load and validate configurable campus metadata and routable building graphs."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CATALOG_PATH = DATA_DIR / "campus_catalog.json"
NODE_TYPES = {"room", "junction", "exit", "staircase", "elevator", "assembly_point", "area"}
_CUSTOM_BUILDINGS: dict[str, dict[str, Any]] = {}


def save_custom_building(building: dict[str, Any]) -> dict[str, Any]:
    """Validate and retain a user-designed graph for the running API session."""
    validate_building_graph(building)
    custom = deepcopy(building)
    custom.setdefault("model_id", custom["id"])
    custom.setdefault("model_status", "custom")
    custom.setdefault("model_description", "User-designed evacuation graph")
    custom.setdefault("campus_location", {"id": "custom", "name": "Custom design"})
    custom.setdefault("floors", [{"id": "custom-floor", "name": "Custom Floor", "level": 0}])
    _CUSTOM_BUILDINGS[custom["id"]] = custom
    return deepcopy(custom)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as data_file:
        payload = json.load(data_file)
    if not isinstance(payload, dict):
        raise ValueError(f"Data file '{path.name}' must contain a JSON object.")
    return payload


def validate_building_graph(building: dict[str, Any], expected_id: str | None = None) -> dict[str, Any]:
    """Validate graph references and route/simulation numeric fields.

    The graph schema permits optional floor IDs and optional explicit exit/assembly
    references. A verified model can add those without changing route algorithms.
    """
    if not isinstance(building.get("id"), str) or not building["id"].strip():
        raise ValueError("Building graph must have a non-empty id.")
    if expected_id and building["id"] != expected_id:
        raise ValueError(f"Building graph id '{building['id']}' does not match catalog id '{expected_id}'.")
    nodes = building.get("nodes")
    corridors = building.get("corridors")
    if not isinstance(nodes, list) or not isinstance(corridors, list):
        raise ValueError("Building graph must contain node and corridor arrays.")

    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id") if isinstance(node, dict) else None
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("Every graph node must have a non-empty string id.")
        if node_id in node_by_id:
            raise ValueError(f"Duplicate node id '{node_id}'.")
        if node.get("type") not in NODE_TYPES:
            raise ValueError(f"Node '{node_id}' has unsupported type '{node.get('type')}'.")
        x, y = node.get("x"), node.get("y")
        if (x is None) != (y is None):
            raise ValueError(f"Node '{node_id}' must provide both x and y coordinates or neither.")
        if x is not None and any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in (x, y)):
            raise ValueError(f"Node '{node_id}' coordinates must be finite numbers.")
        node_by_id[node_id] = node

    floors = building.get("floors", [])
    if not isinstance(floors, list):
        raise ValueError("Building floors must be an array.")
    floor_ids: set[str] = set()
    for floor in floors:
        floor_id = floor.get("id") if isinstance(floor, dict) else None
        if not isinstance(floor_id, str) or not floor_id.strip() or floor_id in floor_ids:
            raise ValueError("Every floor must have a unique, non-empty string id.")
        floor_ids.add(floor_id)
    for node_id, node in node_by_id.items():
        floor_id = node.get("floor_id")
        if floor_id is not None and floor_id not in floor_ids:
            raise ValueError(f"Node '{node_id}' references unknown floor '{floor_id}'.")

    corridor_ids: set[str] = set()
    for corridor in corridors:
        corridor_id = corridor.get("id") if isinstance(corridor, dict) else None
        if not isinstance(corridor_id, str) or not corridor_id.strip():
            raise ValueError("Every corridor must have a non-empty string id.")
        if corridor_id in corridor_ids:
            raise ValueError(f"Duplicate corridor id '{corridor_id}'.")
        corridor_ids.add(corridor_id)
        source, target = corridor.get("from"), corridor.get("to")
        for endpoint in (source, target):
            if not isinstance(endpoint, str) or endpoint not in node_by_id:
                raise ValueError(f"Corridor '{corridor_id}' references unknown node '{endpoint}'.")
        if source == target:
            raise ValueError(f"Corridor '{corridor_id}' must connect two different nodes.")
        if "distance" not in corridor:
            raise ValueError(f"Corridor '{corridor_id}' must define a distance.")
        for cost_name in ("distance", "travel_time_seconds"):
            if cost_name not in corridor:
                continue
            value = corridor[cost_name]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Corridor '{corridor_id}' {cost_name} must be finite and non-negative.")
        if "capacity" in corridor:
            capacity = corridor["capacity"]
            if not isinstance(capacity, (int, float)) or not math.isfinite(capacity) or capacity < 1:
                raise ValueError(f"Corridor '{corridor_id}' capacity must be finite and at least one.")
        if "current_occupancy" in corridor:
            occupancy = corridor["current_occupancy"]
            if not isinstance(occupancy, (int, float)) or not math.isfinite(occupancy) or occupancy < 0:
                raise ValueError(f"Corridor '{corridor_id}' current_occupancy must be finite and non-negative.")

    for reference_field, required_type in (("exit_ids", "exit"), ("assembly_point_ids", "assembly_point")):
        if reference_field not in building:
            continue
        references = building[reference_field]
        if (
            not isinstance(references, list)
            or any(not isinstance(node_id, str) for node_id in references)
            or len(set(references)) != len(references)
        ):
            raise ValueError(f"Building {reference_field} must contain unique node IDs.")
        for node_id in references:
            if node_id not in node_by_id or node_by_id[node_id].get("type") != required_type:
                raise ValueError(f"Building {reference_field} contains invalid node '{node_id}'.")
    return building


def _catalog() -> dict[str, Any]:
    catalog = _read_json(CATALOG_PATH)
    locations = catalog.get("locations")
    models = catalog.get("models")
    if not isinstance(locations, list) or not isinstance(models, list) or not models:
        raise ValueError("Campus catalog must include location and model arrays.")
    location_ids = [item.get("id") for item in locations]
    model_ids = [item.get("id") for item in models]
    if len(set(location_ids)) != len(location_ids) or len(set(model_ids)) != len(model_ids):
        raise ValueError("Campus location and model IDs must be unique.")
    if catalog.get("default_model_id") not in set(model_ids):
        raise ValueError("Campus catalog default_model_id must reference a configured model.")
    location_id_set = set(location_ids)
    for model in models:
        if model.get("location_id") not in location_id_set:
            raise ValueError(f"Model '{model.get('id')}' references an unknown campus location.")
        graph_file = model.get("graph_file")
        if not isinstance(graph_file, str) or Path(graph_file).name != graph_file:
            raise ValueError(f"Model '{model.get('id')}' graph_file must be a filename in the data directory.")
        graph_path = DATA_DIR / graph_file
        graph = _read_json(graph_path)
        if "floors" in model:
            graph["floors"] = deepcopy(model["floors"])
        validate_building_graph(graph, model.get("building_id"))
    return catalog


def load_campus() -> dict[str, Any]:
    """Return campus locations and available routable model choices."""
    catalog = _catalog()
    return {
        "campus": deepcopy(catalog["campus"]),
        "locations": deepcopy(catalog["locations"]),
        "models": [
            {key: value for key, value in model.items() if key != "graph_file"}
            for model in deepcopy(catalog["models"])
        ],
        "default_model_id": catalog["default_model_id"],
    }


def load_building(building_id: str | None = None) -> dict[str, Any]:
    """Load the selected graph and attach its campus provenance metadata."""
    if building_id and building_id in _CUSTOM_BUILDINGS:
        return deepcopy(_CUSTOM_BUILDINGS[building_id])
    catalog = _catalog()
    requested = building_id or catalog["default_model_id"]
    model = next((item for item in catalog["models"] if item["id"] == requested), None)
    if model is None:
        raise ValueError(f"Building model '{requested}' is not available.")
    building = deepcopy(_read_json(DATA_DIR / model["graph_file"]))
    validate_building_graph(building, model["building_id"])
    location = next(item for item in catalog["locations"] if item["id"] == model["location_id"])
    building["model_id"] = model["id"]
    building["model_status"] = model["status"]
    building["model_description"] = model["description"]
    building["campus"] = deepcopy(catalog["campus"])
    building["campus_location"] = deepcopy(location)
    building["floors"] = deepcopy(model.get("floors", building.get("floors", [])))
    return building

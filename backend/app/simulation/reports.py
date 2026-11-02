"""Exports a single simulation run as JSON or a flat, typed CSV."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.simulation.models import SimulationState, effective_conditions, simulation_analytics


def build_report(building: dict[str, Any], state: SimulationState) -> dict[str, Any]:
    conditions = effective_conditions(building, state)
    corridors = []
    for edge in building.get("corridors", []):
        capacity = max(1, int(float(edge.get("capacity", 1))))
        occupancy = state.corridor_occupancy.get(edge["id"], 0)
        corridors.append({
            "corridor_id": edge["id"],
            "occupancy": occupancy,
            "capacity": capacity,
            "occupancy_ratio": occupancy / capacity,
            "confirmed_unsafe": edge["id"] in conditions["unsafe_corridors"],
        })
    return {
        "building_id": state.building_id,
        "building": {
            "id": building.get("id"),
            "building_id": state.building_id,
            "name": building.get("name"),
            "campus": building.get("campus", {}).get("name"),
            "campus_location": building.get("campus_location", {}).get("name"),
            "model_status": building.get("model_status", "unspecified"),
        },
        "scenario": {"id": state.scenario_id, "name": state.scenario_name},
        "simulation": {
            "simulation_id": state.simulation_id,
            "building_id": state.building_id,
            "status": state.status,
            "current_step": state.current_step,
            "current_time_seconds": state.current_time_seconds,
        },
        "settings": state.settings.__dict__.copy(),
        "analytics": simulation_analytics(building, state),
        "evacuees": [person.to_dict() for person in state.evacuees],
        "hazards": [hazard.to_dict() for hazard in state.hazards],
        "events": [event.to_dict() for event in state.event_history],
        "corridor_occupancy": corridors,
        "exit_service": [
            {
                "exit_id": node["id"],
                "throughput_people_per_second": node.get("throughput_people_per_second"),
                "queue": list(state.exit_queues.get(node["id"], [])),
                "service_remaining_seconds": state.exit_service_remaining_seconds.get(node["id"]),
            }
            for node in building.get("nodes", []) if node.get("type") == "exit"
        ],
    }


CSV_FIELDS = [
    "record_type", "simulation_id", "building_id", "building_name", "campus_location", "model_status", "scenario_id", "scenario_name", "status",
    "step", "time_seconds", "record_id", "outcome", "starting_room",
    "walking_speed_mps", "reaction_delay_seconds",
    "exit_id", "queue_length", "throughput_people_per_second",
    "assigned_exit", "route", "value", "details",
]


def build_csv_report(report: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    simulation = report["simulation"]
    common = {
        "simulation_id": simulation["simulation_id"],
        "building_id": report["building"]["id"] or "",
        "building_name": report["building"]["name"] or "",
        "campus_location": report["building"]["campus_location"] or "",
        "model_status": report["building"]["model_status"] or "",
        "scenario_id": report["scenario"]["id"] or "",
        "scenario_name": report["scenario"]["name"] or "",
        "status": simulation["status"],
    }
    writer.writerow({
        **common, "record_type": "summary", "step": simulation["current_step"],
        "time_seconds": simulation["current_time_seconds"],
        "outcome": report["analytics"]["outcome"],
        "details": json.dumps({
            "settings": report["settings"], "analytics": report["analytics"],
        }, sort_keys=True),
    })
    for person in report["evacuees"]:
        writer.writerow({
            **common, "record_type": "evacuee", "record_id": person["evacuee_id"],
            "outcome": person["status"], "starting_room": person["starting_room"],
            "walking_speed_mps": person["walking_speed_mps"] if person["walking_speed_mps"] is not None else "",
            "reaction_delay_seconds": person["reaction_delay_seconds"],
            "assigned_exit": person["assigned_exit"] or "",
            "route": " → ".join(person["route"]),
            "value": person["time_spent_seconds"],
            "details": person.get("unable_reason") or "",
        })
    for hazard in report["hazards"]:
        writer.writerow({
            **common, "record_type": "hazard", "record_id": hazard["hazard_id"],
            "outcome": "active" if hazard["active"] else "resolved",
            "details": json.dumps(hazard, sort_keys=True),
        })
    for event in report["events"]:
        writer.writerow({
            **common, "record_type": "event", "step": event["step"],
            "time_seconds": event["time_seconds"], "record_id": event["event_type"],
            "outcome": event.get("evacuee_id") or "",
            "details": json.dumps(event["details"], sort_keys=True),
        })
    for corridor in report["corridor_occupancy"]:
        writer.writerow({
            **common, "record_type": "corridor", "record_id": corridor["corridor_id"],
            "value": corridor["occupancy_ratio"],
            "details": json.dumps(corridor, sort_keys=True),
        })
    for exit_service in report["exit_service"]:
        writer.writerow({
            **common, "record_type": "exit", "exit_id": exit_service["exit_id"],
            "queue_length": len(exit_service["queue"]),
            "throughput_people_per_second": exit_service["throughput_people_per_second"] or "",
            "value": exit_service["service_remaining_seconds"] or "",
            "details": json.dumps(exit_service, sort_keys=True),
        })
    return output.getvalue()

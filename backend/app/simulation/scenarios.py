"""Repeatable, deterministic demonstration scenario definitions."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


SCENARIOS: dict[str, dict[str, Any]] = {
    "baseline": {
        "name": "Baseline evacuation",
        "description": "Normal operation with no active hazards or manual exit closures.",
        "learning_outcome": "Observe route assignment and evacuation progress without incident changes.",
        "number_of_evacuees": 8,
        "settings": {}, "hazards": [], "unavailable_exits": [],
    },
    "corridor-congestion": {
        "name": "Corridor congestion",
        "description": "Many evacuees share the sample building's main corridor network.",
        "learning_outcome": "Compare capacity queues, occupancy ratios, and utility route changes under load.",
        "number_of_evacuees": 48,
        "settings": {"replan_on_congestion": True, "replan_interval_steps": 3, "congestion_penalty": 1.5},
        "hazards": [], "unavailable_exits": [],
    },
    "fire-corridor": {
        "name": "Fire blocks a main corridor",
        "description": "A fire hazard blocks corridor c4 after evacuees receive initial routes.",
        "learning_outcome": "See the utility agent replace a route through the affected corridor when a safe detour exists.",
        "number_of_evacuees": 4,
        "settings": {},
        "hazards": [{"hazard_type": "fire", "target_type": "corridor", "target_id": "c4", "severity": 0.9}],
        "unavailable_exits": [],
    },
    "exit-unavailable": {
        "name": "North exit unavailable",
        "description": "The north exit is closed before route assignment.",
        "learning_outcome": "Observe exit selection reroute toward the remaining available exit.",
        "number_of_evacuees": 8,
        "settings": {}, "hazards": [], "unavailable_exits": ["exit-north"],
    },
    "restricted-access": {
        "name": "Step-free evacuation",
        "description": "One evacuee starts in each sample room and requires step-free corridors.",
        "learning_outcome": "See accessibility constraints treated as feasibility rules in utility route selection.",
        "evacuees": [
            {"starting_room": room, "accessibility": {"step_free": True}}
            for room in ("room-101", "room-102", "room-201", "room-202")
        ],
        "settings": {}, "hazards": [], "unavailable_exits": [],
    },
    "no-safe-route": {
        "name": "No feasible safe route",
        "description": "The two room-101 connecting corridors are blocked.",
        "learning_outcome": "Distinguish an evacuation that is unable to complete from a successful evacuation.",
        "evacuees": [{"starting_room": "room-101"}],
        "settings": {"blocked_corridors": ["c1", "c13"]},
        "hazards": [], "unavailable_exits": [],
    },
    "ditu-vedanta-fire": {
        "name": "DITU demonstration · fire on Vedanta model corridor",
        "description": "Hypothetical fire incident on illustrative graph corridor c4; c4 is not a verified DIT University corridor.",
        "learning_outcome": "Observe initial assignments being checked against the active hazard and safe alternatives.",
        "number_of_evacuees": 4,
        "settings": {},
        "hazards": [{"hazard_type": "fire", "target_type": "corridor", "target_id": "c4", "severity": 0.9}],
        "unavailable_exits": [],
    },
    "ditu-vedanta-blocked-corridor": {
        "name": "DITU demonstration · blocked model corridor",
        "description": "Hypothetical pre-existing closure of illustrative graph corridor c4; the graph does not represent an official route.",
        "learning_outcome": "Show route search and simulation assignments excluding a blocked edge.",
        "number_of_evacuees": 8,
        "settings": {"blocked_corridors": ["c4"]},
        "hazards": [],
        "unavailable_exits": [],
    },
    "ditu-vedanta-exit-closed": {
        "name": "DITU demonstration · exit unavailable",
        "description": "Hypothetical closure of illustrative node exit-north; this is not a mapped or verified campus emergency exit.",
        "learning_outcome": "Observe routes use the remaining model exit where reachable.",
        "number_of_evacuees": 8,
        "settings": {},
        "hazards": [],
        "unavailable_exits": ["exit-north"],
    },
    "ditu-vedanta-flood": {
        "name": "DITU demonstration · flood on model passage",
        "description": "Hypothetical flood incident on illustrative graph corridor c4; the target ID has no verified geographic location.",
        "learning_outcome": "Observe a flood record create a hard corridor exclusion and trigger replanning.",
        "number_of_evacuees": 4,
        "settings": {},
        "hazards": [{"hazard_type": "flood", "target_type": "corridor", "target_id": "c4", "severity": 0.8}],
        "unavailable_exits": [],
    },
    "ditu-vedanta-crowd-near-exit": {
        "name": "DITU demonstration · crowd near model exits",
        "description": "Hypothetical group of 48 evacuees assigned to the illustrative graph; the count and exit-area crowding are demonstration inputs, not campus occupancy.",
        "learning_outcome": "Observe modeled capacity queues, corridor utilization, and interval-based replanning.",
        "number_of_evacuees": 48,
        "settings": {"replan_on_congestion": True, "replan_interval_steps": 3, "congestion_penalty": 1.5},
        "hazards": [],
        "unavailable_exits": [],
    },
    "ditu-vedanta-multiple-hazards": {
        "name": "DITU demonstration · multiple hypothetical hazards",
        "description": "Hypothetical fire on graph corridor c4 and flood at graph node junction-e. Neither target is a verified DIT University hazard location.",
        "learning_outcome": "Observe simultaneous active exclusions, replanning, and unable-to-evacuate outcomes when alternatives are removed.",
        "number_of_evacuees": 8,
        "settings": {},
        "hazards": [
            {"hazard_type": "fire", "target_type": "corridor", "target_id": "c4", "severity": 0.9},
            {"hazard_type": "flood", "target_type": "node", "target_id": "junction-e", "severity": 0.7},
        ],
        "unavailable_exits": [],
    },
    "blocked-staircase": {
        "name": "Blocked staircase with elevator alternative",
        "description": "A hypothetical closure blocks the main staircase between Floors 2 and 1 while the modeled elevator remains available.",
        "learning_outcome": "Compare vertical evacuation alternatives when a staircase is unavailable.",
        "evacuees": [
            {"starting_room": "f2-room-101", "group": "student"},
            {"starting_room": "f3-room-101", "group": "faculty"},
            {"starting_room": "f4-computer-lab-1", "group": "visitor"},
        ],
        "settings": {"blocked_corridors": ["stair-f1-f2"]},
        "hazards": [], "unavailable_exits": [],
    },
    "elevator-outage": {
        "name": "Elevator outage",
        "description": "A hypothetical elevator outage disables vertical lift links while staircases remain available.",
        "learning_outcome": "Observe routes fall back to staircases when the elevator network is unavailable.",
        "evacuees": [
            {"starting_room": "f2-room-101", "group": "student"},
            {"starting_room": "f5-computer-lab-2", "group": "faculty"},
        ],
        "settings": {"blocked_corridors": [
            "f1-elevator-lobby", "f2-elevator-lobby", "f3-elevator-lobby", "f4-elevator-lobby", "f5-elevator-lobby",
            "elevator-f1-f2", "elevator-f2-f3", "elevator-f3-f4", "elevator-f4-f5",
        ]},
        "hazards": [], "unavailable_exits": [],
    },
}


def list_scenarios() -> list[dict[str, Any]]:
    return [{"scenario_id": key, **deepcopy(value)} for key, value in SCENARIOS.items()]


def get_scenario(scenario_id: str) -> dict[str, Any] | None:
    scenario = SCENARIOS.get(scenario_id)
    return {"scenario_id": scenario_id, **deepcopy(scenario)} if scenario else None

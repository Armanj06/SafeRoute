"""Plain Python simulation state models, independent of FastAPI."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Hazard:
    hazard_id: str
    hazard_type: str
    target_type: str
    target_id: str
    severity: float
    active: bool
    created_step: int
    propagation_enabled: bool = False
    propagation_interval_steps: int = 1
    max_spread: int = 1
    spread_count: int = 0
    propagated_targets: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evacuee:
    evacuee_id: str
    starting_room: str
    current_node: str
    assigned_exit: str | None
    route: list[str]
    route_corridors: list[str]
    route_position: int = 0
    status: str = "waiting"
    time_spent_seconds: float = 0.0
    # None preserves legacy per-corridor travel_time_seconds behavior.
    walking_speed_mps: float | None = None
    reaction_delay_seconds: float = 0.0
    remaining_reaction_seconds: float = 0.0
    accessibility: dict[str, Any] = field(default_factory=dict)
    group: str = "student"
    current_corridor: str | None = None
    next_node: str | None = None
    remaining_segment_seconds: float = 0.0
    waiting_steps: int = 0
    waiting_corridor: str | None = None
    exit_queue_entered_step: int | None = None
    exit_service_remaining_seconds: float | None = None
    unable_reason: str | None = None
    needs_replan: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SimulationEvent:
    sequence: int
    step: int
    time_seconds: float
    event_type: str
    evacuee_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SimulationSettings:
    time_step_seconds: float = 5.0
    congestion_penalty: float = 1.0
    replan_on_congestion: bool = False
    replan_interval_steps: int = 3
    candidate_limit: int = 12
    # None preserves edge travel_time_seconds; missing edge times use 1.2 m/s.
    default_walking_speed_mps: float | None = None
    default_reaction_delay_seconds: float = 0.0
    preference_weights: dict[str, float] | None = None
    blocked_corridors: list[str] = field(default_factory=list)
    unavailable_exits: list[str] = field(default_factory=list)
    unsafe_locations: list[str] = field(default_factory=list)


@dataclass
class SimulationState:
    simulation_id: str
    building_id: str
    status: str
    current_step: int
    current_time_seconds: float
    evacuees: list[Evacuee]
    corridor_occupancy: dict[str, int]
    event_history: list[SimulationEvent]
    settings: SimulationSettings
    evacuee_specs: list[dict[str, Any]]
    hazards: list[Hazard] = field(default_factory=list)
    manually_unavailable_exits: list[str] = field(default_factory=list)
    scenario_id: str | None = None
    scenario_name: str | None = None
    initial_hazards: list[dict[str, Any]] = field(default_factory=list)
    initial_unavailable_exits: list[str] = field(default_factory=list)
    total_simulation_duration_seconds: float | None = None
    exit_queues: dict[str, list[str]] = field(default_factory=dict)
    exit_service_remaining_seconds: dict[str, float | None] = field(default_factory=dict)
    last_successful_evacuation_time_seconds: float | None = None

    def summary(self) -> dict[str, Any]:
        total = len(self.evacuees)
        evacuated = sum(person.status == "evacuated" for person in self.evacuees)
        unable = sum(person.status == "unable_to_evacuate" for person in self.evacuees)
        active = sum(person.status in {"waiting", "moving", "waiting_exit_service"} for person in self.evacuees)
        waiting_for_exit_service = sum(person.status == "waiting_exit_service" for person in self.evacuees)
        replans = sum(event.event_type == "route_replanned" for event in self.event_history)
        evacuation_complete = total > 0 and evacuated == total
        terminated = self.status == "completed"
        return {
            "total_evacuees": total,
            "initial_evacuees": total,
            "total_evacuated": evacuated,
            "total_remaining": total - evacuated,
            "active_remaining": active,
            "waiting_for_exit_service": waiting_for_exit_service,
            "unable_to_evacuate": unable,
            "total_steps": self.current_step,
            "completion_percentage": round(100 * evacuated / total, 2) if total else 0.0,
            "average_evacuation_duration_seconds": (
                sum(person.time_spent_seconds for person in self.evacuees if person.status == "evacuated") / evacuated
                if evacuated else None
            ),
            "active_hazard_count": sum(hazard.active for hazard in self.hazards),
            "route_replanning_events": replans,
            "evacuation_complete": evacuation_complete,
            "simulation_terminated": terminated,
            "outcome": "no_evacuees" if total == 0 else (
                "evacuated" if evacuation_complete else (
                    "terminated_with_people_remaining" if terminated else "in_progress"
                )
            ),
            "simulation_duration_seconds": (
                self.total_simulation_duration_seconds
                if self.total_simulation_duration_seconds is not None
                else self.current_time_seconds
            ),
            "last_successful_evacuation_time_seconds": self.last_successful_evacuation_time_seconds,
            "simulation_termination_time_seconds": (
                self.total_simulation_duration_seconds if terminated else None
            ),
            "completion_status": self.status,
        }

    def to_dict(self, building: dict[str, Any]) -> dict[str, Any]:
        corridor_by_id = {edge["id"]: edge for edge in building.get("corridors", [])}
        loads = {}
        for corridor_id, occupancy in self.corridor_occupancy.items():
            edge = corridor_by_id[corridor_id]
            capacity = int(float(edge.get("capacity", 1)))
            ratio = occupancy / capacity
            if self.settings.default_walking_speed_mps is None:
                base_time = float(edge.get("travel_time_seconds", float(edge.get("distance", 0)) / 1.2))
            else:
                base_time = float(edge.get("distance", 0)) / self.settings.default_walking_speed_mps
            congestion = max(float(edge.get("crowd_density", 0)), ratio)
            loads[corridor_id] = {
                "occupancy": occupancy,
                "capacity": capacity,
                "utilization": ratio,
                "effective_travel_time_seconds": base_time * (1 + self.settings.congestion_penalty * congestion),
            }
        return {
            "simulation_id": self.simulation_id,
            "building_id": self.building_id,
            "status": self.status,
            "current_step": self.current_step,
            "current_time_seconds": self.current_time_seconds,
            "settings": asdict(self.settings),
            "scenario": {"id": self.scenario_id, "name": self.scenario_name} if self.scenario_id else None,
            "hazards": [hazard.to_dict() for hazard in self.hazards],
            "effective_conditions": effective_conditions(building, self),
            "evacuees": [person.to_dict() for person in self.evacuees],
            "corridor_occupancy": dict(self.corridor_occupancy),
            "exit_queues": {exit_id: list(queue) for exit_id, queue in self.exit_queues.items()},
            "exit_service_remaining_seconds": dict(self.exit_service_remaining_seconds),
            "corridor_load": loads,
            "statistics": self.summary(),
            "analytics": simulation_analytics(building, self),
            "event_history": [event.to_dict() for event in self.event_history],
        }


def effective_conditions(building: dict[str, Any], state: SimulationState) -> dict[str, list[str]]:
    """Recompute hard route exclusions without mutating the source graph."""
    blocked_corridors = {
        edge["id"] for edge in building.get("corridors", []) if edge.get("blocked")
    } | set(state.settings.blocked_corridors)
    unsafe_corridors = {
        edge["id"] for edge in building.get("corridors", []) if edge.get("unsafe")
    } | set(state.settings.unsafe_locations)
    unsafe_nodes = {
        node["id"] for node in building.get("nodes", []) if node.get("unsafe")
    } | set(state.settings.unsafe_locations)
    unavailable_exits = set(state.settings.unavailable_exits) | set(state.manually_unavailable_exits)
    for hazard in state.hazards:
        if not hazard.active:
            continue
        targets = [{"target_type": hazard.target_type, "target_id": hazard.target_id}]
        targets.extend(hazard.propagated_targets)
        for target in targets:
            if target["target_type"] == "corridor":
                unsafe_corridors.add(target["target_id"])
            else:
                unsafe_nodes.add(target["target_id"])
                if any(node["id"] == target["target_id"] and node.get("type") == "exit"
                       for node in building.get("nodes", [])):
                    unavailable_exits.add(target["target_id"])
    return {
        "blocked_corridors": sorted(blocked_corridors | unsafe_corridors),
        "unsafe_corridors": sorted(unsafe_corridors),
        "unsafe_nodes": sorted(unsafe_nodes),
        "unavailable_exits": sorted(unavailable_exits),
    }


def simulation_analytics(building: dict[str, Any], state: SimulationState) -> dict[str, Any]:
    """Return measured run outcomes and current corridor-load aggregates."""
    ratios = []
    at_capacity = 0
    high_occupancy = 0
    for corridor in building.get("corridors", []):
        capacity = max(1, int(float(corridor.get("capacity", 1))))
        occupancy = state.corridor_occupancy.get(corridor["id"], 0)
        ratio = occupancy / capacity
        ratios.append(ratio)
        at_capacity += ratio >= 1
        high_occupancy += ratio >= 0.75
    conditions = effective_conditions(building, state)
    return {
        **state.summary(),
        "average_corridor_occupancy_ratio": sum(ratios) / len(ratios) if ratios else 0.0,
        "maximum_corridor_occupancy_ratio": max(ratios, default=0.0),
        "corridors_at_capacity": at_capacity,
        "high_occupancy_corridors": high_occupancy,
        "high_occupancy_threshold": 0.75,
        "unsafe_corridor_count": len(conditions["unsafe_corridors"]),
        "blocked_corridor_count": len(conditions["blocked_corridors"]),
        "unavailable_exit_count": len(conditions["unavailable_exits"]),
    }

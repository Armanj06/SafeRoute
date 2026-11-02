"""Deterministic discrete-time evacuation simulation engine."""
from __future__ import annotations

from copy import deepcopy
from math import ceil, isfinite
from typing import Any
from uuid import uuid4

from app.agents.utility_agent import choose_utility_route, validate_weights
from app.algorithms.common import DEFAULT_WALKING_SPEED_METERS_PER_SECOND
from app.simulation.models import (
    Evacuee, Hazard, SimulationEvent, SimulationSettings, SimulationState,
    effective_conditions,
)


class SimulationEngine:
    """Runs evacuees through capacity-limited corridors using fixed time steps.

    Corridor capacity is treated as a maximum simultaneous occupancy because
    the graph has no separate movement-throughput value. Occupants hold one
    corridor slot until their modeled travel time expires.
    """

    def __init__(self, building: dict[str, Any]):
        self.building = deepcopy(building)
        self.nodes = {node["id"]: node for node in self.building.get("nodes", [])}
        self.corridors = {edge["id"]: edge for edge in self.building.get("corridors", [])}
        self.adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = {
            node_id: [] for node_id in self.nodes
        }
        for edge in self.building.get("corridors", []):
            a, b = edge["from"], edge["to"]
            if a in self.adjacency and b in self.adjacency:
                self.adjacency[a].append((b, edge))
                self.adjacency[b].append((a, edge))
            capacity = self._capacity(edge)
            if capacity < 1:
                raise ValueError(f"Corridor '{edge['id']}' capacity must allow at least one person.")
        for node in self.nodes.values():
            throughput = node.get("throughput_people_per_second")
            if node.get("type") == "exit" and throughput is not None and (
                isinstance(throughput, bool) or not isinstance(throughput, (int, float))
                or not isfinite(throughput) or throughput <= 0
            ):
                raise ValueError(
                    f"Exit '{node['id']}' throughput_people_per_second must be finite and greater than zero."
                )

    @staticmethod
    def _capacity(edge: dict[str, Any]) -> int:
        try:
            value = float(edge.get("capacity", 1))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Corridor '{edge.get('id', '?')}' capacity must be numeric.") from error
        if not isfinite(value) or value < 1:
            raise ValueError(f"Corridor '{edge.get('id', '?')}' capacity must be at least one.")
        return int(value)

    @staticmethod
    def _base_time(edge: dict[str, Any]) -> float:
        value = edge.get(
            "travel_time_seconds",
            float(edge.get("distance", 0)) / DEFAULT_WALKING_SPEED_METERS_PER_SECOND,
        )
        seconds = float(value)
        if not isfinite(seconds) or seconds < 0:
            raise ValueError(f"Corridor '{edge.get('id', '?')}' travel time must be finite and non-negative.")
        return seconds

    def create(
        self,
        evacuee_specs: list[dict[str, Any]],
        settings: SimulationSettings | None = None,
        simulation_id: str | None = None,
    ) -> SimulationState:
        config = deepcopy(settings or SimulationSettings())
        if not isfinite(config.time_step_seconds) or config.time_step_seconds <= 0:
            raise ValueError("time_step_seconds must be positive and finite.")
        if not isfinite(config.congestion_penalty) or config.congestion_penalty < 0:
            raise ValueError("congestion_penalty must be non-negative and finite.")
        if not 1 <= config.replan_interval_steps <= 100:
            raise ValueError("replan_interval_steps must be between 1 and 100.")
        if not 1 <= config.candidate_limit <= 50:
            raise ValueError("candidate_limit must be between 1 and 50.")
        config.preference_weights = validate_weights(config.preference_weights)
        default_speed = config.default_walking_speed_mps
        if default_speed is not None and (
            isinstance(default_speed, bool) or not isinstance(default_speed, (int, float))
            or not isfinite(default_speed) or default_speed <= 0
        ):
            raise ValueError("default_walking_speed_mps must be finite and greater than zero.")
        default_reaction = config.default_reaction_delay_seconds
        if (
            isinstance(default_reaction, bool) or not isinstance(default_reaction, (int, float))
            or not isfinite(default_reaction) or default_reaction < 0
        ):
            raise ValueError("default_reaction_delay_seconds must be finite and non-negative.")
        unknown_corridors = set(config.blocked_corridors) - set(self.corridors)
        if unknown_corridors:
            raise ValueError(f"Unknown blocked corridor(s): {', '.join(sorted(unknown_corridors))}.")
        valid_unsafe_targets = set(self.corridors) | set(self.nodes)
        unknown_unsafe_targets = set(config.unsafe_locations) - valid_unsafe_targets
        if unknown_unsafe_targets:
            raise ValueError(f"Unknown unsafe location(s): {', '.join(sorted(unknown_unsafe_targets))}.")
        valid_exits = {node_id for node_id, node in self.nodes.items() if node.get("type") == "exit"}
        unknown_exits = set(config.unavailable_exits) - valid_exits
        if unknown_exits:
            raise ValueError(f"Unknown unavailable exit(s): {', '.join(sorted(unknown_exits))}.")

        state = SimulationState(
            simulation_id=simulation_id or str(uuid4()),
            building_id=str(self.building.get("id", "default")),
            status="paused",
            current_step=0,
            current_time_seconds=0.0,
            evacuees=[],
            corridor_occupancy={corridor_id: 0 for corridor_id in self.corridors},
            exit_queues={node_id: [] for node_id, node in self.nodes.items() if node.get("type") == "exit"},
            exit_service_remaining_seconds={
                node_id: None for node_id, node in self.nodes.items() if node.get("type") == "exit"
            },
            event_history=[],
            settings=config,
            evacuee_specs=deepcopy(evacuee_specs),
        )
        self._emit(state, "simulation_created", details={"evacuee_count": len(evacuee_specs)})
        for index, spec in enumerate(evacuee_specs, start=1):
            room = spec["starting_room"]
            if room not in self.nodes or self.nodes[room].get("type") not in {"room", "area"}:
                raise ValueError(f"Starting location '{room}' is not a valid room or functional area.")
            speed = spec.get("walking_speed_mps")
            if speed is None:
                speed = config.default_walking_speed_mps
            if speed is not None and (
                isinstance(speed, bool) or not isinstance(speed, (int, float))
                or not isfinite(speed) or speed <= 0
            ):
                raise ValueError("walking_speed_mps must be finite and greater than zero.")
            if speed is not None:
                # Catch finite but impractically small values that overflow the
                # computed travel time before mutating simulation state.
                for edge in self.corridors.values():
                    self._effective_time(edge, 0, 0.0, float(speed))
            reaction = spec.get("reaction_delay_seconds")
            if reaction is None:
                reaction = config.default_reaction_delay_seconds
            if (
                isinstance(reaction, bool) or not isinstance(reaction, (int, float))
                or not isfinite(reaction) or reaction < 0
            ):
                raise ValueError("reaction_delay_seconds must be finite and non-negative.")
            reaction = float(reaction)
            person = Evacuee(
                evacuee_id=f"person-{index:04d}",
                starting_room=room,
                current_node=room,
                assigned_exit=None,
                route=[],
                route_corridors=[],
                walking_speed_mps=float(speed) if speed is not None else None,
                reaction_delay_seconds=reaction,
                remaining_reaction_seconds=reaction,
                accessibility=deepcopy(spec.get("accessibility") or {}),
                group=str(spec.get("group") or "student"),
            )
            self._assign_route(state, person)
            state.evacuees.append(person)
        self._refresh_status(state)
        return state

    def reset(self, state: SimulationState) -> SimulationState:
        fresh = self.create(state.evacuee_specs, state.settings, state.simulation_id)
        fresh.event_history = []
        # Reset begins a new lifecycle even when initial routing has no path;
        # the final refresh below records exactly one terminal event if needed.
        fresh.status = "paused"
        fresh.total_simulation_duration_seconds = None
        fresh.last_successful_evacuation_time_seconds = None
        fresh.scenario_id = state.scenario_id
        fresh.scenario_name = state.scenario_name
        fresh.initial_hazards = deepcopy(state.initial_hazards)
        fresh.initial_unavailable_exits = list(state.initial_unavailable_exits)
        self._emit(fresh, "simulation_reset")
        for hazard in fresh.initial_hazards:
            self.add_hazard(fresh, **hazard, defer_lifecycle=True)
        for exit_id in fresh.initial_unavailable_exits:
            self.set_exit_available(fresh, exit_id, False, defer_lifecycle=True)
        self._refresh_status(fresh)
        return fresh

    def add_hazard(
        self, state: SimulationState, hazard_type: str, target_type: str,
        target_id: str, severity: float, propagation_enabled: bool = False,
        propagation_interval_steps: int = 1, max_spread: int = 1,
        active: bool = True, defer_lifecycle: bool = False,
    ) -> Hazard:
        self._ensure_mutable(state, defer_lifecycle)
        if hazard_type not in {"fire", "flood", "unsafe_area"}:
            raise ValueError("hazard_type must be fire, flood, or unsafe_area.")
        targets = self.nodes if target_type == "node" else self.corridors if target_type == "corridor" else None
        if targets is None:
            raise ValueError("target_type must be node or corridor.")
        if target_id not in targets:
            raise ValueError(f"Unknown {target_type} target '{target_id}'.")
        if not isfinite(severity) or not 0 <= severity <= 1:
            raise ValueError("severity must be between 0 and 1.")
        if propagation_interval_steps < 1 or max_spread < 1:
            raise ValueError("Propagation interval and max_spread must be at least 1.")
        hazard = Hazard(
            hazard_id=f"hazard-{uuid4().hex[:10]}", hazard_type=hazard_type,
            target_type=target_type, target_id=target_id, severity=float(severity),
            active=active, created_step=state.current_step,
            propagation_enabled=propagation_enabled,
            propagation_interval_steps=propagation_interval_steps,
            max_spread=max_spread,
        )
        state.hazards.append(hazard)
        self._emit(state, "hazard_activated" if active else "hazard_created", details=hazard.to_dict())
        if active:
            self._replan_for_conditions(state, "hazard activated")
        if not defer_lifecycle:
            self._refresh_status(state)
        return hazard

    def set_hazard_active(
        self, state: SimulationState, hazard_id: str, active: bool,
        defer_lifecycle: bool = False,
    ) -> Hazard:
        self._ensure_mutable(state, defer_lifecycle)
        hazard = next((item for item in state.hazards if item.hazard_id == hazard_id), None)
        if hazard is None:
            raise ValueError(f"Hazard '{hazard_id}' was not found.")
        if hazard.active == active:
            return hazard
        hazard.active = active
        event = "hazard_activated" if active else "hazard_resolved"
        self._emit(state, event, details=hazard.to_dict())
        self._replan_for_conditions(state, event.replace("_", " "))
        if not defer_lifecycle:
            self._refresh_status(state)
        return hazard

    def set_exit_available(
        self, state: SimulationState, exit_id: str, available: bool,
        defer_lifecycle: bool = False,
    ) -> None:
        self._ensure_mutable(state, defer_lifecycle)
        if exit_id not in self.nodes or self.nodes[exit_id].get("type") != "exit":
            raise ValueError(f"'{exit_id}' is not a valid exit.")
        unavailable = set(state.manually_unavailable_exits)
        if available:
            unavailable.discard(exit_id)
            event = "exit_restored"
        else:
            unavailable.add(exit_id)
            event = "exit_unavailable"
        state.manually_unavailable_exits = sorted(unavailable)
        self._emit(state, event, details={"exit_id": exit_id})
        self._replan_for_conditions(state, event.replace("_", " "))
        if not defer_lifecycle:
            self._refresh_status(state)

    @staticmethod
    def _ensure_mutable(state: SimulationState, defer_lifecycle: bool) -> None:
        if state.status == "completed" and not defer_lifecycle:
            raise ValueError("A completed simulation cannot accept condition changes; reset it first.")

    def start(self, state: SimulationState) -> SimulationState:
        if self._active_people(state) and state.status != "completed":
            state.status = "running"
            self._emit(state, "simulation_started")
        return state

    def pause(self, state: SimulationState) -> SimulationState:
        if state.status == "running":
            state.status = "paused"
            self._emit(state, "simulation_paused")
        return state

    def advance(self, state: SimulationState, steps: int = 1) -> SimulationState:
        if not isinstance(steps, int) or not 1 <= steps <= 100:
            raise ValueError("steps must be an integer between 1 and 100.")
        for _ in range(steps):
            if state.status == "completed":
                break
            self._advance_one_step(state)
        return state

    def _advance_one_step(self, state: SimulationState) -> None:
        next_step = state.current_step + 1
        self._propagate_hazards(state, next_step)
        if (
            state.settings.replan_on_congestion
            and next_step % state.settings.replan_interval_steps == 0
        ):
            self._replan_waiting_people(state)

        # Deterministic FIFO by waiting duration, then stable person ID.
        requests = []
        for person in state.evacuees:
            if person.status not in {"waiting", "moving"} or person.current_corridor:
                continue
            # Reaction delays are rounded up to the next simulation boundary:
            # no movement request is admitted until the countdown reached zero
            # in an earlier step.
            if person.remaining_reaction_seconds > 0:
                continue
            if person.route_position >= len(person.route) - 1:
                if self.nodes.get(person.current_node, {}).get("type") == "exit":
                    self._mark_evacuated(state, person)
                else:
                    self._mark_unable(state, person, "Assigned route ended before reaching an exit.")
                continue
            corridor_id = person.route_corridors[person.route_position]
            conditions = effective_conditions(self.building, state)
            if self._route_step_is_unsafe(person, corridor_id, conditions):
                self._replan_person(state, person, "route invalidated before corridor entry")
                if person.status != "waiting" or person.route_position >= len(person.route) - 1:
                    continue
                corridor_id = person.route_corridors[person.route_position]
                conditions = effective_conditions(self.building, state)
                if self._route_step_is_unsafe(person, corridor_id, conditions):
                    self._mark_unable(state, person, "No safe route remains from the current location.")
                    continue
            requests.append((person, corridor_id))

        requests.sort(key=lambda request: (-request[0].waiting_steps, request[0].evacuee_id))
        for person, corridor_id in requests:
            available = self._capacity(self.corridors[corridor_id]) - state.corridor_occupancy[corridor_id]
            if available > 0:
                edge = self.corridors[corridor_id]
                person.current_corridor = corridor_id
                person.next_node = person.route[person.route_position + 1]
                new_occupancy = state.corridor_occupancy[corridor_id] + 1
                person.remaining_segment_seconds = self._effective_time(
                    edge, new_occupancy, state.settings.congestion_penalty,
                    person.walking_speed_mps,
                )
                person.waiting_corridor = None
                state.corridor_occupancy[corridor_id] = new_occupancy
                self._emit(state, "corridor_entered", person.evacuee_id, {
                    "corridor_id": corridor_id,
                    "occupancy": state.corridor_occupancy[corridor_id],
                })
            else:
                if person.waiting_corridor != corridor_id:
                    self._emit(state, "capacity_wait", person.evacuee_id, {"corridor_id": corridor_id})
                person.waiting_corridor = corridor_id
                person.waiting_steps += 1

        # Existing and newly admitted people make one fixed time-step of progress.
        delta = state.settings.time_step_seconds
        state.current_step = next_step
        state.current_time_seconds = next_step * delta
        self._emit(state, "simulation_step", details={"step": next_step})
        for person in state.evacuees:
            # One elapsed-time increment per simulated step for every person
            # who has not completed evacuation, including temporary unable states.
            if person.status != "evacuated":
                person.time_spent_seconds += delta
            if person.status not in {"waiting", "moving", "waiting_exit_service"}:
                continue
            if person.current_corridor:
                person.status = "moving"
                person.remaining_segment_seconds -= delta
                if person.remaining_segment_seconds <= 0:
                    self._finish_corridor(state, person)
            elif person.needs_replan and person.status == "waiting":
                person.needs_replan = False
                self._replan_person(state, person, "replanned at next safe junction after hazard activation")
            if person.status == "waiting" and not person.current_corridor and person.remaining_reaction_seconds > 0:
                person.remaining_reaction_seconds = max(
                    0.0, person.remaining_reaction_seconds - delta
                )

        self._process_exit_queues(state, next_step)

        self._refresh_status(state)

    def _finish_corridor(self, state: SimulationState, person: Evacuee) -> None:
        corridor_id = person.current_corridor
        destination = person.next_node
        if corridor_id is None or destination is None:
            return
        state.corridor_occupancy[corridor_id] -= 1
        person.current_node = destination
        person.route_position += 1
        person.current_corridor = None
        person.next_node = None
        person.remaining_segment_seconds = 0.0
        person.waiting_steps = 0
        person.waiting_corridor = None
        person.status = "waiting"
        self._emit(state, "node_reached", person.evacuee_id, {
            "node_id": destination,
            "corridor_id": corridor_id,
        })
        if self.nodes.get(destination, {}).get("type") == "exit":
            self._arrive_at_exit(state, person, destination)
        elif person.needs_replan:
            person.needs_replan = False
            self._replan_person(state, person, "replanned at next safe junction after hazard activation")

    def _assign_route(self, state: SimulationState, person: Evacuee, start_node: str | None = None) -> dict[str, Any]:
        start = start_node or person.starting_room
        snapshot = self._routing_snapshot(state, person.walking_speed_mps)
        # Utility routes normally start in a room. During re-planning an
        # evacuee can be at a junction, so promote only that node in this
        # temporary graph copy; the stored building graph remains unchanged.
        for node in snapshot["nodes"]:
            if node["id"] == start:
                node["type"] = "room"
                node.pop("unsafe", None)
                break
        conditions = effective_conditions(self.building, state)
        conditions["unsafe_nodes"] = [node for node in conditions["unsafe_nodes"] if node != start]
        result = choose_utility_route(
            snapshot, start,
            accessibility=person.accessibility,
            preference_weights=state.settings.preference_weights,
            blocked_corridors=set(conditions["blocked_corridors"]),
            unavailable_exits=set(conditions["unavailable_exits"]),
            unsafe_locations=set(conditions["unsafe_nodes"]),
            candidate_limit=state.settings.candidate_limit,
        )
        if result["found"]:
            person.assigned_exit = result["exit"]
            person.route = result["route"]
            person.route_corridors = result["corridors"]
            person.route_position = 0
            person.unable_reason = None
            if start_node is None:
                self._emit(state, "route_assigned", person.evacuee_id, {
                    "exit": result["exit"], "route": result["route"],
                    "utility_score": result["utility_score"],
                })
        else:
            person.status = "unable_to_evacuate"
            person.unable_reason = result["message"]
            self._emit(state, "unable_to_evacuate", person.evacuee_id, {"reason": result["message"]})
        return result

    def _replan_waiting_people(self, state: SimulationState) -> None:
        for person in state.evacuees:
            if person.status != "waiting" or person.current_corridor:
                continue
            self._replan_person(state, person, "configured congestion replanning interval")

    def _replan_person(self, state: SimulationState, person: Evacuee, reason: str) -> None:
        if person.current_corridor:
            person.needs_replan = True
            return
        old_route = person.route[person.route_position:]
        old_corridors = person.route_corridors[person.route_position:]
        result = self._assign_route(state, person, person.current_node)
        if not result["found"]:
            person.status = "unable_to_evacuate"
            person.unable_reason = "No safe alternative route is available."
            person.route = []
            person.route_corridors = []
            person.route_position = 0
            self._emit(state, "unable_to_evacuate", person.evacuee_id, {
                "reason": person.unable_reason, "invalidated_route": old_route,
            })
            return
        person.status = "waiting"
        person.route_position = 0
        person.needs_replan = False
        if result["route"] != old_route:
            self._emit(state, "route_replanned", person.evacuee_id, {
                "previous_route": old_route, "route": result["route"],
                "previous_corridors": old_corridors,
                "reason": reason,
            })

    def _replan_for_conditions(self, state: SimulationState, reason: str) -> int:
        conditions = effective_conditions(self.building, state)
        blocked = set(conditions["blocked_corridors"])
        unsafe_nodes = set(conditions["unsafe_nodes"])
        unavailable_exits = set(conditions["unavailable_exits"])
        # Closure policy: cancel any unfinished service queue at the exit, then
        # replan those people from that node. They can use another route if one
        # exists; otherwise they are recorded as unable to evacuate.
        people_by_id = {person.evacuee_id: person for person in state.evacuees}
        for exit_id in unavailable_exits:
            queue = state.exit_queues.get(exit_id, [])
            if not queue:
                continue
            queued_ids = list(queue)
            queue.clear()
            state.exit_service_remaining_seconds[exit_id] = None
            for evacuee_id in queued_ids:
                person = people_by_id.get(evacuee_id)
                if person and person.status == "waiting_exit_service":
                    person.status = "waiting"
                    person.exit_queue_entered_step = None
                    person.exit_service_remaining_seconds = None
        recalculated = 0
        for person in state.evacuees:
            if person.status not in {"waiting", "moving", "waiting_exit_service"}:
                # A person who previously had no safe route may recover if a
                # hazard is resolved and they are not physically stranded.
                if person.status == "unable_to_evacuate":
                    if person.current_corridor:
                        destination = person.next_node
                        if (person.current_corridor not in blocked and destination not in unsafe_nodes
                                and destination not in unavailable_exits):
                            person.status = "moving"
                            person.unable_reason = None
                            person.needs_replan = True
                            self._emit(state, "evacuee_resumed", person.evacuee_id, {
                                "corridor_id": person.current_corridor, "reason": reason,
                            })
                            recalculated += 1
                    elif person.current_node not in unsafe_nodes:
                        person.status = "waiting"
                        self._replan_person(state, person, reason)
                        recalculated += 1
                continue
            route = person.route[person.route_position:]
            corridors = person.route_corridors[person.route_position:]
            invalid = any(corridor in blocked for corridor in corridors)
            invalid = invalid or any(node in unsafe_nodes or node in unavailable_exits for node in route)
            if not invalid:
                continue
            recalculated += 1
            if person.current_corridor:
                current_corridor = person.current_corridor
                destination = person.next_node
                if current_corridor in blocked or destination in unsafe_nodes or destination in unavailable_exits:
                    self._mark_unable(
                        state, person,
                        "Stranded in an occupied corridor by a newly active hazard; movement stopped in place.",
                        preserve_corridor=True,
                    )
                    self._emit(state, "evacuee_stranded", person.evacuee_id, {
                        "corridor_id": current_corridor, "hazard_reason": reason,
                    })
                else:
                    person.needs_replan = True
            else:
                self._replan_person(state, person, reason)
        self._emit(state, "routes_recalculated", details={"count": recalculated, "reason": reason})
        return recalculated

    def _route_step_is_unsafe(self, person: Evacuee, corridor_id: str, conditions: dict[str, list[str]]) -> bool:
        next_node = person.route[person.route_position + 1]
        return corridor_id in conditions["blocked_corridors"] or next_node in conditions["unsafe_nodes"] or next_node in conditions["unavailable_exits"]

    def _propagate_hazards(self, state: SimulationState, next_step: int) -> None:
        for hazard in state.hazards:
            if (not hazard.active or not hazard.propagation_enabled
                    or hazard.spread_count >= hazard.max_spread
                    or (next_step - hazard.created_step) % hazard.propagation_interval_steps):
                continue
            frontier = hazard.propagated_targets or [{"target_type": hazard.target_type, "target_id": hazard.target_id}]
            additions: list[dict[str, str]] = []
            for source in frontier:
                if source["target_type"] == "node":
                    additions.extend({"target_type": "corridor", "target_id": edge_id}
                                     for _, edge_id in self._edges_from_node(source["target_id"]))
                else:
                    edge = self.corridors[source["target_id"]]
                    additions.extend({"target_type": "node", "target_id": edge[key]} for key in ("from", "to"))
            known = {(hazard.target_type, hazard.target_id)} | {
                (item["target_type"], item["target_id"]) for item in hazard.propagated_targets
            }
            new_targets = [item for item in additions if (item["target_type"], item["target_id"]) not in known]
            if new_targets:
                hazard.propagated_targets.extend(new_targets)
                hazard.spread_count += 1
                self._emit(state, "hazard_propagated", details={
                    "hazard_id": hazard.hazard_id, "targets": new_targets,
                    "spread_count": hazard.spread_count,
                })
                self._replan_for_conditions(state, "hazard propagation")

    def _edges_from_node(self, node_id: str) -> list[tuple[str, str]]:
        return [(neighbor, edge["id"]) for neighbor, edge in self.adjacency.get(node_id, [])]

    def _routing_snapshot(
        self, state: SimulationState, walking_speed_mps: float | None = None,
    ) -> dict[str, Any]:
        snapshot = deepcopy(self.building)
        conditions = effective_conditions(self.building, state)
        for edge in snapshot.get("corridors", []):
            occupancy = state.corridor_occupancy.get(edge["id"], 0)
            capacity = self._capacity(edge)
            ratio = occupancy / capacity
            congestion = max(float(edge.get("crowd_density", 0)), ratio)
            edge["current_occupancy"] = occupancy
            edge["crowd_density"] = congestion
            edge["travel_time_seconds"] = self._effective_time(
                edge, occupancy, state.settings.congestion_penalty, walking_speed_mps
            )
            if edge["id"] in conditions["blocked_corridors"]:
                edge["blocked"] = True
        for node in snapshot.get("nodes", []):
            if node["id"] in conditions["unsafe_nodes"]:
                node["unsafe"] = True
        return snapshot

    def _effective_time(
        self, edge: dict[str, Any], occupancy: int, penalty: float,
        walking_speed_mps: float | None = None,
    ) -> float:
        if walking_speed_mps is None:
            base_time = self._base_time(edge)
        else:
            distance = float(edge.get("distance", 0))
            if not isfinite(distance) or distance < 0:
                raise ValueError(f"Corridor '{edge.get('id', '?')}' distance must be finite and non-negative.")
            base_time = distance / walking_speed_mps
        ratio = occupancy / self._capacity(edge)
        congestion = max(float(edge.get("crowd_density", 0)), ratio)
        effective_time = base_time * (1 + penalty * congestion)
        if not isfinite(effective_time) or effective_time < 0:
            raise ValueError("Effective corridor travel time must be finite and non-negative.")
        return effective_time

    def _mark_evacuated(self, state: SimulationState, person: Evacuee) -> None:
        if person.status == "evacuated":
            return
        person.status = "evacuated"
        person.current_node = person.assigned_exit or person.current_node
        person.exit_queue_entered_step = None
        person.exit_service_remaining_seconds = None
        state.last_successful_evacuation_time_seconds = state.current_time_seconds
        self._emit(state, "evacuated", person.evacuee_id, {
            "exit": person.current_node,
            "time_spent_seconds": person.time_spent_seconds,
        })

    def _arrive_at_exit(self, state: SimulationState, person: Evacuee, exit_id: str) -> None:
        throughput = self.nodes[exit_id].get("throughput_people_per_second")
        if throughput is None:
            self._mark_evacuated(state, person)
            return
        person.status = "waiting_exit_service"
        person.exit_queue_entered_step = state.current_step
        person.exit_service_remaining_seconds = None
        queue = state.exit_queues.setdefault(exit_id, [])
        queue.append(person.evacuee_id)
        people = {item.evacuee_id: item for item in state.evacuees}
        queue.sort(key=lambda evacuee_id: (
            people[evacuee_id].exit_queue_entered_step or 0, evacuee_id
        ))
        self._emit(state, "exit_queue_entered", person.evacuee_id, {
            "exit_id": exit_id, "queue_position": queue.index(person.evacuee_id) + 1,
        })

    def _process_exit_queues(self, state: SimulationState, next_step: int) -> None:
        delta = state.settings.time_step_seconds
        people = {person.evacuee_id: person for person in state.evacuees}
        for exit_id in sorted(state.exit_queues):
            throughput = self.nodes[exit_id].get("throughput_people_per_second")
            queue = state.exit_queues[exit_id]
            if throughput is None or not queue:
                continue
            remaining_interval = delta
            while queue and remaining_interval > 1e-12:
                person = people.get(queue[0])
                if person is None or person.status != "waiting_exit_service":
                    queue.pop(0)
                    state.exit_service_remaining_seconds[exit_id] = None
                    continue
                if person.exit_queue_entered_step is not None and person.exit_queue_entered_step >= next_step:
                    break
                service_remaining = state.exit_service_remaining_seconds[exit_id]
                if service_remaining is None:
                    service_remaining = 1.0 / float(throughput)
                used = min(remaining_interval, service_remaining)
                service_remaining -= used
                remaining_interval -= used
                state.exit_service_remaining_seconds[exit_id] = service_remaining
                person.exit_service_remaining_seconds = service_remaining
                if service_remaining <= 1e-12:
                    queue.pop(0)
                    state.exit_service_remaining_seconds[exit_id] = None
                    self._mark_evacuated(state, person)
                    self._emit(state, "exit_service_completed", person.evacuee_id, {
                        "exit_id": exit_id,
                    })
                else:
                    break

    def _mark_unable(
        self, state: SimulationState, person: Evacuee, reason: str,
        preserve_corridor: bool = False,
    ) -> None:
        if person.current_corridor and not preserve_corridor:
            state.corridor_occupancy[person.current_corridor] -= 1
            person.current_corridor = None
        person.status = "unable_to_evacuate"
        person.unable_reason = reason
        self._emit(state, "unable_to_evacuate", person.evacuee_id, {"reason": reason})

    def _refresh_status(self, state: SimulationState) -> None:
        if not self._active_people(state):
            if state.status == "completed":
                return
            state.status = "completed"
            state.total_simulation_duration_seconds = state.current_time_seconds
            event_type = (
                "simulation_completed"
                if not state.evacuees or state.summary()["evacuation_complete"]
                else "simulation_terminated"
            )
            self._emit(state, event_type, details=state.summary())
        elif state.status not in {"running", "paused"}:
            state.status = "paused"

    @staticmethod
    def _active_people(state: SimulationState) -> list[Evacuee]:
        return [person for person in state.evacuees if person.status in {"waiting", "moving", "waiting_exit_service"}]

    @staticmethod
    def _emit(
        state: SimulationState, event_type: str, evacuee_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        state.event_history.append(SimulationEvent(
            sequence=len(state.event_history) + 1,
            step=state.current_step,
            time_seconds=state.current_time_seconds,
            event_type=event_type,
            evacuee_id=evacuee_id,
            details=details or {},
        ))

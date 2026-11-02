"""Thread-safe in-memory registry for simulations bound to independent graphs."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Callable

from app.simulation.engine import SimulationEngine
from app.simulation.models import SimulationSettings, SimulationState, effective_conditions, simulation_analytics
from app.simulation.scenarios import get_scenario


class SimulationManager:
    def __init__(
        self,
        building: dict[str, Any],
        building_loader: Callable[[str | None], dict[str, Any]] | None = None,
    ):
        # Keep the old constructor/API shape; the default engine remains available
        # for callers that used it directly. Each run receives its own engine copy.
        self.building = deepcopy(building)
        self.engine = SimulationEngine(self.building)
        self._default_building_id = str(self.building.get("id", "default"))
        self._building_loader = building_loader
        self._states: dict[str, SimulationState] = {}
        self._engines: dict[str, SimulationEngine] = {}
        self._buildings: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def _resolve_building(self, building_id: str | None) -> dict[str, Any]:
        if building_id is None:
            graph = self.building
        elif building_id == self._default_building_id:
            graph = self.building
        elif self._building_loader is not None:
            graph = self._building_loader(building_id)
        else:
            raise ValueError(f"Building model '{building_id}' is not available.")
        resolved_id = graph.get("id")
        if building_id is not None and resolved_id != building_id:
            raise ValueError(f"Building model '{building_id}' is not available.")
        return deepcopy(graph)

    def _engine_for(self, simulation_id: str) -> SimulationEngine | None:
        return self._engines.get(simulation_id)

    def building_for(self, state: SimulationState) -> dict[str, Any]:
        with self._lock:
            building = self._buildings.get(state.simulation_id)
            if building is None or state.building_id != building.get("id"):
                raise ValueError(f"Building graph for simulation '{state.simulation_id}' is unavailable.")
            return deepcopy(building)

    def create(
        self, number_of_evacuees: int | None = None,
        evacuee_specs: list[dict[str, Any]] | None = None,
        settings: SimulationSettings | None = None,
        building_id: str | None = None,
    ) -> SimulationState:
        with self._lock:
            building = self._resolve_building(building_id)
            engine = SimulationEngine(building)
            specs = evacuee_specs
            if specs is None:
                rooms = [
                    node["id"] for node in building.get("nodes", [])
                    if node.get("type") in {"room", "area"}
                ]
                if not rooms:
                    raise ValueError("The building does not contain any starting rooms.")
                if number_of_evacuees is None or number_of_evacuees < 1:
                    raise ValueError("number_of_evacuees must be at least one.")
                specs = [
                    {"starting_room": rooms[index % len(rooms)], "accessibility": {}}
                    for index in range(number_of_evacuees)
                ]
            state = engine.create(specs, settings)
            self._states[state.simulation_id] = state
            self._engines[state.simulation_id] = engine
            self._buildings[state.simulation_id] = deepcopy(building)
            return state

    def create_scenario(self, scenario_id: str, building_id: str | None = None) -> SimulationState | None:
        scenario = get_scenario(scenario_id)
        if scenario is None:
            return None
        with self._lock:
            settings = SimulationSettings(**scenario["settings"])
            state = self.create(
                number_of_evacuees=scenario.get("number_of_evacuees"),
                evacuee_specs=scenario.get("evacuees"),
                settings=settings,
                building_id=building_id,
            )
            engine = self._engine_for(state.simulation_id)
            assert engine is not None
            state.scenario_id = scenario_id
            state.scenario_name = scenario["name"]
            state.initial_hazards = [dict(hazard) for hazard in scenario["hazards"]]
            state.initial_unavailable_exits = list(scenario["unavailable_exits"])
            try:
                for hazard in state.initial_hazards:
                    engine.add_hazard(state, **hazard, defer_lifecycle=True)
                for exit_id in state.initial_unavailable_exits:
                    engine.set_exit_available(state, exit_id, False, defer_lifecycle=True)
            except ValueError:
                # Do not leave a partially initialized run in the registry when
                # a graph-specific preset is incompatible with the selected model.
                self._states.pop(state.simulation_id, None)
                self._engines.pop(state.simulation_id, None)
                self._buildings.pop(state.simulation_id, None)
                raise
            engine._emit(state, "scenario_loaded", details={
                "scenario_id": scenario_id,
                "scenario_name": scenario["name"],
                "learning_outcome": scenario["learning_outcome"],
            })
            engine._refresh_status(state)
            return state

    def get(self, simulation_id: str) -> SimulationState | None:
        with self._lock:
            return self._states.get(simulation_id)

    def get_building(self, simulation_id: str) -> dict[str, Any] | None:
        with self._lock:
            building = self._buildings.get(simulation_id)
            return deepcopy(building) if building is not None else None

    def get_engine(self, simulation_id: str) -> SimulationEngine | None:
        with self._lock:
            return self._engine_for(simulation_id)

    def start(self, simulation_id: str) -> SimulationState | None:
        with self._lock:
            state, engine = self._states.get(simulation_id), self._engine_for(simulation_id)
            return engine.start(state) if state and engine else None

    def pause(self, simulation_id: str) -> SimulationState | None:
        with self._lock:
            state, engine = self._states.get(simulation_id), self._engine_for(simulation_id)
            return engine.pause(state) if state and engine else None

    def advance(self, simulation_id: str, steps: int = 1) -> SimulationState | None:
        with self._lock:
            state, engine = self._states.get(simulation_id), self._engine_for(simulation_id)
            return engine.advance(state, steps) if state and engine else None

    def reset(self, simulation_id: str) -> SimulationState | None:
        with self._lock:
            state, engine = self._states.get(simulation_id), self._engine_for(simulation_id)
            if state is None or engine is None:
                return None
            reset_state = engine.reset(state)
            self._states[simulation_id] = reset_state
            return reset_state

    def add_hazard(self, simulation_id: str, **kwargs):
        with self._lock:
            state, engine = self._states.get(simulation_id), self._engine_for(simulation_id)
            return engine.add_hazard(state, **kwargs) if state and engine else None

    def set_hazard_active(self, simulation_id: str, hazard_id: str, active: bool):
        with self._lock:
            state, engine = self._states.get(simulation_id), self._engine_for(simulation_id)
            return engine.set_hazard_active(state, hazard_id, active) if state and engine else None

    def set_exit_available(self, simulation_id: str, exit_id: str, available: bool):
        with self._lock:
            state, engine = self._states.get(simulation_id), self._engine_for(simulation_id)
            if state is None or engine is None:
                return None
            engine.set_exit_available(state, exit_id, available)
            return state

    def serialize(self, state: SimulationState) -> dict[str, Any]:
        with self._lock:
            building = self._buildings[state.simulation_id]
            return state.to_dict(building)

    def summary(self, state: SimulationState) -> dict[str, Any]:
        with self._lock:
            building = self._buildings[state.simulation_id]
            return {
                "simulation_id": state.simulation_id,
                "building_id": state.building_id,
                "status": state.status,
                "current_step": state.current_step,
                "current_time_seconds": state.current_time_seconds,
                **state.summary(),
                "analytics": simulation_analytics(building, state),
            }

    def events(self, state: SimulationState, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [
                event.to_dict() for event in state.event_history
                if event.sequence > after_sequence
            ]

    def conditions(self, state: SimulationState) -> dict[str, list[str]]:
        with self._lock:
            return effective_conditions(self._buildings[state.simulation_id], state)

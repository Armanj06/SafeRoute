import json
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from app.algorithms.comparison import compare_routes
from app.algorithms.routing import find_route
from app.agents.utility_agent import choose_utility_route
from app.services.building import load_building, load_campus, save_custom_building
from app.simulation.models import SimulationSettings
from app.simulation.reports import build_csv_report, build_report
from app.simulation.scenarios import get_scenario, list_scenarios
from app.simulation.service import SimulationManager

router = APIRouter(prefix="/api")


class CustomBuildingRequest(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(default="Custom SafeRoute design", min_length=1, max_length=160)
    floors: list[dict] = Field(default_factory=list)
    nodes: list[dict] = Field(default_factory=list)
    corridors: list[dict] = Field(default_factory=list)
    exit_ids: list[str] = Field(default_factory=list)


class RouteRequest(BaseModel):
    starting_room: str
    building_id: str | None = None
    algorithm: str = "bfs"
    cost_model: str = "distance"
    blocked_corridors: list[str] = Field(default_factory=list)
    unavailable_exits: list[str] = Field(default_factory=list)
    unsafe_locations: list[str] = Field(default_factory=list)


class AccessibilityRequirements(BaseModel):
    step_free: bool = False
    minimum_width_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class UtilityRouteRequest(BaseModel):
    starting_room: str
    building_id: str | None = None
    accessibility: AccessibilityRequirements = Field(default_factory=AccessibilityRequirements)
    preference_weights: dict[str, float] | None = None
    blocked_corridors: list[str] = Field(default_factory=list)
    unavailable_exits: list[str] = Field(default_factory=list)
    unsafe_locations: list[str] = Field(default_factory=list)
    candidate_limit: int = Field(default=12, ge=1, le=50)
    reference_time_seconds: float = Field(default=300.0, gt=0, allow_inf_nan=False)


class RouteComparisonRequest(BaseModel):
    starting_room: str
    building_id: str | None = None
    cost_model: Literal["distance", "travel_time"] = "distance"
    comparison_profile: Literal["current", "slow_north"] = "current"
    simulation_id: str | None = None
    blocked_corridors: list[str] = Field(default_factory=list)
    unavailable_exits: list[str] = Field(default_factory=list)
    unsafe_locations: list[str] = Field(default_factory=list)
    accessibility: AccessibilityRequirements = Field(default_factory=AccessibilityRequirements)
    preference_weights: dict[str, float] | None = None
    candidate_limit: int = Field(default=12, ge=1, le=50)


@router.get("/health")
def health():
    return {"status": "ok", "service": "AI Evacuation Planning API"}


@router.get("/campus")
def campus():
    return load_campus()


@router.get("/building")
def building(building_id: str | None = None):
    try:
        return load_building(building_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/custom-buildings", status_code=201)
def create_custom_building(request: CustomBuildingRequest):
    """Save a user-created graph for this API session and return its validated model."""
    payload = request.model_dump()
    payload["model_id"] = payload["id"]
    payload["model_status"] = "custom"
    payload["model_description"] = "User-designed evacuation graph"
    payload["campus_location"] = {"id": "custom", "name": "Custom design"}
    try:
        return save_custom_building(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/route")
def calculate_route(request: RouteRequest):
    try:
        selected_building = load_building(request.building_id)
        result = find_route(
            selected_building, request.starting_room,
            algorithm=request.algorithm,
            cost_model=request.cost_model,
            blocked_corridors=set(request.blocked_corridors),
            unavailable_exits=set(request.unavailable_exits),
            unsafe_locations=set(request.unsafe_locations),
        )
        result["building_id"] = selected_building["id"]
        return result
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/route/utility")
def calculate_utility_route(request: UtilityRouteRequest):
    try:
        selected_building = load_building(request.building_id)
        result = choose_utility_route(
            selected_building, request.starting_room,
            accessibility=request.accessibility.model_dump(exclude_unset=True),
            preference_weights=request.preference_weights,
            blocked_corridors=set(request.blocked_corridors),
            unavailable_exits=set(request.unavailable_exits),
            unsafe_locations=set(request.unsafe_locations),
            candidate_limit=request.candidate_limit,
            reference_time_seconds=request.reference_time_seconds,
        )
        result["building_id"] = selected_building["id"]
        return result
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/route/compare")
def compare_route_algorithms(request: RouteComparisonRequest):
    state = _simulation_response(request.simulation_id) if request.simulation_id else None
    if state is not None:
        if request.building_id is not None and request.building_id != state.building_id:
            raise HTTPException(
                status_code=422,
                detail=(f"building_id '{request.building_id}' conflicts with simulation model "
                        f"'{state.building_id}'. Omit building_id to use the simulation's model."),
            )
        building_data = simulation_manager.building_for(state)
    else:
        try:
            building_data = load_building(request.building_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    blocked = set(request.blocked_corridors)
    unavailable = set(request.unavailable_exits)
    unsafe = set(request.unsafe_locations)
    if state is not None:
        engine = simulation_manager.get_engine(state.simulation_id)
        if engine is None:
            raise HTTPException(status_code=404, detail=f"Simulation '{state.simulation_id}' was not found.")
        building_data = engine._routing_snapshot(state)
        conditions = simulation_manager.conditions(state)
        blocked.update(conditions["blocked_corridors"])
        unavailable.update(conditions["unavailable_exits"])
        unsafe.update(conditions["unsafe_nodes"])
    if request.comparison_profile == "slow_north":
        if state is not None:
            raise HTTPException(status_code=422, detail="The teaching example uses a separate snapshot; omit simulation_id.")
        if request.cost_model != "travel_time":
            raise HTTPException(status_code=422, detail="The slow-north example must use the travel_time cost model.")
        building_data = deepcopy(building_data)
        corridor = next((edge for edge in building_data["corridors"] if edge["id"] == "c4"), None)
        if corridor is None:
            raise HTTPException(status_code=422, detail="This teaching example requires corridor c4 in the illustrative model.")
        corridor["travel_time_seconds"] = 180.0
    try:
        comparison = compare_routes(
            building_data, request.starting_room, request.cost_model,
            blocked_corridors=blocked,
            unavailable_exits=unavailable,
            unsafe_locations=unsafe,
            accessibility=request.accessibility.model_dump(exclude_unset=True),
            preference_weights=request.preference_weights,
            candidate_limit=request.candidate_limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    comparison["comparison_profile"] = request.comparison_profile
    comparison["travel_time_definition"] = "Estimated traversal of the selected corridors, not algorithm computation time or total crowd evacuation duration."
    comparison["example_description"] = (
        "Teaching example only: corridor c4 takes 180 seconds. Distance and safety restrictions are unchanged; the source graph and live simulation are not modified."
        if request.comparison_profile == "slow_north" else None
    )
    comparison["simulation_id"] = request.simulation_id
    comparison["building_id"] = building_data.get("id")
    comparison["building_name"] = building_data.get("name")
    comparison["model_status"] = building_data.get("model_status", "unspecified")
    comparison["conditions"] = {
        "blocked_corridors": sorted(blocked),
        "unavailable_exits": sorted(unavailable),
        "unsafe_locations": sorted(unsafe),
    }
    return comparison


@router.get("/scenarios")
def scenarios():
    return {"scenarios": list_scenarios()}


@router.get("/scenarios/{scenario_id}")
def scenario_details(scenario_id: str):
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' was not found.")
    return scenario


@router.post("/scenarios/{scenario_id}/start", status_code=201)
def start_scenario(scenario_id: str, building_id: str | None = None):
    try:
        state = simulation_manager.create_scenario(scenario_id, building_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if state is None:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' was not found.")
    return simulation_manager.serialize(state)


class EvacueeSpec(BaseModel):
    starting_room: str
    accessibility: AccessibilityRequirements = Field(default_factory=AccessibilityRequirements)
    walking_speed_mps: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    reaction_delay_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class SimulationCreateRequest(BaseModel):
    building_id: str | None = None
    number_of_evacuees: int | None = Field(default=None, ge=1, le=200)
    evacuees: list[EvacueeSpec] | None = Field(default=None, min_length=1, max_length=200)
    time_step_seconds: float = Field(default=5.0, ge=0.1, le=60, allow_inf_nan=False)
    # None preserves configured edge travel times (and the historic 1.2 m/s fallback).
    walking_speed_mps: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    reaction_delay_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    congestion_penalty: float = Field(default=1.0, ge=0, le=5, allow_inf_nan=False)
    replan_on_congestion: bool = False
    replan_interval_steps: int = Field(default=3, ge=1, le=100)
    candidate_limit: int = Field(default=12, ge=1, le=50)
    preference_weights: dict[str, float] | None = None
    blocked_corridors: list[str] = Field(default_factory=list)
    unavailable_exits: list[str] = Field(default_factory=list)
    unsafe_locations: list[str] = Field(default_factory=list)


class SimulationStepRequest(BaseModel):
    steps: int = Field(default=1, ge=1, le=100)


class HazardCreateRequest(BaseModel):
    hazard_type: Literal["fire", "flood", "unsafe_area"]
    target_type: Literal["node", "corridor"]
    target_id: str = Field(min_length=1)
    severity: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    active: bool = True
    propagation_enabled: bool = False
    propagation_interval_steps: int = Field(default=1, ge=1, le=100)
    max_spread: int = Field(default=1, ge=1, le=10)




simulation_manager = SimulationManager(load_building(), building_loader=load_building)


def _simulation_response(simulation_id: str):
    state = simulation_manager.get(simulation_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' was not found.")
    return state


def _ensure_simulation_accepts_changes(simulation_id: str):
    state = _simulation_response(simulation_id)
    if state.status == "completed":
        raise HTTPException(status_code=409, detail="A completed simulation cannot accept new hazard or exit changes; reset it first.")
    return state


@router.post("/simulations", status_code=201)
def create_simulation(request: SimulationCreateRequest):
    if (request.number_of_evacuees is None) == (request.evacuees is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of number_of_evacuees or evacuees.",
        )
    try:
        specs = None
        if request.evacuees is not None:
            specs = [
                {
                    "starting_room": person.starting_room,
                    "accessibility": person.accessibility.model_dump(exclude_unset=True),
                    "walking_speed_mps": (
                        person.walking_speed_mps
                        if person.walking_speed_mps is not None
                        else request.walking_speed_mps
                    ),
                    "reaction_delay_seconds": (
                        person.reaction_delay_seconds
                        if person.reaction_delay_seconds is not None
                        else request.reaction_delay_seconds
                    ),
                }
                for person in request.evacuees
            ]
        settings = SimulationSettings(
            time_step_seconds=request.time_step_seconds,
            default_walking_speed_mps=request.walking_speed_mps,
            default_reaction_delay_seconds=request.reaction_delay_seconds,
            congestion_penalty=request.congestion_penalty,
            replan_on_congestion=request.replan_on_congestion,
            replan_interval_steps=request.replan_interval_steps,
            candidate_limit=request.candidate_limit,
            preference_weights=request.preference_weights,
            blocked_corridors=request.blocked_corridors,
            unavailable_exits=request.unavailable_exits,
            unsafe_locations=request.unsafe_locations,
        )
        state = simulation_manager.create(
            number_of_evacuees=request.number_of_evacuees,
            evacuee_specs=specs,
            settings=settings,
            building_id=request.building_id,
        )
        return simulation_manager.serialize(state)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: str):
    state = _simulation_response(simulation_id)
    return simulation_manager.serialize(state)


@router.get("/simulations/{simulation_id}/summary")
def get_simulation_summary(simulation_id: str):
    state = _simulation_response(simulation_id)
    return simulation_manager.summary(state)


@router.get("/simulations/{simulation_id}/events")
def get_simulation_events(simulation_id: str, after_sequence: int = 0, event_type: str | None = None):
    if after_sequence < 0:
        raise HTTPException(status_code=422, detail="after_sequence must be non-negative.")
    state = _simulation_response(simulation_id)
    events = simulation_manager.events(state, after_sequence)
    if event_type:
        events = [event for event in events if event["event_type"] == event_type]
    return {"simulation_id": simulation_id, "events": events}


@router.post("/simulations/{simulation_id}/start")
def start_simulation(simulation_id: str):
    state = simulation_manager.start(simulation_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' was not found.")
    return simulation_manager.serialize(state)


@router.post("/simulations/{simulation_id}/pause")
def pause_simulation(simulation_id: str):
    state = simulation_manager.pause(simulation_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' was not found.")
    return simulation_manager.serialize(state)


@router.post("/simulations/{simulation_id}/step")
def advance_simulation(simulation_id: str, request: SimulationStepRequest):
    try:
        state = simulation_manager.advance(simulation_id, request.steps)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if state is None:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' was not found.")
    return simulation_manager.serialize(state)


@router.post("/simulations/{simulation_id}/reset")
def reset_simulation(simulation_id: str):
    state = simulation_manager.reset(simulation_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' was not found.")
    return simulation_manager.serialize(state)


@router.post("/simulations/{simulation_id}/hazards", status_code=201)
def create_hazard(simulation_id: str, request: HazardCreateRequest):
    _ensure_simulation_accepts_changes(simulation_id)
    try:
        hazard = simulation_manager.add_hazard(
            simulation_id,
            hazard_type=request.hazard_type,
            target_type=request.target_type,
            target_id=request.target_id,
            severity=request.severity,
            propagation_enabled=request.propagation_enabled,
            propagation_interval_steps=request.propagation_interval_steps,
            max_spread=request.max_spread,
            active=request.active,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    state = _simulation_response(simulation_id)
    return {"hazard": hazard.to_dict(), "simulation": simulation_manager.serialize(state)}


@router.get("/simulations/{simulation_id}/hazards")
def list_hazards(simulation_id: str, active_only: bool = False):
    state = _simulation_response(simulation_id)
    hazards = [hazard.to_dict() for hazard in state.hazards if not active_only or hazard.active]
    return {"simulation_id": simulation_id, "hazards": hazards}


@router.post("/simulations/{simulation_id}/hazards/{hazard_id}/activate")
def activate_hazard(simulation_id: str, hazard_id: str):
    _ensure_simulation_accepts_changes(simulation_id)
    try:
        hazard = simulation_manager.set_hazard_active(simulation_id, hazard_id, True)
    except ValueError as error:
        raise HTTPException(status_code=404 if "not found" in str(error) else 422, detail=str(error)) from error
    state = _simulation_response(simulation_id)
    return {"hazard": hazard.to_dict(), "simulation": simulation_manager.serialize(state)}


@router.post("/simulations/{simulation_id}/hazards/{hazard_id}/deactivate")
def deactivate_hazard(simulation_id: str, hazard_id: str):
    _ensure_simulation_accepts_changes(simulation_id)
    try:
        hazard = simulation_manager.set_hazard_active(simulation_id, hazard_id, False)
    except ValueError as error:
        raise HTTPException(status_code=404 if "not found" in str(error) else 422, detail=str(error)) from error
    state = _simulation_response(simulation_id)
    return {"hazard": hazard.to_dict(), "simulation": simulation_manager.serialize(state)}


@router.post("/simulations/{simulation_id}/exits/{exit_id}/unavailable")
def make_exit_unavailable(simulation_id: str, exit_id: str):
    _ensure_simulation_accepts_changes(simulation_id)
    try:
        state = simulation_manager.set_exit_available(simulation_id, exit_id, False)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return simulation_manager.serialize(state)


@router.post("/simulations/{simulation_id}/exits/{exit_id}/restore")
def restore_exit(simulation_id: str, exit_id: str):
    _ensure_simulation_accepts_changes(simulation_id)
    try:
        state = simulation_manager.set_exit_available(simulation_id, exit_id, True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return simulation_manager.serialize(state)


@router.get("/simulations/{simulation_id}/conditions")
def get_simulation_conditions(simulation_id: str):
    state = _simulation_response(simulation_id)
    return {"simulation_id": simulation_id, **simulation_manager.conditions(state)}


@router.get("/simulations/{simulation_id}/report")
def export_simulation_report(simulation_id: str, format: Literal["json", "csv"] = "json"):
    state = _simulation_response(simulation_id)
    report = build_report(simulation_manager.building_for(state), state)
    filename = f"evacuation-report-{simulation_id}.{format}"
    if format == "csv":
        return Response(
            content=build_csv_report(report),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        content=json.dumps(report, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

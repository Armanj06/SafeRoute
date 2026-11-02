"""Utility-based evacuation agent for ranking bounded route candidates."""
from __future__ import annotations

from math import isfinite
from typing import Any

from app.agents.candidate_routes import generate_candidate_routes
from app.algorithms.common import DEFAULT_WALKING_SPEED_METERS_PER_SECOND, failure

DEFAULT_WEIGHTS = {
    "time": 0.35,
    "safety": 0.35,
    "crowd": 0.20,
    "accessibility": 0.10,
}


def validate_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Require the four known, non-negative weights to sum to one."""
    chosen = dict(DEFAULT_WEIGHTS if weights is None else weights)
    if set(chosen) != set(DEFAULT_WEIGHTS):
        raise ValueError("Weights must include exactly: time, safety, crowd, accessibility.")
    for name, value in chosen.items():
        if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise ValueError(f"Weight '{name}' must be a finite non-negative number.")
    if abs(sum(chosen.values()) - 1.0) > 1e-6:
        raise ValueError("Preference weights must sum to 1.0.")
    return {name: float(value) for name, value in chosen.items()}


def _unit_interval(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a number between 0 and 1.") from error
    if not isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"{label} must be a number between 0 and 1.")
    return result


def _congestion(edge: dict[str, Any]) -> float:
    density = _unit_interval(edge.get("crowd_density", 0), "crowd_density")
    capacity = edge.get("capacity")
    occupancy = edge.get("current_occupancy")
    if capacity is None or occupancy is None:
        utilization = 0.0
    else:
        try:
            capacity_value, occupancy_value = float(capacity), float(occupancy)
        except (TypeError, ValueError) as error:
            raise ValueError("Corridor capacity and occupancy must be numeric.") from error
        if not isfinite(capacity_value) or capacity_value <= 0 or not isfinite(occupancy_value) or occupancy_value < 0:
            raise ValueError("Corridor capacity must be positive and occupancy non-negative.")
        utilization = min(1.0, occupancy_value / capacity_value)
    # Use the stronger signal so a density estimate and occupancy ratio are
    # not added together and counted twice.
    return max(density, utilization)


def score_candidate(candidate: dict[str, Any], weights: dict[str, float], reference_time_seconds: float) -> dict[str, Any]:
    edges = candidate["_edges"]
    travel_time = candidate["estimated_travel_time_seconds"]
    time_score = 1.0 / (1.0 + travel_time / reference_time_seconds)
    # Risk values represent estimated/uncertain risk. A confirmed unsafe edge
    # never reaches scoring because graph preparation excludes it.
    safety_score = 1.0
    for edge in edges:
        risk = _unit_interval(edge.get("hazard_risk", 0), "hazard_risk")
        safety_score *= 1.0 - risk

    if edges:
        durations = [
            float(edge.get("travel_time_seconds", float(edge.get("distance", 0)) / DEFAULT_WALKING_SPEED_METERS_PER_SECOND))
            for edge in edges
        ]
        duration_total = sum(durations)
        if duration_total > 0:
            average_congestion = sum(
                duration * _congestion(edge) for duration, edge in zip(durations, edges)
            ) / duration_total
        else:
            average_congestion = sum(_congestion(edge) for edge in edges) / len(edges)
        crowd_score = 1.0 - average_congestion
        accessibility_score = sum(
            1.0 if edge.get("step_free", True) else 0.5 for edge in edges
        ) / len(edges)
    else:
        crowd_score = 1.0
        accessibility_score = 1.0

    factor_scores = {
        "time": time_score,
        "safety": safety_score,
        "crowd": crowd_score,
        "accessibility": accessibility_score,
    }
    utility = sum(weights[name] * factor_scores[name] for name in weights)
    return {"utility_score": utility, "factor_scores": factor_scores}


def choose_utility_route(
    building: dict[str, Any], starting_room: str,
    accessibility: dict[str, Any] | None = None,
    preference_weights: dict[str, float] | None = None,
    blocked_corridors: set[str] | None = None,
    unavailable_exits: set[str] | None = None,
    unsafe_locations: set[str] | None = None,
    candidate_limit: int = 12,
    reference_time_seconds: float = 300.0,
) -> dict[str, Any]:
    """Pick the highest-utility route among a bounded, time-ordered candidate set."""
    weights = validate_weights(preference_weights)
    if not isinstance(candidate_limit, int) or not 1 <= candidate_limit <= 50:
        raise ValueError("candidate_limit must be an integer between 1 and 50.")
    if not isinstance(reference_time_seconds, (int, float)) or not isfinite(reference_time_seconds) or reference_time_seconds <= 0:
        raise ValueError("reference_time_seconds must be a positive finite number.")
    generated = generate_candidate_routes(
        building, starting_room, blocked_corridors, unavailable_exits,
        unsafe_locations, accessibility, candidate_limit,
    )
    if not generated["candidates"]:
        no_route_status = generated["status"] if generated["complete"] else "search_incomplete"
        no_route_message = generated["message"] if generated["complete"] else (
            "Candidate search reached its expansion limit before verifying a feasible route; no route was recommended."
        )
        return {
            **failure(no_route_status, no_route_message, "utility", starting_room, "travel_time"),
            "candidate_count": 0,
            "search_states_expanded": generated["expanded"],
            "candidate_search_complete": generated["complete"],
            "preferences": {"accessibility": accessibility or {}, "weights": weights},
            "factor_scores": None,
            "utility_score": None,
            "explanation": no_route_message,
        }

    scored = []
    for candidate in generated["candidates"]:
        scored.append((score_candidate(candidate, weights, float(reference_time_seconds)), candidate))
    (scores, chosen) = max(scored, key=lambda pair: pair[0]["utility_score"])
    contribution = {
        name: weights[name] * scores["factor_scores"][name] for name in weights
    }
    strongest = sorted((name for name in contribution if weights[name] > 0), key=contribution.get, reverse=True)[:2]
    reasons = ", ".join(name.replace("_", " ") for name in strongest)
    explanation = (
        f"Selected as the highest-utility route among {len(scored)} evaluated candidates; "
        f"its strongest weighted factors were {reasons}."
    )
    if not generated["complete"]:
        explanation += " Candidate search was bounded, so this is best among evaluated candidates, not a global utility optimum."
    return {
        "found": True,
        "status": "found",
        "message": "A feasible evacuation route was selected.",
        "algorithm": "utility",
        "starting_room": starting_room,
        "exit": chosen["route"][-1],
        "route": chosen["route"],
        "corridors": chosen["corridors"],
        "distance": chosen["distance"],
        "estimated_travel_time_seconds": chosen["estimated_travel_time_seconds"],
        "total_cost": chosen["estimated_travel_time_seconds"],
        "cost_model": "travel_time",
        "segments": len(chosen["corridors"]),
        "utility_score": scores["utility_score"],
        "factor_scores": scores["factor_scores"],
        "preferences": {"accessibility": accessibility or {}, "weights": weights},
        "candidate_count": len(scored),
        "search_states_expanded": generated["expanded"],
        "candidate_search_complete": generated["complete"],
        "explanation": explanation,
    }

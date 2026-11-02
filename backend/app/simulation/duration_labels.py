"""Eligibility contract for completed evacuation-duration training labels.

Only a non-empty, fully evacuated, internally consistent terminal run has a
well-defined ``evacuation_duration_seconds`` target. A terminal attempt that
leaves people behind is not a completed evacuation duration.
"""
from __future__ import annotations

from math import isclose, isfinite
from typing import Any

from app.simulation.models import SimulationState


TARGET_NAME = "evacuation_duration_seconds"


def _result(
    eligible: bool,
    reason_code: str,
    target_value_seconds: float | None = None,
) -> dict[str, Any]:
    return {
        "eligible": eligible,
        "reason_code": reason_code,
        "target_name": TARGET_NAME if eligible else None,
        "target_value_seconds": target_value_seconds if eligible else None,
    }


def _valid_time(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and value >= 0
    )


def duration_label_eligibility(state: SimulationState) -> dict[str, Any]:
    """Return whether ``state`` supplies a valid complete-evacuation duration.

    Stable reason codes are ``no_evacuees``, ``simulation_not_terminated``,
    ``inconsistent_completion_metadata``, and ``evacuation_incomplete``.
    The target comes from the existing terminal simulation time and is checked
    against the last successful completion timestamp and per-person durations.
    This function is deterministic and does not mutate the simulation state.
    """
    total = len(state.evacuees)
    if total == 0:
        return _result(False, "no_evacuees")

    summary = state.summary()
    terminated = state.status == "completed"

    # A terminal timestamp on an active/paused run, or a missing terminal
    # timestamp on a completed run, means the stored lifecycle metadata conflicts.
    if (terminated and state.total_simulation_duration_seconds is None) or (
        not terminated and state.total_simulation_duration_seconds is not None
    ):
        return _result(False, "inconsistent_completion_metadata")
    if not terminated:
        return _result(False, "simulation_not_terminated")

    evacuated = sum(person.status == "evacuated" for person in state.evacuees)
    remaining = total - evacuated
    active = sum(
        person.status in {"waiting", "moving", "waiting_exit_service"}
        for person in state.evacuees
    )
    unable = sum(person.status == "unable_to_evacuate" for person in state.evacuees)
    metadata_matches = (
        summary["simulation_terminated"] is True
        and summary["completion_status"] == "completed"
        and summary["total_evacuees"] == total
        and summary["total_evacuated"] == evacuated
        and summary["total_remaining"] == remaining
        and summary["active_remaining"] == active
        and summary["unable_to_evacuate"] == unable
        and summary["evacuation_complete"] is (evacuated == total)
        and summary["outcome"] == ("evacuated" if evacuated == total else "terminated_with_people_remaining")
        and evacuated + unable + active == total
        and active == 0
        and _valid_time(state.current_time_seconds)
        and _valid_time(state.total_simulation_duration_seconds)
        and isclose(
            state.total_simulation_duration_seconds,
            state.current_time_seconds,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    )
    if not metadata_matches:
        return _result(False, "inconsistent_completion_metadata")
    if evacuated != total:
        return _result(False, "evacuation_incomplete")

    target = summary["simulation_termination_time_seconds"]
    last_success = state.last_successful_evacuation_time_seconds
    person_completion_times = [person.time_spent_seconds for person in state.evacuees]
    if (
        not _valid_time(target)
        or not _valid_time(last_success)
        or not all(_valid_time(value) for value in person_completion_times)
        or not isclose(target, state.total_simulation_duration_seconds, rel_tol=1e-9, abs_tol=1e-9)
        or not isclose(target, last_success, rel_tol=1e-9, abs_tol=1e-9)
        or not isclose(target, max(person_completion_times), rel_tol=1e-9, abs_tol=1e-9)
    ):
        return _result(False, "inconsistent_completion_metadata")

    return _result(True, "eligible", float(target))

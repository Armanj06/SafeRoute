# Evaluation results

## Setup and repeatability

**Recorded:** 2026-10-31, local checkout, Python 3.14 environment. Selected graph: `dit-vedanta-illustrative` (11 nodes, 13 corridors; static `c8` blocked). Scenarios: all twelve definitions in `backend/app/simulation/scenarios.py`. No random seeds are required: scenario placements, engine tie-breaking, and movement are deterministic for a fixed source/input.

The algorithm comparison used `POST /api/route/compare` on selected building `dit-vedanta-illustrative`, start `room-101`, distance cost, default conditions, and default utility weights. All strategies received a shared graph/safety snapshot. Ordinary route algorithms report expanded frontier nodes; Utility AI reports candidate path states, which is a different measure. One fresh comparison measurement is shown below. Its millisecond values are recorded facts, not stable benchmark results.

For each scenario, a fresh `SimulationManager` was created, the preset was loaded, the simulation was started, and the existing engine was advanced one tick per loop until terminal state. The harness sampled `corridor_occupancy` after every tick and derived peak count and maximum occupancy/capacity ratio. The harness did not alter application code or simulation behavior. A 300-step guard was used; no scenario reached it. “Time” and evacuation duration are simulated seconds at 5 seconds per step, not wall-clock runtime. The presets include the baseline static blocked corridor `c8`; the no-safe-route scenario additionally blocks `c1` and `c13`.

## Route comparison result

| Algorithm | Found | Exit | Route | Distance | Estimated time | Selected cost | Expanded measure | One measured call |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| BFS | Yes | exit-north | room-101 → junction-a → junction-b → exit-north | 60 m | 50.00 s | 60 m | 6 graph nodes | 0.023375 ms |
| Dijkstra | Yes | exit-north | room-101 → junction-a → junction-b → exit-north | 60 m | 50.00 s | 60 m | 6 graph nodes | 0.019041 ms |
| A* | Yes | exit-north | room-101 → junction-a → junction-b → exit-north | 60 m | 50.00 s | 60 m | 4 graph nodes | 0.033250 ms |
| Utility AI | Yes | exit-north | room-101 → junction-a → junction-b → exit-north | 60 m | 50.00 s | 50 s (time-based) | 16 candidate states | 0.059542 ms |

This sample has the same selected route for all four strategies. A* expanded fewer graph nodes here but its measured call was slower in this single tiny run; that observation illustrates why an 11-node timing sample cannot establish a performance advantage. Utility candidate-state count is not directly comparable to node count.

## Scenario results

| Preset | Initial people | Terminal steps | Evacuated | Unable | Remaining | Completion | Mean successful duration | Replan events | Peak occupancy (single corridor) | Peak utilization |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 8 | 23 | 8 | 0 | 0 | 100% | 91.875 s | 0 | 4 | 22.22% |
| Corridor congestion | 48 | 41 | 48 | 0 | 0 | 100% | 134.0625 s | 3 | 20 | 100% |
| Fire blocks corridor | 4 | 27 | 4 | 0 | 0 | 100% | 116.25 s | 4 | 2 | 11.11% |
| North exit unavailable | 8 | 28 | 8 | 0 | 0 | 100% | 116.875 s | 8 | 4 | 22.22% |
| Step-free evacuation | 4 | 22 | 4 | 0 | 0 | 100% | 91.25 s | 0 | 2 | 11.11% |
| No feasible safe route | 1 | 0 | 0 | 1 | 1 | 0% | N/A | 0 | 0% |
| DITU demo: Vedanta fire (`c4`) | 4 | 27 | 4 | 0 | 0 | 100% | 116.25 s | 4 | 2 | 11.11% |
| DITU demo: blocked corridor (`c4`) | 8 | 28 | 8 | 0 | 0 | 100% | 116.875 s | 0 | 4 | 22.22% |
| DITU demo: exit unavailable (`exit-north`) | 8 | 28 | 8 | 0 | 0 | 100% | 116.875 s | 8 | 4 | 22.22% |
| DITU demo: flood (`c4`) | 4 | 27 | 4 | 0 | 0 | 100% | 116.25 s | 4 | 2 | 11.11% |
| DITU demo: crowd near model exits | 48 | 41 | 48 | 0 | 0 | 100% | 134.0625 s | 3 | 20 | 100% |
| DITU demo: multiple hazards (`c4`, `junction-e`) | 8 | 0 | 0 | 8 | 8 | 0% | N/A | 8 | 0 | 0% |

## Other metrics and availability

| Metric requested | Available source | Result/qualification |
| --- | --- | --- |
| Campus catalog and selected model | `GET /api/campus`, `GET /api/building?building_id=...` | Verified live: five configured campus reference names; one routable illustrative model; model response contains no floor model. |
| Route availability, path and destination | Route results / comparison endpoint | Verified for all three algorithms using the selected `building_id` by live HTTP request; sample result above. Failure status/messages are returned for invalid, unavailable, or unreachable cases. |
| Path distance and estimated travel time | Common route result | Returned for every found route; these are synthetic inputs/fallbacks. |
| Completion and unable-to-evacuate count | Simulation `analytics` / `statistics` | Returned for each run; scenario measurements are shown above. |
| Current congestion and corridor occupancy | Serialized `corridor_load` and analytics | Returned at the current step. Final state is normally empty after completion. |
| Peak occupancy/utilization | Not retained as built-in API aggregate | Derived for this report by sampling each step. It cannot be reproduced from only the final completed-run response. |
| Replanning event count | Simulation analytics/event history | Returned as event count; figures shown above. The fire/exit presets cause initial route invalidation; congestion setting also enables periodic waiting-person replanning. |
| Algorithm execution time | `POST /api/route/compare` `duration_ms` | One local measurement shown. Wall time is noisy on this graph and not a statistically meaningful benchmark. |
| Throughput, realistic human evacuation time, hazard spread accuracy | Not represented/validated | Unavailable; do not infer from model occupancy or time output. |

## Honest interpretation

These values verify that the current implementation can run its presets and exposes the metrics used by the dashboard. The comparison shows expected objective semantics on this one input, but does not prove A* is faster or Utility AI is safer. Ten of twelve scenarios evacuated every modeled person. The baseline no-route scenario had one unable person; the multiple-hazards case had eight unable people at step zero because all safe routes were excluded. The crowd demonstration reached a declared occupancy cap under the model and still completed all 48 modeled evacuees; this is not evidence about a real corridor. Hazard and access scenarios exercise exclusions, but they do not establish physical safety or accessibility compliance. All DITU-labeled scenario graph IDs and people counts are hypothetical.

The application exposes current occupancy, not a stored peak. The report's peak values come from step-by-step sampling and are repeatable with the method above, but a student using only `/report` after the run cannot retrieve the historic maximum without replaying the preset or independently sampling it. Simulation duration is model time; algorithm duration is wall-clock time. Do not compare those quantities.

## Reproduction steps

1. Run the application as documented in [demo-guide.md](demo-guide.md).
2. For shortest-path routes, call `POST /api/route/compare` with `{"building_id":"dit-vedanta-illustrative","starting_room":"room-101","cost_model":"distance"}` or use the dashboard's **Compare all strategies** control.
3. For scenario results, create a fresh preset through `POST /api/scenarios/{scenario_id}/start`, call its `/start` endpoint, then request `/step` with `{"steps":1}` and read `current_step`, `corridor_occupancy`, `analytics`, and event history after each step until `status` is `completed`.
4. At each sampled tick, compute `max(occupancy)` and `max(occupancy/capacity)` over `corridor_load`; collect final summary and replan-event count. The `/api/docs` schema documents the endpoints.
5. Each step moves simulated time by the configured interval; the browser's polling delay changes wall-clock demonstration speed only.

See **START_HERE.md** for the updated launcher, demonstration steps, and verification boundary.

# AI-Based Emergency Evacuation Planning System

A full-stack university mini-project that models a building as a graph and calculates routes from rooms to available exits. The dashboard is DIT University, Dehradun–referenced: official campus location names are configurable, while its single routable Vedanta graph is prominently labeled illustrative and is not an official floor plan or evacuation plan.

## Project structure

- `backend/app/api/` — FastAPI endpoints and request models
- `backend/app/algorithms/` — BFS, Dijkstra, A*, shared costs, and route reconstruction
- `backend/app/data/sample_building.json` — room, junction, exit, coordinate, and corridor graph
- `backend/app/data/campus_catalog.json` — campus source metadata, verified location names, and available graph models
- `backend/app/services/` — sample building loader
- `backend/tests/` — deterministic algorithm and API tests
- `frontend/` — Vite + React dashboard
- `data/` — project-level space for future datasets
- `docs/submission/` — project report, algorithm analysis, evaluation, architecture, demo guide, and viva preparation

University submission material is collected under [`docs/submission/`](docs/submission/). Start with [the project report](docs/submission/project-report.md), [the DIT campus model and provenance](docs/submission/campus-model.md), [the demo guide](docs/submission/demo-guide.md), and [the recorded evaluation](docs/submission/evaluation-results.md).

## DIT University campus reference model

Official public references identify campus locations including Vedanta, Chanakya, Charak, Vastu, and Vishveshwarya. The catalog lists the source and model status for each. Only one routable model currently exists: a Vedanta-referenced illustrative teaching graph that reuses the original sample node/corridor identifiers. Other named locations are reference-only and are not offered as routable buildings. No source reviewed verifies the model's room/corridor connections, floors, exits, stairs, distances, capacities, assembly points, or evacuation paths. See [the campus model and provenance notes](docs/submission/campus-model.md).

`GET /api/campus` returns campus locations and available model choices. `GET /api/building?building_id=dit-vedanta-illustrative` returns the selected graph; `building_id` is also accepted by route and route-comparison requests. Existing requests that omit it continue to use the configured default model. The selector does not invent floor choices: floor selection is disabled while no floor-level graph is configured. Do not interpret the illustrative graph or routes as DIT University-approved or operational guidance.

## Route algorithms

All searches treat corridors as bidirectional edges and skip corridors marked blocked or unsafe, unsafe locations supplied in the request, and unavailable or unsafe exits.

- **BFS** explores by number of corridors and returns a route with the fewest segments. It does not minimize distance or travel time; its reported cost is only the cost of the selected route.
- **Dijkstra** uses a priority queue to find the minimum non-negative total edge cost. Choose distance or estimated travel time as the cost model.
- **A\*** uses the same cost model and a priority queue ordered by `g(n) + h(n)`. It derives an admissible heuristic by multiplying straight-line coordinate distance by the smallest observed edge-cost/coordinate-distance ratio. If coordinates are incomplete, it falls back to `h(n) = 0`, which preserves optimality and behaves like Dijkstra.

Distance costs use corridor `distance` in meters. Travel-time costs use `travel_time_seconds`; the sample graph has estimated values based on 1.2 m/s walking speed. For custom corridors without a time value, the backend applies that same speed assumption. These estimates are illustrative and are not calibrated for occupants, stairs, congestion, or mobility needs.

## Run the application

Backend (Python 3.10+), from the `backend/` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend (Node.js 22.12+) in another terminal, from `frontend/`:

```bash
npm install
npm run dev
```

Open the Vite address, normally http://localhost:5173. The dashboard uses the Vite /api proxy to the backend on port 8000 by default. API documentation is available at http://localhost:8000/docs.

## API example

`POST /api/route` accepts the original `starting_room` field, an optional configured `building_id`, and routing controls:

```json
{
  "starting_room": "room-101",
  "building_id": "dit-vedanta-illustrative",
  "algorithm": "astar",
  "cost_model": "distance",
  "blocked_corridors": [],
  "unavailable_exits": [],
  "unsafe_locations": []
}
```

`algorithm` can be `bfs`, `dijkstra`, or `astar`; it defaults to `bfs` for compatibility. `cost_model` can be `distance` or `travel_time`. Responses include status, selected algorithm, start, exit, ordered nodes and corridors, distance, estimated seconds, total selected cost, and a message. Unsupported algorithms or cost models return HTTP 422 with a readable detail.

## Tests

From the `backend/` directory:

```bash
source .venv/bin/activate
pytest
```

## Current features

- Health and sample building endpoints
- Sample graph with rooms, junctions, two exits, corridor distances, coordinates, estimated travel times, and a blocked corridor
- BFS, Dijkstra, and A* routing with blocked/unsafe corridor and unavailable/unsafe exit handling
- Distance and estimated-time cost models
- Utility-based route ranking with static risk, crowd/capacity, accessibility, and time factors
- React dashboard selectors for BFS, Dijkstra, A*, and the utility agent, with step-free preference and factor breakdown
- In-memory dynamic fire, flood, and unsafe-area hazards with hard route exclusions, exit closures, and automatic utility-agent replanning

## Next development milestones

1. Calibrate hazard, capacity, and travel-time inputs against measured site data.
2. Calibrate simulation capacity and movement times against observed data.
3. Add editable building maps and persistent building/simulation storage.
4. Add authentication, audit logging, and deployment configuration.

## Utility-Based AI Agent

The optional **Utility-Based AI Agent** evaluates several feasible simple routes and selects the highest-scoring one. This differs from BFS, which optimizes corridor count, and Dijkstra/A*, which optimize one edge-cost measure: the utility agent combines several normalized route factors and preferences.

### Safety and accessibility rules

Blocked corridors (`blocked: true` or blocked IDs), confirmed unsafe corridors (`unsafe: true` or unsafe IDs), unsafe nodes, and unavailable exits are removed before route generation. Estimated `hazard_risk` is an uncertain 0–1 score and only affects ranking; it does not mark a route confirmed unsafe. Confirmed unsafe state is a hard exclusion. Accessibility constraints such as `step_free` and `minimum_width_m` are also applied before scoring. A route that violates a requirement can never win due to another factor.

The sample graph includes static illustrative hazard-risk estimates, crowd-density estimates, occupancy/capacity values, step-free flags, and clear widths. Dynamic hazards are separate per-simulation state and never rewrite the source graph.

### Utility formula

The default weights are `time=0.35`, `safety=0.35`, `crowd=0.20`, and `accessibility=0.10`. All four weights must be finite, non-negative, and sum to 1. The dashboard offers balanced, faster, safer, and less-crowded presets; the API accepts custom weights.

`utility = time_weight × time_score + safety_weight × safety_score + crowd_weight × crowd_score + accessibility_weight × accessibility_score`

Each factor is normalized from 0 to 1:

- `time_score = 1 / (1 + route_seconds / reference_time_seconds)` (the reference defaults to 300 seconds).
- `safety_score` is the product of `(1 - hazard_risk)` for the route's corridors.
- Corridor congestion is `max(crowd_density, current_occupancy / capacity)`, capped at 1. `crowd_score` is one minus its route travel-time-weighted average. Taking the maximum avoids counting density and occupancy as separate penalties for the same crowding.
- `accessibility_score` averages 1 for step-free corridors and 0.5 otherwise. Accessibility requirements remain hard constraints regardless of this soft preference score.

### Candidate search and API

`POST /api/route/utility` accepts `starting_room`, optional `accessibility` (`step_free`, `minimum_width_m`), `preference_weights`, `blocked_corridors`, `unavailable_exits`, `unsafe_locations`, `candidate_limit` (1–50, default 12), and `reference_time_seconds` (default 300). Example:

```json
{
  "starting_room": "room-101",
  "accessibility": {"step_free": true},
  "preference_weights": {"time": 0.2, "safety": 0.5, "crowd": 0.2, "accessibility": 0.1},
  "candidate_limit": 12
}
```

The candidate generator explores simple paths in estimated-time order and is capped at 5,000 graph expansions and the requested candidate limit. It then scores the candidates separately and returns the selected route, factor scores, utility, preferences, explanation, candidate count, and whether candidate search completed. If bounded search ends before it verifies a feasible route, it returns `search_incomplete` and recommends no path. If it finds candidates but search is incomplete, the selected route is only the highest utility among evaluated candidates; it is not claimed to be a global utility optimum. The regular `/api/route` endpoint and BFS, Dijkstra, and A* behavior remain available.

The model is a university demonstration, not a certified emergency-planning or dispatch system. Hazard, occupancy, capacity, accessibility, and travel-time values need reliable site-specific measurement before they can support operational decisions.

## Phase 5: analysis and repeatable demonstrations

The dashboard can compare BFS, Dijkstra, A*, and the Utility-Based AI Agent against the same graph, start, selected distance/time cost, and current simulation safety conditions. Each ordinary search reports its expanded graph states and measured algorithm-call duration. Utility AI reports candidate states expanded instead of graph nodes because its bounded candidate-path generator measures different work. Durations are wall-clock measurements for small in-process calls and are useful for demonstrations, not benchmarking.

Simulation analytics come from the selected backend run. Completion is `evacuated / initial_evacuees`; remaining includes everyone who has not evacuated, including those unable to evacuate. Average evacuation duration includes successful evacuees only and is unavailable when nobody has evacuated. High occupancy means a corridor occupancy/capacity ratio of at least 0.75; at-capacity means a ratio of at least 1.0. These congestion values describe modeled movement constraints, not hazards. A terminal simulation with people remaining is reported separately from a successful evacuation.

Twelve deterministic presets are available from the dashboard: six original examples and six DITU-labeled hypothetical demonstrations for a fire, blocked corridor, unavailable exit, flood, crowding, and multiple hazards on the illustrative graph. Each campus scenario names its graph IDs and assumptions; scenario counts and targets are not campus observations. Presets create normal simulation objects with documented initial conditions, so the same stepping engine, hazards, events, analytics, and exports apply. Reset restores the selected preset's initial restrictions and hazards.

`POST /api/route/compare` returns the four strategy results and comparison methodology. It accepts the regular route fields (`starting_room`, `cost_model`, safety/accessibility inputs); an optional `simulation_id` uses that run's current effective conditions and corridor-load snapshot. `GET /api/scenarios` lists presets, `GET /api/scenarios/{scenario_id}` gets one, and `POST /api/scenarios/{scenario_id}/start` creates it. `GET /api/simulations/{id}/report?format=json|csv` exports only that run's settings, analytics, evacuees, hazards, events, and corridor occupancy.

Event history is shown chronologically with filters for steps, hazards, exits, replanning, evacuee outcomes, and termination. The congestion view shows actual occupancy against corridor capacity. JSON and CSV downloads are generated by the backend from the selected run.

### Phase 5 verification

From `backend/`, run `source .venv/bin/activate && pytest -q`. From `frontend/`, run `npm test`, `npm run lint`, and `npm run build`. For manual API exploration, start the backend and visit `/docs`; scenario, comparison, and report endpoints are documented there.

### Frontend section guide

The sidebar navigates to Building Overview, Live Monitoring, Route Planner, Crowd Simulation, Hazard Management, Scenario Testing, and Analytics & Reports. The current run is shared between these sections and its ID is held in session storage for a reload recovery attempt. The frontend uses the centralized API client in `frontend/src/services/api.js`; the actual frontend-to-backend mapping and manual acceptance checklist are in [docs/frontend-integration-audit.md](docs/frontend-integration-audit.md).

Demonstration flow: calculate/compare routes, load a scenario or create a run, start it, inspect live status and events, activate a hazard or close an exit, observe backend replanning and updated conditions, then download a JSON or CSV report for the run. Starting a fresh route after safety changes uses the current simulation exclusions.

### Current limitations

- Simulation and scenario state is in memory and is lost when the backend restarts.
- Presets are deterministic teaching examples, not calibrated building plans; crowd movement is still illustrative.
- Strategy comparison timing is sensitive to machine load and the graph is too small for meaningful performance claims.
- Utility AI uses a bounded candidate search and does not guarantee a global utility optimum.
- Export reports cover one selected run and are not persisted or aggregated across simulations.

## Discrete-time crowd simulation

The **Crowd simulation** section provides an illustrative, deterministic evacuation run. Create a simulation with 1–200 people, start or pause it, advance one tick manually, or reset it. By default, starting rooms are assigned round-robin in building node order. The browser advances a running simulation using one `/step` request per tick; change `VITE_SIMULATION_TICK_MS` in a frontend `.env` file to adjust the display cadence (default 800 ms). The API's simulated time advances by `time_step_seconds` (default 5 seconds), independently of browser wall-clock timing.

Each explicit evacuee may specify `walking_speed_mps` and `reaction_delay_seconds`. `POST /api/simulations` also accepts those fields at the top level as defaults for generated evacuees and for explicit evacuees that omit an override. The speed default is `null`, preserving each corridor's existing `travel_time_seconds` (or its 1.2 m/s fallback); the reaction-delay default is `0` seconds. Speed must be finite and greater than zero; delay must be finite and non-negative. Graph `distance` is in metres, so an explicit speed calculates segment base time as `distance / walking_speed_mps`, then applies the existing congestion multiplier.

Timing is deterministic and quantized to `time_step_seconds`. A positive reaction delay is rounded up to a later step boundary before corridor admission; for example, a 7-second delay with 5-second steps means movement starts at the 10-second boundary. A segment completes at the first step boundary at or after its calculated duration; a 6-second segment with 5-second steps consumes 10 simulated seconds. Zero-delay agents retain the existing behavior of entering at the first step and progressing during that step. Per-person elapsed time includes reaction, queue waiting, and movement. These are simulated estimates, not validated evacuation measurements.

Exits may optionally define `throughput_people_per_second` in a building graph. It is a finite positive service rate (people per second); omission retains immediate evacuation. A configured exit serves one FIFO line in deterministic arrival order, with evacuee ID breaking same-step ties. Service time is `1 / throughput_people_per_second`; fractional service periods progress in fixed simulation steps and completion is reported at the first step boundary at or after service ends. If an exit becomes unavailable, its unfinished queue is canceled and each person is replanned from that exit node; they use another available exit when a route exists, otherwise they become unable to evacuate. No throughput values are configured for the illustrative campus graph. Queue state belongs to the individual simulation run. These controls are illustrative and are not calibrated emergency-response capacities.

For each explicit simulation step, elapsed time advances once for each evacuee who has not yet evacuated, including a temporarily `unable_to_evacuate` person if other people keep the run active and it later recovers. Pausing without stepping does not add time. Hazard and exit-availability changes refresh termination immediately after replanning. A direct engine run with no evacuees is immediately completed at time zero with outcome `no_evacuees`; the API still requires at least one evacuee.

The engine assigns routes with the utility-based route selector. At each tick it admits corridor requests in deterministic FIFO order (longest waiting first, then evacuee ID), subject to each corridor's integer capacity. People move through one corridor segment at a time. When enabled, waiting people reconsider routes every configured number of steps using current simulated corridor load. A person already moving through a corridor is allowed to finish that segment before replanning.

Effective travel time is `base_travel_time × (1 + congestion_penalty × max(static_crowd_density, occupancy / capacity))`. Occupancy is the simulated count inside that corridor, including newly admitted people. It never modifies the loaded building graph; the engine makes a snapshot for route selection. Corridor capacity here means the maximum simultaneous number of people in a corridor, not a measured throughput rate.

### Simulation API

- `POST /api/simulations` creates a run. Pass exactly one of `number_of_evacuees` or `evacuees`; each explicit evacuee has a `starting_room` and optional accessibility requirements. Optional `building_id` selects a catalog model; omission preserves the configured default, and unknown explicit IDs return HTTP 422. The response and report metadata include the selected ID. Each run retains an independent graph/engine copy for routing, hazards, exits, analytics, and exports.
- `GET /api/simulations/{id}` returns the run, evacuees, corridor occupancy/load, statistics, settings, and event history.
- `GET /api/simulations/{id}/summary` returns aggregate counts and duration.
- `GET /api/simulations/{id}/events?after_sequence=0` returns event records after a sequence number.
- `POST /api/simulations/{id}/start`, `/pause`, `/step` (`{"steps": 1}`), and `/reset` control the run. Step accepts 1–100.

`POST /api/scenarios/{scenario_id}/start` also accepts optional `building_id` as a query parameter. Existing presets are tied to graph identifiers; a preset whose start, hazard, blocked corridor, or exit references do not exist in the selected graph is rejected with HTTP 422. `POST /api/route/compare` uses its explicit `building_id` when unassociated with a simulation. With `simulation_id`, it uses the run's bound graph when `building_id` is omitted and rejects an explicitly conflicting ID with HTTP 422.

Simulation state is held in process memory and is cleared when the backend restarts. No database, live sensor feed, or operational dispatch integration is included. The sample graph's risk, crowd, capacity, and time values are demonstration inputs; validate with measured site data before drawing real-world conclusions.

### Simulation milestones

1. Add persistent run storage and user-selectable evacuee placement.
2. Calibrate corridor capacity and movement times with site observations.
3. Add mobility-aware movement profiles and richer visualization.
4. Evaluate plans against measured or independently validated scenarios.

## Dynamic hazards and automatic replanning

Hazards are explicit simulation records, separate from the original building graph. Supported types are `fire`, `flood`, and `unsafe_area`; each record stores a unique ID, node/corridor target, severity from 0 to 1, active state, creation step, and optional connected-spread settings. An active hazard is a **hard safety exclusion** regardless of severity: targeted corridors are blocked and targeted nodes are unsafe. An incident on an exit also makes that exit unavailable.

Effective conditions are recomputed from static graph flags, simulation-level restrictions, manual exit closures, and all active hazard targets. Resolving one hazard only removes its own contribution. Static blocks, other active hazards, and manual closures remain in force. The source graph is never rewritten.

When conditions change, the simulation scans evacuees whose remaining route uses a newly unsafe corridor/node or unavailable exit. Waiting evacuees are replanned immediately with the Utility-Based AI Agent. If no alternative exists, the evacuee is marked `unable_to_evacuate` and the old route is cleared. A moving evacuee whose current segment remains safe finishes that segment, then replans at its endpoint. If the current corridor or immediate destination becomes unsafe, movement stops and the person is marked stranded in place; their node position is unchanged and corridor occupancy remains held. The model never teleports them through a hazard.

Optional propagation is disabled by default. When enabled per hazard, each propagation step reaches only adjacent graph targets (a node spreads to connected corridors; a corridor spreads to its endpoint nodes), at the configured step interval and up to `max_spread` layers. It is deterministic and illustrative, not a validated fire, smoke, or flood dynamics model.

### Hazard API

Create an incident during a non-completed simulation:

```http
POST /api/simulations/{simulation_id}/hazards
Content-Type: application/json

{
  "hazard_type": "fire",
  "target_type": "corridor",
  "target_id": "c3",
  "severity": 0.8,
  "propagation_enabled": false
}
```

- `GET /api/simulations/{id}/hazards?active_only=true` lists active incidents; omit the flag for active and resolved history.
- `POST /api/simulations/{id}/hazards/{hazard_id}/activate` and `/deactivate` change a stored incident and immediately recompute/replan.
- `POST /api/simulations/{id}/exits/{exit_id}/unavailable` and `/restore` close or reopen a manual exit restriction. An active hazard on that exit remains authoritative.
- `GET /api/simulations/{id}/conditions` returns effective blocked corridors, unsafe nodes, and unavailable exits.
- `GET /api/simulations/{id}/events?after_sequence=0&event_type=route_replanned` filters history to a chosen hazard or route event.

The Crowd Simulation panel lets users select an incident type and graph target, set severity, optionally enable propagation, resolve incidents, and close/restore exits. The map labels blocked routes, hazards, and unavailable exits; route overlays and the cumulative “Routes recalculated” count come from backend simulation state.

## Offline synthetic dataset generation

An offline generator runs the existing deterministic engine directly; FastAPI does not need to be started. From `backend/`:

```bash
source .venv/bin/activate
python -m scripts.generate_simulation_dataset --limit 12 --output ../data/synthetic/saferoute_duration_sample.jsonl
```

The default matrix has 36 unique configurations. `--limit N` runs the first N rows in stable matrix order. `--building-id` selects a configured graph, and `--overwrite` is required to replace an existing output. If graph loading, input validation, or a run fails, generation stops with a diagnostic and does not commit a partial output file.

Each JSONL line is one record with `metadata`, `inputs`, and `outcomes`. The preserved sample artifact uses schema `1.0`; current generator output uses schema `1.1` and adds the starting-room distribution plus per-evacuee final outcomes (described below). Metadata carries a run ID, stable scenario/configuration IDs, graph-content SHA-256, simulator/schema versions, scenario family, terminal outcome, and duration-label eligibility. Inputs capture graph-relative structure, corridor capacities, exit throughput settings, restrictions, simulation settings with their source (`scenario_configuration` or `simulator_default`), and per-evacuee starting location, effective speed mode, reaction delay, and accessibility. Outcomes contain the engine's final `summary` and the result from `app.simulation.duration_labels.duration_label_eligibility`.

The configuration SHA-256 is computed from canonical JSON of the resolved pre-run `inputs` only (sorted keys, compact encoding, and no non-finite values). It excludes run IDs, timestamps, outcomes, and target values; identical input records therefore have the same hash and are deduplicated before simulation. The run ID distinguishes an execution and is not part of the configuration identity.

The duration target is eligible only for a non-empty terminal run in which every evacuee has evacuated and the summary, terminal time, latest successful completion timestamp, and individual completion times agree. Empty, nonterminal, and partial runs do not receive a duration target; incomplete terminal runs are retained as outcomes, not relabeled as successful durations. Invalid configurations and interrupted/nonterminating runs trigger the documented fail-fast policy and do not produce a dataset file.

The current matrix varies 1 or 8 evacuees (round-robin placement), plus 8 evacuees concentrated in the first room; the one-person concentrated case is omitted because it resolves to the same input as one-person round-robin. Other dimensions are graph travel-time mode or a synthetic 1.0 m/s default, 0 or 5 seconds of reaction delay, and baseline, one-exit-unavailable, or first-room-corridor-blocked conditions. These are experiment-design values, not measured occupant behavior. The selected illustrative graph has no exit-throughput values, so the generator records its existing immediate-exit default rather than inventing capacities. Graph hashes and features are from the selected graph; the DITU-referenced graph remains explicitly illustrative, not verified campus geometry. This JSONL is synthetic simulator output, not real-world evacuation evidence.

The console summary reports generated configurations, exact duplicates skipped, successful and incomplete outcomes, failed runs, eligible labels, coverage, and output location. The verified 12-row command above produced 12 configurations, 0 duplicates, 8 complete-success runs, 4 incomplete runs, 0 failed runs, 8 eligible labels, and 66.7% label coverage; the JSONL is saved at `data/synthetic/saferoute_duration_sample.jsonl`. This is a result from the illustrative simulator, not an empirical evacuation finding. Exact duplicates are removed because repeating a deterministic configuration does not create an independent training example. No model is trained by this tool.

### Dataset quality validation

New generator output uses JSONL schema `1.1`. It includes the resolved starting-room distribution and each evacuee's final status, time spent, current node, assigned exit, and unable-to-evacuate reason. The existing 12-row sample remains schema `1.0` to preserve the original artifact; the validator supports both versions and warns that the older schema has no per-agent final states to cross-check.

Generate the complete default matrix to a new file and validate either dataset from `backend/`:

```bash
python -m scripts.generate_simulation_dataset --output ../data/synthetic/saferoute_duration_full.jsonl
python -m scripts.validate_simulation_dataset ../data/synthetic/saferoute_duration_sample.jsonl
python -m scripts.validate_simulation_dataset ../data/synthetic/saferoute_duration_full.jsonl
```

The generation command above creates the checked-in full output once; if that file already exists, choose another output filename or pass `--overwrite` deliberately.

The validator is read-only. It checks JSONL structure, supported schema versions, unique run/configuration IDs, canonical configuration hashes, model identity, summary arithmetic, per-agent counts and completion times where available, duration-label eligibility and consistency, and finite non-negative numeric values. It reports feature variation and eligible-duration distributions; a nonzero exit status indicates integrity errors. Re-running generation uses the existing no-overwrite protection unless `--overwrite` is explicitly supplied. The full default matrix was recorded at `data/synthetic/saferoute_duration_full.jsonl` (36 configurations, 24 complete successes, 12 incomplete outcomes, 24 eligible duration labels, 66.7% coverage); these are deterministic outputs of one illustrative graph and are not training-quality empirical evidence.

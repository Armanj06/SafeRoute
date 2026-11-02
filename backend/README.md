# Backend

FastAPI provides `GET /api/campus`, a validated campus/model catalog, the selected building graph, BFS/Dijkstra/A* route endpoints, and `POST /api/route/utility` for bounded utility-based route selection. The only campus-labeled graph is explicitly illustrative and does not represent a verified DIT University floor plan. From `backend/`, activate `.venv` and run `uvicorn app.main:app --reload`. Interactive API documentation is available at `/docs`.

Run the complete suite with `pytest` from this directory.

## Crowd simulation

The deterministic discrete-time engine lives in `app/simulation/`. It assigns each evacuee a utility-selected route, arbitrates corridor entry by waiting time and stable ID, limits concurrent corridor occupancy by capacity, and can replan waiting evacuees at a configured interval. Effective travel time uses `base_time * (1 + congestion_penalty * max(static_crowd_density, occupancy / capacity))`. The original building graph is not mutated.

`POST /api/simulations` accepts optional `walking_speed_mps` and `reaction_delay_seconds` defaults; explicit evacuee records may override them. The speed default is `null`, preserving edge `travel_time_seconds` and the historic 1.2 m/s fallback; reaction delay defaults to zero. Distance is in metres. Explicit speed must be finite and positive, and delay finite and non-negative. Reaction countdown and corridor traversal are rounded up to simulation-step boundaries. Per-person elapsed time includes reaction, waiting, and movement; these remain illustrative simulated estimates, not real evacuation measurements.

An exit node may optionally define `throughput_people_per_second` (finite positive people per second). Omitting it preserves the existing immediate-exit behavior. Configured exits have one per-run FIFO queue ordered by arrival step and then evacuee ID. Service duration is the reciprocal rate; fractional service time is quantized to simulation-step boundaries. If an exit becomes unavailable, unfinished service is canceled and queued people are replanned from that exit; no alternative marks them unable to evacuate. No throughput values are configured for the illustrative campus model. JSON and CSV reports include queue state and exit throughput. These synthetic controls are not validated exit-capacity measurements.

Elapsed time advances once per simulation step for every evacuee who has not evacuated, including temporarily unable evacuees while the run remains active. A pause without a step does not advance time. External hazard and exit-availability mutations refresh lifecycle status immediately after replanning. A direct engine run with no evacuees completes at time zero with outcome `no_evacuees`; the HTTP API continues to require at least one person.

The API supports `POST /api/simulations`, `GET /api/simulations/{id}`, `/summary`, and `/events`, plus `POST` controls at `/start`, `/pause`, `/step`, and `/reset`. A simulation accepts optional `building_id`; omission uses the catalog default, while an unknown explicit ID returns HTTP 422. The selected ID and an isolated graph/engine copy remain bound to the run through simulation controls, hazards, exits, analytics, and reports. Runs are stored in process memory and reset when the server restarts. From this directory, run `source .venv/bin/activate && pytest` for algorithm, API, and simulation coverage.

## Phase 5 comparison, scenarios, metrics, and reports

`POST /api/route/compare` runs BFS, Dijkstra, A*, and the utility agent on the same inputs. Ordinary route algorithms report counted expanded graph states and measured call duration. The utility agent reports candidate-search states instead, since it uses a bounded candidate generator. Optional `simulation_id` applies that simulation's bound graph, effective blocked/unsafe/unavailable conditions, and current corridor occupancy snapshot. Omit `building_id` to inherit the simulation graph; if supplied, it must match the simulation's `building_id` or the request receives HTTP 422. Without `simulation_id`, comparison uses the explicit model or catalog default.

`GET /api/scenarios` lists twelve deterministic presets: six generic graph examples and six hypothetical Vedanta-model demonstrations. Start one with `POST /api/scenarios/{scenario_id}/start?building_id=...`; omission uses the default model. Graph-specific preset references are validated against the selected graph and incompatible scenarios return HTTP 422 rather than silently ignoring restrictions. Reset reapplies its initial restrictions and hazards.

Synthetic test graphs with distinct node, corridor, and exit IDs verify graph binding and isolation. They are test fixtures only and are not listed in the production campus catalog.

Simulation serialization and `GET /api/simulations/{id}/summary` include derived analytics. Completion percentage is evacuated people divided by initial people; remaining includes unable-to-evacuate people. Average duration uses successful evacuees only. High occupancy is utilization >= 0.75, while at capacity is >= 1.0. Termination with evacuees remaining is reported distinctly from successful completion. Congestion is not a hazard status.

`GET /api/simulations/{id}/report?format=json` returns the selected run's settings, metrics, evacuees, hazards, events, and corridor utilization. Use `format=csv` for a flat table with summary, evacuee, hazard, event, and corridor records. Both formats are generated from a single in-memory run.

## Dynamic hazards

The simulation state stores explicit fire, flood, and unsafe-area incidents. Effective conditions are derived on demand from static graph blocks, configured restrictions, manual exit availability, and every active hazard, so resolving an incident never overrides an independent restriction or mutates the original building graph. Hazard corridors and nodes are hard route exclusions regardless of severity. Affected waiting evacuees are immediately replanned by the utility agent; a moving person finishes a safe segment before replanning. A person in a newly unsafe current corridor or headed into an unsafe endpoint is stopped and marked stranded in place with their corridor occupancy retained.

Create an incident with `POST /api/simulations/{id}/hazards` using `hazard_type` (`fire`, `flood`, `unsafe_area`), `target_type` (`node` or `corridor`), `target_id`, severity 0–1, and optional `propagation_enabled`, `propagation_interval_steps`, and `max_spread`. List hazards with `GET /api/simulations/{id}/hazards`; add `?active_only=true` for active ones. Activate/deactivate using the hazard-specific control endpoints. Manual exit closure/restoration uses `/exits/{exit_id}/unavailable` and `/restore`. `GET /conditions` returns effective constraints. Event history supports `event_type` filters such as `hazard_propagated` or `route_replanned`.

Propagation is off by default. Enabled incidents expand deterministically through adjacent graph connections for a bounded number of layers; this is an illustrative connectivity rule, not a scientifically validated fire, smoke, or flood model. Resolved hazards remain in history but no longer contribute effective conditions. Reset clears hazards and manual exit overrides.

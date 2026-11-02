# SafeRoute: AI-Based Emergency Evacuation Planning System

## Abstract

SafeRoute is an academic, full-stack prototype for exploring evacuation route planning in a small graph referenced to DIT University, Dehradun. A React dashboard communicates with a FastAPI service that calculates routes with breadth-first search (BFS), Dijkstra's algorithm, A* search, and a bounded utility-based route selector. The backend also includes a deterministic, discrete-time crowd simulation, illustrative hazard records, route replanning, scenario presets, and per-run JSON/CSV reports. Public references support selected campus names and high-level functions only; the routable graph and its measurements are synthetic. The software is for teaching and demonstration; it is not a certified or university-endorsed emergency-response system.

## Introduction and problem statement

An evacuation planner must find a usable path from an occupied room to an exit while accounting for corridor distance, estimated movement time, closures, hazards, and, in a simulation, shared capacity. A route with the fewest corridor segments is not necessarily the shortest or fastest route. Dynamic conditions can invalidate a route after assignment. SafeRoute makes these differences visible using graph-search algorithms and a simple movement model.

The project problem is: given a building graph, starting room, available exits, and safety restrictions, return a feasible route and explain its cost; for a simulated group, model movement through limited-capacity corridors and report outcomes.

## Objectives and scope

- Represent rooms, junctions, exits, and corridors as a graph.
- Return an ordered route to an available exit while excluding blocked/unsafe corridors and nodes.
- Demonstrate unweighted search, weighted shortest-path search, heuristic search, and multi-factor utility ranking.
- Model group movement in fixed time steps, corridor capacity, hazards, and selected replanning behavior.
- Provide deterministic presets, API-generated metrics, and exports for repeatable classroom demonstrations.

The scope is a local university mini-project prototype. It has no live sensors, map editor, authentication, database, dispatch integration, or validated physical movement/hazard model.

## System requirements

- Python 3.10 or later and pip for the FastAPI backend.
- Node.js 20 or later and npm for the Vite frontend.
- A browser and two local development ports, normally 8000 and 5173.
- Python packages are listed in `backend/requirements.txt`; JavaScript dependencies are declared in `frontend/package.json` and its lock file.

Compatibility was verified in this checkout with Python 3.14 and the installed Node/npm toolchain. See [demo-guide.md](demo-guide.md) for setup commands.

## Architecture

The React UI loads building/scenario data and calls typed-by-convention JSON endpoints through a centralized fetch wrapper. FastAPI validates request shapes, dispatches routing to algorithm modules, and delegates simulation state changes to an in-memory manager and engine. The same process exposes run summaries, event history, and JSON/CSV exports. See [architecture.md](architecture.md) for the component diagram and [docs/frontend-integration-audit.md](../frontend-integration-audit.md) for the route-to-UI mapping.

## Graph representation

The source graph is `backend/app/data/sample_building.json`, selected by `backend/app/data/campus_catalog.json` as the sole routable model, `dit-vedanta-illustrative`. It contains 11 nodes (four rooms, five junctions, and two hypothetical exits) and 13 undirected corridors. Each corridor has an ID, endpoint IDs, distance, estimated travel time, and illustrative utility/simulation attributes such as risk, crowd density, occupancy, capacity, and step-free access. Corridor `c8` is statically marked blocked. `prepare_graph` builds an adjacency list for each route request, excludes blocked or unsafe corridors and unsafe endpoint nodes, and identifies usable exits. Additional node types for areas, staircases, and assembly points are supported by validation and map presentation, but none has been added to the current graph because its layout is unverified.

Campus names, source links, and available model status are kept in a JSON catalog, not scattered through React. Vedanta's public name and broad facility listings are referenced from official public material; all interior connections, floors, exits, stairs, assembly points, graph distances, occupancy, and evacuation routes in the model remain illustrative. Other configured locations are reference-only and have no routable graph. Details and sources are in [campus-model.md](campus-model.md).

The route response includes the ordered node path, corridor IDs, exit, distance, estimated travel time, selected total cost and cost model. Distance is in metres; travel time uses the corridor's `travel_time_seconds`, falling back to distance divided by 1.2 m/s when no time estimate is present. These values are illustrative estimates, not site measurements.

## Algorithm design

The algorithms operate on the same filtered graph and can target any usable exit. Detailed implementation-level complexity, cost semantics, and caveats are in [algorithm-analysis.md](algorithm-analysis.md).

- **BFS** uses a FIFO queue and minimizes corridor count. It reports the distance/time of that chosen path but does not minimize either weighted quantity.
- **Dijkstra** uses a min-priority queue and minimizes the selected non-negative edge-cost sum: distance or estimated travel time.
- **A\*** orders the frontier by `f(n) = g(n) + h(n)`. It scales Euclidean distance by a conservative lower bound derived from usable corridor costs and coordinate lengths. Missing coordinates disable the heuristic (`h = 0`), retaining Dijkstra-like optimality.
- **Utility AI** generates a bounded set of simple routes ordered by estimated time and ranks them using time, estimated safety, congestion, and accessibility. Accessibility requirements and confirmed unsafe conditions are hard feasibility filters; estimated risk is a soft preference. The chosen route is best only among evaluated candidates, not necessarily a global utility optimum.

All route searches exclude static/dynamic blocked or unsafe corridors, unsafe locations, and unavailable/unsafe exits. The simulation uses the utility agent for initial assignments and replanning; it does not let the user choose BFS/Dijkstra/A* as the simulator's internal assignment policy.

## Utility function and safety constraints

The default weights are time 0.35, safety 0.35, crowd 0.20, and accessibility 0.10. Weights must be finite, non-negative, and sum to one. The route score is a weighted sum of normalized factor scores: time decreases with estimated route duration; safety is the product of `(1 - hazard_risk)` across corridors; crowd is one minus the travel-time-weighted mean of the stronger of static crowd density and simulated occupancy/capacity; accessibility averages a step-free score of 1 or non-step-free score of 0.5. A required step-free route or minimum corridor width is enforced before scoring.

Confirmed blocked/unsafe edges, unsafe nodes, unavailable exits, and unmet accessibility requirements are hard exclusions. The hazard `severity` field is recorded but every active hazard target currently acts as a hard exclusion regardless of severity. The model does not compute probabilistic risk or infer safety from a severity threshold.

## Crowd simulation

The engine assigns utility-selected routes, then advances the run in fixed time steps. People request corridor entry in deterministic order (waiting duration, then person ID); the configured corridor capacity limits simultaneous occupancy. People move one segment at a time. Optional per-agent `walking_speed_mps` uses graph distance in metres divided by metres per second; if omitted, existing corridor `travel_time_seconds` values remain in effect, with a 1.2 m/s fallback when a corridor has no estimate. Optional `reaction_delay_seconds` defaults to zero. Positive reaction delays and segment traversal both round up to simulation-step boundaries. Congestion-adjusted segment duration is based on base travel time multiplied by `1 + congestion_penalty × max(static crowd density, occupancy/capacity)`. Occupancy is a concurrency limit, not a measured throughput rate. Optional congestion replanning affects waiting occupants at the configured interval. Moving people finish a safe segment before replanning. These are simulated estimates and are not validated real-world evacuation measurements.

An exit node can optionally specify `throughput_people_per_second`; exits without it retain immediate completion. Configured exits process a per-simulation FIFO queue ordered by arrival step then evacuee ID. Service duration is the reciprocal of the rate and is quantized to simulation-step boundaries. If an exit closes, unfinished service is canceled and those people are replanned from the exit; no valid alternative marks them unable to evacuate. The campus fixture has no configured throughput values, and synthetic values must not be interpreted as measured DIT University capacities.

The simulation records evacuated, remaining, active, unable-to-evacuate, and waiting-for-exit-service counts; completion percentage; successful evacuees' mean modeled duration; last successful evacuation time; simulation termination time; route-replanning event count; current corridor loads; and high/at-capacity corridor counts. JSON and CSV reports include exit throughput and queue state. The dashboard and API analytics report **current** occupancy at the observation point. Peak occupancy is not a persistent API metric, although it can be calculated by sampling each returned step during an experiment (as done for the results in this report).

## Dynamic hazard handling

Fire, flood, and unsafe-area incidents can target a node or corridor. Active targets contribute hard exclusions; an incident on an exit makes that exit unavailable. Conditions combine static flags, simulation settings, manual exit closures, and all active hazard targets without changing the original graph. Affected waiting evacuees are replanned; a moving evacuee finishes a safe segment then replans. If the current segment or immediate destination becomes unsafe, the simulation stops that evacuee in place and retains corridor occupancy. Optional propagation follows adjacent graph connectivity with a configured interval and bounded number of layers. It is illustrative connectivity propagation, not a physical fire/smoke/flood simulation.

## API and frontend integration

The frontend's `src/services/api.js` wrapper defaults to `http://localhost:8000` and can be configured with `VITE_API_URL`. Core operations include `GET /api/health`, `GET /api/campus`, `GET /api/building?building_id=...`, `POST /api/route`, and `POST /api/route/utility`. The selected model ID is sent with route requests and returned in route/comparison/report metadata. `POST /api/route/compare` runs BFS, Dijkstra, A*, and Utility AI against the same graph/safety inputs and reports search counters plus call durations. Simulation and scenario endpoints create/control runs, change hazard/exit conditions, retrieve analytics/events, and export one run as JSON or CSV. FastAPI's interactive schema is available at `/docs`.

The dashboard lets a presenter select a room, algorithm, and (for shortest-path search) cost model, calculate and highlight a route, and compare strategies. Other sections control scenarios/simulations, hazards/exits, event filters, and report downloads. The UI uses returned API values for these operations; the schematic floor-plan coordinates and fixture metrics themselves are authored in the sample JSON.

## Experimental methodology

The results in [evaluation-results.md](evaluation-results.md) were collected on 2026-10-31 from the checked-out source. The route experiment compared all four route strategies on the same start, graph, default restrictions, distance cost, and default utility weights. The scenario experiment instantiated each of the twelve presets (six general and six DIT-labeled illustrative scenarios) with a fresh `SimulationManager`, started it, advanced one simulation tick at a time until terminal state, and sampled corridor occupancy after each tick to calculate observed peak occupancy/utilization. Simulation time is modeled time, not wall-clock time. Campus labels identify the demonstration model only; no real DIT floor geometry or emergency route has been verified.

The small graph is useful for a repeatable classroom demonstration but too small to infer scalability. Per-call algorithm timings are measurements, not theoretical complexity results, and are sensitive to timer resolution, interpreter/runtime state, hardware, and system load.

## Results (verified)

On the baseline start `room-101`, all three shortest-path searches returned `room-101 → junction-a → junction-b → exit-north`, 60 m and 50 estimated seconds. BFS/Dijkstra expanded six states; A* expanded four on this coordinate fixture. The route-comparison endpoint also returned a utility-selected path and its candidate-state counter. See the timestamped table and methodology in [evaluation-results.md](evaluation-results.md); one timing sample is explicitly not a performance claim.

Ten of twelve presets evacuated all configured people in this local measurement. `no-safe-route` ended with one person unable to evacuate, and `ditu-vedanta-multiple-hazards` ended with eight unable to evacuate at step zero. The blocked-corridor scenario (`c4`) and unavailable-exit scenario both completed via the other modeled path. The crowd preset sampled a peak of 20 people (100% of the illustrative corridor capacity) and recorded three replanning events. These are outcomes of synthetic graph inputs, not campus safety findings. Peak values were calculated by sampling each step; the normal API exposes current occupancy, not a peak field.

## Limitations

- The graph is a small schematic; coordinate geometry, corridor dimensions, capacity, crowd density, hazard risk, and travel time are illustrative, not validated against a real building.
- The software is an academic prototype, not a certified emergency-response, life-safety, or dispatch system. It must not be used as the sole basis for real evacuation decisions.
- Simulation and scenario state live in process memory and disappear when the backend restarts. Browser session storage can remember an ID but cannot restore a lost backend run.
- Movement is deterministic and segment-based; no realistic human behavior, mobility population distribution, smoke dynamics, panic, visibility, stair/lift behavior, or sensor assimilation is modeled.
- A* coordinates are treated as Euclidean coordinate units. The admissible scale is derived from graph edge ratios, but this guarantee presumes the supplied coordinates/edge costs describe a consistent geometric lower bound; it is not a certification of real travel time.
- Utility route candidate search is bounded (up to 5,000 path-state expansions and at most 50 requested candidates); it can miss a higher-utility path outside the evaluated set.
- Route comparison durations are noisy at this graph size. Utility's candidate-state count is not directly comparable to graph-node expansions.
- API's health/readiness response is a simple process health check; it does not validate the graph or a physical emergency plan.
- Existing README statements about the UI or endpoint mapping should be cross-checked against [docs/frontend-integration-audit.md](../frontend-integration-audit.md) when interface behavior changes. The audit is an implementation checklist, not evidence that every browser/device combination has been tested.

## Future improvements

1. Validate graph geometry, corridor costs, accessible routes, capacities, and hazard assumptions with qualified site data.
2. Add persistent scenario/run storage and versioned building plans.
3. Add broader deterministic benchmark graphs and repeated timing trials with a documented measurement harness.
4. Improve simulation calibration and model throughput, mobility needs, and uncertainty.
5. Add authentication, authorization, audit logging, deployment configuration, and operational safety review before any non-academic use.
6. Add visual/editable building imports and independently review heuristic and safety assumptions.

## Conclusion

SafeRoute provides a working demonstration of graph-based evacuation planning and a connected frontend/backend simulation workflow. Its value for a university demonstration is that it makes objective differences, safety exclusions, route changes, and modeled group outcomes inspectable. Its synthetic inputs and simplified behavior limit conclusions to software demonstration and algorithm education; meaningful operational claims require qualified validation and measured site data.

# Frontend

Vite + React dashboard for route selection using BFS, Dijkstra, A*, or the Utility-Based AI Agent. It reads the campus/model catalog, selected graph, and route results from FastAPI and highlights the selected API route. The current Vedanta-referenced model is illustrative; the other campus names are reference-only and cannot be routed.

Run `npm install` and `npm run dev` from this directory. The API defaults to `http://localhost:8000`; copy `.env.example` to `.env.local` and set `VITE_API_URL` when the backend uses another address.

The dashboard also includes an illustrative crowd simulation section with create/start/pause/step/reset controls, evacuee counts, recent events, and corridor occupancy/capacity indicators. It advances running simulations by polling the backend step endpoint. Configure `VITE_API_URL` for a non-default API address and `VITE_SIMULATION_TICK_MS` for the browser's tick request interval (default `800`).

Sidebar buttons scroll to Building Overview, Live Monitoring, Route Planner, Crowd Simulation, Hazard Management, Scenario Testing, and Analytics & Reports. The active marker follows the selected navigation item. The current simulation ID is kept in browser session storage and reloaded from the API on refresh; the backend's in-memory run can disappear when its process restarts.

The Crowd Simulation panel also supports manually activating and resolving fire, flood, and unsafe-area hazards on graph nodes or corridors, optional illustrative propagation, and manual exit closure/restoration. Active hazards appear with a labeled marker; unsafe corridors and unavailable exits are marked in addition to their color. Route changes and the recalculation count are read from the API simulation state.

The route planner includes BFS, Dijkstra, A*, and the Utility-Based AI Agent. BFS minimizes corridor count; Dijkstra and A* optimize distance or estimated travel time, while A* uses a safe coordinate heuristic when available. **Compare all strategies** displays API-returned routes, exits, costs, explored-state counts, and measured search time. A comparison can use current simulation conditions.

The simulation dashboard includes backend-defined repeatable scenarios, run-derived completion and duration analytics, occupancy/capacity visualization, a chronological event timeline with filters, and JSON/CSV report downloads. Congestion labels describe modeled occupancy; they do not mark a corridor unsafe. Terminated runs with people remaining are distinct from successful evacuation.

Configure `VITE_API_URL` in a `.env` file if FastAPI is not at `http://localhost:8000`. Run `npm run build` to verify the production bundle.

Run the frontend API-service tests with `npm test` and lint the source with `npm run lint`.

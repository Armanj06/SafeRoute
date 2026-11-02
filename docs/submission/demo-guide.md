# SafeRoute demonstration guide

## Before the demonstration

Requirements: Python 3.10+, pip, Node.js 20+, and npm. Open two terminals in the project root, then start the backend and frontend separately. Run commands from the stated directories.

### Backend terminal

```bash
cd AI-Evacuation-System/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Windows PowerShell activation is `.venv\Scripts\Activate.ps1`. Keep this terminal running. Open `http://localhost:8000/api/health` (expect `{"status":"ok", ...}`), `http://localhost:8000/api/building`, or `http://localhost:8000/docs`.

### Frontend terminal

```bash
cd AI-Evacuation-System/frontend
npm install
npm run dev
```

Open the Vite URL printed by the command, normally `http://localhost:5173`. The API client defaults to `http://localhost:8000`; configure `VITE_API_URL` in a local `.env` if the API uses a different host. Restart Vite after changing env values. The backend CORS allow-list currently includes localhost and 127.0.0.1 on port 5173; changing the frontend port/host may require updating `backend/app/main.py`.

## Recommended demonstration order (8–12 minutes)

1. **Campus model:** explain that DIT University names are sourced from public official material, while the only selectable building graph is a hypothetical, illustrative model labeled Vedanta. No floor is available; the map is a schematic, not a verified floor plan. Point out the four modeled start areas, junctions, exits, and statically blocked `c8` corridor.
2. **Objective differences:** use `room-101`. Choose BFS and calculate; then choose Dijkstra and A* using distance. Compare all strategies. Explain that BFS minimizes corridor segments, while Dijkstra/A* minimize the selected edge cost. Route-comparison search counts and milliseconds are returned by the backend; timing on this small fixture is noisy.
3. **Cost model:** switch the shortest-path cost model to estimated travel time and recalculate. Explain that corridor times are configured estimates/fallbacks, not live walking measurements.
4. **Step-free constraint:** select the Utility-Based AI Agent and require step-free corridors. Show its factor breakdown and explain that accessibility is a feasibility condition when required, while utility preferences rank the feasible candidates.
5. **Repeatable baseline:** load the Baseline scenario, start it, and observe step progression, evacuee statuses, current corridor occupancy, and event history. Pause or reset to keep the session controlled.
6. **Dynamic condition:** load Fire blocks a main corridor, or create a run and activate a fire on `c4`. Observe effective restrictions and route-replanning events. Resolve the hazard and compare the conditions again. Make clear that the visual hazard spread is connectivity-based and illustrative.
7. **Exit handling:** load North exit unavailable. Show that routes use the remaining exit; optionally restore it through the hazard/exit controls.
8. **Outcomes and reports:** load No feasible safe route and point out `unable_to_evacuate` and terminal-with-people-remaining status. Download that run's JSON or CSV report to show the backend's run-specific export. Also try Corridor congestion to see queues, occupancy/capacity, and replans.

## Example API workflow

Route request (same request shape for each shortest-path algorithm):

```bash
curl -s http://localhost:8000/api/route \
  -H 'Content-Type: application/json' \
  -d '{"building_id":"dit-vedanta-illustrative","starting_room":"room-101","algorithm":"astar","cost_model":"distance"}'
```

Compare strategies on identical inputs:

```bash
curl -s http://localhost:8000/api/route/compare \
  -H 'Content-Type: application/json' \
  -d '{"building_id":"dit-vedanta-illustrative","starting_room":"room-101","cost_model":"distance"}'
```

List presets, then create a scenario run:

```bash
curl -s http://localhost:8000/api/scenarios
curl -s -X POST http://localhost:8000/api/scenarios/baseline/start
curl -s -X POST http://localhost:8000/api/scenarios/ditu-vedanta-fire/start
```

The creation response includes a generated `simulation_id`; pass it to `POST /api/simulations/{id}/start`, `/step` (JSON `{"steps":1}`), `/summary`, and `/report?format=json|csv` as documented in `/docs`.

## Expected observations

- The source graph has 11 nodes, 13 corridors, four rooms, two exits, and statically blocked `c8`.
- `GET /api/campus` returns five named campus reference locations and only one routable graph model. Other named places are reference-only. Catalog presence does not verify building access, floor layout, routes, exits, or safety procedures.
- `room-101` with the distance objective uses 60 m through Junction A and Junction B to the North Exit in the checked-in fixture.
- BFS can select a higher-distance route than Dijkstra if a test graph offers fewer edges but greater weights; the sample does not need to show a difference for all starts.
- A* has `h=0` fallback if coordinate data is incomplete. It remains optimal but may not expand fewer nodes.
- Scenario runs are deterministic for a given code/input, but simulation state is held in backend memory and disappears on backend restart.
- At completion, current corridor occupancy is normally zero. Peak occupancy in the evaluation report was calculated by sampling every tick; it is not retained as a built-in summary metric.

## Common problems and recovery

- **API is offline / building not loaded:** confirm the backend terminal is running; visit `/api/health`; check the API URL and browser console/network response.
- **Campus selector lists a reference-only place:** only Vedanta has an illustrative graph in this prototype. Select it to calculate a route; other locations cannot be routed.
- **Floor selector is disabled:** the current graph has no verified or modeled floor assignments. This is expected.
- **Port 8000 is occupied:** identify the process using the port before stopping anything. Alternatively run Uvicorn on another port and set `VITE_API_URL` to that address; also add the frontend origin/port to FastAPI CORS in `app/main.py`.
- **Port 5173 is occupied:** Vite may print another port. Because the backend CORS list is explicit, add that exact local origin to `allow_origins` before browser requests.
- **A previous simulation cannot be restored:** expected after a backend restart because runs are in memory. Load a new preset or create a new simulation.
- **Hazard controls are unavailable:** create/load a run first. Reset a completed run to return it to the initial scenario state before changing hazards.
- **Route shows no safe path:** inspect effective conditions, blocked corridors, unavailable exits, and unsafe nodes; reset or choose a scenario that provides a feasible alternative.
- **Report download fails:** ensure a simulation exists and the backend still holds its ID; retry from the active run's export controls.
- **UI seems stale after changing restrictions:** current route results are cleared on the frontend when effective conditions change; calculate a new route after the update.

## Submission / test commands

Backend: `cd backend && source .venv/bin/activate && python -m pytest -q`.

Frontend: `cd frontend && npm test && npm run lint && npm run build`.

For a live route API smoke test, use the curl requests above or `/docs`. The automated backend test suite contains endpoint-function and model validation tests. A browser walkthrough remains valuable for checking the complete interaction and download flows.

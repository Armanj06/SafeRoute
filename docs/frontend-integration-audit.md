# Frontend integration audit and feature checklist

Audit target: the existing SafeRoute frontend, FastAPI route module, simulation models/service, hazards, scenarios, reports, tests, and READMEs. The project already exposed the operations below; this work connects them to centralized frontend API methods and functional dashboard navigation instead of adding duplicate backend routes.

## Feature-to-endpoint checklist

| Frontend area | Backend endpoint(s) | Integration |
| --- | --- | --- |
| Building Overview and API status | `GET /api/building`, `GET /api/health` | Graph/name/description loaded from API; API state shown in header; route and safety overlays use returned data. |
| Route Planner | `POST /api/route`, `POST /api/route/utility` | BFS/Dijkstra/A*/utility requests use selected start, cost/preferences, and current simulation safety restrictions. |
| Strategy comparison | `POST /api/route/compare` | Displays backend route metrics, search-state counts, measured call time, and no-route outcomes. |
| Live Monitoring | `GET /api/simulations/{id}` | Active/paused run refreshes only while the monitoring section is active and tab is visible; timeout polling is serialized and cancelled on exit/unmount. The state response carries event history. |
| Crowd Simulation | `POST /api/simulations`, `GET /api/simulations/{id}`, `POST /api/simulations/{id}/start`, `/pause`, `/step`, `/reset` | Optional `building_id` selects a catalog graph; omitted IDs retain the default. The backend binds an isolated graph/engine copy to each run and returns its `building_id`. Current run shared across sections; per-person status, current node, and route shown. |
| Hazard Management | `POST /api/simulations/{id}/hazards`, `POST /api/simulations/{id}/hazards/{hazard_id}/activate|deactivate`, `POST /api/simulations/{id}/exits/{exit_id}/unavailable|restore` | These responses contain refreshed simulation hazards and `effective_conditions`. Unsafe changes clear the stale planner result so the operator can request a fresh path. |
| Scenario Testing | `GET /api/scenarios`, `POST /api/scenarios/{scenario_id}/start?building_id=...` | The list response contains descriptions/configuration; no second copy of scenario definitions in frontend. Optional model ID defaults compatibly; graph-specific scenario references are validated and incompatible presets return HTTP 422. |
| Analytics and Reports | `POST /api/route/compare`, `GET /api/simulations/{id}/report?format=json|csv`, simulation `analytics` response | Comparison inherits its associated run's graph when `building_id` is omitted and rejects explicit mismatches; without a run it uses the requested/default model. Current-run analytics and occupancy use API state; report exports carry the bound building ID. |
| Event timeline and filtering | Event history in `GET /api/simulations/{id}` | Chronological backend event records rendered with client-side filters and route-replanning details. The API client also supports the dedicated filtered events endpoint. |

## Findings and disposition

- **Functional before work:** algorithm routing and comparison, run creation/stepping, hazard mutation and exit controls, scenario loading, timeline, analytics, and report endpoints existed. The prior overview exposed those controls in one long view.
- **Partial before work:** dashboard data was fetched directly in UI components; connection/error handling differed by operation; current simulation was not recovered after reload; auto-step polling was sequential but was not abortable; report fetching did not belong to a shared service.
- **Missing before work:** sidebar navigation actions, a focused live-monitor data refresh, visible evacuee detail rows, an empty-monitor instruction, systematic stale simulation recovery, centralized frontend API tests.
- **Corrected integration:** API wrappers use the actual `/api/...` route contracts and unwrap the actual response bodies; report fetching leaves raw response streams intact for Blob downloads. Expired in-memory simulation IDs surface a recovery message.
- **No backend operation was missing:** start/pause/step/reset, hazard activation/deactivation, exit closure/restoration, effective conditions, event filters, scenarios, and reports already exist, so no new endpoint or dependency is needed for these UI tasks.

## Manual acceptance checklist

- [ ] Start FastAPI and Vite; confirm the API badge reports online and the graph loads.
- [ ] Use sidebar navigation and verify the active marker follows the selected destination.
- [ ] Select each route algorithm/cost model, calculate, inspect the API route and metrics, then compare strategies.
- [ ] Create a simulation or load each preset; start, pause/resume, step, and reset it.
- [ ] Watch counts, time, evacuee rows, corridor capacity, and chronological event filters update from returned state.
- [ ] Activate a node/corridor hazard, close an exit, resolve/restore them, and calculate a fresh safe route; inspect replanning events.
- [ ] Download JSON and CSV and verify the browser filenames and run-specific data.
- [ ] Reload the browser with a current run; verify state restoration, and restart the API to verify the expired-run recovery message.
- [ ] Repeat at laptop and narrow viewport widths; use keyboard focus to operate navigation, selects, and buttons.

The backend stores simulation state in memory. Restoring the browser tab can recover a run only while the same backend process still holds it.

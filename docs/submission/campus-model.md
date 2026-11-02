# DIT University campus reference model

## Purpose and data status

SafeRoute is **DIT University, Dehradun–referenced**, not an official DIT University system. It uses public source material only to configure campus place names and broad facility descriptions. The application does not reproduce an official campus map or floor plan, and DIT University has not approved, endorsed, or deployed it.

The campus data lives in `backend/app/data/campus_catalog.json`, separate from React components. The sole routable graph lives in `backend/app/data/sample_building.json`; it is a schematic teaching graph and its node/corridor IDs (room-101, c1, c4, exit-north, etc.) remain generic model IDs. The graph’s existing coordinates, connections, blocked corridor, distance/time values, capacities, crowd estimates, exits, and routes are hypothetical—not measurements or verified architectural details.

## Public information used

| Configured location name | Information the public reference supports | Model availability |
| --- | --- | --- |
| Vedanta | The 2023–24 campus brochure identifies the School of Computing, Admissions Office, Veda Library, and Indoor Auditorium. The virtual-tour page also labels Vedanta and some interior views. | One illustrative graph, with no verified indoor geometry. |
| Chanakya | Brochure map identifies the Administrative Block and lists engineering departments; virtual-tour labels include Chanakya reception/lawns. | Reference only; no routable graph. |
| Charak | Brochure/virtual tour identify Charak with the Faculty of Pharmacy. | Reference only; no routable graph. |
| Vastu | Brochure uses “Vastu” for the Faculty of Architecture & Design; the virtual-tour page uses “Vaastu”. The catalog uses “Vastu” and records the alternate spelling in its description. | Reference only; no routable graph. |
| Vishveshwarya | Brochure map identifies Civil Engineering, Petroleum & Energy Studies, and Management Studies. | Reference only; no routable graph. |

Sources:

- [DIT University Brochure 2023–24](https://www.dituniversity.edu.in/pdf/dit_brochure_2023-24.pdf) — campus map labels and broad facility/department names.
- [DIT University Virtual Tour](https://www.dituniversity.edu.in/virtual-tour/) — public place names and selected interior labels.
- [Academic Facilities](https://www.dituniversity.edu.in/campus-life/academic-facilities) — public descriptions of classrooms, libraries, labs, and other facilities.

These references do **not** verify room-to-corridor links, floor IDs, building entrances used as emergency exits, staircase placement/accessibility, route distances/times, occupancy/capacity values, assembly points, hazard locations, or approved evacuation paths. No such details are attributed to DIT University in SafeRoute.

## Current routable model

`GET /api/campus` returns a catalog with five reference names but exactly one available model: `dit-vedanta-illustrative`. `GET /api/building?building_id=dit-vedanta-illustrative` returns its graph, source metadata, status, and floor list. The root building model selector offers only this routable graph; reference-only locations are shown disabled with their model status. There are no floor-level maps, so floor selection is disabled and says so visibly.

The displayed graph currently has room nodes, junction nodes, exit nodes, and corridors, with one static blocked edge. It has no verified staircase or assembly-point nodes, so the UI legend only adds those symbols when a future selected graph actually contains those node types. The graph never calls any modeled exit an official DIT emergency exit. A persistent dashboard notice says the layout and route data are illustrative and that the project is not endorsed by the university.

## Graph fields and validation

The existing graph shape remains the route engine contract. `backend/app/services/building.py` now validates graph data when loading it:

- building ID is present and matches the catalog entry;
- node IDs and corridor IDs are unique;
- node types are one of `room`, `junction`, `exit`, `staircase`, `assembly_point`, or `area`;
- any supplied `x`/`y` pair is complete and finite;
- floors have unique IDs, and a node’s optional `floor_id` refers to a configured floor;
- every corridor endpoint references a known node, and endpoints differ;
- corridor distance is present, and distance/travel-time weights are finite and non-negative;
- optional capacity is finite and at least one; optional occupancy is finite and non-negative;
- optional `exit_ids` and `assembly_point_ids` refer to nodes of the appropriate types.

Current APIs accept `building_id` for building retrieval, normal routes, utility routes, and route comparison; omitted IDs retain the default model for compatibility. The comparison result and report identify the model. The simulator manager remains scoped to the single configured default graph; adding a second simulation model requires a per-building simulation-manager registry before scenarios can be selected across buildings. There is no graph upload API.

## Campus-oriented hypothetical scenarios

Six `ditu-vedanta-*` scenario presets run through the existing simulation engine. Their descriptions explicitly call out the hypothetical graph IDs and assumed crowd counts:

- fire on illustrative corridor `c4`;
- pre-closed illustrative corridor `c4`;
- unavailable illustrative exit node `exit-north`;
- flood on illustrative corridor `c4`;
- 48-person crowd demonstration on the illustrative graph;
- simultaneous illustrative hazards on `c4` and `junction-e`.

These IDs do not encode actual building areas or campus locations. The scenario names reference Vedanta solely because that is the one configured model label. Hazard severity, spread, movement, crowd, and capacity outcomes are hypothetical demonstration data. The existing six generic graph scenarios remain available as well.

## Adding a verified building or floor graph

Only add data after receiving authoritative architectural drawings/approved evacuation information and permission to use them:

1. Add an entry to the catalog with a stable model ID, parent location ID, approved display name, graph filename, model status, and floor IDs/names. Keep the source and validation status documented.
2. Add a graph JSON file with unique node IDs/types, coordinates only in a documented coordinate system, floor references, corridor endpoints, measured corridor costs, explicitly identified exits/assembly points, accessibility metadata, and measured capacity inputs where available.
3. Set `exit_ids` and `assembly_point_ids` only to verified referenced nodes. Never infer these from a visual campus brochure.
4. Run the graph through `validate_building_graph` and add tests for the new catalog/model, route alternatives, restrictions, floor references, and all connected simulation scenarios.
5. Before adding a second routable building, scope simulation managers/scenarios/reports by building ID; the present simulation manager is a singleton for the only current model.
6. Obtain professional safety review and validate the simulator against site measurements before presenting operational claims.

There is no import workflow today. All model changes are developer-authored JSON and catalog changes.

## Run and demonstration

Follow [demo-guide.md](demo-guide.md) to start the backend/frontend. The campus selector shows Vedanta as the only graph-backed location; other names remain reference-only. Select a room and an algorithm, calculate a route, then load one of the DITU hypothetical scenarios, start/step it, inspect event history and replan counts, and export the run report. The report includes the selected building ID/name/location and `illustrative` model status.

For a non-operational deployment, verified architectural drawings, approved evacuation plans, correct exits and assembly points, verified accessibility, actual occupancy/capacity, professional fire/life-safety review, simulation calibration, and deployment/security review are mandatory. SafeRoute itself is an academic prototype and makes no guarantee of safety during an emergency.

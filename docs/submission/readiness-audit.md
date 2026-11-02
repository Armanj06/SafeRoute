# Submission readiness audit

**Audit date:** 2026-10-31 (original integration findings retained; campus-specific checks added). **Scope:** checked-in source, tests, root/backend/frontend READMEs, submission docs, campus catalog and graph validation, available local API, and frontend lint/build.

## Readiness summary

The application is demonstrable as a local academic prototype: the campus catalog selects one explicitly illustrative graph, backend and frontend automated checks pass in this checkout, and direct HTTP checks return catalog/building/routes. The dashboard includes route planning/comparison, scenarios, simulation, hazard/exit controls, analytics, timeline, and report download. The completed browser smoke checks reported by the existing integration work are not a substitute for repeating the full acceptance checklist on the target presentation computer.

## Findings and disposition

| Area | Finding | Submission disposition |
| --- | --- | --- |
| Route planner | Route selection is a user action: changing algorithm/start/cost clears stale results; the user must press Calculate again. API validation failures and unreachable routes have readable messages. | Demonstrate one calculation per algorithm and one no-route result. |
| Current exit metric | The planner previously counted all configured exits despite active simulation closures. | Fixed during this audit to exclude exit IDs in `simulation.effective_conditions.unavailable_exits`. The overview already used effective conditions. |
| Sync label | The footer said “Building data synced just now” although no timestamp or sync event was tracked. | Fixed to say “Sample building graph loaded”; it no longer implies measured freshness. |
| Occupancy metrics | API analytics include current occupancy aggregates, not a saved peak. End-of-run current occupancy is usually zero. | Evaluation peak is explicitly calculated by sampling each simulation tick. UI label remains current occupancy. |
| Completion / unable | Remaining includes all not evacuated; unable-to-evacuate is a subset. Terminal state can mean completed processing with people remaining, not successful evacuation. | UI separates completion, unable count, and terminal outcome; explain the distinction. |
| Timing | Route comparison uses `perf_counter_ns` around one algorithm call. The illustrative graph is tiny; timer/runtime noise can dominate. | Show timing only as a returned measurement, not evidence of one strategy being faster. |
| Utility result | Bounded search may be incomplete and does not claim global utility optimality. Candidate-state count is not comparable to graph nodes expanded. | Dashboard and docs disclose both properties. |
| Hazards and safety | Every active hazard target is a hard exclusion regardless of severity; optional spread follows adjacency, not physical hazard behavior. | Demonstrate as route-condition logic only; disclose illustrative model. |
| Simulation behavior | Capacity is a simultaneous occupancy cap. Movement is deterministic, segment-based, and uses synthetic travel times. | Use “modeled”/“illustrative” phrasing; do not describe the numbers as real occupancy or throughput. |
| Persistence | Simulation state and report inputs are in backend memory and disappear at restart. Session storage only remembers the current ID. | Explain restart recovery by loading a fresh scenario. |
| API and UI integration | `GET /api/health`, building endpoint, and three route algorithm requests responded successfully by HTTP. Unsupported algorithm returned HTTP 422. Automated backend tests cover API function/request behavior. | Do not claim TestClient execution; it could not initialize here because `httpx2` is absent. |
| Browser coverage | `docs/frontend-integration-audit.md` has a manual acceptance list for navigation, route selections, simulation controls, hazards/exits, exports, reload, and narrow-screen/keyboard checks. | Run this list on the demonstration machine; automated tests do not validate all browser layout and download behavior. |

## Incomplete or manual workflows

- Route, scenario, hazard, exit, event, report-export, API-restart recovery, and responsive/keyboard workflows require manual browser demonstration for end-to-end confidence.
- The report API exports the selected run only. The application does not persist or aggregate results across runs.
- Historic peak occupancy cannot be retrieved from a final run report; it must be sampled while stepping.
- Only Vedanta is routable and only as a hypothetical graph; the four other public-reference location names are not graph models. There are no floor assignments, floor plans, verified exits, assembly points, stairs, or validated real-world route distances.
- Utility AI is included in the selector, route comparison endpoint, and comparison cards. Present it separately from shortest-path optimality because its objective and state-count semantics differ.
- The UI is a single long dashboard with in-page sidebar navigation. Verify scrolling/active navigation and keyboard use in the actual room/browser size.

## Verification actually performed for this audit

- Backend and frontend results for the final campus-specific revision are recorded in the top-level completion summary; the earlier baseline run was 61 backend tests and 5 frontend API tests.
- Live HTTP: campus catalog, selected building, and BFS/Dijkstra/A* route responses were directly checked. Final rerun results are recorded in the completion summary.
- Deterministic evaluation: twelve presets were stepped in fresh local managers and results recorded in [evaluation-results.md](evaluation-results.md).
- FastAPI `TestClient` attempt: unavailable because installed Starlette requires `httpx2`; this did not change dependencies. Live HTTP plus backend tests supplied API verification.

## Limitations to state in a presentation

SafeRoute is an academic prototype, not a certified emergency-response system. The building layout, graph costs, crowd behavior, occupancy assumptions, accessibility metadata, risk scores, and hazard propagation are illustrative rather than validated real-world models. There is no live sensor feed, operational dispatch, persistent run database, or site-specific safety validation. A trained building safety professional and authoritative site data would be required for real operational use.

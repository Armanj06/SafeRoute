# Viva questions and concise answers

## Graph theory and routing

1. **How is the building represented?** As an undirected weighted graph: rooms/junctions/exits are nodes and corridors are edges with distance, estimated time, and other attributes.
2. **Why are corridors modeled as undirected?** The sample JSON uses one corridor relation in both directions. Real one-way or directional restrictions would need directed edges or direction-specific rules.
3. **What does BFS optimize here?** Number of corridor segments, not metres or seconds.
4. **Why can BFS return a longer route in metres?** It treats every corridor as one hop even if edge distances differ.
5. **What does Dijkstra optimize?** The sum of non-negative corridor costs for the selected cost model: distance or estimated travel time.
6. **Why must Dijkstra's edge costs be non-negative?** Its greedy rule finalizes the least-cost frontier node; negative edges can invalidate that guarantee.
7. **What is A*'s `g`, `h`, and `f`?** `g` is cost accumulated from the start, `h` estimates remaining cost, and `f=g+h` orders the priority queue.
8. **How is the A* heuristic made safe?** It scales straight-line coordinate distance by the smallest observed corridor cost per coordinate distance; missing coordinates use zero heuristic.
9. **What does `h=0` mean?** A* loses coordinate guidance but becomes Dijkstra-equivalent and retains optimality under the same non-negative costs.
10. **How are multiple exits handled?** The search stops at the first available exit popped from its frontier; A* estimates to the nearest usable exit.
11. **How is the route reconstructed?** Each improved/discovered node stores its parent node and corridor; the chain is walked backward from the exit and reversed.
12. **What are the usual BFS time and space complexities?** `O(V+E)` time and `O(V)` search state, plus `O(V+E)` adjacency construction/storage.
13. **What is Dijkstra's complexity in this code?** Lazy `heapq` adjacency-list search is conservatively `O((V+E) log E)` time and `O(V+E)` extra storage, including duplicate heap entries.
14. **Is A* always faster than Dijkstra?** No. A useful heuristic can reduce expansions, but weak/zero heuristics and overhead can make it similar or slower.
15. **How does the code handle zero-cost corridors?** Weighted search accepts finite non-negative zero costs and updates only on strict improvement, preventing equal-cost zero cycles from replacing predecessors.

## Utility AI and safety

16. **Why have Utility AI in addition to shortest path?** It ranks routes on several preferences—time, estimated risk, crowding, accessibility—instead of one additive shortest-path objective.
17. **What is the utility formula?** A weighted sum of normalized time, safety, crowd, and accessibility scores; weights must total one.
18. **Does a high utility score prove a route is safe?** No. Static risk is illustrative and uncertain; hard exclusions remove known blocked/unsafe items, but the scores are not certified risk assessments.
19. **Is the utility agent globally optimal?** No. It examines a bounded set of simple routes (up to 5,000 expansions and requested candidate limit up to 50) and returns the best scored candidate it evaluated.
20. **How is step-free access enforced?** It filters non-step-free corridors before candidates are generated when step-free access is required; it is a hard constraint, not a score trade-off.
21. **What does an unavailable exit do?** It is removed from the goal set before search, so routes must reach another usable exit or return no route.
22. **How do active hazards influence routing?** A targeted corridor/node becomes an effective exclusion; a hazard targeting an exit makes it unavailable. The exclusion currently does not vary by severity.
23. **What happens if a moving evacuee's current route becomes unsafe?** If current segment or immediate destination is unsafe, the model stops/strands the evacuee in place and holds corridor occupancy; otherwise a moving evacuee can finish a safe segment and replan.

## Simulation and evaluation

24. **How does the crowd simulation advance?** In fixed time ticks; people request corridor slots, are admitted by waiting duration then stable ID, and occupy one corridor segment until modeled travel time expires.
25. **What does corridor capacity mean?** Maximum simultaneous occupancy in this prototype, not an empirically calibrated throughput-per-second value.
26. **How is travel time changed by congestion?** Base segment time is multiplied by `1 + penalty × max(static density, occupancy/capacity)`.
27. **What does completion percentage mean?** Evacuated people divided by initial evacuees. Remaining includes anyone not evacuated, including people unable to evacuate.
28. **How is average evacuation duration calculated?** Mean simulated time for successful evacuees only; it is unavailable when none has evacuated.
29. **Does the API store peak corridor occupancy?** No. It reports current load and current-state aggregates. An experiment can calculate peak by sampling each step, as in this report.
30. **Are measured algorithm milliseconds comparable to Big-O?** No. Big-O describes growth with graph size; one wall-clock measurement is affected by machine/runtime noise and graph size.
31. **Why compare algorithms on identical conditions?** To avoid attributing differences caused by different start, graph, closures, or cost model to the search strategy.

## API architecture, testing, and limitations

32. **What does FastAPI do?** Validates requests, serves graph/routing/scenario/simulation/report endpoints, and returns JSON (or CSV report responses).
33. **How does React call the backend?** Through a centralized fetch wrapper with configurable `VITE_API_URL`, JSON request bodies, and readable errors.
34. **Where does simulation state live?** In a process-local in-memory `SimulationManager`; restart loses runs and reports.
35. **How are tests organized?** Backend pytest files cover algorithms, API validation, utility scoring, hazards, simulation, scenarios, and reports; frontend Node tests exercise the API service wrapper.
36. **What does the no-safe-route scenario demonstrate?** It distinguishes a completed/terminated simulation state with a person unable to evacuate from successful 100% evacuation.
37. **Are hazards physically simulated?** No. Optional propagation follows graph adjacency with bounded steps; it does not solve smoke, fire, or fluid dynamics.
38. **Can SafeRoute be deployed as an emergency dispatch product as-is?** No. It is an academic prototype with illustrative inputs and simplified models, without validation, operational safety assurance, persistent storage, or sensor integration.
39. **What is a future evaluation improvement?** Use measured building geometry/costs, independently validated scenarios, repeated runs with controlled seeds/inputs, and a larger benchmark set; publish uncertainty and calibration assumptions.
40. **Why keep the graph small for this demo?** It keeps route states and outcomes inspectable in a viva, but does not support meaningful scalability conclusions.

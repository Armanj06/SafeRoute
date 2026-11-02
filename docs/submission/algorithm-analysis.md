# Algorithm analysis

This document describes the implementation in `backend/app/algorithms/` and `backend/app/agents/`. Complexity claims use `V` for nodes, `E` for corridors, and `L` for returned route length. The graph is represented as an undirected adjacency list rebuilt by `prepare_graph` for each call.

## Shared behavior and cost inputs

`prepare_graph` validates that the starting ID is a room or modeled area, excludes unsafe starts, constructs adjacency while omitting blocked/unsafe corridors and unsafe endpoints, and filters unavailable or unsafe exits. Searches stop at any remaining exit. `edge_cost` supports non-negative `distance` or `travel_time`; missing travel-time estimates fall back to `distance / 1.2`. Negative/non-finite costs raise `ValueError`. Route reconstruction follows predecessor node/corridor records backwards, reverses both lists, and sums distance, estimated time, and selected cost.

The route API accepts BFS, Dijkstra, and A* and defaults to BFS for compatibility. Utility AI has a separate endpoint and comparison entry; it optimizes a score over candidate paths rather than an edge-cost sum.

## BFS

**Purpose:** find a route with the fewest corridor segments (fewest edges), without regard to corridor distance/time.

**Input/output:** the graph, starting room, optional blocked/unsafe corridor/location and unavailable-exit sets, plus a reporting cost model. Returns the common route result with `found`, status/message, route node IDs, corridor IDs, exit, distance, estimated seconds, selected cost, and segment count. On failure it returns an empty route and a reason such as `invalid_start`, `unsafe_start`, `no_available_exits`, or `unreachable`.

**Implementation:** `collections.deque` FIFO queue, visited set on discovery, and one predecessor `(parent, corridor)` per discovered node. A goal is accepted when dequeued. This is standard unweighted BFS; the selected path's reported cost does not turn the search into weighted optimization.

**Complexity:** graph filtering/adjacency construction is `O(V + E)` time and space. Traversal is `O(V + E)` time and `O(V)` additional queue/visited/predecessor state in the usual adjacency-list model. Reconstruction and metric summation take `O(L)`. These are asymptotic operation counts, not timings measured on SafeRoute's sample graph.

**Safety and edge cases:** blocked/unsafe edges and unsafe nodes do not enter the search graph; unavailable exits are not goals. A disconnected start returns an unreachable result. Zero-cost corridors are valid but irrelevant to BFS's objective. Unsupported cost model names are rejected even though BFS does not use weights for route choice, because the response reports a cost.

**Strength/limitation:** simple, predictable, and optimal by number of segments. A short-in-segments path can be longer or slower than a multi-segment route.

## Dijkstra

**Purpose:** minimize the total selected non-negative edge cost to any usable exit.

**Input/output:** same route and restriction inputs as BFS; `cost_model` selects distance or estimated time. It returns the common route response, where `total_cost` has the selected unit.

**Implementation:** `heapq` min-priority queue with a monotonic tie-break counter, a best-cost dictionary, and predecessor records. A popped queue item is ignored if it is stale (`current_cost != costs[current]`). Relaxation updates a neighbor only for a strictly smaller path cost. The first non-stale goal popped is optimal for non-negative weights.

**Complexity:** preparation costs `O(V + E)`. With lazy duplicate heap entries, a conservative adjacency-list bound is `O((V + E) log E)` time and `O(V + E)` additional storage (the heap can contain multiple entries per vertex/edge relaxation). For simple graphs, this is commonly summarized as `O((V + E) log V)` under the standard indexed-heap model. Reconstruction is `O(L)`. This repository uses Python's lazy `heapq` pattern, not an indexed decrease-key heap.

**Safety and edge cases:** uses the same prefiltered safe graph as BFS. `edge_cost` permits zero costs and rejects negative, invalid, or non-finite selected costs. Strict improvement prevents zero-cost cycles from repeatedly replacing equal-cost predecessors. The route API translates unsupported algorithm/cost inputs to HTTP 422.

**Strength/limitation:** optimal for one additive cost model. It cannot simultaneously optimize distance, time, risk, crowding, and accessibility unless those are encoded in one valid scalar edge cost; this implementation uses the separate Utility AI for multi-factor ranking.

## A* search

**Purpose:** minimize the same distance/time edge-cost sum as Dijkstra, while using coordinates to prioritize promising nodes.

**Input/output:** same as Dijkstra. The response includes the route and common cost metrics; there is no heuristic value in the public response.

**Implementation:** `heapq` ordered by `f = g + h`, with `g` stored in the cost map, predecessor map, and stale-entry check. The goal is the nearest among usable exits under the admissible lower bound. `coordinate_heuristic_scale` inspects all usable corridors and chooses the minimum ratio of selected edge cost to Euclidean coordinate length. The heuristic is this scale multiplied by Euclidean distance to the nearest usable exit. By triangle inequality and the minimum edge ratio, this is a consistent lower bound when the coordinates and edge costs are coherent. If any node lacks numeric `x` and `y`, or no positive coordinate-edge ratio can be established, scale is zero and `h(n)=0`; this safely reduces the search to Dijkstra behavior.

**Complexity:** graph preparation and heuristic scale calculation are `O(V + E)` time/space. With a consistent heuristic, each node is expanded at most once in the idealized graph-search analysis and lazy-heap queue work has the same conservative `O((V + E) log E)` form as Dijkstra. In this implementation there is no explicit closed set, and improved `g` values can be enqueued again; the consistency of the generated heuristic prevents useful reopens after a node's best pop under valid costs. With `h=0`, behavior is Dijkstra-equivalent. A*'s general worst case can expand a large fraction of the graph; a weak heuristic offers little advantage. Timing differences are implementation/data/runtime dependent.

**Safety and edge cases:** shares the same exclusions and cost validation as Dijkstra. Exit selection is included in the heuristic by taking the minimum estimated cost over currently usable exits. Missing/incomplete coordinates fall back to zero rather than an unverified guess.

**Strength/limitation:** can expand fewer states when coordinates provide useful guidance while preserving the same weighted optimum. Its guidance is only as meaningful as graph coordinates and edge-cost consistency; on this fixture those coordinates are schematic.

## Utility AI

**Purpose:** rank a selection of feasible routes using several normalized preferences, rather than minimize one path cost.

**Input/output:** starting point, safety exclusions, optional step-free/minimum-width requirements, normalized preference weights, candidate limit, and reference time. Output contains selected route, distance/time, utility and factor scores, explanation, candidate count, expanded path-state count, and candidate-search completeness. It is exposed at `/api/route/utility` and included in `/api/route/compare`.

**Implementation:** the candidate generator performs best-first enumeration of simple paths ordered by estimated travel time. It caps graph/path-state expansions at 5,000 and candidates at 50 (API default 12). The agent scores each candidate using weighted time, safety, crowd, and accessibility factors. Accessibility restrictions and confirmed safety exclusions are applied before scoring; uncertain `hazard_risk` remains a soft score. If the candidate search is incomplete, the response states the selected path is best among those evaluated. If no candidate is found before an incomplete bound, it returns `search_incomplete` rather than claiming no path exists.

**Complexity:** exhaustive enumeration of simple paths can be exponential in `V`; this is not a polynomial shortest-path algorithm. In the actual implementation, search is bounded by at most `X=5,000` popped path states and `K<=50` accepted candidates. Each expansion scans outgoing edges, creates/checks a path tuple/set, and may push extensions; storage includes the frontier's path tuples and corridor tuples, so it depends on frontier width and path lengths. Candidate scoring is `O(K × L)` for routes of typical length `L`. The configured expansion limit makes work finite in the normal API, but does not make the result globally utility-optimal.

**Safety and edge cases:** shares blocked/unsafe/unavailable-exit graph preparation; accessibility requirements filter edges as hard constraints. Risk estimates alone do not make a corridor safe or unsafe. Invalid weight sets or corridor score fields raise validation errors. A small candidate limit or dense graph can omit an alternative with a better utility score.

**Strength/limitation:** communicates trade-offs and preferences and feeds simulation assignment/replanning. Its output is preference-dependent and bounded; it is not a proof of global optimality, and factor inputs need local calibration.

## Objective comparison

| Strategy | What is optimized | Search state | Optimality claim |
| --- | --- | --- | --- |
| BFS | Number of corridor edges | One graph node | Fewest-edge route |
| Dijkstra | Sum of distance or estimated-time weights | One graph node plus best `g` | Minimum selected non-negative additive cost |
| A* | Same sum as Dijkstra, guided by `h` | One graph node plus `g`/`f` | Same optimum with this consistent/fallback heuristic |
| Utility AI | Weighted multi-factor score | Simple path candidates | Highest score among evaluated candidates only |

## Safety and replanning behavior

For direct route calls, the backend excludes static blocked/unsafe corridor flags, supplied blocked/unsafe corridor IDs, unsafe endpoints/locations, and unavailable/unsafe exits before search. For simulations, active hazards and manual closures are folded into effective conditions. Waiting people can be replanned on condition changes or at configured congestion intervals. A moving person finishes a segment only when it remains safe; if the current segment or immediate destination becomes unsafe, the model strands them in place and keeps their occupancy. These are code rules, not a claim of real-world emergency safety certification.

## Measurement versus complexity

The comparison endpoint measures call wall time with `perf_counter_ns` and counts ordinary algorithm frontier nodes when popped (including the goal). Utility reports popped path candidates separately. These are measured, input- and machine-dependent values; they do not establish asymptotic complexity or comparative performance from this 11-node graph.

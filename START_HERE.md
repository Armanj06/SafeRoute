# SafeRoute setup and demonstration

Educational evacuation planning prototype. The graph is illustrative and ML duration prediction is future work.

## Install once

Use Python 3.10+ and Node.js 22.12+ (Node 24 recommended for the bundled Vite 8 release).
From the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
python run.py
```

Windows: use `python` instead of `python3`, and activate with `.venv\Scripts\activate`.
Open http://127.0.0.1:5173. Ctrl+C stops both services. The launcher starts services; it does not install dependencies.

## Demonstrate

1. Choose Plan & simulate. Select a starting room from the map with a click or keyboard Enter/Space; the dropdown also works.
2. Choose BFS, Dijkstra, A*, or Utility AI. Calculate a route. Click Compare all four strategies to reveal the full-width comparison. See FIXES_AND_DEMO.md for the delayed-corridor teaching example.
3. Load Baseline, then choose Start or Resume as displayed. Pause, step, resume, and reset to explore movement.
4. Load the fire, exit-unavailable, congestion, and no-safe-route presets. Inspect replanning, events, and outcomes.
5. Open hazard controls during an editable run to add/remove active hazards or change exit availability.
6. Open Reports & analysis; export JSON and CSV. Terminated does not always mean everybody evacuated.
7. Use map zoom controls and reset to 100% to see the whole graph. Narrow screens use a compact navigation bar.

## Verify

```bash
cd backend
python -m pytest -q
python -m scripts.validate_simulation_dataset ../data/synthetic/saferoute_duration_expanded.jsonl
cd ../frontend
npm test
npm run lint
npm run build
```

## Sharing and deployment

By default frontend requests `/api` on its own origin; Vite proxies to port 8000. Keep both services running. For a tunnel add only its exact hostname to `server.allowedHosts` in frontend/vite.config.js. VITE_API_URL may override the proxy for a separately hosted API, which then needs explicit backend CORS configuration. A production static host must provide its own `/api` reverse proxy or a configured API URL. This is not production deployment configuration.

## Verified changes

- Fixed backend import failure by defining RouteComparisonRequest before its endpoint is registered.
- Added accessible map room selection and per-map zoom/reset controls.
- Corrected misplaced SVG hazard legend labels.
- Improved type sizes, spacing, navigation contrast, controls and responsive layout.
- Updated hash navigation and same-origin API defaults; removed duplicate Vite server setting.
- Added this setup guide and a cross-platform launcher.
- Connected the UI refinement styles to the loaded stylesheet and removed duplicate strategy-comparison rendering.

## Verification boundary

157 backend tests passed; 6 frontend API tests passed; production build and lint passed. Live HTTP checks ran all 12 scenarios to termination and exported both formats. Browser verification passed for map click/keyboard selection, zoom/reset, A* routing, strategy comparison, fire-scenario pause/step/resume/completion, no-route outcomes and JSON/CSV downloads. Mobile at 390 px had no horizontal overflow, and no page errors were observed. Real browser screenshots are included in the 17-page report and docs/submission/screenshots. Simulation state is in memory and disappears on backend restart.

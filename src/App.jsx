import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertTriangle, ArrowUpRight, BarChart3, Building2, Check, ChevronDown, Clock3, Compass, DoorOpen, Download, Flame, GitCompareArrows, MapPin, Navigation, Route, Shield, Users } from 'lucide-react'
import { api, downloadSimulationReport } from './services/api.js'
import AdvancedWorkspace from './components/AdvancedWorkspace.jsx'

const SIMULATION_TICK_INTERVAL_MS = Number(import.meta.env.VITE_SIMULATION_TICK_MS || 800)
const UTILITY_WEIGHTS = {
  balanced: { time: 0.35, safety: 0.35, crowd: 0.2, accessibility: 0.1 },
  fastest: { time: 0.55, safety: 0.2, crowd: 0.15, accessibility: 0.1 },
  safest: { time: 0.2, safety: 0.55, crowd: 0.15, accessibility: 0.1 },
  'less-crowded': { time: 0.2, safety: 0.25, crowd: 0.45, accessibility: 0.1 },
}

const formatMetric = (value) => Number(value).toLocaleString('en', { maximumFractionDigits: 1 })
const floorName = (floorId, floors = []) => floors.find((floor) => floor.id === floorId)?.name || floorId
const routeFloorSummary = (route = [], nodes = [], floors = []) => [...new Set(route.map((id) => nodes.find((node) => node.id === id)?.floor_id).filter(Boolean))].map((id) => floorName(id, floors))

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: Building2 },
  { id: 'plan', label: 'Plan & simulate', icon: Route },
  { id: 'reports', label: 'Reports & analysis', icon: BarChart3 },
]

function BuildingMap({ building, result, simulation, startingNodeId, floorId, onSelectStart }) {
  const [zoom, setZoom] = useState(1)
  const width = 920 / zoom, height = 640 / zoom
  const routeNodes = new Set(result?.route || [])
  const simulatedRoutes = (simulation?.evacuees || []).filter((person) => ['waiting', 'moving'].includes(person.status)).flatMap((person) => person.route_corridors || [])
  const routeCorridors = new Set(result?.found ? (result.corridors || []) : simulatedRoutes)
  const conditions = simulation?.effective_conditions || {}
  const unsafeCorridors = new Set(conditions.unsafe_corridors || [])
  const blockedCorridors = new Set(conditions.blocked_corridors || [])
  const unsafeNodes = new Set(conditions.unsafe_nodes || [])
  const unavailableExits = new Set(conditions.unavailable_exits || [])
  const hazards = (simulation?.hazards || []).filter((hazard) => hazard.active)
  const visibleNodes = (building?.nodes || []).filter((node) => !floorId || !node.floor_id || node.floor_id === floorId)
  const nodeById = Object.fromEntries(visibleNodes.map((node) => [node.id, node]))
  return <><div className="map-toolbar"><span>{onSelectStart ? "Click a room to choose your start" : "Simulated movement and corridor load"}</span><div><button type="button" aria-label="Zoom out" disabled={zoom <= 1} onClick={() => setZoom(Math.max(1, zoom - .25))}>−</button><button type="button" aria-label="Reset map zoom" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button><button type="button" aria-label="Zoom in" disabled={zoom >= 2} onClick={() => setZoom(Math.min(2, zoom + .25))}>+</button></div></div><svg className="map-svg" viewBox={`${(920-width)/2} ${(640-height)/2} ${width} ${height}`} preserveAspectRatio="xMidYMid meet" role="group" aria-label={`${building?.model_status === 'illustrative' ? 'Illustrative schematic' : 'Building graph'} with corridors, restrictions, and evacuation route`}>
    <defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M 24 0 L 0 0 0 24" fill="none" stroke="#e8edf1" strokeWidth="1" /></pattern></defs>
    <rect width="920" height="640" fill="url(#grid)" rx="18" />
    {(building?.corridors || []).filter((corridor) => nodeById[corridor.from] && nodeById[corridor.to]).sort((a, b) => Number(routeCorridors.has(a.id)) - Number(routeCorridors.has(b.id))).map((corridor) => {
      const a = nodeById[corridor.from], b = nodeById[corridor.to]
      if (!a || !b) return null
      const selected = routeCorridors.has(corridor.id)
      const load = simulation?.corridor_load?.[corridor.id]
      const congestionClass = load?.utilization >= 1 ? 'full' : load?.utilization >= 0.75 ? 'crowded' : ''
      return <g key={corridor.id}>
        <title>{`${nodeById[corridor.from]?.label || corridor.from} to ${nodeById[corridor.to]?.label || corridor.to}, ${corridor.distance} meters${corridor.blocked || blockedCorridors.has(corridor.id) ? ', blocked' : ''}${load ? `, occupancy ${load.occupancy} of ${load.capacity}` : ''}`}</title>
        <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={`corridor ${corridor.blocked || blockedCorridors.has(corridor.id) ? 'blocked' : ''} ${unsafeCorridors.has(corridor.id) ? 'hazard-blocked' : ''} ${selected ? 'selected' : ''} ${congestionClass}`} />
        {(corridor.blocked || blockedCorridors.has(corridor.id)) && <g transform={`translate(${(a.x+b.x)/2}, ${(a.y+b.y)/2})`}><circle r="12" className="blocked-mark"/><path d="M-4 -4L4 4M4 -4L-4 4" className="blocked-cross"/><text y="25" className="hazard-label">BLOCKED</text></g>}
        {!corridor.blocked && !unsafeCorridors.has(corridor.id) && <text x={(a.x+b.x)/2} y={(a.y+b.y)/2-8} className="distance-label">{corridor.distance}m</text>}
        {hazards.filter((hazard) => hazard.target_type === 'corridor' && (hazard.target_id === corridor.id || hazard.propagated_targets?.some((target) => target.target_type === 'corridor' && target.target_id === corridor.id))).map((hazard) => <g key={hazard.hazard_id} transform={`translate(${(a.x+b.x)/2}, ${(a.y+b.y)/2})`}><circle r="10" className="hazard-marker"/><text y="4" className="hazard-symbol">!</text></g>)}
        {load?.occupancy > 0 && <g className="occupancy-badge" transform={`translate(${(a.x+b.x)/2}, ${(a.y+b.y)/2+8})`}><rect x="-29" y="-9" width="58" height="16" rx="7"/><text y="2">{load.occupancy}/{load.capacity} · {(load.utilization * 100).toFixed(0)}%</text></g>}
      </g>
    })}
    {visibleNodes.map((node) => {
      const active = routeNodes.has(node.id), isRoom = node.type === 'room' || node.type === 'area', isExit = node.type === 'exit'
      const isStaircase = node.type === 'staircase'
      const isElevator = node.type === 'elevator'
      const isAssemblyPoint = node.type === 'assembly_point'
      const hazardHere = hazards.some((hazard) => (hazard.target_type === 'node' && hazard.target_id === node.id) || hazard.propagated_targets?.some((target) => target.target_type === 'node' && target.target_id === node.id))
      const unavailable = unavailableExits.has(node.id)
      const selectable = Boolean(onSelectStart && ['room', 'area'].includes(node.type))
      return <g role={selectable ? 'button' : undefined} tabIndex={selectable ? 0 : undefined} aria-label={selectable ? `Start from ${node.label}` : undefined} aria-pressed={selectable ? startingNodeId === node.id : undefined} onClick={selectable ? () => onSelectStart(node.id) : undefined} onKeyDown={selectable ? (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectStart(node.id) } } : undefined} key={node.id} transform={`translate(${node.x}, ${node.y})`} className={`map-node ${node.type === 'area' ? 'lab-node' : ''} ${active ? 'active' : ''} ${startingNodeId === node.id ? 'selected-start' : ''} ${hazardHere || unsafeNodes.has(node.id) ? 'unsafe-node' : ''} ${unavailable ? 'unavailable-exit' : ''}`}>
        <title>{`${node.label || node.id}${active ? ', on selected route' : ''}${hazardHere || unsafeNodes.has(node.id) ? ', unsafe or affected by hazard' : ''}${unavailable ? ', unavailable exit' : ''}`}</title>
        {isRoom ? <><rect x="-55" y="-27" width="110" height="54" rx="10" className="room-box"/><text y="4" className="room-label">{node.label}</text></> : isExit ? <><circle r="28" className="exit-box"/><text y="4" className="exit-icon">⇧</text><text y="48" className="node-caption">{node.label}</text></> : isStaircase ? <><rect x="-13" y="-13" width="26" height="26" rx="5" className="staircase-marker"/><text y="4" className="special-node-icon">↕</text><text y="-19" className="node-caption">{node.label}</text></> : isElevator ? <><rect x="-13" y="-13" width="26" height="26" rx="5" className="elevator-marker"/><text y="4" className="special-node-icon">↕</text><text y="-19" className="node-caption">{node.label}</text></> : isAssemblyPoint ? <><path d="M0 -14L14 0L0 14L-14 0Z" className="assembly-marker"/><text y="4" className="special-node-icon">A</text><text y="-19" className="node-caption">{node.label}</text></> : <><circle r="7" className="junction-dot"/><text y="-18" className="node-caption">{node.label}</text></>}
        {hazardHere && <g transform="translate(43,-27)"><circle r="10" className="hazard-marker"/><text y="4" className="hazard-symbol">!</text></g>}
        {unavailable && <text x="0" y={isExit ? 68 : 38} className="hazard-label">UNAVAILABLE ×</text>}
      </g>
    })}
    <g transform="translate(36, 588)"><circle r="5" fill="#ef6254"/><text x="12" y="4" className="legend-text">Blocked / unsafe (×)</text><circle cx="150" r="5" fill="#17a884"/><text x="162" y="4" className="legend-text">Recommended route</text><circle cx="325" r="8" className="hazard-marker"/><text x="322" y="4" className="hazard-symbol">!</text><text x="340" y="4" className="legend-text">Active hazard</text><text x="445" y="4" className="legend-text">Unavailable exit (×)</text></g>
  </svg></>
}

export default function App() {
  const [activeSection, setActiveSection] = useState('overview')
  const [campusCatalog, setCampusCatalog] = useState(null)
  const [selectedBuildingId, setSelectedBuildingId] = useState('')
  const [selectedFloorId, setSelectedFloorId] = useState('')
  const [building, setBuilding] = useState(null)
  const [savedSimulationId] = useState(() => {
    try { return window.sessionStorage.getItem('saferoute.simulationId') }
    catch { return null }
  })
  const [room, setRoom] = useState('')
  const [algorithm, setAlgorithm] = useState('bfs')
  const [costModel, setCostModel] = useState('distance')
  const [utilityPreference, setUtilityPreference] = useState('balanced')
  const [stepFree, setStepFree] = useState(false)
  const [simulation, setSimulation] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [scenarioChoice, setScenarioChoice] = useState('baseline')
  const [simCount, setSimCount] = useState(8)
  const [simReplan, setSimReplan] = useState(true)
  const [simError, setSimError] = useState('')
  const [simNotice, setSimNotice] = useState('')
  const [simBusy, setSimBusy] = useState(false)
  const [hazardType, setHazardType] = useState('fire')
  const [hazardTargetType, setHazardTargetType] = useState('corridor')
  const [hazardTargetId, setHazardTargetId] = useState('')
  const [hazardSeverity, setHazardSeverity] = useState(0.8)
  const [hazardPropagation, setHazardPropagation] = useState(false)
  const [comparison, setComparison] = useState(null)
  const [mapRevision, setMapRevision] = useState(0)
  const [comparisonOpen, setComparisonOpen] = useState(false)
  const [comparisonError, setComparisonError] = useState('')
  const comparisonSection = useRef(null)
  const [comparisonBusy, setComparisonBusy] = useState(false)
  const [exporting, setExporting] = useState('')
  const [eventFilter, setEventFilter] = useState('all')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [apiStatus, setApiStatus] = useState('checking')
  const routeRequestController = useRef(null)
  const comparisonRequestController = useRef(null)
  const buildingRequestController = useRef(null)
  const simulationMutationVersion = useRef(0)
  const simulationRef = useRef(null)

  useEffect(() => {
    if (comparisonOpen) comparisonSection.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [comparisonOpen, comparison])

  function showComparisonRoute(entry) {
    setMapRevision((value) => value + 1)
    setAlgorithm(entry.algorithm)
    if (entry.cost_model) setCostModel(entry.cost_model)
    setResult({ ...entry, fromComparison: true, comparison_profile: comparison?.comparison_profile })
    setActiveSection('plan')
    document.getElementById('map')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function clearRoutingResults() {
    routeRequestController.current?.abort()
    comparisonRequestController.current?.abort()
    routeRequestController.current = null
    comparisonRequestController.current = null
    setResult(null); setComparison(null); setComparisonError(''); setError('')
    setLoading(false); setComparisonBusy(false)
  }
  function applySimulation(nextSimulation) {
    const previous = simulationRef.current
    const previousConditions = JSON.stringify(previous?.effective_conditions || null)
    const nextConditions = JSON.stringify(nextSimulation?.effective_conditions || null)
    if (previous && (previous.simulation_id !== nextSimulation?.simulation_id || previousConditions !== nextConditions)) {
      clearRoutingResults()
    }
    simulationRef.current = nextSimulation
    setSimulation(nextSimulation)
  }
  function expireSimulation(simulationId) {
    if (simulationRef.current?.simulation_id !== simulationId) return
    simulationRef.current = null
    setSimulation(null)
    clearRoutingResults()
    try { window.sessionStorage.removeItem('saferoute.simulationId') } catch { /* storage can be disabled */ }
  }

  async function selectBuilding(modelId) {
    if (!modelId || modelId === selectedBuildingId) return
    buildingRequestController.current?.abort()
    const controller = new AbortController()
    buildingRequestController.current = controller
    clearRoutingResults()
    setSelectedBuildingId(modelId)
    setSelectedFloorId('')
    setBuilding(null)
    setRoom('')
    simulationRef.current = null
    setSimulation(null)
    try { window.sessionStorage.removeItem('saferoute.simulationId') } catch { /* storage can be disabled */ }
    setSimError('')
    try {
      const { data } = await api.buildingById(modelId, { signal: controller.signal })
      if (buildingRequestController.current !== controller) return
      setBuilding(data)
      setSelectedFloorId(data.floors?.[0]?.id || '')
      setRoom(data.nodes.find((node) => ['room', 'area'].includes(node.type))?.id || '')
    } catch (reason) {
      if (reason.name !== 'AbortError' && buildingRequestController.current === controller) {
        setError(reason.message || 'Could not load the selected building model.')
      }
    }
  }

  function selectCampusLocation(locationId) {
    const model = campusCatalog?.models?.find((item) => item.location_id === locationId)
    if (model) selectBuilding(model.id)
  }

  function selectFloor(floorId) {
    setSelectedFloorId(floorId)
    clearRoutingResults()
    const firstRoom = building?.nodes.find((node) => node.type === 'room' && node.floor_id === floorId)
    if (firstRoom) setRoom(firstRoom.id)
  }

  useEffect(() => {
    const controller = new AbortController()
    api.campus({ signal: controller.signal }).then(({ data }) => {
      setCampusCatalog(data)
      const model = data.models.find((item) => item.id === data.default_model_id) || data.models[0]
      if (!model) throw new Error('No routable campus model is configured.')
      setSelectedBuildingId(model.id)
      setSelectedFloorId(model.floors?.[0]?.id || '')
      return api.buildingById(model.id, { signal: controller.signal })
    }).then(({ data }) => {
      if (controller.signal.aborted) return
      setBuilding(data)
      setRoom(data.nodes.find((node) => ['room', 'area'].includes(node.type))?.id || '')
    }).catch((reason) => { if (reason.name !== 'AbortError') setError(reason.message) })
    api.health({ signal: controller.signal }).then(() => setApiStatus('online')).catch((reason) => { if (reason.name !== 'AbortError') setApiStatus('offline') })
    api.scenarios({ signal: controller.signal }).then(({ data }) => setScenarios(data.scenarios || [])).catch((reason) => { if (reason.name !== 'AbortError') setSimError(reason.message) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!savedSimulationId) return undefined
    const controller = new AbortController()
    const version = simulationMutationVersion.current
    api.simulation(savedSimulationId, { signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted && simulationMutationVersion.current === version) applySimulation(data)
    }).catch((reason) => {
      if (controller.signal.aborted) return
      try { window.sessionStorage.removeItem('saferoute.simulationId') } catch { /* storage can be disabled */ }
      setSimError(reason.status === 404
        ? 'The previous simulation is no longer stored by the backend. Create a new run or load a scenario.'
        : reason.message)
    })
    return () => controller.abort()
  }, [savedSimulationId])

  useEffect(() => {
    try {
      if (simulation?.simulation_id) window.sessionStorage.setItem('saferoute.simulationId', simulation.simulation_id)
    } catch { /* simulation remains usable when browser storage is disabled */ }
  }, [simulation?.simulation_id])

  useEffect(() => {
    const hash = window.location.hash.slice(1)
    if (hash && building) document.getElementById(hash)?.scrollIntoView({ block: 'start' })
  }, [building])

  function navigateTo(sectionId) {
    setActiveSection(sectionId)
    const targetId = sectionId === 'plan' ? 'route-planner'
      : sectionId === 'reports' ? 'analytics-reports' : 'building-overview'
    window.history.replaceState(null, '', `#${targetId}`)
    document.getElementById(targetId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const rooms = useMemo(() => building?.nodes.filter((node) => ['room', 'area'].includes(node.type) && (!selectedFloorId || node.floor_id === selectedFloorId)) || [], [building, selectedFloorId])
  const floorStats = useMemo(() => (building?.floors || []).map((floor) => {
    const people = (simulation?.evacuees || []).filter((person) => building.nodes.find((node) => node.id === person.starting_room)?.floor_id === floor.id)
    return { ...floor, total: people.length, evacuated: people.filter((person) => person.status === 'evacuated').length, active: people.filter((person) => ['waiting', 'moving', 'waiting_exit_service'].includes(person.status)).length }
  }), [building, simulation])
  const selectedScenario = scenarios.find((scenario) => scenario.scenario_id === scenarioChoice)
  const scenarioPeople = selectedScenario?.number_of_evacuees ?? selectedScenario?.evacuees?.length
  const hazardTargets = useMemo(() => (hazardTargetType === 'corridor' ? building?.corridors : building?.nodes) || [], [building, hazardTargetType])
  const effectiveHazardTargetId = hazardTargets.some((target) => target.id === hazardTargetId) ? hazardTargetId : hazardTargets[0]?.id || ''

  useEffect(() => {
    if (!simulation?.simulation_id || simulation.status !== 'running') return undefined
    const controller = new AbortController()
    let timer
    let stopped = false
    const advance = async () => {
      const version = simulationMutationVersion.current
      try {
        const { data: nextState } = await api.stepSimulation(simulation.simulation_id, { steps: 1 }, { signal: controller.signal })
        if (stopped) return
        if (simulationMutationVersion.current !== version) {
          timer = setTimeout(advance, SIMULATION_TICK_INTERVAL_MS)
          return
        }
        applySimulation(nextState)
        if (nextState.status === 'running') timer = setTimeout(advance, SIMULATION_TICK_INTERVAL_MS)
      } catch (reason) {
        if (!stopped && reason.name !== 'AbortError') {
          setApiStatus(reason.status === 404 ? 'online' : 'offline')
          setSimError(reason.status === 404
            ? 'This simulation is no longer available. The backend may have restarted; create a new run or load a scenario.'
            : reason.message || 'Could not advance the simulation.')
          if (reason.status === 404) expireSimulation(simulation.simulation_id)
        }
      }
    }
    timer = setTimeout(advance, SIMULATION_TICK_INTERVAL_MS)
    return () => { stopped = true; clearTimeout(timer); controller.abort() }
  }, [simulation?.simulation_id, simulation?.status])

  useEffect(() => {
    if (activeSection === 'overview' || !simulation?.simulation_id || !['running', 'paused'].includes(simulation.status)) return undefined
    const simulationId = simulation.simulation_id
    const controller = new AbortController()
    let timer
    let stopped = false
    const refresh = async () => {
      if (stopped) return
      if (document.visibilityState === 'visible') {
        const version = simulationMutationVersion.current
        try {
          const { data } = await api.simulation(simulationId, { signal: controller.signal })
          if (stopped) return
          if (version !== simulationMutationVersion.current) {
            timer = window.setTimeout(refresh, Math.max(1500, SIMULATION_TICK_INTERVAL_MS * 2))
            return
          }
          const current = simulationRef.current
          if (current && current.simulation_id === simulationId) {
            const currentSequence = current.event_history?.at(-1)?.sequence ?? 0
            const nextSequence = data.event_history?.at(-1)?.sequence ?? 0
            if (data.current_step > current.current_step || (data.current_step === current.current_step && nextSequence >= currentSequence)) {
              applySimulation(data)
            }
          }
          setApiStatus('online')
        } catch (reason) {
          if (stopped || reason.name === 'AbortError') return
          setApiStatus(reason.status === 404 ? 'online' : 'offline')
          setSimError(reason.status === 404
            ? 'The backend no longer has this simulation. Create a new run or load a scenario.'
            : reason.message)
          if (reason.status === 404) expireSimulation(simulationId)
        }
      }
      if (!stopped) timer = window.setTimeout(refresh, Math.max(1500, SIMULATION_TICK_INTERVAL_MS * 2))
    }
    timer = window.setTimeout(refresh, 0)
    return () => { stopped = true; window.clearTimeout(timer); controller.abort() }
  }, [activeSection, simulation?.simulation_id, simulation?.status])

  async function simulationRequest(path, body = {}) {
    simulationMutationVersion.current += 1
    setSimBusy(true); setSimError(''); setSimNotice('')
    try {
      const { data: payload } = await api.post(path, body)
      applySimulation(payload.simulation || payload)
      clearRoutingResults()
      setSimNotice(path.includes('/hazards') ? 'Hazard state updated. The API returned refreshed safety conditions and route changes.'
        : path.includes('/exits/') ? 'Exit availability and effective conditions were refreshed.'
          : path.endsWith('/reset') ? 'Simulation reset to its initial state.'
            : path.includes('/scenarios/') ? 'Scenario loaded from the backend.' : 'Simulation state updated.')
      return payload
    } catch (reason) {
      setSimError(reason.status === 404
        ? 'This simulation or item is no longer available. The backend may have restarted; create a new run or load a scenario.'
        : reason.message || 'Simulation request failed.')
      return null
    } finally { setSimBusy(false) }
  }

  async function createCrowdSimulation(event) {
    event.preventDefault()
    await simulationRequest('/api/simulations', {
      number_of_evacuees: Number(simCount),
      time_step_seconds: 5,
      congestion_penalty: 1,
      replan_on_congestion: simReplan,
      replan_interval_steps: 3,
    })
  }
  async function loadDemoScenario() {
    const loaded = await simulationRequest(`/api/scenarios/${scenarioChoice}/start`)
    if (loaded) {
      setResult(null)
      setComparison(null)
      setEventFilter('all')
    }
  }
  async function addSimulationHazard(event) {
    event.preventDefault()
    if (!simulation || !effectiveHazardTargetId) return
    const updated = await simulationRequest(`/api/simulations/${simulation.simulation_id}/hazards`, {
      hazard_type: hazardType, target_type: hazardTargetType, target_id: effectiveHazardTargetId,
      severity: Number(hazardSeverity), propagation_enabled: hazardPropagation,
      propagation_interval_steps: 1, max_spread: 2,
    })
    if (updated) { setResult(null); setComparison(null) }
  }
  async function updateExitAvailability(exitId, available) {
    if (!simulation) return
    const updated = await simulationRequest(`/api/simulations/${simulation.simulation_id}/exits/${exitId}/${available ? 'restore' : 'unavailable'}`)
    if (updated) { setResult(null); setComparison(null) }
  }
  async function setHazardActive(hazardId, active) {
    if (!simulation) return
    const updated = await simulationRequest(`/api/simulations/${simulation.simulation_id}/hazards/${hazardId}/${active ? 'activate' : 'deactivate'}`)
    if (updated) { setResult(null); setComparison(null) }
  }
  async function compareStrategies(profileOverride) {
    const profile = typeof profileOverride === 'string' ? profileOverride : 'current'
    setComparisonOpen(true)
    setComparisonError('')
    if (!room) return
    comparisonRequestController.current?.abort()
    const controller = new AbortController()
    comparisonRequestController.current = controller
    setComparisonBusy(true); setError(''); setComparison(null)
    try {
      const { data: payload } = await api.compareRoutes({
          building_id: selectedBuildingId, starting_room: room, cost_model: profile === 'slow_north' ? 'travel_time' : costModel,
          simulation_id: profile === 'slow_north' ? null : simulation?.simulation_id || null,
          comparison_profile: profile,
          accessibility: { step_free: stepFree },
          preference_weights: UTILITY_WEIGHTS[utilityPreference],
      }, { signal: controller.signal })
      if (comparisonRequestController.current !== controller) return
      setComparison(payload)
    } catch (reason) {
      if (reason.name !== 'AbortError' && comparisonRequestController.current === controller) setComparisonError(reason.message || 'Could not compare route strategies.')
    } finally { if (comparisonRequestController.current === controller) setComparisonBusy(false) }
  }
  async function exportReport(format) {
    if (!simulation) return
    setSimError(''); setSimNotice(''); setExporting(format)
    try {
      await downloadSimulationReport(simulation.simulation_id, format)
      setSimNotice(`${format.toUpperCase()} report downloaded.`)
    } catch (reason) {
      setSimError(reason.message || `Could not export the ${format.toUpperCase()} report.`)
    } finally { setExporting('') }
  }
  function resetSimulation() {
    if (!simulation) return
    if (window.confirm('Reset this simulation to its initial state? Current progress and event history will be replaced.')) {
      simulationRequest(`/api/simulations/${simulation.simulation_id}/reset`)
    }
  }
  async function calculateRoute(event) {
    event.preventDefault()
    if (!room) return
    routeRequestController.current?.abort()
    const controller = new AbortController()
    routeRequestController.current = controller
    setLoading(true); setError(''); setResult(null)
    try {
      const utilityMode = algorithm === 'utility'
      const conditions = simulation?.effective_conditions || {}
      const routeRestrictions = {
        blocked_corridors: conditions.blocked_corridors || [],
        unavailable_exits: conditions.unavailable_exits || [],
        unsafe_locations: conditions.unsafe_nodes || [],
      }
      const body = utilityMode
        ? { building_id: selectedBuildingId, starting_room: room, accessibility: { step_free: stepFree }, preference_weights: UTILITY_WEIGHTS[utilityPreference], ...routeRestrictions }
        : { building_id: selectedBuildingId, starting_room: room, algorithm, cost_model: costModel, ...routeRestrictions }
      const { data: payload } = utilityMode ? await api.utilityRoute(body, { signal: controller.signal }) : await api.route(body, { signal: controller.signal })
      if (routeRequestController.current !== controller) return
      setResult(payload)
    } catch (reason) {
      if (reason.name !== 'AbortError' && routeRequestController.current === controller) setError(reason.message || 'Route request failed. Please try again.')
    } finally { if (routeRequestController.current === controller) setLoading(false) }
  }
  const startLabel = rooms.find((item) => item.id === room)?.label || 'Select a room'
  const exitLabel = building?.nodes.find((item) => item.id === result?.exit)?.label
  const analytics = simulation?.analytics || simulation?.statistics
  const filteredEvents = (simulation?.event_history || []).filter((event) => {
    if (eventFilter === 'all') return true
    if (eventFilter === 'hazard') return event.event_type.startsWith('hazard_')
    if (eventFilter === 'exit') return event.event_type.startsWith('exit_')
    if (eventFilter === 'route_replanned') return ['route_replanned', 'routes_recalculated'].includes(event.event_type)
    if (eventFilter === 'evacuee') return ['evacuated', 'unable_to_evacuate', 'evacuee_stranded', 'evacuee_resumed'].includes(event.event_type)
    return event.event_type === eventFilter
  }).slice(-20)

  function applySavedScenario(savedScenario) {
    if (savedScenario.floorId) setSelectedFloorId(savedScenario.floorId)
    if (savedScenario.room) setRoom(savedScenario.room)
    if (savedScenario.algorithm) setAlgorithm(savedScenario.algorithm)
    if (savedScenario.costModel) setCostModel(savedScenario.costModel)
    if (savedScenario.scenarioChoice) setScenarioChoice(savedScenario.scenarioChoice)
    clearRoutingResults()
  }

  function applyCustomBuilding(customBuilding) {
    clearRoutingResults()
    setSelectedBuildingId(customBuilding.id)
    setBuilding(customBuilding)
    setSelectedFloorId(customBuilding.floors?.[0]?.id || '')
    setRoom(customBuilding.nodes?.find((node) => ['room', 'area'].includes(node.type))?.id || '')
    setSimulation(null)
    simulationRef.current = null
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Shield size={20} fill="currentColor" /></div><div><strong>SafeRoute</strong><span>EVACUATION AI</span></div></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav aria-label="Dashboard sections">{NAV_ITEMS.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${activeSection === id ? 'active' : ''}`} aria-current={activeSection === id ? 'page' : undefined} onClick={() => navigateTo(id)}><Icon size={17}/>{label}{id === 'plan' && simulation?.status === 'running' && <span className="nav-dot" aria-label="Simulation running" />}</button>)}</nav>
      <div className="sidebar-divider" />
      <div className="sidebar-section-title">CAMPUS MODEL</div>
      <div className="building-choice"><div className="building-icon"><Building2 size={17}/></div><div><strong>{building?.campus_location?.name || 'Loading campus…'}</strong><span>{building?.model_status === 'illustrative' ? 'Illustrative graph only' : 'Graph loaded from FastAPI'}</span></div></div>
      <div className="sidebar-bottom"><div className="help-card"><div className="help-icon"><AlertTriangle size={16}/></div><strong>Demonstration model</strong><p>Routes follow modeled corridor and exit conditions only.</p><a href="#map">View campus graph <ArrowUpRight size={13}/></a></div><div className="profile"><div className="avatar">AJ</div><div><strong>SafeRoute operator</strong><span>Demonstration workspace</span></div></div></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div className="breadcrumb">SafeRoute <span>/</span> <strong>{NAV_ITEMS.find((item) => item.id === activeSection)?.label || 'Overview'}</strong></div><div className="top-actions"><div className={`status-pill ${apiStatus}`}><span /> API {apiStatus === 'checking' ? 'connecting' : apiStatus}</div><div className="date-label">Academic demonstration workspace</div><div className="avatar small">AJ</div></div></header>
      <div className="page-content">
        <div className="page-heading" id="building-overview"><div><div className="eyebrow">EMERGENCY MANAGEMENT / OVERVIEW</div><h1>Plan a clearer path to safety.</h1><p>Choose a starting room, compare routes, then explore how a simulated evacuation responds to changing conditions.</p></div><div className="overview-actions"><button className="primary-action" type="button" onClick={() => navigateTo('plan')}><Navigation size={16}/>Plan an evacuation</button><div className="incident-button" role="status"><span className="incident-dot"/> {analytics ? `${analytics.active_hazard_count} active simulated hazard${analytics.active_hazard_count === 1 ? '' : 's'}` : 'No active simulated hazards'}</div></div></div>
        <div className="campus-notice" role="note"><AlertTriangle size={17}/><div><strong>DIT University campus reference · illustrative model</strong><p>{campusCatalog?.campus?.notice || 'Campus reference metadata is loading.'} {campusCatalog?.campus?.endorsement_notice}</p><div>{(campusCatalog?.campus?.sources || []).map((source) => <a key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.title}</a>)}</div></div></div>
        <section className="overview-analytics" aria-label="Current simulation overview">
          <div className="overview-card"><span>TOTAL EVACUEES</span><strong>{analytics?.initial_evacuees ?? '—'}</strong><small>Initial people in this run</small></div>
          <div className="overview-card success"><span>EVACUATED</span><strong>{analytics?.total_evacuated ?? '—'}</strong><small>{analytics ? `${analytics.completion_percentage}% complete` : 'Run a simulation'}</small></div>
          <div className="overview-card"><span>AVAILABLE EXITS</span><strong>{building ? building.nodes.filter((node) => node.type === 'exit' && !node.unsafe && !simulation?.effective_conditions?.unsafe_nodes?.includes(node.id) && !simulation?.effective_conditions?.unavailable_exits?.includes(node.id)).length : '—'}</strong><small>{simulation?.effective_conditions?.unavailable_exits?.length ? `${simulation.effective_conditions.unavailable_exits.length} closed` : 'No exit closures'}</small></div>
          <div className="overview-card hazard"><span>ACTIVE HAZARDS</span><strong>{analytics?.active_hazard_count ?? '—'}</strong><small>{simulation?.status || 'No simulation running'}</small></div>
        </section>
        <section className="plan-intro" id="route-planner"><div><div className="eyebrow">PLAN & SIMULATE</div><h2>Build a route, then test it under changing conditions.</h2><p>Start with a room and routing algorithm. Simulation and incident controls remain available below.</p></div></section>
        <section className="planner-grid">
          <div className="panel map-panel" id="map"><div className="panel-heading"><div><div className="panel-kicker">CAMPUS GRAPH</div><h2>{building?.name || 'Building model'}</h2></div><div className="map-badge"><span/> Illustrative schematic</div></div>
            <details className="model-settings"><summary>Model and floor settings</summary><div className="campus-model-controls">
              <label htmlFor="campus-location-select">CAMPUS LOCATION</label>
              <select id="campus-location-select" value={campusCatalog?.models?.find((model) => model.id === selectedBuildingId)?.location_id || ''} onChange={(event) => selectCampusLocation(event.target.value)} disabled={!campusCatalog}>
                {(campusCatalog?.locations || []).map((location) => {
                  const modeled = campusCatalog.models.some((model) => model.location_id === location.id)
                  return <option key={location.id} value={location.id} disabled={!modeled}>{location.name}{modeled ? ' · illustrative model available' : ' · reference only, no routable model'}</option>
                })}
              </select>
              <label htmlFor="building-model-select">ROUTABLE BUILDING MODEL</label>
              <select id="building-model-select" value={selectedBuildingId} onChange={(event) => selectBuilding(event.target.value)} disabled={!campusCatalog || campusCatalog.models.length === 0}>
                {(campusCatalog?.models || []).map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}
              </select>
              <label htmlFor="floor-select">FLOOR</label>
              <select id="floor-select" value={selectedFloorId} onChange={(event) => selectFloor(event.target.value)} disabled={!building?.floors?.length}>
                {building?.floors?.length ? building.floors.map((floor) => <option key={floor.id} value={floor.id}>{floor.name || floor.id}</option>) : <option value="">No verified floor model available</option>}
              </select>
              <p className="campus-reference-copy"><strong>Public location reference:</strong> {campusCatalog?.locations?.find((location) => location.id === building?.campus_location?.id)?.verified_description || 'Location details are loading.'} This is name/function context only; it does not locate a routable room or corridor.</p>
            </div></details>
            <div className="map-wrap">{building ? <BuildingMap key={`${building.id}-${mapRevision}`} building={building} result={result?.found ? result : null} simulation={simulation} startingNodeId={room} floorId={selectedFloorId} onSelectStart={(id) => { setRoom(id); clearRoutingResults() }}/> : <div className="map-loading">Loading selected graph…</div>}</div>
            <div className="map-legend" aria-label="Map legend"><span><i className="legend-room"/> Room / area</span><span><i className="legend-junction"/> Junction</span><span><i className="legend-exit"/> Modeled exit</span>{building?.nodes.some((node) => node.type === 'staircase') && <span><i className="legend-stair"/> Staircase</span>}{building?.nodes.some((node) => node.type === 'elevator') && <span><i className="legend-elevator"/> Elevator</span>}{building?.nodes.some((node) => node.type === 'assembly_point') && <span><i className="legend-assembly"/> Assembly point</span>}<span><i className="legend-route"/> Selected route</span><span><i className="legend-blocked"/> Blocked / unsafe</span><span><i className="legend-hazard"/> Active hazard</span><span><i className="legend-start"/> Start location</span></div>
            <div className="map-foot"><span><MapPin size={14}/> {building?.campus_location?.name || 'Campus model'}</span><span>Graph schematic · not geographically accurate</span></div></div>
          <div className="panel route-panel"><div className="panel-heading"><div><div className="panel-kicker">ROUTE PLANNER</div><h2>Find an evacuation route</h2></div><div className="compass-icon"><Compass size={19}/></div></div><p className="panel-description">Choose a starting room and route strategy. Weighted algorithms minimize the selected cost.</p>
            <form onSubmit={calculateRoute}><label htmlFor="algorithm-select">ROUTE ALGORITHM</label><div className="select-wrap"><Route size={16}/><select id="algorithm-select" value={algorithm} onChange={(event) => { setAlgorithm(event.target.value); clearRoutingResults() }}><option value="bfs">BFS · fewest corridor segments</option><option value="dijkstra">Dijkstra · lowest total cost</option><option value="astar">A* · guided lowest-cost search</option><option value="utility">Utility-Based AI Agent</option></select><ChevronDown size={15}/></div>{algorithm === 'utility' ? <><label htmlFor="utility-preference" className="field-label">AGENT PREFERENCE</label><div className="select-wrap"><Compass size={16}/><select id="utility-preference" value={utilityPreference} onChange={(event) => { setUtilityPreference(event.target.value); clearRoutingResults() }}><option value="balanced">Balanced priorities</option><option value="fastest">Prefer faster routes</option><option value="safest">Prefer lower hazard risk</option><option value="less-crowded">Prefer less crowded routes</option></select><ChevronDown size={15}/></div><label className="step-free-toggle"><input type="checkbox" checked={stepFree} onChange={(event) => { setStepFree(event.target.checked); clearRoutingResults() }}/> Require step-free corridors</label></> : <><label htmlFor="cost-model-select" className="field-label">COST MODEL</label><div className="select-wrap"><Clock3 size={16}/><select id="cost-model-select" value={costModel} onChange={(event) => { setCostModel(event.target.value); clearRoutingResults() }}><option value="distance">Distance (meters)</option><option value="travel_time">Estimated travel time (seconds)</option></select><ChevronDown size={15}/></div></>}<label htmlFor="room-select" className="field-label">STARTING LOCATION</label><div className="select-wrap"><MapPin size={16}/><select id="room-select" value={room} onChange={(event) => { setRoom(event.target.value); clearRoutingResults() }} disabled={!rooms.length}>{rooms.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><ChevronDown size={15}/></div>
              <div className="condition-row"><div><span className="condition-mark blocked-mark-small"><span/></span><span>Blocked corridors</span></div><strong>{building?.corridors.filter((corridor) => corridor.blocked).length ?? '—'}</strong></div>
              <div className="condition-row"><div><span className="condition-mark exit-mark"><DoorOpen size={13}/></span><span>Available exits</span></div><strong>{building ? building.nodes.filter((node) => node.type === 'exit' && !node.unsafe && !simulation?.effective_conditions?.unsafe_nodes?.includes(node.id) && !simulation?.effective_conditions?.unavailable_exits?.includes(node.id)).length : '—'}</strong></div>
              <button className="calculate-button" type="submit" disabled={!building || loading}><Navigation size={16}/>{loading ? 'Finding route…' : 'Calculate evacuation route'}<ArrowUpRight size={16}/></button>
            </form>
            {error && <div className="error-box"><AlertTriangle size={16}/>{error}</div>}
            {result?.found ? <div className="result-card">{result.comparison_profile === 'slow_north' && <p className="example-route-note">Teaching example: north corridor takes 180 s. Source building unchanged.</p>}<div className="result-top"><div className="result-check"><Check size={16}/></div><div><strong>{result.algorithm === 'utility' ? 'Utility-based route selected' : 'Route ready'}</strong><span>{result.algorithm === 'utility' ? `${result.candidate_count} candidate routes evaluated` : `${result.algorithm.toUpperCase()} · ${result.cost_model === 'travel_time' ? 'estimated travel time' : 'distance'} optimized`}</span></div><span className="result-tag">{result.status.toUpperCase()}</span></div><div className="result-destination"><span>DESTINATION</span><strong><DoorOpen size={17}/> {exitLabel}</strong></div><div className="route-stats"><div><span>FROM</span><strong>{startLabel}</strong></div><div><span>DISTANCE</span><strong>{result.distance}m</strong></div><div><span>TOTAL COST</span><strong>{result.total_cost} {result.cost_model === 'distance' ? 'm' : 's'}</strong></div></div><div className="travel-time"><Clock3 size={13}/> Estimated travel time: <strong>{formatMetric(result.estimated_travel_time_seconds)}s</strong></div>{result.algorithm === 'utility' && result.factor_scores && <div className="utility-breakdown"><div className="utility-score"><span>ROUTE UTILITY</span><strong>{(result.utility_score * 100).toFixed(1)}%</strong></div>{Object.entries(result.factor_scores).map(([factor, score]) => <div className="factor-row" key={factor}><span>{factor}</span><div className="factor-track"><i style={{ width: `${score * 100}%` }}/></div><strong>{(score * 100).toFixed(0)}%</strong></div>)}<p>{result.explanation}</p>{!result.candidate_search_complete && <small>Candidate search was bounded; this is the best route among those evaluated.</small>}</div>}<div className="route-floor-summary">Vertical route: {routeFloorSummary(result.route, building?.nodes || [], building?.floors || []).join(' → ')}</div><div className="route-steps"><div className="step-line"/><div className="step"><span className="step-dot start"/><span>{startLabel}</span><small>START</small></div>{result.route.slice(1,-1).map((id) => <div className="step" key={id}><span className="step-dot"/><span>{building.nodes.find((node) => node.id === id)?.label || id}</span></div>)}<div className="step"><span className="step-dot end"/><span>{exitLabel}</span><small>EXIT</small></div></div></div> : result && <div className="error-box"><AlertTriangle size={16}/>{result.message}</div>}
            {!result && <div className="planner-note"><Flame size={15}/><span>{algorithm === 'utility' ? 'Confirmed unsafe routes are excluded before utility scoring.' : 'Routes automatically avoid blocked corridors and unsafe locations.'}</span></div>}
            <div className="comparison-launch"><button className="compare-button" type="button" onClick={() => compareStrategies('current')} disabled={comparisonBusy || !building || !room}><GitCompareArrows size={16}/>{comparisonBusy ? 'Comparing…' : 'Compare all four strategies'}</button><p>See route choices, walking estimates, and measured computation time side by side.</p></div>

          </div>
        </section>
        {comparisonOpen && <section className="comparison-workspace panel" id="route-comparison" ref={comparisonSection} aria-label="Route strategy comparison" aria-busy={comparisonBusy}>
          <div className="comparison-workspace-heading"><div><div className="panel-kicker">ALGORITHM LAB</div><h2>Compare route strategies</h2><p>Walking time belongs to a route. Computation time belongs to the search algorithm.</p></div><button type="button" className="comparison-close" onClick={() => setComparisonOpen(false)}>Close comparison</button></div>
          <div className="comparison-actions"><button type="button" onClick={() => compareStrategies('current')} disabled={comparisonBusy}>Compare current conditions</button><button type="button" onClick={() => compareStrategies('slow_north')} disabled={comparisonBusy}>Try slower north corridor example</button></div>
          {comparisonBusy && <p role="status">Calculating all four strategies on the same graph snapshot…</p>}
          {comparisonError && <div className="error-box" role="alert">{comparisonError}</div>}
          {!comparisonBusy && !comparisonError && !comparison && <p>Compare the current conditions or try the teaching example below.</p>}
          {comparison && <>
            <div className="comparison-context"><strong>{comparison.comparison_profile === 'slow_north' ? 'Teaching example · north corridor delay' : `Current conditions · ${building?.nodes.find((node) => node.id === comparison.starting_room)?.label || comparison.starting_room}`}</strong><span>{comparison.example_description || `BFS counts segments; Dijkstra and A* optimize ${comparison.cost_model === 'distance' ? 'distance' : 'travel time'}. Utility AI balances several preferences.`}</span></div>
            {comparison.results.filter((entry) => entry.found).length > 1 && new Set(comparison.results.filter((entry) => entry.found).map((entry) => JSON.stringify(entry.corridors))).size === 1 && <p className="same-route-note">These strategies selected the same corridor path. Under the same travel assumptions, its distance and travel time are identical. The computation times below measure a different quantity.</p>}
            <div className="comparison-cards">{comparison.results.map((entry) => <article className={`comparison-card ${entry.found ? '' : 'no-route'} ${result?.fromComparison && result.algorithm === entry.algorithm ? 'chosen' : ''}`} key={entry.algorithm}>
              <div className="comparison-card-title"><strong>{entry.algorithm === 'utility' ? 'Utility AI' : entry.algorithm === 'astar' ? 'A*' : entry.algorithm.toUpperCase()}</strong><span>{entry.found ? 'Route found' : 'No route'}</span></div>
              <p className="strategy-objective">{entry.algorithm === 'bfs' ? 'Fewest corridor segments' : entry.algorithm === 'utility' ? 'Best evaluated utility' : `Lowest ${comparison.cost_model === 'distance' ? 'distance' : 'travel cost'}`}</p>
              {entry.found ? <><div className="comparison-route">{entry.route.map((id) => building?.nodes.find((node) => node.id === id)?.label || id).join(' → ')}</div>
                <div className="comparison-metrics"><span><b>ROUTE DISTANCE</b>{formatMetric(entry.distance)} m</span><span><b>ESTIMATED TRAVEL</b>{formatMetric(entry.estimated_travel_time_seconds)} s</span><span><b>CORRIDOR SEGMENTS</b>{entry.corridors.length}</span><span><b>COMPUTATION</b>{entry.duration_ms < .001 ? '<0.001' : entry.duration_ms.toFixed(3)} ms</span></div>
                <p className="comparison-expansions">{entry.nodes_expanded == null ? `${entry.candidate_states_expanded ?? '—'} candidate states examined` : `${entry.nodes_expanded} graph nodes expanded`}</p>
                {entry.utility_score != null && <p className="comparison-utility">Utility score: {(entry.utility_score * 100).toFixed(1)}% · bounded candidate search</p>}
                <button type="button" aria-pressed={Boolean(result?.fromComparison && result.algorithm === entry.algorithm)} onClick={() => showComparisonRoute(entry)}>Show {entry.algorithm === 'astar' ? 'A*' : entry.algorithm === 'utility' ? 'Utility AI' : entry.algorithm.toUpperCase()} route on map</button>
              </> : <p>{entry.message}</p>}
            </article>)}</div>
            <p className="comparison-note">Travel estimates are not the duration of evacuating a crowd. Computation is one local algorithm call in milliseconds and can vary with runtime noise. Dijkstra and A* can return identical optimal paths. Utility AI is best only among its evaluated candidates. Examples modify only the comparison snapshot.</p>
          </>}
        </section>}
        <section className="simulation-section" id="live-monitoring">
          <div className="simulation-section-heading"><div><div className="eyebrow">DISCRETE-TIME MODEL · ILLUSTRATIVE ONLY</div><h2>{simulation?.scenario?.name || 'Crowd simulation'}</h2><p>Capacity-limited movement, dynamic hazards, and route analysis. This is not live building occupancy.</p></div><div className={`simulation-status ${simulation?.status || 'idle'}`}><span/>{analytics?.outcome?.replaceAll('_', ' ') || simulation?.status || 'not created'}</div></div>
          <div className="simulation-layout">
            <div className="panel simulation-controls" id="crowd-simulation">
              <div className="panel-kicker">SIMULATION CONTROLS</div>
              <div className="scenario-loader" id="scenario-testing">
                <label htmlFor="scenario-select">DEMONSTRATION SCENARIO</label>
                <div className="scenario-load-row"><select id="scenario-select" value={scenarioChoice} onChange={(event) => setScenarioChoice(event.target.value)}>{scenarios.map((item) => <option key={item.scenario_id} value={item.scenario_id}>{item.name}</option>)}</select><button type="button" onClick={loadDemoScenario} disabled={simBusy || !scenarios.length}>{simBusy ? 'Loading…' : 'Load'}</button></div>
                <p>{selectedScenario ? `${selectedScenario.description} ${selectedScenario.learning_outcome} ${scenarioPeople ?? 'Configured'} evacuees · ${(selectedScenario.hazards || []).length} initial hazards · ${(selectedScenario.unavailable_exits || []).length} closed exits.` : 'Scenario definitions load from the backend.'}</p>
              </div>
              <form onSubmit={createCrowdSimulation}>
                <label htmlFor="evacuee-count">NUMBER OF EVACUEES</label>
                <input id="evacuee-count" type="number" min="1" max="200" value={simCount} onChange={(event) => setSimCount(event.target.value)} />
                <p className="simulation-help">Default starts are distributed round-robin across the building's rooms.</p>
                <label className="step-free-toggle replan-toggle"><input type="checkbox" checked={simReplan} onChange={(event) => setSimReplan(event.target.checked)}/> Replan waiting people when congestion changes (every 3 steps)</label>
                <button className="calculate-button" type="submit" disabled={simBusy || !building}><Users size={15}/>{simBusy ? 'Creating…' : 'Create simulation'}</button>
              </form>
              {simNotice && <div className="success-box" role="status"><Check size={14}/>{simNotice}</div>}
              <div className="simulation-buttons">
                <button type="button" onClick={() => simulation && simulationRequest(`/api/simulations/${simulation.simulation_id}/start`)} disabled={!simulation || simBusy || simulation.status === 'running' || simulation.status === 'completed'}>{simulation?.status === 'paused' ? 'Resume' : 'Start'}</button>
                <button type="button" onClick={() => simulation && simulationRequest(`/api/simulations/${simulation.simulation_id}/pause`)} disabled={!simulation || simBusy || simulation.status !== 'running'}>Pause</button>
                <button type="button" onClick={() => simulation && simulationRequest(`/api/simulations/${simulation.simulation_id}/step`, { steps: 1 })} disabled={!simulation || simBusy || simulation.status === 'completed' || simulation.status === 'running'}>Step forward</button>
                <button type="button" onClick={resetSimulation} disabled={!simulation || simBusy}>Reset</button>
              </div>
              <details className="hazard-controls" id="hazard-management">
                <summary><Flame size={15}/>Hazards, closures, and replanning</summary>
                <div className="hazard-content"><div className="panel-kicker">DYNAMIC HAZARDS</div>
                <form onSubmit={addSimulationHazard}>
                  <label htmlFor="hazard-kind">INCIDENT TYPE</label>
                  <select id="hazard-kind" value={hazardType} onChange={(event) => setHazardType(event.target.value)}><option value="fire">Fire</option><option value="flood">Flood</option><option value="unsafe_area">Unsafe-area incident</option></select>
                  <label htmlFor="hazard-target-type">TARGET TYPE</label>
                  <select id="hazard-target-type" value={hazardTargetType} onChange={(event) => setHazardTargetType(event.target.value)}><option value="corridor">Corridor</option><option value="node">Room / junction / exit</option></select>
                  <label htmlFor="hazard-target">TARGET</label>
                  <select id="hazard-target" value={effectiveHazardTargetId} onChange={(event) => setHazardTargetId(event.target.value)}>{hazardTargets.map((target) => <option key={target.id} value={target.id}>{target.label || target.id}</option>)}</select>
                  <label htmlFor="hazard-severity">SEVERITY ({Number(hazardSeverity).toFixed(1)})</label>
                  <input id="hazard-severity" type="range" min="0" max="1" step="0.1" value={hazardSeverity} onChange={(event) => setHazardSeverity(event.target.value)} />
                  <label className="step-free-toggle replan-toggle"><input type="checkbox" checked={hazardPropagation} onChange={(event) => setHazardPropagation(event.target.checked)}/> Enable illustrative propagation (up to 2 connected steps)</label>
                  <button className="hazard-submit" type="submit" disabled={!simulation || simBusy || simulation.status === 'completed'}><Flame size={14}/>Activate hazard</button>
                </form>
                <div className="exit-controls"><strong>Exit availability</strong>{(building?.nodes || []).filter((node) => node.type === 'exit').map((exit) => {
                  const unavailable = simulation?.effective_conditions?.unavailable_exits?.includes(exit.id)
                  return <div key={exit.id}><span>{exit.label}{unavailable ? ' · Unavailable' : ' · Available'}</span><button type="button" onClick={() => updateExitAvailability(exit.id, unavailable)} disabled={!simulation || simBusy || simulation.status === 'completed'}>{unavailable ? 'Restore' : 'Close'}</button></div>
                })}</div>
                {(simulation?.hazards || []).length > 0 && <div className="hazard-list"><strong>Hazard history</strong>{simulation.hazards.slice().reverse().map((hazard) => <div key={hazard.hazard_id}><span className={hazard.active ? 'hazard-active-label' : ''}>{hazard.hazard_type.replace('_', ' ')} · {hazard.target_id} · {hazard.active ? 'active' : 'resolved'}</span><button type="button" onClick={() => setHazardActive(hazard.hazard_id, !hazard.active)} disabled={simBusy || simulation.status === 'completed'}>{hazard.active ? 'Resolve' : 'Activate'}</button></div>)}</div>}
                <div className="replan-count">Routes recalculated: <strong>{(simulation?.event_history || []).filter((event) => event.event_type === 'route_replanned').length}</strong><small>Calculate a fresh route after changing conditions.</small></div>
                </div>
              </details>
              {simError && <div className="error-box"><AlertTriangle size={15}/>{simError}</div>}
              {simulation && <div className="simulation-clock"><Clock3 size={15}/><span>Simulation time</span><strong>{simulation.current_time_seconds}s</strong><small>Step {simulation.current_step}</small></div>}
            </div>
            <div className="simulation-results" id="analytics-reports">
              <div className="reports-heading"><div><div className="eyebrow">REPORTS & ANALYSIS</div><h2>Review the current run</h2><p>Results are available only while the backend retains this simulation.</p></div>{simulation && <button className="report-compare" type="button" onClick={compareStrategies} disabled={comparisonBusy || !building || !room}>{comparisonBusy ? 'Comparing…' : 'Compare strategies'}</button>}</div>
              {!simulation && <div className="monitor-empty"><strong>No simulation is being monitored</strong><span>Create a run or load a backend scenario to view live evacuee, hazard, corridor, and event data.</span><button type="button" onClick={() => navigateTo('plan')}>Open planning controls</button></div>}
              <div className="simulation-stat-grid">
                <div className="simulation-stat"><span>EVACUATED</span><strong>{simulation?.statistics.total_evacuated ?? '—'}</strong></div>
                <div className="simulation-stat"><span>STILL EVACUATING</span><strong>{analytics?.active_remaining ?? '—'}</strong></div>
                <div className="simulation-stat"><span>UNABLE TO EVACUATE</span><strong>{simulation?.statistics.unable_to_evacuate ?? '—'}</strong></div>
                <div className="simulation-stat"><span>EVACUATION STATUS</span><strong>{analytics?.evacuation_complete ? 'Complete' : analytics?.simulation_terminated ? 'Terminated' : simulation ? 'In progress' : '—'}</strong></div>
              </div>
              <div className="analytics-strip">
                <div><span>COMPLETION</span><strong>{analytics ? `${analytics.completion_percentage}%` : '—'}</strong></div>
                <div><span>SIMULATION STEPS</span><strong>{analytics?.total_steps ?? '—'}</strong></div>
                <div><span>AVG EVACUATION DURATION</span><strong>{analytics?.average_evacuation_duration_seconds == null ? 'Not yet available' : `${analytics.average_evacuation_duration_seconds.toFixed(1)}s`}</strong></div>
                <div><span>ROUTE REPLANS</span><strong>{analytics?.route_replanning_events ?? '—'}</strong></div>
                <div><span>HIGH OCCUPANCY CORRIDORS</span><strong>{analytics?.high_occupancy_corridors ?? '—'}</strong><small>≥ {(analytics?.high_occupancy_threshold ?? 0.75) * 100}% occupied</small></div>
                <div><span>CORRIDORS AT CAPACITY</span><strong>{analytics?.corridors_at_capacity ?? '—'}</strong><small>Separate from confirmed hazards</small></div>
                <div><span>ACTIVE HAZARDS</span><strong>{analytics?.active_hazard_count ?? '—'}</strong></div>
                <div><span>BLOCKED CORRIDORS</span><strong>{analytics?.blocked_corridor_count ?? '—'}</strong></div>
                <div><span>SIMULATION TIME</span><strong>{simulation ? `${simulation.current_time_seconds}s` : '—'}</strong></div>
              </div>
              {simulation && <div className={`outcome-banner ${analytics?.evacuation_complete ? 'success' : analytics?.simulation_terminated ? 'incomplete' : ''}`}><strong>{analytics?.evacuation_complete ? 'Evacuation complete' : analytics?.simulation_terminated ? 'Simulation terminated with people remaining' : 'Simulation is in progress'}</strong><span>{analytics?.total_evacuated ?? 0} evacuated of {analytics?.initial_evacuees ?? 0}; {analytics?.unable_to_evacuate ?? 0} unable to evacuate safely.</span></div>}
              {simulation && <div className="floor-statistics"><div className="floor-statistics-heading"><strong>Floor-wise evacuation</strong><span>People are grouped by their starting floor.</span></div>{floorStats.map((floor) => <div className="floor-stat-row" key={floor.id}><b>{floor.name}</b><span>{floor.evacuated}/{floor.total} evacuated</span><strong>{floor.active ? `${floor.active} active` : 'clear'}</strong></div>)}</div>}
              <div className="panel simulation-map-panel"><div className="panel-heading"><div><div className="panel-kicker">CORRIDOR LOAD</div><h2>Occupancy / capacity</h2></div><span className="congestion-legend"><i/>Busy <i/>At capacity</span></div>{building ? <div className="simulation-map-wrap"><BuildingMap building={building} simulation={simulation} startingNodeId={room}/></div> : <div className="map-loading">Loading building map…</div>}</div>
              {simulation && <div className="congestion-list"><div><strong>Current corridor utilization</strong><span>Congestion is a movement constraint, not a hazard finding.</span></div>{Object.entries(simulation.corridor_load || {}).sort(([, a], [, b]) => b.utilization - a.utilization).slice(0, 6).map(([corridorId, load]) => <div key={corridorId} className={load.utilization >= 0.75 ? 'high' : ''}><b>{corridorId}</b><span>{load.occupancy}/{load.capacity} people · {(load.utilization * 100).toFixed(0)}%</span><strong>{load.utilization >= 1 ? 'AT CAPACITY' : load.utilization >= 0.75 ? 'HIGH OCCUPANCY' : 'AVAILABLE'}</strong></div>)}</div>}
              {simulation && <div className="evacuee-list"><div className="evacuee-list-heading"><strong>Evacuee status</strong><span>Showing {Math.min(simulation.evacuees.length, 20)} of {simulation.evacuees.length}</span></div>{simulation.evacuees.slice(0, 20).map((person) => <div className="evacuee-row" key={person.evacuee_id}><b>{person.evacuee_id}</b><span className="evacuee-group">{person.group || 'student'}</span><span className={`status-label ${person.status}`}>{person.status.replaceAll('_', ' ')}</span><span>At {building?.nodes.find((node) => node.id === person.current_node)?.label || person.current_node}</span><small>{person.route.length ? person.route.map((id) => building?.nodes.find((node) => node.id === id)?.label || id).join(' → ') : person.unable_reason || 'No remaining route'}</small></div>)}</div>}
              {simulation && <div className="report-actions"><strong>Export this run</strong><button type="button" onClick={() => exportReport('json')} disabled={simBusy || Boolean(exporting)}><Download size={14}/>{exporting === 'json' ? 'Preparing…' : 'JSON report'}</button><button type="button" onClick={() => exportReport('csv')} disabled={simBusy || Boolean(exporting)}><Download size={14}/>{exporting === 'csv' ? 'Preparing…' : 'CSV report'}</button></div>}
              {simulation && <div className="simulation-events"><div className="timeline-heading"><strong>Simulation timeline</strong><label>Filter <select value={eventFilter} onChange={(event) => setEventFilter(event.target.value)}><option value="all">All events</option><option value="simulation_step">Simulation steps</option><option value="hazard">Hazards</option><option value="exit">Exit changes</option><option value="route_replanned">Route replanning</option><option value="evacuee">Evacuee outcomes</option><option value="simulation_terminated">Termination</option></select></label></div>{filteredEvents.length ? <ol className="timeline-list">{filteredEvents.map((event) => <li key={event.sequence}><span className="timeline-marker"/><div><strong>{event.event_type.replaceAll('_', ' ')}</strong><small>Step {event.step} · {event.time_seconds}s{event.evacuee_id ? ` · ${event.evacuee_id}` : ''}</small>{event.event_type === 'route_replanned' && <p>{(event.details.previous_route || []).join(' → ')} <b>→</b> {(event.details.route || []).join(' → ')}</p>}{event.event_type === 'routes_recalculated' && <p>{event.details.count ?? 0} route changes · {event.details.reason}</p>}{event.details?.reason && !['route_replanned', 'routes_recalculated'].includes(event.event_type) && <p>{event.details.reason}</p>}</div></li>)}</ol> : <p className="empty-events">No events match this filter yet.</p>}</div>}
            </div>
          </div>
        </section>
        <AdvancedWorkspace building={building} selectedFloorId={selectedFloorId} floorStats={floorStats} comparison={comparison} simulation={simulation} result={result} room={room} algorithm={algorithm} costModel={costModel} scenarioChoice={scenarioChoice} onApplyScenario={applySavedScenario} onCustomBuildingSaved={applyCustomBuilding} />
        <div className="bottom-note"><span><Activity size={14}/> Evacuation system ready</span><span>Sample building graph loaded <span className="sync-dot"/></span></div>
      </div>
    </main>
  </div>
}

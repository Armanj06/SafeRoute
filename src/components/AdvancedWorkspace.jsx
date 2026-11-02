import { useEffect, useMemo, useState } from 'react'
import { api } from '../services/api.js'

const PALETTE = [
  { type: 'room', label: 'Room', icon: '□' },
  { type: 'lab', label: 'Computer lab', icon: '⌘' },
  { type: 'staircase', label: 'Staircase', icon: '↕' },
  { type: 'elevator', label: 'Elevator', icon: '⇅' },
  { type: 'exit', label: 'Emergency exit', icon: '⇧' },
]

const keyFor = (value) => `saferoute.saved.${value}`

export default function AdvancedWorkspace({ building, selectedFloorId, floorStats = [], comparison, simulation, result, room, algorithm, costModel, scenarioChoice, onApplyScenario, onCustomBuildingSaved }) {
  const [editorFloor, setEditorFloor] = useState(selectedFloorId || building?.floors?.[0]?.id || '')
  const [editorNodes, setEditorNodes] = useState([])
  const [savedScenarios, setSavedScenarios] = useState(() => {
    try { return JSON.parse(localStorage.getItem(keyFor('scenarios')) || '[]') } catch { return [] }
  })
  const [dragType, setDragType] = useState('')
  const [notice, setNotice] = useState('')
  const [editorCorridors, setEditorCorridors] = useState([])
  const [connectMode, setConnectMode] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [saveBusy, setSaveBusy] = useState(false)

  useEffect(() => { if (selectedFloorId) setEditorFloor(selectedFloorId) }, [selectedFloorId])
  useEffect(() => { try { localStorage.setItem(keyFor('scenarios'), JSON.stringify(savedScenarios)) } catch { /* storage may be disabled */ } }, [savedScenarios])

  const alerts = useMemo(() => {
    const conditions = simulation?.effective_conditions || {}
    const items = []
    ;(simulation?.hazards || []).filter((hazard) => hazard.active).forEach((hazard) => items.push({ level: 'critical', title: `${hazard.hazard_type.replaceAll('_', ' ')} active`, detail: `Affected target: ${hazard.target_id}` }))
    ;(conditions.blocked_corridors || []).forEach((corridor) => items.push({ level: 'warning', title: `Corridor ${corridor} blocked`, detail: 'Routes will avoid this segment and may be recalculated.' }))
    ;(conditions.unavailable_exits || []).forEach((exit) => items.push({ level: 'warning', title: `${exit} unavailable`, detail: 'Evacuees will be directed to another modeled exit.' }))
    if (simulation && !simulation.analytics?.evacuation_complete && simulation.analytics?.unable_to_evacuate > 0) items.push({ level: 'critical', title: 'People need assistance', detail: `${simulation.analytics.unable_to_evacuate} evacuee(s) have no safe route.` })
    return items
  }, [simulation])

  const comparisonRows = comparison?.results?.filter((entry) => entry.found) || []
  const maxTravel = Math.max(...comparisonRows.map((entry) => Number(entry.estimated_travel_time_seconds) || 0), 1)
  const floorMax = Math.max(...floorStats.map((floor) => floor.total || 0), 1)

  function dropNode(event) {
    event.preventDefault()
    const type = dragType || event.dataTransfer.getData('text/plain')
    if (!type) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = Math.min(88, Math.max(8, ((event.clientX - bounds.left) / bounds.width) * 100))
    const y = Math.min(88, Math.max(8, ((event.clientY - bounds.top) / bounds.height) * 100))
    const palette = PALETTE.find((item) => item.type === type)
    setEditorNodes((current) => [...current, { id: `${type}-${Date.now()}`, type, label: palette?.label || type, x, y }])
    setDragType('')
  }

  function selectEditorNode(nodeId) {
    if (!connectMode) return
    if (!selectedNodeId) { setSelectedNodeId(nodeId); return }
    if (selectedNodeId !== nodeId && !editorCorridors.some((edge) => (edge.from === selectedNodeId && edge.to === nodeId) || (edge.from === nodeId && edge.to === selectedNodeId))) {
      const from = editorNodes.find((node) => node.id === selectedNodeId)
      const to = editorNodes.find((node) => node.id === nodeId)
      const distance = Math.max(1, Math.round(Math.hypot((from.x - to.x) * 9.2, (from.y - to.y) * 6.4) / 2))
      setEditorCorridors((current) => [...current, { id: `corridor-${Date.now()}`, from: from.id, to: to.id, distance, travel_time_seconds: Number((distance / 1.2).toFixed(1)), capacity: 20 }])
    }
    setSelectedNodeId('')
  }

  async function saveBuildingMap() {
    const rooms = editorNodes.filter((node) => ['room', 'lab'].includes(node.type))
    const exits = editorNodes.filter((node) => node.type === 'exit')
    if (!rooms.length || !exits.length) { setNotice('Add at least one room and one emergency exit before saving the map.'); return }
    if (!editorCorridors.length) { setNotice('Connect the map nodes with at least one corridor before saving.'); return }
    setSaveBusy(true)
    try {
      const floor = building?.floors?.find((item) => item.id === editorFloor) || { id: editorFloor || 'custom-floor', name: 'Custom Floor', level: 0 }
      const payload = {
        id: `custom-${Date.now()}`,
        name: 'My SafeRoute building design',
        floors: [{ id: floor.id, name: floor.name, level: floor.level || 0 }],
        nodes: editorNodes.map((node) => ({ id: node.id, label: node.label, type: node.type === 'lab' ? 'area' : node.type, floor_id: floor.id, x: Math.round(node.x * 9.2), y: Math.round(node.y * 6.4) })),
        corridors: editorCorridors.map((edge) => ({ ...edge, travel_time_seconds: edge.travel_time_seconds })),
        exit_ids: exits.map((node) => node.id),
      }
      const { data } = await api.saveCustomBuilding(payload)
      onCustomBuildingSaved?.(data)
      setNotice('Custom building saved. The planner is now using your design.')
    } catch (error) {
      setNotice(error.message || 'Could not save this building design.')
    } finally { setSaveBusy(false) }
  }

  function removeEditorNode(nodeId) {
    setEditorNodes((current) => current.filter((item) => item.id !== nodeId))
    setEditorCorridors((current) => current.filter((edge) => edge.from !== nodeId && edge.to !== nodeId))
  }

  function saveScenario() {
    const item = { id: Date.now(), name: `Scenario ${savedScenarios.length + 1}`, savedAt: new Date().toLocaleString(), floorId: selectedFloorId, room, algorithm, costModel, scenarioChoice }
    setSavedScenarios((current) => [item, ...current].slice(0, 8))
    setNotice('Scenario saved locally in this browser.')
  }

  function exportDesign() {
    const blob = new Blob([JSON.stringify({ floor: editorFloor, nodes: editorNodes }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'saferoute-building-design.json'; link.click(); URL.revokeObjectURL(url)
  }

  return <section className="advanced-workspace" id="advanced-workspace">
    <div className="advanced-heading"><div><div className="eyebrow">ADVANCED WORKSPACE</div><h2>Design, compare, and document the response</h2><p>These tools sit on top of the working graph and simulation so your analysis stays easy to explain.</p></div><div className="advanced-actions"><button type="button" onClick={() => window.print()}>Print / Save PDF</button><button type="button" className="primary-action" onClick={saveScenario}>Save scenario</button></div></div>
    {notice && <div className="advanced-notice" role="status">{notice}</div>}
    <div className="advanced-grid">
      <article className="advanced-card editor-card"><div className="advanced-card-heading"><div><span className="panel-kicker">BUILDING EDITOR</span><h3>Design and calculate your own map</h3></div><div className="editor-card-actions"><button type="button" onClick={exportDesign}>Export design</button><button type="button" className="editor-save-button" onClick={saveBuildingMap} disabled={saveBusy}>{saveBusy ? 'Saving…' : 'Save map & use it'}</button></div></div><p className="advanced-help">Drag components onto the floor, enable connection mode, then click two components to create a corridor. Saving converts your design into a routable graph.</p><div className="editor-toolbar"><select value={editorFloor} onChange={(event) => setEditorFloor(event.target.value)}>{(building?.floors || []).map((floor) => <option value={floor.id} key={floor.id}>{floor.name}</option>)}</select><button type="button" className={connectMode ? 'connect-active' : ''} onClick={() => { setConnectMode((value) => !value); setSelectedNodeId('') }}>{connectMode ? 'Connection mode on' : 'Connect corridors'}</button><button type="button" onClick={() => { setEditorNodes([]); setEditorCorridors([]) }}>Clear preview</button></div><div className="editor-body"><div className="editor-palette">{PALETTE.map((item) => <button key={item.type} draggable onDragStart={(event) => { setDragType(item.type); event.dataTransfer.setData('text/plain', item.type) }} type="button"><span>{item.icon}</span>{item.label}</button>)}</div><div className="editor-canvas" onDragOver={(event) => event.preventDefault()} onDrop={dropNode}><span className="editor-canvas-label">{building?.floors?.find((floor) => floor.id === editorFloor)?.name || 'Selected floor'} · {connectMode ? 'click two nodes to connect' : 'design preview'}</span><svg className="editor-lines" viewBox="0 0 100 100" preserveAspectRatio="none">{editorCorridors.map((edge) => { const from = editorNodes.find((node) => node.id === edge.from); const to = editorNodes.find((node) => node.id === edge.to); return from && to ? <line key={edge.id} x1={from.x} y1={from.y} x2={to.x} y2={to.y} /> : null })}</svg>{editorNodes.map((node) => <button key={node.id} type="button" className={`editor-node ${node.type} ${selectedNodeId === node.id ? 'editor-node-selected' : ''}`} style={{ left: `${node.x}%`, top: `${node.y}%` }} onClick={() => connectMode ? selectEditorNode(node.id) : removeEditorNode(node.id)} title={connectMode ? 'Select this node to connect it' : 'Click to remove'}><b>{PALETTE.find((item) => item.type === node.type)?.icon}</b><span>{node.label}</span></button>)}{!editorNodes.length && <span className="editor-empty">Drop a room, lab, staircase, elevator, or exit here</span>}</div></div></article>
      <article className="advanced-card alert-card"><div className="advanced-card-heading"><div><span className="panel-kicker">EMERGENCY CONTROL</span><h3>Live alerts and route warnings</h3></div><span className={`alert-count ${alerts.length ? 'active' : ''}`}>{alerts.length} alert{alerts.length === 1 ? '' : 's'}</span></div>{alerts.length ? <div className="alert-list">{alerts.map((alert, index) => <div className={`alert-item ${alert.level}`} key={`${alert.title}-${index}`}><span>!</span><div><strong>{alert.title}</strong><small>{alert.detail}</small></div></div>)}</div> : <div className="all-clear"><span>✓</span><div><strong>No active emergency restrictions</strong><small>Start a simulation or activate a hazard to see live warnings.</small></div></div>}{simulation?.status === 'running' && <div className="movement-indicator"><i/><i/><i/> Evacuees are moving through the model</div>}</article>
      <article className="advanced-card chart-card"><div className="advanced-card-heading"><div><span className="panel-kicker">ALGORITHM COMPARISON</span><h3>Travel-time profile</h3></div><span className="chart-caption">seconds</span></div>{comparisonRows.length ? <div className="bar-chart">{comparisonRows.map((entry) => <div className="bar-row" key={entry.algorithm}><span>{entry.algorithm === 'astar' ? 'A*' : entry.algorithm === 'utility' ? 'Utility AI' : entry.algorithm.toUpperCase()}</span><div><i style={{ width: `${Math.max(5, ((Number(entry.estimated_travel_time_seconds) || 0) / maxTravel) * 100)}%` }}/></div><b>{Number(entry.estimated_travel_time_seconds || 0).toFixed(1)}s</b></div>)}</div> : <p className="chart-empty">Run “Compare all four strategies” to populate this chart.</p>}</article>
      <article className="advanced-card chart-card"><div className="advanced-card-heading"><div><span className="panel-kicker">FLOOR COMPARISON</span><h3>Evacuation progress by floor</h3></div><span className="chart-caption">people</span></div>{floorStats.length ? <div className="bar-chart floor-chart">{floorStats.map((floor) => <div className="bar-row" key={floor.id}><span>{floor.name.replace('Floor ', 'F')}</span><div><i style={{ width: `${Math.max(5, ((floor.total || 0) / floorMax) * 100)}%` }}/></div><b>{floor.evacuated || 0}/{floor.total || 0}</b></div>)}</div> : <p className="chart-empty">Create a simulation to see floor-level progress.</p>}</article>
      <article className="advanced-card scenario-card"><div className="advanced-card-heading"><div><span className="panel-kicker">SCENARIO LIBRARY</span><h3>Save and reload your test cases</h3></div><span className="chart-caption">local</span></div>{savedScenarios.length ? <div className="saved-list">{savedScenarios.map((item) => <div className="saved-item" key={item.id}><div><strong>{item.name}</strong><small>{item.savedAt} · {item.algorithm.toUpperCase()}</small></div><button type="button" onClick={() => { onApplyScenario?.(item); setNotice(`${item.name} loaded into the planner.`) }}>Load</button></div>)}</div> : <p className="chart-empty">Save the current room, floor, algorithm, and scenario controls here for your next demonstration.</p>}</article>
    </div>
    <div className="advanced-footnote">{result?.found ? `Current route: ${result.distance}m · ${Number(result.estimated_travel_time_seconds || 0).toFixed(1)}s estimated walking time.` : 'Tip: use the editor for explaining a floor plan, then use the live map for validated routing.'}</div>
  </section>
}

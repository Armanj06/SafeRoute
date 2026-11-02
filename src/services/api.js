const API_URL = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function detailMessage(payload) {
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg).filter(Boolean).join('; ')
  }
  if (typeof payload?.detail === 'string') return payload.detail
  if (typeof payload?.message === 'string') return payload.message
  return ''
}

async function request(path, { method = 'GET', body, signal, responseType = 'json' } = {}) {
  let response
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      signal,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError('The planning API is unreachable. Check that the backend is running.')
  }

  const contentType = response.headers.get('content-type') || ''
  if (response.ok && responseType === 'raw') return { data: null, response }
  let payload
  try {
    payload = contentType.includes('json') ? await response.json() : await response.text()
  } catch {
    throw new ApiError('The API returned an unreadable response.', response.status)
  }
  if (!response.ok) {
    throw new ApiError(detailMessage(payload) || `The API request failed (${response.status}).`, response.status)
  }
  if (contentType.includes('json') && (payload === null || typeof payload !== 'object')) {
    throw new ApiError('The API returned an unexpected response.', response.status)
  }
  return { data: payload, response }
}

const post = (path, body, options) => request(path, { ...options, method: 'POST', body })

function simulationPath(id, suffix = '') {
  return `/api/simulations/${encodeURIComponent(id)}${suffix}`
}

export const api = {
  baseUrl: API_URL,
  get: (path, options) => request(path, options),
  post: (path, body, options) => post(path, body, options),
  health: (options) => request('/api/health', options),
  campus: (options) => request('/api/campus', options),
  building: (options) => request('/api/building', options),
  buildingById: (id, options) => request(`/api/building?building_id=${encodeURIComponent(id)}`, options),
  saveCustomBuilding: (body, options) => post('/api/custom-buildings', body, options),
  scenarios: (options) => request('/api/scenarios', options),
  scenario: (id, options) => request(`/api/scenarios/${encodeURIComponent(id)}`, options),
  startScenario: (id, options) => post(`/api/scenarios/${encodeURIComponent(id)}/start`, {}, options),
  route: (body, options) => post('/api/route', body, options),
  utilityRoute: (body, options) => post('/api/route/utility', body, options),
  compareRoutes: (body, options) => post('/api/route/compare', body, options),
  createSimulation: (body, options) => post('/api/simulations', body, options),
  simulation: (id, options) => request(simulationPath(id), options),
  summary: (id, options) => request(simulationPath(id, '/summary'), options),
  events: (id, params = {}, options) => {
    const query = new URLSearchParams(params).toString()
    return request(`${simulationPath(id, '/events')}${query ? `?${query}` : ''}`, options)
  },
  startSimulation: (id, options) => post(simulationPath(id, '/start'), {}, options),
  pauseSimulation: (id, options) => post(simulationPath(id, '/pause'), {}, options),
  stepSimulation: (id, body, options) => post(simulationPath(id, '/step'), body, options),
  resetSimulation: (id, options) => post(simulationPath(id, '/reset'), {}, options),
  createHazard: (id, body, options) => post(simulationPath(id, '/hazards'), body, options),
  hazards: (id, params = {}, options) => {
    const query = new URLSearchParams(params).toString()
    return request(`${simulationPath(id, '/hazards')}${query ? `?${query}` : ''}`, options)
  },
  setHazardActive: (id, hazardId, active, options) => post(simulationPath(id, `/hazards/${encodeURIComponent(hazardId)}/${active ? 'activate' : 'deactivate'}`), {}, options),
  setExitAvailable: (id, exitId, available, options) => post(simulationPath(id, `/exits/${encodeURIComponent(exitId)}/${available ? 'restore' : 'unavailable'}`), {}, options),
  conditions: (id, options) => request(simulationPath(id, '/conditions'), options),
  report: (id, format, options = {}) => request(`${simulationPath(id, '/report')}?format=${encodeURIComponent(format)}`, { ...options, responseType: 'raw' }),
}

export async function downloadSimulationReport(id, format) {
  const { response } = await api.report(id, format)
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
    || `evacuation-report-${id}.${format}`
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}

import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError, api } from './api.js'

test('route calls use the configurable base URL and JSON body', async () => {
  const originalFetch = globalThis.fetch
  let request
  globalThis.fetch = async (url, options) => {
    request = { url, options }
    return new Response(JSON.stringify({ found: true, route: ['room', 'exit'] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const { data } = await api.route({ starting_room: 'room', algorithm: 'dijkstra' })
    assert.equal(request.url, `${api.baseUrl}/api/route`)
    assert.equal(request.options.method, 'POST')
    assert.deepEqual(JSON.parse(request.options.body), { starting_room: 'room', algorithm: 'dijkstra' })
    assert.deepEqual(data.route, ['room', 'exit'])
  } finally { globalThis.fetch = originalFetch }
})

test('campus catalog and selected building use backend data endpoints', async () => {
  const originalFetch = globalThis.fetch
  const requested = []
  globalThis.fetch = async (url) => {
    requested.push(url)
    return new Response(JSON.stringify({ models: [], nodes: [] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await api.campus()
    await api.buildingById('dit-vedanta-illustrative')
    assert.deepEqual(requested, [
      `${api.baseUrl}/api/campus`,
      `${api.baseUrl}/api/building?building_id=dit-vedanta-illustrative`,
    ])
  } finally { globalThis.fetch = originalFetch }
})

test('HTTP validation errors are exposed as readable API errors', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Unknown starting room.' }), {
    status: 422, headers: { 'Content-Type': 'application/json' },
  })
  try {
    await assert.rejects(api.route({ starting_room: 'missing' }), (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.status, 422)
      assert.equal(error.message, 'Unknown starting room.')
      return true
    })
  } finally { globalThis.fetch = originalFetch }
})

test('report requests leave CSV and JSON bodies available for download', async () => {
  const originalFetch = globalThis.fetch
  let url
  globalThis.fetch = async (requestUrl) => {
    url = requestUrl
    return new Response('record_type,simulation_id\nsummary,run-1\n', {
      status: 200, headers: { 'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename="run.csv"' },
    })
  }
  try {
    const { response } = await api.report('run-1', 'csv')
    assert.match(url, /\/api\/simulations\/run-1\/report\?format=csv$/)
    assert.equal(await response.text(), 'record_type,simulation_id\nsummary,run-1\n')
  } finally { globalThis.fetch = originalFetch }
})

test('malformed JSON responses produce a readable API error', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('{not-json', {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
  try {
    await assert.rejects(api.health(), (error) => {
      assert.ok(error instanceof ApiError)
      assert.equal(error.message, 'The API returned an unreadable response.')
      return true
    })
  } finally { globalThis.fetch = originalFetch }
})

test('event filters are encoded with the existing event endpoint schema', async () => {
  const originalFetch = globalThis.fetch
  let requestedUrl
  globalThis.fetch = async (url) => {
    requestedUrl = url
    return new Response(JSON.stringify({ simulation_id: 'run 1', events: [] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await api.events('run 1', { after_sequence: 3, event_type: 'route_replanned' })
    assert.match(requestedUrl, /run%201\/events\?after_sequence=3&event_type=route_replanned$/)
  } finally { globalThis.fetch = originalFetch }
})

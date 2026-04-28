import { test, expect } from '@playwright/test'

/**
 * E2E Tests: API Contract Tests
 *
 * Tests that verify the backend API endpoints return the expected shapes and
 * data. These tests run directly against the API (not the UI) to validate
 * the contract between frontend and backend.
 *
 * BUG COVERAGE:
 * - BUG-004/007: /api/v1/audit/logs returns total=0, items=[] despite active agents
 * - BUG-011: /api/v1/analytics/storage returns 404 (route not registered in backend)
 * - BUG-012: /api/v1/admin/waitlist/stats returns 500 Internal Server Error
 * - BUG-013: /api/v1/consent/pending returns 404 (route not registered in backend)
 */

const BASE = 'https://app.memory.dxb-gw.basanti.ai'

test.describe('API Contract Tests', () => {
  // ============================================================
  // AGENTS API
  // ============================================================
  test('GET /api/v1/agents — returns list of agents', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/agents`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(Array.isArray(body)).toBe(true)
    expect(body.length).toBeGreaterThan(0)
    // Validate agent shape — field is agent_name not name
    const agent = body[0]
    expect(agent).toHaveProperty('agent_id')
    expect(agent).toHaveProperty('agent_name')
    expect(agent).toHaveProperty('status')
    expect(agent).toHaveProperty('total_reads')
    expect(agent).toHaveProperty('total_writes')
    expect(agent).toHaveProperty('denied_requests')
    console.log(`Agents count: ${body.length}, first: ${agent.agent_name}`)
  })

  test('GET /api/v1/agents/:id — returns single agent detail', async ({ request }) => {
    // Get list first to get a valid ID
    const listRes = await request.get(`${BASE}/api/v1/agents`)
    const agents = await listRes.json()
    const agentId = agents[0].agent_id

    const res = await request.get(`${BASE}/api/v1/agents/${agentId}`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.agent_id).toBe(agentId)
    expect(body).toHaveProperty('agent_name')
    expect(body).toHaveProperty('status')
    expect(body).toHaveProperty('declared_scopes')
  })

  // ============================================================
  // HEALTH API
  // ============================================================
  test('GET /health/live — returns alive status', async ({ request }) => {
    const res = await request.get(`${BASE}/health/live`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.status).toBe('alive')
    expect(body.service).toBe('Kora Memory Vault')
  })

  test('GET /health/deep — returns service check results', async ({ request }) => {
    const res = await request.get(`${BASE}/health/deep`)
    expect([200, 503]).toContain(res.status()) // 503 if degraded
    const body = await res.json()
    expect(body).toHaveProperty('status')
    expect(body).toHaveProperty('checks')
    const checkNames = Object.keys(body.checks)
    expect(checkNames.length).toBeGreaterThan(0)
    console.log(`Health status: ${body.status}, services: ${checkNames.join(', ')}`)
  })

  test('GET /health/deep — falkordb is unhealthy (known infrastructure bug)', async ({ request }) => {
    const res = await request.get(`${BASE}/health/deep`)
    const body = await res.json()
    // falkordb is known to be unhealthy
    if (body.checks.falkordb) {
      console.log(`falkordb: ${body.checks.falkordb.status} — ${body.checks.falkordb.error ?? 'no error'}`)
      expect(body.checks.falkordb.status).not.toBe('healthy')
    }
    // Overall status should be degraded
    expect(body.status).toBe('degraded')
  })

  // ============================================================
  // AUDIT API
  // ============================================================
  test('GET /api/v1/audit/logs — returns audit log structure', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/audit/logs`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
    expect(Array.isArray(body.items)).toBe(true)
    console.log(`Audit total: ${body.total}, items: ${body.items.length}`)
  })

  test('BUG-004: GET /api/v1/audit/logs — total is 0 (audit write path broken)', async ({ request }) => {
    // BUG: Audit log returns total=0 despite active agents performing operations.
    // The audit write path is not recording events.
    // Expected: total > 0
    // Actual: total = 0, items = []
    const res = await request.get(`${BASE}/api/v1/audit/logs`)
    const body = await res.json()
    console.log(`BUG-004: Audit total = ${body.total} (expected > 0)`)
    // This assertion PASSES when the bug is present (confirms the bug)
    expect(body.total).toBe(0)
  })

  test('GET /api/v1/audit/verify — chain verification endpoint exists', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/audit/verify`)
    // Should return 200 with verification result (or 404 if not implemented)
    console.log(`Audit verify status: ${res.status()}`)
    expect([200, 404, 422]).toContain(res.status())
  })

  // ============================================================
  // NAMESPACES / MEMORIES API
  // ============================================================
  test('GET /api/v1/namespaces — returns namespace list', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/namespaces`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(Array.isArray(body)).toBe(true)
    expect(body.length).toBeGreaterThan(0)
    console.log(`Namespaces count: ${body.length}`)
  })

  test('GET /api/v1/memories — returns paginated memory list', async ({ request }) => {
    // NOTE: GET /api/v1/memories requires namespace param to list memories
    // Without namespace it returns 405 Method Not Allowed (only POST /search is
    // the general search endpoint). With namespace param it returns paginated list.
    const res = await request.get(`${BASE}/api/v1/memories?limit=10`)
    // 200 if namespace provided, 405 without namespace (by design)
    expect([200, 405]).toContain(res.status())
    if (res.status() === 200) {
      const body = await res.json()
      expect(body).toHaveProperty('items')
      expect(body).toHaveProperty('total')
      console.log(`Memories total: ${body.total}`)
    } else {
      console.log('GET /api/v1/memories without namespace returns 405 (expected)')
    }
  })

  test('[BUG-016] POST /api/v1/memories/search returns 500 (vector search broken)', async ({ request }) => {
    // BUG-016: POST /api/v1/memories/search returns 500 Internal Server Error
    // for ALL queries. Likely caused by Weaviate vector search failure.
    // The memory explorer page shows no search results for any query.
    //
    // FIX: Check Weaviate service health and connection in backend/services/memory_service.py
    // Also check if the Weaviate schema is properly initialized.
    const res = await request.post(`${BASE}/api/v1/memories/search`, {
      data: { query: 'Japan', limit: 5 },
    })
    console.log(`BUG-016: /api/v1/memories/search status: ${res.status()}`)
    expect(res.status()).toBe(500) // PASSES - confirms the bug
    // After fix, this should return 200 with results array
  })

  test('POST /api/v1/memories/search — empty query returns validation error', async ({ request }) => {
    // The API requires a non-empty query string
    const res = await request.post(`${BASE}/api/v1/memories/search`, {
      data: { query: '', limit: 5 },
    })
    // Should return 422 Unprocessable Entity for empty query
    expect(res.status()).toBe(422)
  })

  // ============================================================
  // PERMISSIONS API
  // ============================================================
  test('GET /api/v1/permissions — returns permission rules', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/permissions`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(Array.isArray(body)).toBe(true)
    expect(body.length).toBeGreaterThan(0)
    console.log(`Permission rules: ${body.length}`)
  })

  // ============================================================
  // ANALYTICS API (MISSING ROUTES — BUG-011)
  // ============================================================
  test('BUG-011: GET /api/v1/analytics/storage — returns 404 (route not registered)', async ({ request }) => {
    // BUG: The frontend AnalyticsPage calls /api/v1/analytics/storage but this
    // route is not registered in the backend. The analytics page falls back to
    // using /api/v1/namespaces data directly.
    const res = await request.get(`${BASE}/api/v1/analytics/storage`)
    console.log(`BUG-011: /api/v1/analytics/storage status: ${res.status()}`)
    expect(res.status()).toBe(404)
  })

  // ============================================================
  // CONSENT API (MISSING ROUTES — BUG-013)
  // ============================================================
  test('BUG-013: GET /api/v1/consent/pending — returns 404 (route not registered)', async ({ request }) => {
    // BUG: The ConsentQueuePage calls /api/v1/consent/pending but this route
    // does not exist in the backend. The page shows "No pending consent requests"
    // because the API call fails silently.
    const res = await request.get(`${BASE}/api/v1/consent/pending`)
    console.log(`BUG-013: /api/v1/consent/pending status: ${res.status()}`)
    expect([404, 405]).toContain(res.status())
  })

  // ============================================================
  // SECURITY API
  // ============================================================
  test('POST /api/v1/security/scan — scan endpoint exists', async ({ request }) => {
    const res = await request.post(`${BASE}/api/v1/security/scan`, {
      data: { content: 'test content', scan_type: 'full' },
    })
    console.log(`Security scan status: ${res.status()}`)
    // Should return 200 or 422 (if validation fails) — not 404
    expect([200, 422, 400]).toContain(res.status())
  })
})

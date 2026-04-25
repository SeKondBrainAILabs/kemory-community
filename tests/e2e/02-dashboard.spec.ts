import { test, expect } from '@playwright/test'

/**
 * Dashboard Overview Tests
 *
 * Validates the stat cards, Service Health section, and Recent Activity feed.
 *
 * WIRING AUDIT COVERAGE:
 * - BUG-001: System Health stat card stuck in skeleton (nginx /health redirect)
 * - BUG-002: Audit total = 0 (log_audit_event never called from any service)
 * - BUG-004: Agent reads/writes/denied always 0 (counters never incremented)
 * - BUG-005: FalkorDB unhealthy (connection error to falkordb:6379)
 */

const BASE = 'https://app.memory.dxb-gw.basanti.ai'

test.describe('Dashboard Overview — UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')
    // Wait for the main content area to appear (not networkidle which hangs on Keycloak)
    await page.waitForSelector('nav, [class*="sidebar"], [class*="layout"]', { timeout: 10000 })
  })

  test('Dashboard page loads and shows main layout', async ({ page }) => {
    await expect(page).toHaveTitle(/Kora|Memory Vault|Dashboard/i)
    // Main navigation should be present
    const nav = page.locator('nav').first()
    await expect(nav).toBeVisible({ timeout: 5000 })
  })

  test('Sidebar navigation links are present', async ({ page }) => {
    // Check key sidebar links exist
    const agentsLink = page.locator('a[href="/agents"]').first()
    await expect(agentsLink).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Dashboard Overview — API-based checks', () => {
  // These tests use the request API directly (no browser rendering needed)
  // They are fast and reliable regardless of Keycloak state

  test('Agents stat card data: GET /api/v1/agents returns agents', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/agents`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
    expect(data.length).toBeGreaterThan(0)
    expect(data[0]).toHaveProperty('agent_id')
    expect(data[0]).toHaveProperty('agent_name')
    expect(data[0]).toHaveProperty('status')
    console.log(`Dashboard Agents card: ${data.length} agents`)
  })

  test('Memories stat card data: GET /api/v1/namespaces returns namespaces', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/namespaces`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
    expect(data.length).toBeGreaterThan(0)
    expect(data[0]).toHaveProperty('namespace')
    expect(data[0]).toHaveProperty('count')
    const totalMemories = data.reduce((sum: number, ns: { count: number }) => sum + ns.count, 0)
    console.log(`Dashboard Memories card: ${totalMemories} memories in ${data.length} namespaces`)
  })

  test('[BUG-001] Health card data: GET /health/deep API works but browser nav to /health fails', async ({ request }) => {
    // The API endpoint itself works correctly (returns 200 OK or 503 when degraded)
    const res = await request.get(`${BASE}/health/deep`)
    expect([200, 503]).toContain(res.status())
    const data = await res.json()
    expect(data).toHaveProperty('status')
    expect(data).toHaveProperty('checks')
    // But browser navigation to /health triggers nginx redirect bug (see 01-navigation.spec.ts)
    console.log(`Health API status: ${data.status}, services: ${Object.keys(data.checks).join(', ')}`)
  })

  test('[BUG-002] Audit stat card: GET /api/v1/audit/logs always returns 0 (write path broken)', async ({ request }) => {
    // BUG-002: log_audit_event() is never called from any backend service.
    // The audit log is always empty despite active agents performing operations.
    //
    // FIX REQUIRED in:
    //   backend/services/memory_service.py: add log_audit_event() to create/update/delete/search
    //   backend/services/agent_service.py: add log_audit_event() to register/approve/suspend/revoke
    //   backend/services/gatekeeper_service.py: add log_audit_event() on deny/jit_pending outcomes
    const res = await request.get(`${BASE}/api/v1/audit/logs?limit=5`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('items')
    expect(data).toHaveProperty('total')
    // BUG-002: This assertion confirms the bug (total is 0)
    expect(data.total).toBe(0)
    console.log(`BUG-002 CONFIRMED: Audit total = ${data.total} (expected > 0 with active agents)`)
  })

  test('[BUG-004] Agent stats: total_reads/total_writes/denied_requests are always 0', async ({ request }) => {
    // BUG-004: The counter columns exist in the DB schema but are never incremented.
    // memory_service.py does not call agent.total_reads++ or agent.total_writes++
    // gatekeeper_service.py does not call agent.denied_requests++ on deny
    const res = await request.get(`${BASE}/api/v1/agents`)
    const agents = await res.json()
    for (const agent of agents) {
      expect(agent.total_reads).toBe(0)
      expect(agent.total_writes).toBe(0)
      expect(agent.denied_requests).toBe(0)
    }
    console.log(`BUG-004 CONFIRMED: All ${agents.length} agents have 0/0/0 reads/writes/denied`)
  })

  test('[BUG-005] FalkorDB is unhealthy in health/deep response', async ({ request }) => {
    // BUG-005: FalkorDB container has connection error: "Error -2 connecting to falkordb:6379"
    // This causes the overall system status to be "degraded"
    //
    // FIX: Check docker-compose falkordb service configuration and network connectivity
    const res = await request.get(`${BASE}/health/deep`)
    const data = await res.json()
    expect(data.status).toBe('degraded')
    expect(data.checks.falkordb.status).toBe('unhealthy')
    console.log(`BUG-005 CONFIRMED: falkordb status = ${data.checks.falkordb.status}`)
    console.log(`  Error: ${data.checks.falkordb.error}`)
  })
})

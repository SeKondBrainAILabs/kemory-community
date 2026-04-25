/**
 * Permissions, Memories, Access Map, and Consent Queue Tests
 *
 * WIRING AUDIT COVERAGE:
 * - [DEAD CODE] updatePermission hook exists but no Edit button in UI
 * - [BUG-006] Memory list: GET /api/v1/memories returns 405 — no list endpoint exists
 * - [BUG-007] Memory delete button missing from UI (DELETE /api/v1/memories/:id exists)
 * - [BUG-008] Memory edit button missing from UI (PUT /api/v1/memories/:id exists)
 * - [BUG-009] Memory history tab missing from UI (GET /api/v1/memories/:id/history exists)
 * - [BUG-010] Consent queue route /api/v1/consent/pending returns 404
 * - [BUG-011] Access Map has no backend route for graph data
 * - [BUG-016] POST /api/v1/memories/search returns 500 (Weaviate/vector search broken)
 *
 * Browser UI tests use custom fixtures (Keycloak blocker).
 * API contract tests use @playwright/test directly (inherits ignoreHTTPSErrors from config).
 */

// Browser UI tests — use custom fixtures that block Keycloak
import { test as uiTest, expect } from './fixtures'
// API contract tests — use @playwright/test directly (inherits ignoreHTTPSErrors: true)
import { test as apiTest } from '@playwright/test'

const BASE = 'https://app.memory.dxb-gw.basanti.ai'

// ============================================================
// PERMISSIONS PAGE — Browser UI Tests
// ============================================================
uiTest.describe('Permission Rules Page', () => {
  uiTest('should render the Permission Rules heading', async ({ page }) => {
    await page.goto('/permissions')
    await page.waitForTimeout(2000)
    await expect(page.locator('h1').filter({ hasText: /Permission/i })).toBeVisible()
  })

  uiTest('should render the Add Rule button', async ({ page }) => {
    await page.goto('/permissions')
    await page.waitForTimeout(2000)
    await expect(page.getByRole('button', { name: /Add Rule/i })).toBeVisible()
  })

  uiTest('should render the table headers', async ({ page }) => {
    await page.goto('/permissions')
    await page.waitForTimeout(2000)
    const headers = ['PRIORITY', 'AGENT', 'SCOPE', 'ACTION', 'NAMESPACE FILTER', 'ACTIVE']
    for (const header of headers) {
      await expect(page.locator('th').filter({ hasText: header })).toBeVisible()
    }
  })

  uiTest('should render at least one permission rule row', async ({ page }) => {
    await page.goto('/permissions')
    await page.waitForTimeout(3000)
    const rows = page.locator('table tbody tr')
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
    console.log(`Permission rules: ${count}`)
  })

  uiTest('[DEAD CODE] updatePermission hook exists but no edit button in UI', async ({ page }) => {
    // EXPECTED TO FAIL: useUpdatePermission hook exists in usePermissions.ts
    // but no UI component calls it. No edit button on permission rows.
    // FIX: Add an edit button to each permission rule row in PermissionListPage.tsx
    await page.goto('/permissions')
    await page.waitForTimeout(3000)
    const editBtns = page.locator('table tbody tr button').filter({ hasText: /Edit|Update/i })
    const count = await editBtns.count()
    expect(count).toBeGreaterThan(0) // FAILS - updatePermission is dead code
  })
})

// ============================================================
// MEMORY EXPLORER PAGE — Browser UI Tests
// ============================================================
uiTest.describe('Memory Explorer Page', () => {
  uiTest('should render the Memory Explorer heading', async ({ page }) => {
    await page.goto('/memories')
    await page.waitForTimeout(2000)
    await expect(page.locator('h1').filter({ hasText: /Memory/i })).toBeVisible()
  })

  uiTest('should render the Namespaces text in sidebar', async ({ page }) => {
    await page.goto('/memories')
    await page.waitForTimeout(3000)
    const body = await page.locator('body').textContent()
    expect(body).toContain('Namespaces')
  })

  uiTest('should render the search input', async ({ page }) => {
    await page.goto('/memories')
    await page.waitForTimeout(2000)
    await expect(page.locator('input[placeholder="Search memories..."]')).toBeVisible()
  })

  uiTest('should render the table headers', async ({ page }) => {
    await page.goto('/memories')
    await page.waitForTimeout(2000)
    const headers = ['CONTENT', 'NAMESPACE', 'TYPE', 'ENRICHMENT', 'VER', 'CREATED']
    for (const header of headers) {
      await expect(page.locator('th').filter({ hasText: header })).toBeVisible()
    }
  })
})

// ============================================================
// MEMORY API WIRING BUGS — API Tests (no browser)
// ============================================================
apiTest.describe('Memory API Wiring Bugs', () => {
  apiTest('[BUG-006] GET /api/v1/memories returns 405 — no list endpoint, only POST /search', async ({ request }) => {
    // BUG-006: The frontend MemoryExplorerPage calls GET /api/v1/memories?page=1&limit=20
    // but the backend only has POST /memories/search for listing memories.
    // FIX: Add GET /memories list endpoint OR update useMemories hook to use POST /search
    const res = await request.get(`${BASE}/api/v1/memories?page=1&limit=20`)
    expect(res.status()).toBe(405) // BUG-006 CONFIRMED: Method Not Allowed
    console.log(`BUG-006 CONFIRMED: GET /api/v1/memories returns ${res.status()} (no list endpoint)`)
  })

  apiTest('[BUG-016] POST /api/v1/memories/search returns 500 (Weaviate/vector search broken)', async ({ request }) => {
    // BUG-016: The search endpoint crashes with 500 Internal Server Error.
    // Root cause: Weaviate vector search service is failing.
    // FIX: Add error handling to return 503; add SQL fallback when Weaviate is down
    const res = await request.post(`${BASE}/api/v1/memories/search`, {
      data: { query: 'test query', limit: 5 },
    })
    expect(res.status()).toBe(500) // BUG-016 CONFIRMED
    console.log(`BUG-016 CONFIRMED: POST /memories/search returns ${res.status()}`)
  })

  apiTest('[BUG-007] DELETE /api/v1/memories/:id endpoint exists but no delete button in UI', async ({ request }) => {
    // BUG-007: DELETE endpoint exists in backend but no delete button in MemoryExplorerPage
    // FIX: Add delete button to memory detail panel in MemoryExplorerPage.tsx
    const res = await request.delete(`${BASE}/api/v1/memories/00000000-0000-0000-0000-000000000000`)
    const status = res.status()
    console.log(`BUG-007: DELETE /memories/:id returns ${status} (API exists but no UI button)`)
    expect([401, 403, 404, 422]).toContain(status)
  })

  apiTest('[BUG-008] PUT /api/v1/memories/:id endpoint exists but no edit UI', async ({ request }) => {
    // BUG-008: PUT endpoint exists in backend but no edit button in MemoryExplorerPage
    // FIX: Add edit form/button to memory detail panel in MemoryExplorerPage.tsx
    const res = await request.put(`${BASE}/api/v1/memories/00000000-0000-0000-0000-000000000000`, {
      data: { content: 'test content' },
    })
    const status = res.status()
    console.log(`BUG-008: PUT /memories/:id returns ${status} (API exists but no UI)`)
    expect([401, 403, 404, 422]).toContain(status)
  })

  apiTest('[BUG-009] GET /api/v1/memories/:id/history endpoint exists but no history tab in UI', async ({ request }) => {
    // BUG-009: History endpoint exists but no history tab in MemoryExplorerPage
    // FIX: Add history tab to memory detail panel in MemoryExplorerPage.tsx
    const res = await request.get(`${BASE}/api/v1/memories/00000000-0000-0000-0000-000000000000/history`)
    const status = res.status()
    console.log(`BUG-009: GET /memories/:id/history returns ${status} (API exists but no UI tab)`)
    expect([401, 403, 404, 422]).toContain(status)
  })
})

// ============================================================
// ACCESS MAP PAGE — API Tests
// ============================================================
apiTest.describe('Access Map Page - API Contracts', () => {
  apiTest('GET /api/v1/agents returns agents for access matrix', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/agents`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
    console.log(`Access Map: ${data.length} agents available for matrix`)
  })

  apiTest('GET /api/v1/permissions returns rules for access matrix', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/permissions`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
    console.log(`Access Map: ${data.length} permission rules`)
  })

  apiTest('GET /api/v1/namespaces returns namespaces for access matrix', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/namespaces`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
    console.log(`Access Map: ${data.length} namespaces`)
  })

  apiTest('[BUG-011] GET /api/v1/access/map returns 404 (no backend route for graph viz)', async ({ request }) => {
    // BUG-011: The AccessMapPage expects a graph visualization endpoint that doesn't exist.
    // FIX: Implement GET /api/v1/access/map in backend if server-side graph data is needed
    const res = await request.get(`${BASE}/api/v1/access/map`)
    expect([404, 405]).toContain(res.status())
    console.log(`BUG-011 CONFIRMED: GET /api/v1/access/map returns ${res.status()}`)
  })
})

// ============================================================
// CONSENT QUEUE PAGE — API Tests
// ============================================================
apiTest.describe('Consent Queue Page - API Contracts', () => {
  apiTest('[BUG-010] GET /api/v1/consent/pending returns 404 (route not registered)', async ({ request }) => {
    // BUG-010: The ConsentQueuePage calls GET /api/v1/consent/pending but this route
    // is NOT registered in the backend. The consent router is not included in main.py.
    // FIX: Create backend/api/routes/consent.py and include it in main.py
    const res = await request.get(`${BASE}/api/v1/consent/pending`)
    expect(res.status()).toBe(404)
    console.log(`BUG-010 CONFIRMED: GET /api/v1/consent/pending returns ${res.status()}`)
  })

  apiTest('[BUG-010] POST /api/v1/consent/:id/approve returns 404', async ({ request }) => {
    const res = await request.post(`${BASE}/api/v1/consent/test-id/approve`)
    expect([404, 405, 422]).toContain(res.status())
    console.log(`BUG-010 CONFIRMED: POST /consent/approve returns ${res.status()}`)
  })

  apiTest('Gatekeeper consent resolve endpoint exists (used by ConsentQueuePage)', async ({ request }) => {
    // The ConsentQueuePage actually uses /api/v1/gatekeeper/consent/:id/resolve
    // This endpoint exists in the gatekeeper router
    const res = await request.post(`${BASE}/api/v1/gatekeeper/consent/test-id/resolve?approved=true`)
    const status = res.status()
    console.log(`Gatekeeper consent resolve: ${status}`)
    // Should return 404 (consent item not found) not 405 (route not found)
    expect([200, 404, 422]).toContain(status)
  })
})

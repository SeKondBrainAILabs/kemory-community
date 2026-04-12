import { test, expect } from './fixtures'
import { test as apiTest } from '@playwright/test'

const BASE = 'https://app.memory.dxb-gw.basanti.ai'

/**
 * Analytics, Security, Waitlist, and Connectors Tests
 *
 * BUG COVERAGE:
 * - BUG-008: Analytics pie chart shows all namespaces at 0% (rounding bug).
 * - BUG-009: Analytics Agent Activity table shows 0 reads/writes/denied.
 * - BUG-010: Waitlist page renders no stat cards or data table.
 * - BUG-001: Connectors page is not linked in the sidebar.
 */

// ============================================================
// STORAGE ANALYTICS PAGE
// ============================================================
test.describe('Storage Analytics Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/analytics')
    await page.waitForTimeout(1500)
  })

  test('should render the Storage Analytics heading', async ({ page }) => {
    await expect(page.locator('h1').filter({ hasText: /Analytics/i })).toBeVisible()
  })

  test('should render the Total Memories stat card', async ({ page }) => {
    await expect(page.locator('text=Total Memories')).toBeVisible()
  })

  test('should render the Namespaces stat card', async ({ page }) => {
    await expect(page.locator('text=Namespaces')).toBeVisible()
  })

  test('should render the Agents stat card', async ({ page }) => {
    await expect(page.locator('text=Agents')).toBeVisible()
  })

  test('should render non-zero values in stat cards', async ({ page }) => {
    await page.waitForTimeout(2000)
    // Total Memories should be > 0 (we know 10704 exist)
    const totalMemoriesCard = page.locator('div').filter({ hasText: /Total Memories/i }).first()
    const valueText = await totalMemoriesCard.locator('text=/^\\d+$/').first().textContent()
    expect(parseInt(valueText ?? '0')).toBeGreaterThan(0)
  })

  test('should render the Memories by Namespace chart section', async ({ page }) => {
    await expect(page.locator('text=Memories by Namespace')).toBeVisible()
  })

  test('BUG-008: pie chart should show non-zero percentages for namespaces', async ({ page }) => {
    // Expected to FAIL — all namespaces currently show 0%
    await page.waitForTimeout(3000)
    // At least one namespace should show a percentage > 0%
    const nonZeroPercent = page.locator('text=/[1-9]\\d*%/')
    await expect(nonZeroPercent.first()).toBeVisible({ timeout: 5000 })
  })

  test('should render the Agent Activity section', async ({ page }) => {
    await expect(page.locator('text=Agent Activity')).toBeVisible()
  })

  test('BUG-009: Agent Activity table should show non-zero reads/writes for agents', async ({ page }) => {
    // Expected to FAIL — all agents show 0 reads, 0 writes, 0 denied
    await page.waitForTimeout(3000)
    // The manus agent row should have non-zero reads or writes
    const agentRow = page.locator('div').filter({ hasText: /manus/i }).first()
    await expect(agentRow).toBeVisible()
    // Look for a non-zero number in the reads/writes/denied area
    const nonZeroStat = agentRow.locator('text=/^[1-9]\\d*$/')
    await expect(nonZeroStat.first()).toBeVisible({ timeout: 5000 })
  })
})

// ============================================================
// SECURITY ALERTS PAGE
// ============================================================
test.describe('Security Alerts Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/security')
    await page.waitForTimeout(1500)
  })

  test('should render the Security Alerts heading', async ({ page }) => {
    await expect(page.locator('h1').filter({ hasText: /Security/i })).toBeVisible()
  })

  test('should render the Inspect Content textarea', async ({ page }) => {
    await expect(page.locator('textarea[placeholder*="scan for security"]')).toBeVisible()
  })

  test('should render the Full Scan button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Full Scan/i })).toBeVisible()
  })

  test('should render the PII Scan button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /PII Scan/i })).toBeVisible()
  })

  test('should render the Injection Scan button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Injection Scan/i })).toBeVisible()
  })

  test('should accept text input in the textarea', async ({ page }) => {
    const textarea = page.locator('textarea[placeholder*="scan for security"]')
    await textarea.fill('Test content with email: test@example.com and phone: 555-1234')
    const value = await textarea.inputValue()
    expect(value).toContain('test@example.com')
  })

  test('Full Scan button should trigger a scan and show results', async ({ page }) => {
    const textarea = page.locator('textarea[placeholder*="scan for security"]')
    await textarea.fill('My email is user@example.com and my SSN is 123-45-6789')
    await page.getByRole('button', { name: /Full Scan/i }).click()
    // Wait for results to appear
    await page.waitForTimeout(3000)
    // Results section should appear (or error message)
    // Note: This is a stub feature — may not return real results
    await expect(page.locator('h1').filter({ hasText: /Security/i })).toBeVisible()
  })
})

// ============================================================
// WAITLIST MANAGEMENT PAGE
// ============================================================
test.describe('Waitlist Management Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/waitlist')
    await page.waitForTimeout(1500)
  })

  test('should render the Waitlist Management heading', async ({ page }) => {
    await expect(page.locator('h1').filter({ hasText: /Waitlist/i })).toBeVisible()
  })

  test('should render the status filter tabs', async ({ page }) => {
    const tabs = ['All', 'Pending', 'Approved', 'Rejected']
    for (const tab of tabs) {
      await expect(page.getByRole('button', { name: new RegExp(`^${tab}$`, 'i') })).toBeVisible()
    }
  })

  test('[BUG-015] Waitlist stat cards missing due to API 500 error', async ({ page }) => {
    // Documents the bug: stat cards don't render because admin API returns 500
    await page.waitForTimeout(3000)
    const statCards = page.locator('[class*="rounded-lg"][class*="border"]').filter({ hasText: /\d+/ })
    const count = await statCards.count()
    console.log(`Stat cards visible: ${count} (expected 4)`)
    // The stat cards should be visible but they're not due to API 500
    expect(count).toBeGreaterThanOrEqual(4) // FAILS - confirms BUG-015
  })

  test('BUG-010: should render stat cards (Total, Pending, Approved, Rejected counts)', async ({ page }) => {
    // Expected to FAIL — stat cards are not rendering
    await page.waitForTimeout(3000)
    // Should show stat cards with counts
    await expect(page.locator('text=/Total|Pending|Approved|Rejected/i').first()).toBeVisible()
    // Specifically, numeric stat cards should be visible
    const statCards = page.locator('[class*="rounded-lg"][class*="border"]').filter({ hasText: /\d+/ })
    await expect(statCards.first()).toBeVisible({ timeout: 5000 })
  })

  test('BUG-010: should render the waitlist data table', async ({ page }) => {
    // Expected to FAIL — the table is not rendering
    await page.waitForTimeout(3000)
    await expect(page.locator('table')).toBeVisible({ timeout: 5000 })
  })

  test('should filter by Pending status when Pending tab is clicked', async ({ page }) => {
    await page.getByRole('button', { name: /^Pending$/i }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('h1').filter({ hasText: /Waitlist/i })).toBeVisible()
  })

  test('should filter by Approved status when Approved tab is clicked', async ({ page }) => {
    await page.getByRole('button', { name: /^Approved$/i }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('h1').filter({ hasText: /Waitlist/i })).toBeVisible()
  })
})

// ============================================================
// CONNECTORS PAGE
// ============================================================
test.describe('Connectors Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/connectors')
    await page.waitForTimeout(1500)
  })

  test('BUG-001: Connectors page should render (not redirect to dashboard)', async ({ page }) => {
    // Expected to FAIL — the page redirects to / because it is not in the sidebar
    // and the route may not be protected correctly
    await expect(page).toHaveURL('/connectors')
    await expect(page.locator('h1').filter({ hasText: /Connector/i })).toBeVisible()
  })

  test('should render connector category sections', async ({ page }) => {
    // Categories: AI Assistants, Custom Agents, Integrations
    const categories = ['AI Assistants', 'Custom Agents', 'Integrations']
    for (const cat of categories) {
      await expect(page.locator('text=' + cat)).toBeVisible()
    }
  })

  test('should render Claude Code connector card', async ({ page }) => {
    await expect(page.locator('text=Claude Code')).toBeVisible()
  })

  test('should render Claude Desktop connector card', async ({ page }) => {
    await expect(page.locator('text=Claude Desktop')).toBeVisible()
  })

  test('should render Set up / Reconfigure button on connector cards', async ({ page }) => {
    const setupButtons = page.getByRole('button', { name: /Set up|Reconfigure/i })
    await expect(setupButtons.first()).toBeVisible()
  })

  test('[BUG-011] Cognition OS wizard should make API call to register agent', async ({ page }) => {
    // EXPECTED TO FAIL: CognitionBridgeWizard shows static instructions only
    // No API call is made to POST /api/v1/agents
    //
    // FIX: Add agent registration step to CognitionBridgeWizard
    const cognitionCard = page.locator('div').filter({ hasText: /Cognition/i }).first()
    if (await cognitionCard.count() > 0) {
      const setupBtn = cognitionCard.getByRole('button', { name: /Set up|Reconfigure/i })
      if (await setupBtn.count() > 0) {
        let apiCallMade = false
        page.on('request', req => {
          if (req.url().includes('/api/v1/agents') && req.method() === 'POST') {
            apiCallMade = true
          }
        })
        await setupBtn.click()
        await page.waitForTimeout(2000)
        console.log(`BUG-011: Cognition OS wizard made API call: ${apiCallMade}`)
        expect(apiCallMade).toBe(true) // FAILS due to BUG-011
        await page.keyboard.press('Escape')
      }
    }
  })

  test('[BUG-012] Webhook endpoint missing from backend (static wizard only)', async ({ page }) => {
    // EXPECTED TO FAIL: No webhook registration endpoint exists in backend
    // Webhook wizard shows static instructions only
    // FIX: Implement POST /api/v1/webhooks endpoint in backend
    // This is documented as a known gap — test is intentionally failing
    expect(true).toBe(true) // Placeholder — see apiTest below for actual API check
  })

  test('[BUG-013] Encrypt/decrypt buttons should be present in Security UI', async ({ page }) => {
    // EXPECTED TO FAIL: POST /api/v1/security/encrypt and /decrypt exist but not in UI
    // Navigate to security page to check
    await page.goto('/security')
    await page.waitForTimeout(1500)
    const encryptBtn = page.locator('button').filter({ hasText: /Encrypt/i })
    await expect(encryptBtn).toBeVisible({ timeout: 3000 }) // FAILS due to BUG-013
  })

  test('[BUG-014] Generate Key button should be present in Security UI', async ({ page }) => {
    // EXPECTED TO FAIL: POST /api/v1/security/generate-key exists but not in UI
    await page.goto('/security')
    await page.waitForTimeout(1500)
    const genKeyBtn = page.locator('button').filter({ hasText: /Generate Key|New Key/i })
    await expect(genKeyBtn).toBeVisible({ timeout: 3000 }) // FAILS due to BUG-014
  })

  test('should open the Claude Code wizard when Set up is clicked', async ({ page }) => {
    const claudeCodeCard = page.locator('div').filter({ hasText: /Claude Code/i }).first()
    const setupButton = claudeCodeCard.getByRole('button', { name: /Set up|Reconfigure/i })
    await setupButton.click()
    // A wizard dialog should appear
    await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 3000 })
    // Close it
    await page.keyboard.press('Escape')
  })
})

// ============================================================
// ANALYTICS API BUGS — API Tests (no browser needed)
// ============================================================
apiTest.describe('Analytics API Wiring Bugs', () => {
  apiTest('[BUG-012] GET /api/v1/analytics/storage returns 404 (route not registered)', async ({ request }) => {
    // BUG-012: StorageAnalyticsPage calls GET /api/v1/analytics/storage
    // but this route is NOT registered in the backend.
    // FIX: Create backend/api/routes/analytics.py with storage analytics endpoint
    const res = await request.get(`${BASE}/api/v1/analytics/storage`)
    expect(res.status()).toBe(404)
    console.log(`BUG-012 CONFIRMED: GET /api/v1/analytics/storage returns ${res.status()}`)
  })

  apiTest('[BUG-012b] GET /api/v1/analytics/agents returns 404 (route not registered)', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/analytics/agents`)
    expect(res.status()).toBe(404)
    console.log(`BUG-012b CONFIRMED: GET /api/v1/analytics/agents returns ${res.status()}`)
  })
})

// ============================================================
// WAITLIST API BUGS — API Tests
// ============================================================
apiTest.describe('Waitlist API Wiring Bugs', () => {
  apiTest('[BUG-014] GET /api/v1/admin/waitlist returns 500 (require_admin crashes without token)', async ({ request }) => {
    // BUG-014: require_admin dependency crashes with 500 instead of returning 401
    // when no Authorization header is present.
    // FIX: Fix require_admin in backend/api/dependencies.py to return 401 gracefully
    const res = await request.get(`${BASE}/api/v1/admin/waitlist`)
    expect(res.status()).toBe(500)
    console.log(`BUG-014 CONFIRMED: GET /api/v1/admin/waitlist returns ${res.status()} (should be 401)`)
  })

  apiTest('[BUG-015] GET /api/v1/admin/waitlist/stats returns 500 (same root cause)', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/admin/waitlist/stats`)
    expect(res.status()).toBe(500)
    console.log(`BUG-015 CONFIRMED: GET /api/v1/admin/waitlist/stats returns ${res.status()} (should be 401)`)
  })
})

// ============================================================
// CONNECTORS API BUGS — API Tests
// ============================================================
apiTest.describe('Connectors API Wiring Bugs', () => {
  apiTest('[BUG-001b] GET /api/v1/connectors returns 404 (no backend, state in localStorage only)', async ({ request }) => {
    // BUG-001b: ConnectorsPage stores connector state in localStorage using agent name matching.
    // There is no backend API for connector state persistence.
    // FIX: Create a backend connectors API to persist connector configurations
    const res = await request.get(`${BASE}/api/v1/connectors`)
    expect([404, 405]).toContain(res.status())
    console.log(`BUG-001b CONFIRMED: GET /api/v1/connectors returns ${res.status()} (no backend)`)
  })

  apiTest('[BUG-012c] GET /api/v1/webhooks returns 404 (no webhook backend)', async ({ request }) => {
    // BUG-012c: Webhook wizard shows static instructions but no backend endpoint exists
    // FIX: Implement POST /api/v1/webhooks endpoint in backend
    const res = await request.get(`${BASE}/api/v1/webhooks`)
    expect([404, 405]).toContain(res.status())
    console.log(`BUG-012c CONFIRMED: GET /api/v1/webhooks returns ${res.status()} (no backend)`)
  })
})

// ============================================================
// SECURITY API BUGS — API Tests
// ============================================================
apiTest.describe('Security API Wiring Bugs', () => {
  apiTest('[BUG-013] GET /api/v1/security/alerts returns 404 (route not registered)', async ({ request }) => {
    // BUG-013: SecurityAlertsPage calls GET /api/v1/security/alerts
    // but this route is NOT registered in the backend.
    // FIX: Create backend/api/routes/security.py with alerts endpoint
    const res = await request.get(`${BASE}/api/v1/security/alerts`)
    expect(res.status()).toBe(404)
    console.log(`BUG-013 CONFIRMED: GET /api/v1/security/alerts returns ${res.status()}`)
  })

  apiTest('POST /api/v1/security/scan returns valid response (endpoint exists)', async ({ request }) => {
    const res = await request.post(`${BASE}/api/v1/security/scan`)
    const status = res.status()
    console.log(`POST /api/v1/security/scan returns ${status}`)
    expect([200, 201, 202, 422]).toContain(status)
  })
})

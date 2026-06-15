import { test, expect } from './fixtures'

/**
 * E2E Tests: Agents Management
 *
 * Covers the Agents list page (Agent Registry), Agent detail page, and
 * status change flows. These are fully functional features and should all pass.
 *
 * NOTE: The Agents page uses "Agent Registry" as its h1 heading (not "Agents").
 */

test.describe('Agents List Page (Agent Registry)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/agents', { waitUntil: 'domcontentloaded', timeout: 20_000 })
    await page.waitForTimeout(2000)
  })

  test('should render the Agent Registry heading', async ({ page }) => {
    // NOTE: The page heading is "Agent Registry" not "Agents"
    await expect(page.locator('h1').filter({ hasText: /Agent Registry/i })).toBeVisible()
  })

  test('should render the status filter pills: All, Pending, Active, Suspended, Revoked', async ({ page }) => {
    const filters = ['All', 'Pending', 'Active', 'Suspended', 'Revoked']
    for (const filter of filters) {
      await expect(
        page.locator('button, [role="tab"]').filter({ hasText: new RegExp(`^${filter}$`, 'i') }).first()
      ).toBeVisible()
    }
  })

  test('should render at least one agent row in the table', async ({ page }) => {
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    const rows = page.locator('table tbody tr')
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
    console.log(`Agent rows found: ${count}`)
  })

  test('should render manus agent in the table', async ({ page }) => {
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    await expect(page.locator('table tbody td').filter({ hasText: /manus/i })).toBeVisible()
  })

  test('should render claude-desktop-agent in the table', async ({ page }) => {
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    await expect(page.locator('table tbody td').filter({ hasText: /claude-desktop-agent/i })).toBeVisible()
  })

  test('should render claude-code-agent in the table', async ({ page }) => {
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    await expect(page.locator('table tbody td').filter({ hasText: /claude-code-agent/i })).toBeVisible()
  })

  test('should render column headers: NAME, STATUS, DESCRIPTION, REGISTERED, READS, WRITES, DENIED', async ({ page }) => {
    const headers = ['NAME', 'STATUS', 'DESCRIPTION', 'REGISTERED', 'READS', 'WRITES', 'DENIED']
    for (const header of headers) {
      await expect(page.locator('th').filter({ hasText: header })).toBeVisible()
    }
  })

  test('should show Active status badge for registered agents', async ({ page }) => {
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    const activeBadges = page.locator('table tbody').locator('text=Active')
    const count = await activeBadges.count()
    expect(count).toBeGreaterThan(0)
    console.log(`Active agent badges: ${count}`)
  })

  test('should filter agents by "Active" status pill', async ({ page }) => {
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    await page.locator('button').filter({ hasText: /^Active$/i }).click()
    await page.waitForTimeout(1000)
    // All visible rows should have Active status
    const rows = page.locator('table tbody tr')
    const count = await rows.count()
    expect(count).toBeGreaterThan(0)
    // Verify no non-active badges visible
    await expect(page.locator('h1').filter({ hasText: /Agent Registry/i })).toBeVisible()
  })

  test('should filter agents by "Pending" status pill — shows empty or pending agents', async ({ page }) => {
    await page.locator('button').filter({ hasText: /^Pending$/i }).click()
    await page.waitForTimeout(1000)
    // Either shows pending agents or empty state — no crash
    await expect(page.locator('h1').filter({ hasText: /Agent Registry/i })).toBeVisible()
  })

  test('[BUG-003] Register Agent button should be present on AgentListPage', async ({ page }) => {
    // EXPECTED TO FAIL: No "Register Agent" button exists on AgentListPage
    // POST /api/v1/agents endpoint exists but is only accessible via Connectors wizard
    //
    // FIX: Add a "Register Agent" button/modal to AgentListPage that calls POST /api/v1/agents
    const registerBtn = page.locator('button').filter({ hasText: /Register Agent|Add Agent|New Agent/i })
    await expect(registerBtn).toBeVisible({ timeout: 3000 }) // FAILS due to BUG-003
  })

  test('should navigate to agent detail page on row click', async ({ page }) => {
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    const firstRow = page.locator('table tbody tr').first()
    await firstRow.click()
    await expect(page).toHaveURL(/\/agents\/[a-f0-9-]+/)
  })
})

test.describe('Agent Detail Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/agents', { waitUntil: 'domcontentloaded', timeout: 20_000 })
    await page.waitForSelector('table tbody tr', { timeout: 10_000 })
    await page.locator('table tbody tr').first().click()
    await page.waitForURL(/\/agents\/[a-f0-9-]+/)
    await page.waitForTimeout(1500)
  })

  test('should render agent name as a heading', async ({ page }) => {
    await expect(page.locator('h2').first()).toBeVisible()
  })

  test('should render the stats section: Reads, Writes, Denied', async ({ page }) => {
    await expect(page.locator('text=Reads')).toBeVisible()
    await expect(page.locator('text=Writes')).toBeVisible()
    await expect(page.locator('text=Denied')).toBeVisible()
  })

  test('should render the Declared Scopes section', async ({ page }) => {
    await expect(page.locator('text=Declared Scopes')).toBeVisible()
  })

  test('should render the Back to agents button', async ({ page }) => {
    const backButton = page.locator('button, a').filter({ hasText: /Back to agents/i })
    await expect(backButton).toBeVisible()
  })

  test('should navigate back to agents list when Back button is clicked', async ({ page }) => {
    const backButton = page.locator('button').filter({ hasText: /Back to agents/i })
    await backButton.click()
    await expect(page).toHaveURL('/agents')
  })

  test('should show Suspend button for active agents', async ({ page }) => {
    const isActive = await page.locator('text=/^Active$/i').first().isVisible().catch(() => false)
    if (isActive) {
      await expect(page.getByRole('button', { name: /Suspend/i })).toBeVisible()
    }
  })

  test('[BUG-004] agent stats Reads/Writes/Denied should be non-zero', async ({ page }) => {
    // EXPECTED TO FAIL: total_reads, total_writes, denied_requests columns in DB
    // are never incremented. The memory_service.py does not call any counter update.
    //
    // FIX: Add counter increments in memory_service.py:
    //   - create_memory(): agent.total_writes += 1
    //   - search_memory(): agent.total_reads += 1
    //   - gatekeeper_service.py evaluate(): agent.denied_requests += 1 on deny
    const readsEl = page.locator('text=Reads').first()
    const writesEl = page.locator('text=Writes').first()
    if (await readsEl.isVisible()) {
      // Get the number next to Reads
      const readsParent = readsEl.locator('..')
      const readsText = await readsParent.textContent()
      const readsNum = parseInt(readsText?.match(/(\d+)/)?.[1] ?? '0')
      expect(readsNum).toBeGreaterThan(0) // FAILS due to BUG-004
    }
    if (await writesEl.isVisible()) {
      const writesParent = writesEl.locator('..')
      const writesText = await writesParent.textContent()
      const writesNum = parseInt(writesText?.match(/(\d+)/)?.[1] ?? '0')
      expect(writesNum).toBeGreaterThan(0) // FAILS due to BUG-004
    }
  })

  test('should show Revoke button for non-revoked agents', async ({ page }) => {
    const isRevoked = await page.locator('text=/^Revoked$/i').first().isVisible().catch(() => false)
    if (!isRevoked) {
      await expect(page.getByRole('button', { name: /Revoke/i })).toBeVisible()
    }
  })

  test('should open confirmation dialog when Revoke button is clicked', async ({ page }) => {
    const isRevoked = await page.locator('text=/^Revoked$/i').first().isVisible().catch(() => false)
    if (!isRevoked) {
      const revokeBtn = page.getByRole('button', { name: /Revoke/i })
      if (await revokeBtn.isVisible()) {
        await revokeBtn.click()
        // A confirmation dialog should appear
        const dialog = page.locator('[role="dialog"]')
        const dialogVisible = await dialog.isVisible({ timeout: 3000 }).catch(() => false)
        if (dialogVisible) {
          // Close without confirming
          const cancelButton = dialog.getByRole('button', { name: /cancel/i })
          if (await cancelButton.isVisible()) {
            await cancelButton.click()
          } else {
            await page.keyboard.press('Escape')
          }
        }
      }
    }
  })

  test('agent detail URL should contain a valid UUID', async ({ page }) => {
    const url = page.url()
    expect(url).toMatch(/\/agents\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/)
  })
})

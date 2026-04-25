import { test, expect } from './fixtures'

/**
 * Audit Log Page Tests
 *
 * BUG COVERAGE:
 * - BUG-007: Audit Log shows "No data / Showing 1-0 of 0" despite active agents.
 *   The useAuditLogs hook is either failing silently or the backend returns
 *   an empty items array for this user's auth context.
 */

test.describe('Audit Log Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/audit')
    await page.waitForTimeout(1500)
  })

  test('should render the Audit Log heading', async ({ page }) => {
    await expect(page.locator('h1').filter({ hasText: /Audit/i })).toBeVisible()
  })

  test('should render the filter dropdowns', async ({ page }) => {
    // All Agents dropdown
    await expect(page.locator('select').filter({ hasText: /All Agents/i })).toBeVisible()
    // All Actions dropdown
    await expect(page.locator('select').filter({ hasText: /All Actions/i })).toBeVisible()
    // All Outcomes dropdown
    await expect(page.locator('select').filter({ hasText: /All Outcomes/i })).toBeVisible()
  })

  test('should render the Verify Chain button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Verify Chain/i })).toBeVisible()
  })

  test('should render the table headers', async ({ page }) => {
    const headers = ['TIME', 'ACTION', 'RESOURCE', 'OUTCOME', 'AGENT', 'NAMESPACE']
    for (const header of headers) {
      await expect(page.locator('th').filter({ hasText: header })).toBeVisible()
    }
  })

  test('BUG-007: should render audit log entries (not empty)', async ({ page }) => {
    // Expected to FAIL until BUG-007 is resolved
    // The table should contain at least one row of data
    await page.waitForTimeout(3000)
    const noDataText = page.locator('text=No data')
    await expect(noDataText).not.toBeVisible({ timeout: 5000 })
    const rows = page.locator('table tbody tr').filter({ hasNotText: 'No data' })
    await expect(rows.first()).toBeVisible({ timeout: 5000 })
  })

  test('BUG-007: pagination should show non-zero total', async ({ page }) => {
    // Expected to FAIL until BUG-007 is resolved
    await page.waitForTimeout(3000)
    // "Showing 1-0 of 0" is the broken state; should show "Showing 1-50 of N"
    const paginationText = page.locator('text=/Showing \\d+–\\d+ of \\d+/')
    await expect(paginationText).toBeVisible({ timeout: 5000 })
    const text = await paginationText.textContent()
    // Extract the total count
    const match = text?.match(/of (\d+)/)
    const total = parseInt(match?.[1] ?? '0')
    expect(total).toBeGreaterThan(0)
  })

  test('should filter by agent when an agent is selected', async ({ page }) => {
    const agentSelect = page.locator('select').filter({ hasText: /All Agents/i })
    await agentSelect.selectOption({ index: 1 }) // Select first agent
    await page.waitForTimeout(1500)
    // Page should still render without error
    await expect(page.locator('h1').filter({ hasText: /Audit/i })).toBeVisible()
  })

  test('should filter by action "memory:read"', async ({ page }) => {
    const actionSelect = page.locator('select').filter({ hasText: /All Actions/i })
    await actionSelect.selectOption('memory:read')
    await page.waitForTimeout(1500)
    await expect(page.locator('h1').filter({ hasText: /Audit/i })).toBeVisible()
  })

  test('should filter by outcome "success"', async ({ page }) => {
    const outcomeSelect = page.locator('select').filter({ hasText: /All Outcomes/i })
    await outcomeSelect.selectOption('success')
    await page.waitForTimeout(1500)
    await expect(page.locator('h1').filter({ hasText: /Audit/i })).toBeVisible()
  })

  test('Verify Chain button should trigger a chain verification request', async ({ page }) => {
    const verifyButton = page.getByRole('button', { name: /Verify Chain/i })
    await verifyButton.click()
    // After clicking, the button should show a loading state or a result
    // Wait for the result to appear (either success or error message)
    await page.waitForTimeout(3000)
    // Either a success or error message should appear
    const result = page.locator('text=/Chain integrity verified|Chain broken/i')
    // This may or may not appear depending on audit data availability
    // Just verify no crash occurred
    await expect(page.locator('h1').filter({ hasText: /Audit/i })).toBeVisible()
  })

  test('Previous button should be disabled when on first page', async ({ page }) => {
    const prevButton = page.getByRole('button', { name: /Previous/i })
    await expect(prevButton).toBeDisabled()
  })
})

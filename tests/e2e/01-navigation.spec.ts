import { test, expect } from '@playwright/test'

/**
 * E2E Tests: Navigation & Sidebar
 *
 * Verifies that every sidebar link navigates to the correct route and that
 * the page heading renders. These tests serve as a baseline to ensure no
 * routes are broken or redirecting unexpectedly.
 *
 * BUG COVERAGE:
 * - BUG-001: Connectors page (/connectors) is NOT accessible — redirects to /
 *   (route exists in App.tsx but is missing from sidebar nav AND is blocked by
 *   the catch-all redirect in the router)
 * - BUG-005: /health route triggers nginx 301 → HTTP redirect → 400 Bad Request
 *   (nginx misconfiguration: /health path proxied to HTTP port 3000 instead of HTTPS)
 * - BUG-006: Analytics sidebar link was observed to navigate to /security instead
 *   of /analytics during live testing (sidebar index offset bug)
 */

test.describe('Sidebar Navigation', () => {
  test('should navigate to Dashboard Overview', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL('/')
    await expect(page.locator('h1').filter({ hasText: /Dashboard/i })).toBeVisible()
  })

  test('should navigate to Agents page', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /^Agents$/i }).click()
    await expect(page).toHaveURL('/agents')
    // Agents page uses "Agent Registry" as its h1
    await expect(page.locator('h1').filter({ hasText: /Agent Registry/i })).toBeVisible()
  })

  test('BUG-005: /health direct navigation triggers nginx 400 error', async ({ page }) => {
    // BUG: navigating to /health causes nginx to redirect to HTTP port 3000
    // which then returns "400 Bad Request: The plain HTTP request was sent to HTTPS port"
    // Expected: React SPA should handle /health route and render HealthStatusPage
    // Actual: nginx 301 redirect to http://app.memory.dxb-gw.basanti.ai:3000/health/
    await page.goto('/health', { waitUntil: 'domcontentloaded', timeout: 20_000 })
    const finalUrl = page.url()
    const h1Text = await page.locator('h1').first().innerText().catch(() => '')
    console.log('Health page URL:', finalUrl, 'h1:', h1Text)
    // Document the bug: this SHOULD be the health page but ISN'T
    // When fixed, this test should be updated to expect /health URL and "Health Status" heading
    if (h1Text.includes('400')) {
      console.log('BUG-005 CONFIRMED: Health page shows 400 Bad Request nginx error')
    }
    // The test passes as documentation — the assertion below will FAIL when the bug is fixed
    // (which is the desired behavior — it will alert you the bug is resolved)
    await expect(page.locator('h1').filter({ hasText: /400 Bad Request/i })).toBeVisible()
  })

  test('should navigate to Audit Log page', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /^Audit Log$/i }).click()
    await expect(page).toHaveURL('/audit')
    await expect(page.locator('h1').filter({ hasText: /Audit Log/i })).toBeVisible()
  })

  test('should navigate to Permissions page', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /^Permissions$/i }).click()
    await expect(page).toHaveURL('/permissions')
    await expect(page.locator('h1').filter({ hasText: /Permission Rules/i })).toBeVisible()
  })

  test('should navigate to Memories page', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /^Memories$/i }).click()
    await expect(page).toHaveURL('/memories')
    await expect(page.locator('h1').filter({ hasText: /Memory Explorer/i })).toBeVisible()
  })

  test('should navigate to Access Map page', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /^Access Map$/i }).click()
    await expect(page).toHaveURL('/access')
    await expect(page.locator('h1').filter({ hasText: /Access Map/i })).toBeVisible()
  })

  test('should navigate to Consent Queue page', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /^Consent Queue$/i }).click()
    await expect(page).toHaveURL('/consent')
    await expect(page.locator('h1').filter({ hasText: /Consent Queue/i })).toBeVisible()
  })

  test('should navigate to Analytics page', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /^Analytics$/i }).click()
    await expect(page).toHaveURL('/analytics')
    await expect(page.locator('h1').filter({ hasText: /Storage Analytics/i })).toBeVisible()
  })

  test('should navigate to Security page', async ({ page }) => {
    await page.goto('/security')
    await expect(page).toHaveURL('/security')
    await expect(page.locator('h1').filter({ hasText: /Security Alerts/i })).toBeVisible()
  })

  test('should navigate to Waitlist page', async ({ page }) => {
    await page.goto('/waitlist')
    await expect(page).toHaveURL('/waitlist')
    await expect(page.locator('h1').filter({ hasText: /Waitlist Management/i })).toBeVisible()
  })

  test('BUG-001: /connectors route is inaccessible — redirects to /', async ({ page }) => {
    // BUG: ConnectorsPage is defined in App.tsx router but navigating to /connectors
    // redirects to / (the catch-all or RequireAuth redirect is intercepting it).
    // Additionally, there is NO sidebar link to /connectors.
    // Expected: /connectors should render the ConnectorsPage component
    // Actual: redirects to / (Dashboard)
    await page.goto('/connectors', { waitUntil: 'domcontentloaded', timeout: 20_000 })
    const finalUrl = page.url()
    console.log('Connectors URL:', finalUrl)
    // Document the bug: this SHOULD stay at /connectors
    await expect(page).toHaveURL('/')
    console.log('BUG-001 CONFIRMED: /connectors redirects to /')
  })

  test('BUG-001: Connectors page has no sidebar navigation link', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 20_000 })
    const connectorsLink = page.locator('nav a:has-text("Connectors"), aside a:has-text("Connectors")')
    await expect(connectorsLink).toHaveCount(0)
    console.log('BUG-001 CONFIRMED: No Connectors link in sidebar navigation')
  })

  test('unknown routes redirect to dashboard', async ({ page }) => {
    await page.goto('/this-route-does-not-exist')
    await expect(page).toHaveURL('/')
  })
})

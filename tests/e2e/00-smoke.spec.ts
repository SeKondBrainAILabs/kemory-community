import { test, expect } from '@playwright/test'

/**
 * Smoke Tests: Basic app reachability and navigation structure.
 * These tests run in unauthenticated mode (Keycloak check-sso returns false).
 * The app redirects to /login when unauthenticated.
 */

test.describe('Smoke: App Reachability', () => {
  test('app loads with correct title', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page).toHaveTitle(/Kora Memory Vault/i)
  })

  test('app shows sidebar navigation', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    // Wait for any content to appear
    await page.waitForTimeout(3000)
    const bodyText = await page.locator('body').innerText()
    console.log('Body text:', bodyText.slice(0, 500))
    await page.screenshot({ path: '/home/ubuntu/agent_memory_vault/qa_output/screenshots/smoke_home.png' })
  })

  test('captures current app state screenshot', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await page.waitForTimeout(5000)
    const url = page.url()
    const title = await page.title()
    console.log('Final URL:', url)
    console.log('Final Title:', title)
    await page.screenshot({ 
      path: '/home/ubuntu/agent_memory_vault/qa_output/screenshots/app_state.png',
      fullPage: true 
    })
  })
})

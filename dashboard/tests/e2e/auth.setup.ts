import { test as setup, expect } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/**
 * Auth Setup: Handles the s25d Secure DXB Gateway login then saves browser
 * state so all subsequent tests can reuse the authenticated session.
 *
 * Credentials:
 *   Gateway user: admin
 *   Gateway pass: Hanuman88!!
 */
const AUTH_FILE = path.join(__dirname, '.auth', 'user.json')

setup('authenticate via s25d gateway', async ({ page }) => {
  // Navigate to the app — this will redirect to the gateway login
  await page.goto('/', { waitUntil: 'domcontentloaded' })

  // Check if we hit the gateway login page
  const url = page.url()
  const title = await page.title()
  console.log('Initial URL:', url)
  console.log('Initial Title:', title)

  // If we see the gateway login form, authenticate through it
  const usernameInput = page.locator('input[name="username"], input[type="text"]').first()
  const passwordInput = page.locator('input[type="password"]').first()

  if (await usernameInput.isVisible({ timeout: 5_000 }).catch(() => false)) {
    console.log('Gateway login form detected — filling credentials')
    await usernameInput.fill('admin')
    await passwordInput.fill('Hanuman88!!')

    const submitBtn = page.locator('button[type="submit"], input[type="submit"]').first()
    await submitBtn.click()

    // Wait for the gateway to pass us through to the app
    await page.waitForURL(/app\.memory\.dxb-gw\.basanti\.ai(?!.*login)/, { timeout: 20_000 })
    console.log('Post-gateway URL:', page.url())
  } else {
    console.log('No gateway login form — app is directly accessible')
  }

  // Now check if the app itself has a Keycloak login
  const appLoginInput = page.locator('input[name="username"], input[id="username"]').first()
  if (await appLoginInput.isVisible({ timeout: 5_000 }).catch(() => false)) {
    console.log('App Keycloak login detected — filling credentials')
    await appLoginInput.fill('admin')
    await page.locator('input[type="password"]').first().fill('Hanuman88!!')
    await page.locator('button[type="submit"]').first().click()
    await page.waitForURL('**/', { timeout: 15_000 })
  }

  // Wait for the dashboard to be visible
  await page.waitForSelector('nav, [data-testid="sidebar"], aside', { timeout: 15_000 })
  console.log('Dashboard loaded — saving auth state')

  // Save auth state (cookies + localStorage)
  await page.context().storageState({ path: AUTH_FILE })
  console.log('Auth state saved to:', AUTH_FILE)
})

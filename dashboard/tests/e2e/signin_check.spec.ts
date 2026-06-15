import { test } from '@playwright/test'

test('check sign-in redirect URL', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })

  // Intercept the navigation triggered by Sign In
  const [response] = await Promise.all([
    page.waitForEvent('framenavigated').catch(() => null),
    page.locator('button:has-text("Sign in"), a:has-text("Sign in")').first().click()
  ])

  await page.waitForTimeout(2000)
  console.log('After Sign In URL:', page.url())
  console.log('After Sign In Title:', await page.title())
  await page.screenshot({ path: '/tmp/after_signin2.png' })

  // Try to get all network requests
  const requests: string[] = []
  page.on('request', req => requests.push(req.url()))
  await page.waitForTimeout(1000)
  console.log('Recent requests:', requests.slice(-5).join('\n'))
})

import { test } from '@playwright/test'

const pages = [
  { path: '/', name: 'Dashboard' },
  { path: '/agents', name: 'Agents' },
  { path: '/health', name: 'Health' },
  { path: '/audit', name: 'Audit' },
  { path: '/permissions', name: 'Permissions' },
  { path: '/memories', name: 'Memories' },
  { path: '/access', name: 'Access' },
  { path: '/consent', name: 'Consent' },
  { path: '/analytics', name: 'Analytics' },
  { path: '/security', name: 'Security' },
  { path: '/waitlist', name: 'Waitlist' },
]

for (const p of pages) {
  test(`heading check: ${p.name}`, async ({ page }) => {
    await page.goto(p.path, { waitUntil: 'domcontentloaded', timeout: 20_000 })
    await page.waitForTimeout(2000)
    const h1 = await page.locator('h1').allInnerTexts()
    const h2 = await page.locator('h2').allInnerTexts()
    const h3 = await page.locator('h3').allInnerTexts()
    console.log(`${p.name} - h1: ${JSON.stringify(h1)}, h2: ${JSON.stringify(h2.slice(0,3))}, h3: ${JSON.stringify(h3.slice(0,3))}`)
  })
}

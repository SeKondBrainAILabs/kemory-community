import { test } from '@playwright/test'

const pages = [
  { path: '/', name: 'dashboard' },
  { path: '/agents', name: 'agents' },
  { path: '/health', name: 'health' },
  { path: '/audit', name: 'audit' },
  { path: '/permissions', name: 'permissions' },
  { path: '/memories', name: 'memories' },
  { path: '/access', name: 'access' },
  { path: '/consent', name: 'consent' },
  { path: '/analytics', name: 'analytics' },
  { path: '/security', name: 'security' },
  { path: '/waitlist', name: 'waitlist' },
]

for (const p of pages) {
  test(`screenshot: ${p.name}`, async ({ page }) => {
    await page.goto(p.path, { waitUntil: 'domcontentloaded', timeout: 20_000 })
    await page.waitForTimeout(3000)
    await page.screenshot({ 
      path: `/home/ubuntu/agent_memory_vault/qa_output/screenshots/${p.name}.png`,
      fullPage: true 
    })
  })
}

import { test } from '@playwright/test'

test('health page debug', async ({ page }) => {
  const requests: string[] = []
  page.on('request', req => requests.push(`${req.method()} ${req.url()}`))
  page.on('response', res => console.log(`RESPONSE: ${res.status()} ${res.url()}`))
  
  await page.goto('/health', { waitUntil: 'domcontentloaded', timeout: 20_000 })
  await page.waitForTimeout(3000)
  
  console.log('URL after navigation:', page.url())
  console.log('All requests:')
  requests.forEach(r => console.log(' ', r))
  
  const bodyText = await page.locator('body').innerText()
  console.log('Body:', bodyText.slice(0, 300))
})

import { test as base, expect, Page } from '@playwright/test'

/**
 * Custom Playwright fixtures for the Memory Vault test suite.
 *
 * The `page` fixture is extended to override page.goto to use
 * `domcontentloaded` by default (prevents hanging on
 *    API-heavy pages that never reach `load` state in headless mode)
 */
export const test = base.extend<{ page: Page }>({
  page: async ({ page }, use) => {
    // Override goto to use domcontentloaded by default
    const originalGoto = page.goto.bind(page)
    page.goto = (url: string, options?: Parameters<Page['goto']>[1]) =>
      originalGoto(url, { waitUntil: 'domcontentloaded', ...options })

    await use(page)
  },
})
export { expect }

import { test as base, expect, Page } from '@playwright/test'

/**
 * Custom Playwright fixtures for the Memory Vault test suite.
 *
 * The `page` fixture is extended to:
 * 1. Block Keycloak's `check-sso` silent iframe (prevents headless browser hanging)
 * 2. Override page.goto to use `domcontentloaded` by default (prevents hanging on
 *    API-heavy pages that never reach `load` state in headless mode)
 */
export const test = base.extend<{ page: Page }>({
  page: async ({ page }, use) => {
    // Block Keycloak silent SSO check iframe — this prevents the browser from
    // hanging on the Keycloak auth check in headless mode
    await page.route('**/realms/**', route => route.abort())
    await page.route('**/auth/realms/**', route => route.abort())
    await page.route('**/keycloak/**', route => route.abort())
    await page.route('**/*.well-known/openid-configuration**', route => route.abort())
    await page.route('**/protocol/openid-connect/**', route => route.abort())

    // Override goto to use domcontentloaded by default
    const originalGoto = page.goto.bind(page)
    page.goto = (url: string, options?: Parameters<Page['goto']>[1]) =>
      originalGoto(url, { waitUntil: 'domcontentloaded', ...options })

    await use(page)
  },
})
export { expect }

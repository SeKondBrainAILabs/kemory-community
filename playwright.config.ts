import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright E2E Test Configuration
 * Target: https://app.memory.dxb-gw.basanti.ai
 *
 * The app is publicly accessible with NO authentication required.
 * SSL errors are bypassed (self-signed / CN-mismatch cert on the DXB gateway).
 */
export default defineConfig({
  testDir: './tests/e2e',
  testIgnore: ['**/auth.setup.ts'],
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['html', { outputFolder: '../qa_output/playwright-report', open: 'never' }],
    ['json', { outputFile: '../qa_output/playwright-results.json' }],
    ['list'],
  ],
  use: {
    baseURL: 'https://app.memory.dxb-gw.basanti.ai',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
    ignoreHTTPSErrors: true,
    navigationTimeout: 20_000,
    actionTimeout: 10_000,
    launchOptions: {
      args: [
        '--ignore-certificate-errors',
        '--ignore-ssl-errors',
        '--allow-insecure-localhost',
        '--no-sandbox',
        '--disable-setuid-sandbox',
      ],
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  outputDir: '../qa_output/test-results',
})

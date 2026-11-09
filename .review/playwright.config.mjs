// Temporary, isolated browser review; removed before the final PR is delivered.
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '../tests/browser',
  testMatch: 'contour-openings.spec.mjs',
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: [['list']],
  outputDir: '../.test-output/tribulation-contour',
  use: {
    viewport: { width: 1440, height: 1000 },
    locale: 'en-GB',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }]
});

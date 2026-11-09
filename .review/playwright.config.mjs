// Temporary article review, removed before the final website PR is delivered.
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '.',
  testMatch: 'water-wine.spec.mjs',
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: [['list']],
  outputDir: '../.test-output/water-wine',
  use: {
    viewport: { width: 1440, height: 1000 },
    locale: 'en-GB',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});

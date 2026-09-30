import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: true,
  workers: process.env.CI ? 2 : 2,
  retries: 0,
  timeout: 30000,
  reporter: [['list'], ['html', { open: 'never', outputFolder: '.test-output/browser-report' }]],
  outputDir: '.test-output/browser-results',
  use: {
    baseURL: 'http://127.0.0.1:8080',
    viewport: { width: 1440, height: 1000 },
    locale: 'en-GB',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: {
    command: 'python3 -m http.server 8080 --bind 127.0.0.1 --directory dist',
    url: 'http://127.0.0.1:8080/en/',
    reuseExistingServer: !process.env.CI,
    timeout: 30000
  }
});

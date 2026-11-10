// Temporary execution of the permanent fixtures without original-article overrides.
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '../tests/browser',
  testMatch: ['figure-quotes.spec.mjs', 'native-figure-wrap.spec.mjs',
    'native-verse-quote.spec.mjs', 'verse-image-sizing.spec.mjs'],
  workers: 2,
  retries: 0,
  timeout: 30000,
  reporter: [['list']],
  outputDir: '../.test-output/article-layout-review/permanent-regressions',
  use: { browserName: 'chromium', viewport: { width: 1440, height: 1000 },
    locale: 'en-GB', colorScheme: 'light', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
});
